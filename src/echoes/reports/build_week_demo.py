"""Sanitized, deterministic Build Week export for the Milestone 7 lexical result.

The public bundle deliberately exports stable feature identifiers, positions,
frequencies, scores, references, and hashes. It never exports source lexical
values, reconstructed text, English glosses, morphology strings, or local
source paths.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast
from uuid import uuid4

import duckdb

from echoes.lexical.config import (
    LexicalConfig,
    LexicalExperimentPreregistration,
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    validate_preregistration_against_config,
)
from echoes.lexical.storage import processed_from_directory, read_artifact_frame
from echoes.manifests import SourceManifest, load_source_catalog

DEMO_EXPORT_SCHEMA_VERSION: Final = 1
DEFAULT_ARTIFACT_ROOT: Final = Path("data/processed/lexical/schema-v1")
DEFAULT_DATABASE_PATH: Final = Path("data/processed/project_echoes.duckdb")
DEFAULT_EXPORT_ROOT: Final = Path("demo/data/echoes-demo-v1")
DEFAULT_SOURCE_MANIFEST: Final = Path("data/manifests/sources.yaml")

DEMO_DATA_FILENAMES: Final[tuple[str, ...]] = (
    "overview.json",
    "known-recoveries.json",
    "unreviewed-candidates.json",
    "textual-uncertainty-examples.json",
)
DEMO_FILENAMES: Final[tuple[str, ...]] = (*DEMO_DATA_FILENAMES, "manifest.json")
SOURCE_IDS: Final[tuple[str, ...]] = (
    "macula-hebrew",
    "macula-greek",
    "oshb-morphhb",
    "openbible-cross-references",
)
ORIGINAL_LANGUAGE_CORPUS_PAIRS: Final[tuple[str, ...]] = ("hb_hb", "gnt_gnt")
PUBLIC_EVIDENCE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "lemma",
        "root",
        "lemma_ngram",
        "root_ngram",
        "lemma_skipgram",
        "root_skipgram",
    }
)
PROHIBITED_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "feature_value",
        "lemma_value",
        "root_value",
        "surface",
        "surface_form",
        "normalized_form",
        "normalized_surface",
        "source_text",
        "reconstructed_text",
        "token_text",
        "token_value",
        "english_gloss",
        "gloss",
        "morphology",
        "morph",
        "source_file",
        "source_path",
        "local_path",
        "raw_record",
        "raw_source_record",
        "excerpt",
        "notes",
        "openbible_relationship_ids_json",
        "detector_contributions_json",
        "score_components_json",
    }
)
PROHIBITED_PATH_FRAGMENTS: Final[tuple[str, ...]] = (
    "data/raw/",
    "data\\raw\\",
    "data/processed/",
    "data\\processed\\",
)
_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_FEATURE_ID_RE: Final = re.compile(r"^LF_[a-f0-9]{64}$")
_CANDIDATE_ID_RE: Final = re.compile(r"^LCP_[a-f0-9]{64}$")
_ORIGINAL_SCRIPT_RE: Final = re.compile(r"[\u0370-\u03ff\u0590-\u05ff]")
_ABSOLUTE_WINDOWS_PATH_RE: Final = re.compile(r"(?i)(?:^|[\s\"'])[a-z]:[\\/]")


class BuildWeekDemoError(RuntimeError):
    """Raised when a safe and authenticated demonstration bundle cannot be built."""


@dataclass(frozen=True, slots=True)
class BuildWeekDemoArtifacts:
    """One completed public demonstration export."""

    output_root: Path
    lexical_run_id: str
    known_recovery_count: int
    unreviewed_candidate_count: int
    uncertainty_example_count: int
    sha256_by_name: dict[str, str]

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self.output_root / name for name in DEMO_FILENAMES)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise BuildWeekDemoError(f"{label} must be serialized JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BuildWeekDemoError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise BuildWeekDemoError(f"{label} must decode to an object")
    return cast(dict[str, object], parsed)


def _json_positions(value: object, *, label: str) -> list[int]:
    if not isinstance(value, str):
        raise BuildWeekDemoError(f"{label} must be serialized JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BuildWeekDemoError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or not parsed:
        raise BuildWeekDemoError(f"{label} must contain at least one position")
    positions: list[int] = []
    for item in parsed:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise BuildWeekDemoError(f"{label} contains an invalid position")
        positions.append(item)
    return positions


def _rows(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> list[dict[str, object]]:
    cursor = connection.execute(query, list(parameters))
    names = [str(item[0]) for item in cursor.description]
    if len(names) != len(set(names)):
        raise BuildWeekDemoError("demo query returned duplicate column names")
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> int:
    row = connection.execute(query, list(parameters)).fetchone()
    if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
        raise BuildWeekDemoError("demo aggregate query did not return one integer")
    return int(row[0])


def _require_exact_keys(value: object, expected: set[str], *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise BuildWeekDemoError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise BuildWeekDemoError(
            f"{label} fields differ from the public schema: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    return cast(dict[str, object], value)


def _walk_public_tree(value: object, *, path: str = "$") -> Iterator[tuple[str, object]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BuildWeekDemoError(f"{path} contains a non-string key")
            if key.casefold() in PROHIBITED_PUBLIC_KEYS:
                raise BuildWeekDemoError(f"{path}.{key} is prohibited in the public bundle")
            yield from _walk_public_tree(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_public_tree(item, path=f"{path}[{index}]")


def _validate_public_tree(value: object) -> None:
    for path, item in _walk_public_tree(value):
        if isinstance(item, float) and not math.isfinite(item):
            raise BuildWeekDemoError(f"{path} contains a non-finite float")
        if isinstance(item, str):
            if _ORIGINAL_SCRIPT_RE.search(item):
                raise BuildWeekDemoError(f"{path} contains source-script text")
            if _ABSOLUTE_WINDOWS_PATH_RE.search(item):
                raise BuildWeekDemoError(f"{path} contains an absolute local path")
            lowered = item.casefold()
            if any(fragment in lowered for fragment in PROHIBITED_PATH_FRAGMENTS):
                raise BuildWeekDemoError(f"{path} contains a private data path")


def _validate_evidence_item(value: object, *, label: str) -> None:
    row = _require_exact_keys(
        value,
        {
            "evidence_id",
            "evidence_family",
            "feature_id",
            "passage_a_positions",
            "passage_b_positions",
            "corpus_frequency",
            "document_frequency",
            "passage_a_local_frequency",
            "passage_b_local_frequency",
            "association_score",
            "independence_expected_count",
            "contains_primary_rare_item",
            "counts_as_independent_co_signal",
        },
        label=label,
    )
    if not isinstance(row["feature_id"], str) or not _FEATURE_ID_RE.fullmatch(row["feature_id"]):
        raise BuildWeekDemoError(f"{label}.feature_id is invalid")
    if row["evidence_family"] not in PUBLIC_EVIDENCE_FAMILIES:
        raise BuildWeekDemoError(f"{label}.evidence_family is not public")
    for key in ("passage_a_positions", "passage_b_positions"):
        positions = row[key]
        if (
            not isinstance(positions, list)
            or not positions
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in positions
            )
        ):
            raise BuildWeekDemoError(f"{label}.{key} contains invalid positions")


def _validate_detector_item(value: object, *, label: str) -> None:
    _require_exact_keys(
        value,
        {
            "detector",
            "direction",
            "score",
            "quantized_score",
            "query_rank",
            "reverse_rank",
            "rrf_contribution",
            "penalty_contribution",
            "adjusted_score",
            "score_trace_digest",
        },
        label=label,
    )


def _validate_null_comparison(value: object, *, label: str) -> None:
    _require_exact_keys(
        value,
        {
            "selected_score_threshold",
            "both_null_families_present",
            "candidate_empirical_rate",
            "candidate_estimated_empirical_fdr",
            "observed_candidate_count",
            "mean_null_candidate_count",
            "empirical_interval_95",
            "observed_to_null_enrichment",
            "empirical_tail_probability",
            "threshold_estimated_empirical_fdr",
        },
        label=label,
    )


def _validate_pair(value: object, *, label: str, expected_status: str) -> None:
    row = _require_exact_keys(
        value,
        {
            "candidate_pair_id",
            "passage_a_reference",
            "passage_b_reference",
            "corpus_pair",
            "known_link_status",
            "highest_openbible_vote",
            "mapping_quality",
            "review_eligible",
            "eligibility_reason",
            "detector_support_count",
            "directional_support_count",
            "raw_rrf_score",
            "rrf_score",
            "total_penalty_contribution",
            "rare_rule_passed",
            "independent_co_signal_count",
            "shared_lemma_count",
            "shared_root_count",
            "shared_rare_lemma_count",
            "shared_rare_root_count",
            "disputed_passage_flag",
            "reference_gap",
            "ketiv_structural_uncertainty",
            "contains_english_derived_evidence",
            "evidence_digest",
            "shared_lexical_evidence",
            "detector_scores",
            "null_comparison",
        },
        label=label,
    )
    candidate_id = row["candidate_pair_id"]
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID_RE.fullmatch(candidate_id):
        raise BuildWeekDemoError(f"{label}.candidate_pair_id is invalid")
    if row["corpus_pair"] not in ORIGINAL_LANGUAGE_CORPUS_PAIRS:
        raise BuildWeekDemoError(f"{label} is not an original-language pair")
    if row["known_link_status"] != expected_status:
        raise BuildWeekDemoError(f"{label} has the wrong known-link status")
    if row["contains_english_derived_evidence"] is not False:
        raise BuildWeekDemoError(f"{label} contains English-derived evidence")
    shared = row["shared_lexical_evidence"]
    scores = row["detector_scores"]
    if not isinstance(shared, list) or not shared:
        raise BuildWeekDemoError(f"{label} lacks public shared lexical evidence")
    if not isinstance(scores, list) or not scores:
        raise BuildWeekDemoError(f"{label} lacks detector scores")
    for index, item in enumerate(shared):
        _validate_evidence_item(item, label=f"{label}.shared_lexical_evidence[{index}]")
    for index, item in enumerate(scores):
        _validate_detector_item(item, label=f"{label}.detector_scores[{index}]")
    _validate_null_comparison(row["null_comparison"], label=f"{label}.null_comparison")


def validate_public_demo_payloads(payloads: Mapping[str, object]) -> None:
    """Fail closed if a payload can expose prohibited or unexpected public fields."""

    expected = set(DEMO_DATA_FILENAMES)
    if set(payloads) != expected:
        raise BuildWeekDemoError(
            "demo payload names differ from the governed public schema: "
            f"expected={sorted(expected)}, actual={sorted(payloads)}"
        )
    for value in payloads.values():
        _validate_public_tree(value)

    overview = _require_exact_keys(
        payloads["overview.json"],
        {
            "export_schema_version",
            "export_name",
            "run_identity",
            "corpus_counts",
            "passage_counts",
            "benchmark_counts",
            "detectors",
            "feature_coverage",
            "null_model_summary",
            "candidate_counts",
            "tier3_global_performance",
            "source_attribution",
            "scientific_caveats",
            "no_candidate_review",
        },
        label="overview",
    )
    if overview["export_schema_version"] != DEMO_EXPORT_SCHEMA_VERSION:
        raise BuildWeekDemoError("overview export schema version is invalid")
    if overview["no_candidate_review"] is not True:
        raise BuildWeekDemoError("overview must state that no candidate review occurred")

    for filename, status, minimum, maximum in (
        (
            "known-recoveries.json",
            "represented_in_openbible_snapshot",
            0,
            25,
        ),
        (
            "unreviewed-candidates.json",
            "not_represented_in_openbible_snapshot",
            0,
            100,
        ),
    ):
        collection = _require_exact_keys(
            payloads[filename],
            {
                "export_schema_version",
                "selection_procedure",
                "requested_count",
                "actual_count",
                "no_candidate_review",
                "scientific_caveat",
                "pairs",
            },
            label=filename,
        )
        pairs = collection["pairs"]
        if not isinstance(pairs, list):
            raise BuildWeekDemoError(f"{filename}.pairs must be an array")
        if collection["actual_count"] != len(pairs):
            raise BuildWeekDemoError(f"{filename}.actual_count is inconsistent")
        if not (minimum <= len(pairs) <= maximum):
            raise BuildWeekDemoError(f"{filename} count exceeds its governed bound")
        if collection["no_candidate_review"] is not True:
            raise BuildWeekDemoError(f"{filename} must state that no review occurred")
        for index, pair in enumerate(pairs):
            _validate_pair(pair, label=f"{filename}.pairs[{index}]", expected_status=status)

    uncertainty = _require_exact_keys(
        payloads["textual-uncertainty-examples.json"],
        {
            "export_schema_version",
            "selection_procedure",
            "actual_count",
            "examples",
            "unavailable_categories",
            "no_interpretive_decision",
        },
        label="textual uncertainty",
    )
    examples = uncertainty["examples"]
    if not isinstance(examples, list) or uncertainty["actual_count"] != len(examples):
        raise BuildWeekDemoError("textual uncertainty count is inconsistent")
    if uncertainty["no_interpretive_decision"] is not True:
        raise BuildWeekDemoError("textual uncertainty must remain non-interpretive")
    kinds: set[str] = set()
    for index, example in enumerate(examples):
        row = _require_exact_keys(
            example,
            {
                "example_kind",
                "sensitivity_id",
                "corpus_pair",
                "detector",
                "direction",
                "baseline_profile",
                "comparison_profile",
                "baseline_reading",
                "comparison_reading",
                "query_reference",
                "target_reference",
                "baseline_query_passage_id",
                "comparison_query_passage_id",
                "baseline_target_passage_id",
                "comparison_target_passage_id",
                "baseline_score",
                "comparison_score",
                "score_delta",
                "baseline_rank",
                "comparison_rank",
                "rank_delta",
                "top_k_overlap",
                "affected_locus_count",
                "disputed_passage_flag",
                "excluded_reason",
                "baseline_sequence_digest",
                "comparison_sequence_digest",
                "explanatory_metadata",
            },
            label=f"textual uncertainty example {index}",
        )
        kind = row["example_kind"]
        if kind not in {"qere_ketiv", "critical_core_disputed_profile"}:
            raise BuildWeekDemoError("textual uncertainty example kind is invalid")
        kinds.add(str(kind))
    if "qere_ketiv" not in kinds:
        raise BuildWeekDemoError("a verified Qere/Ketiv example is required")


def _validate_manifest(manifest: object, data_payloads: Mapping[str, bytes]) -> None:
    _validate_public_tree(manifest)
    row = _require_exact_keys(
        manifest,
        {
            "export_schema_version",
            "export_name",
            "lexical_run_id",
            "passage_run_id",
            "benchmark_run_id",
            "configuration_sha256",
            "preregistration_sha256",
            "source_attribution",
            "generated_file_sha256",
            "export_counts",
            "public_field_policy",
            "no_candidate_review",
            "milestone_8_started",
        },
        label="manifest",
    )
    if row["export_schema_version"] != DEMO_EXPORT_SCHEMA_VERSION:
        raise BuildWeekDemoError("manifest export schema version is invalid")
    if row["no_candidate_review"] is not True or row["milestone_8_started"] is not False:
        raise BuildWeekDemoError("manifest review boundary is invalid")
    hashes = row["generated_file_sha256"]
    if not isinstance(hashes, dict) or set(hashes) != set(DEMO_DATA_FILENAMES):
        raise BuildWeekDemoError("manifest file hashes are incomplete")
    for filename, payload in data_payloads.items():
        digest = hashes.get(filename)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise BuildWeekDemoError(f"manifest hash is invalid for {filename}")
        if digest != _sha256_bytes(payload):
            raise BuildWeekDemoError(f"manifest hash differs for {filename}")


def _source_attribution(path: Path) -> list[dict[str, object]]:
    catalog = load_source_catalog(path)
    output: list[dict[str, object]] = []
    for source_id in SOURCE_IDS:
        source = catalog.find(source_id)
        if source is None:
            raise BuildWeekDemoError(f"required source manifest is missing: {source_id}")
        output.append(_public_source_attribution(source))
    return output


def _public_source_attribution(source: SourceManifest) -> dict[str, object]:
    if (
        not source.licensing_complete
        or source.version_or_commit is None
        or source.license is None
        or source.license_url is None
        or source.required_attribution is None
    ):
        raise BuildWeekDemoError(f"source attribution is incomplete: {source.source_id}")
    return {
        "source_id": source.source_id,
        "source_name": source.source_name,
        "version_or_commit": source.version_or_commit,
        "repository_or_location": source.repository_or_location,
        "license": source.license,
        "license_url": source.license_url,
        "required_attribution": source.required_attribution,
        "public_use": (
            "aggregate identifiers, references, positions, frequencies, scores, "
            "hashes, and validation metadata only; no source text or annotation values"
        ),
    }


def _validate_metadata(
    metadata: Mapping[str, object],
    *,
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
) -> None:
    config_hash = lexical_config_sha256(config)
    preregistration_hash = lexical_preregistration_sha256(preregistration)
    if metadata["configuration_hash"] != config_hash:
        raise BuildWeekDemoError("lexical metadata configuration hash is stale")
    if metadata["preregistration_hash"] != preregistration_hash:
        raise BuildWeekDemoError("lexical metadata preregistration hash is stale")
    if preregistration.preregistration_sha256 != preregistration_hash:
        raise BuildWeekDemoError("frozen preregistration digest is not authentic")
    if metadata["experiment_version"] != preregistration.experiment_version:
        raise BuildWeekDemoError("lexical metadata experiment version is stale")


def _selected_candidate_rows(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    projection = """
        p.candidate_pair_id,
        p.passage_a_reference,
        p.passage_b_reference,
        p.corpus_pair,
        p.known_link_status,
        p.highest_openbible_vote,
        p.mapping_quality,
        p.review_eligible,
        p.eligibility_reason,
        p.detector_support_count,
        p.directional_support_count,
        p.contains_english_derived_evidence,
        p.disputed_passage_flag,
        p.reference_gap,
        p.ketiv_structural_uncertainty,
        e.raw_rrf_score,
        e.rrf_score,
        e.total_penalty_contribution,
        e.rare_rule_passed,
        e.independent_co_signal_count,
        e.shared_lemma_count,
        e.shared_root_count,
        e.shared_rare_lemma_count,
        e.shared_rare_root_count,
        e.null_model_empirical_rate,
        e.estimated_empirical_fdr,
        e.selected_score_threshold,
        e.both_null_families_present,
        e.evidence_digest
    """
    known: list[dict[str, object]] = []
    for corpus_pair in ORIGINAL_LANGUAGE_CORPUS_PAIRS:
        known.extend(
            _rows(
                connection,
                f"""
                SELECT {projection}
                FROM lexical_candidate_pairs p
                JOIN lexical_candidate_evidence e USING(candidate_pair_id)
                WHERE p.known_link_status='represented_in_openbible_snapshot'
                  AND p.corpus_pair=?
                  AND NOT p.contains_english_derived_evidence
                  AND (e.shared_lemma_count + e.shared_root_count) > 0
                ORDER BY e.rrf_score DESC NULLS LAST, p.candidate_pair_id
                LIMIT 10
                """,
                [corpus_pair],
            )
        )
    known.sort(
        key=lambda row: (
            str(row["corpus_pair"]),
            -float(str(row["rrf_score"])),
            str(row["candidate_pair_id"]),
        )
    )

    unreviewed = _rows(
        connection,
        f"""
        SELECT {projection}, q.queue_rank
        FROM lexical_candidate_review_queue q
        JOIN lexical_candidate_pairs p USING(candidate_pair_id)
        JOIN lexical_candidate_evidence e USING(candidate_pair_id)
        WHERE p.known_link_status='not_represented_in_openbible_snapshot'
          AND p.corpus_pair IN ('hb_hb','gnt_gnt')
          AND NOT p.contains_english_derived_evidence
          AND (e.shared_lemma_count + e.shared_root_count) > 0
        ORDER BY q.queue_rank, p.candidate_pair_id
        LIMIT 50
        """,
    )
    return known, unreviewed


def _selected_evidence(
    connection: duckdb.DuckDBPyConnection,
    candidate_ids: Sequence[str],
) -> dict[str, list[dict[str, object]]]:
    if not candidate_ids:
        return {}
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = _rows(
        connection,
        f"""
        SELECT evidence_id, candidate_pair_id, evidence_family, feature_id,
               passage_a_positions_json, passage_b_positions_json,
               corpus_frequency, document_frequency,
               passage_a_local_frequency, passage_b_local_frequency,
               association_score, independence_expected_count,
               contains_primary_rare_item, counts_as_independent_co_signal
        FROM (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY candidate_pair_id
                   ORDER BY contains_primary_rare_item DESC,
                            counts_as_independent_co_signal DESC,
                            corpus_frequency,
                            evidence_family,
                            evidence_id
                 ) AS public_evidence_rank
          FROM lexical_shared_evidence
          WHERE candidate_pair_id IN ({placeholders})
            AND NOT english_derived
            AND evidence_family IN (
              'lemma','root','lemma_ngram','root_ngram','lemma_skipgram','root_skipgram'
            )
        )
        WHERE public_evidence_rank <= 12
        ORDER BY candidate_pair_id, public_evidence_rank, evidence_id
        """,
        list(candidate_ids),
    )
    output: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        output[str(row["candidate_pair_id"])].append(
            {
                "evidence_id": row["evidence_id"],
                "evidence_family": row["evidence_family"],
                "feature_id": row["feature_id"],
                "passage_a_positions": _json_positions(
                    row["passage_a_positions_json"],
                    label="passage A evidence positions",
                ),
                "passage_b_positions": _json_positions(
                    row["passage_b_positions_json"],
                    label="passage B evidence positions",
                ),
                "corpus_frequency": row["corpus_frequency"],
                "document_frequency": row["document_frequency"],
                "passage_a_local_frequency": row["passage_a_local_frequency"],
                "passage_b_local_frequency": row["passage_b_local_frequency"],
                "association_score": row["association_score"],
                "independence_expected_count": row["independence_expected_count"],
                "contains_primary_rare_item": row["contains_primary_rare_item"],
                "counts_as_independent_co_signal": row["counts_as_independent_co_signal"],
            }
        )
    return dict(output)


def _selected_detector_scores(
    connection: duckdb.DuckDBPyConnection,
    candidate_ids: Sequence[str],
) -> dict[str, list[dict[str, object]]]:
    if not candidate_ids:
        return {}
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = _rows(
        connection,
        f"""
        SELECT candidate_pair_id, detector, direction, score, quantized_score,
               query_rank, reverse_rank, score_contribution, penalty_contribution,
               adjusted_score, score_trace_digest
        FROM lexical_candidate_detector_scores
        WHERE candidate_pair_id IN ({placeholders})
        ORDER BY candidate_pair_id,
                 CASE WHEN detector='rrf_composite' THEN 0 ELSE 1 END,
                 detector,
                 direction
        """,
        list(candidate_ids),
    )
    output: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        candidate_id = str(row["candidate_pair_id"])
        if len(output[candidate_id]) >= 24:
            continue
        output[candidate_id].append(
            {
                "detector": row["detector"],
                "direction": row["direction"],
                "score": row["score"],
                "quantized_score": row["quantized_score"],
                "query_rank": row["query_rank"],
                "reverse_rank": row["reverse_rank"],
                "rrf_contribution": row["score_contribution"],
                "penalty_contribution": row["penalty_contribution"],
                "adjusted_score": row["adjusted_score"],
                "score_trace_digest": row["score_trace_digest"],
            }
        )
    return dict(output)


def _selected_thresholds(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, object]]:
    rows = _rows(
        connection,
        """
        SELECT corpus_pair, score_threshold, observed_candidate_count,
               mean_null_candidate_count, null_interval_low, null_interval_high,
               observed_to_null_enrichment, empirical_tail_probability,
               estimated_empirical_fdr
        FROM lexical_threshold_calibration
        WHERE detector='rrf_composite' AND selected
        ORDER BY corpus_pair, score_threshold
        """,
    )
    output: dict[str, dict[str, object]] = {}
    for row in rows:
        corpus_pair = str(row["corpus_pair"])
        if corpus_pair in output:
            raise BuildWeekDemoError(f"multiple selected RRF thresholds exist for {corpus_pair}")
        output[corpus_pair] = row
    return output


def _null_comparison(
    row: Mapping[str, object],
    thresholds: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    threshold = thresholds.get(str(row["corpus_pair"]))
    return {
        "selected_score_threshold": row["selected_score_threshold"],
        "both_null_families_present": row["both_null_families_present"],
        "candidate_empirical_rate": row["null_model_empirical_rate"],
        "candidate_estimated_empirical_fdr": row["estimated_empirical_fdr"],
        "observed_candidate_count": (
            None if threshold is None else threshold["observed_candidate_count"]
        ),
        "mean_null_candidate_count": (
            None if threshold is None else threshold["mean_null_candidate_count"]
        ),
        "empirical_interval_95": (
            None
            if threshold is None
            else [threshold["null_interval_low"], threshold["null_interval_high"]]
        ),
        "observed_to_null_enrichment": (
            None if threshold is None else threshold["observed_to_null_enrichment"]
        ),
        "empirical_tail_probability": (
            None if threshold is None else threshold["empirical_tail_probability"]
        ),
        "threshold_estimated_empirical_fdr": (
            None if threshold is None else threshold["estimated_empirical_fdr"]
        ),
    }


def _pair_payload(
    row: Mapping[str, object],
    *,
    evidence: Mapping[str, list[dict[str, object]]],
    detector_scores: Mapping[str, list[dict[str, object]]],
    thresholds: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    candidate_id = str(row["candidate_pair_id"])
    return {
        "candidate_pair_id": candidate_id,
        "passage_a_reference": row["passage_a_reference"],
        "passage_b_reference": row["passage_b_reference"],
        "corpus_pair": row["corpus_pair"],
        "known_link_status": row["known_link_status"],
        "highest_openbible_vote": row["highest_openbible_vote"],
        "mapping_quality": row["mapping_quality"],
        "review_eligible": row["review_eligible"],
        "eligibility_reason": row["eligibility_reason"],
        "detector_support_count": row["detector_support_count"],
        "directional_support_count": row["directional_support_count"],
        "raw_rrf_score": row["raw_rrf_score"],
        "rrf_score": row["rrf_score"],
        "total_penalty_contribution": row["total_penalty_contribution"],
        "rare_rule_passed": row["rare_rule_passed"],
        "independent_co_signal_count": row["independent_co_signal_count"],
        "shared_lemma_count": row["shared_lemma_count"],
        "shared_root_count": row["shared_root_count"],
        "shared_rare_lemma_count": row["shared_rare_lemma_count"],
        "shared_rare_root_count": row["shared_rare_root_count"],
        "disputed_passage_flag": row["disputed_passage_flag"],
        "reference_gap": row["reference_gap"],
        "ketiv_structural_uncertainty": row["ketiv_structural_uncertainty"],
        "contains_english_derived_evidence": row["contains_english_derived_evidence"],
        "evidence_digest": row["evidence_digest"],
        "shared_lexical_evidence": evidence.get(candidate_id, []),
        "detector_scores": detector_scores.get(candidate_id, []),
        "null_comparison": _null_comparison(row, thresholds),
    }


def _uncertainty_example(row: Mapping[str, object], *, kind: str) -> dict[str, object]:
    return {
        "example_kind": kind,
        "sensitivity_id": row["sensitivity_id"],
        "corpus_pair": row["corpus_pair"],
        "detector": row["detector"],
        "direction": row["direction"],
        "baseline_profile": row["baseline_profile"],
        "comparison_profile": row["comparison_profile"],
        "baseline_reading": row["baseline_reading"],
        "comparison_reading": row["comparison_reading"],
        "query_reference": row["query_reference"],
        "target_reference": row["target_reference"],
        "baseline_query_passage_id": row["baseline_query_passage_id"],
        "comparison_query_passage_id": row["comparison_query_passage_id"],
        "baseline_target_passage_id": row["baseline_target_passage_id"],
        "comparison_target_passage_id": row["comparison_target_passage_id"],
        "baseline_score": row["baseline_score"],
        "comparison_score": row["comparison_score"],
        "score_delta": row["score_delta"],
        "baseline_rank": row["baseline_rank"],
        "comparison_rank": row["comparison_rank"],
        "rank_delta": row["rank_delta"],
        "top_k_overlap": row["top_k_overlap"],
        "affected_locus_count": row["affected_locus_count"],
        "disputed_passage_flag": bool(row.get("disputed_passage_flag", False)),
        "excluded_reason": row["excluded_reason"],
        "baseline_sequence_digest": row["baseline_sequence_digest"],
        "comparison_sequence_digest": row["comparison_sequence_digest"],
        "explanatory_metadata": (
            "Registered Qere-versus-Ketiv sensitivity over an OSHB-affected verse; "
            "the export provides identities and score/sequence changes, not source text."
            if kind == "qere_ketiv"
            else "Registered edition-complete versus critical-core sensitivity incident "
            "to a passage carrying the governed disputed-text flag; no textual judgment."
        ),
    }


def _uncertainty_payload(connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    qere_rows = _rows(
        connection,
        """
        SELECT *, false AS disputed_passage_flag
        FROM lexical_sensitivity_results
        WHERE sensitivity_type='hebrew_qere_ketiv'
          AND affected_locus_count > 0
        ORDER BY CASE WHEN excluded_reason IS NULL THEN 0 ELSE 1 END,
                 abs(score_delta) DESC NULLS LAST,
                 sensitivity_id
        LIMIT 1
        """,
    )
    if not qere_rows:
        raise BuildWeekDemoError("no verified Qere/Ketiv sensitivity example is available")

    disputed_rows = _rows(
        connection,
        """
        SELECT s.*, true AS disputed_passage_flag
        FROM lexical_sensitivity_results s
        LEFT JOIN passages query_passage
          ON query_passage.passage_id=s.baseline_query_passage_id
        LEFT JOIN passages target_passage
          ON target_passage.passage_id=s.baseline_target_passage_id
        WHERE s.sensitivity_type='critical_core_profile'
          AND (
            coalesce(query_passage.disputed_passage_flag, false)
            OR coalesce(target_passage.disputed_passage_flag, false)
          )
        ORDER BY CASE WHEN s.excluded_reason IS NULL THEN 0 ELSE 1 END,
                 abs(s.score_delta) DESC NULLS LAST,
                 s.sensitivity_id
        LIMIT 1
        """,
    )
    examples = [_uncertainty_example(qere_rows[0], kind="qere_ketiv")]
    unavailable: list[str] = []
    if disputed_rows:
        examples.append(
            _uncertainty_example(
                disputed_rows[0],
                kind="critical_core_disputed_profile",
            )
        )
    else:
        unavailable.append(
            "No critical-core sensitivity row incident to a governed disputed passage "
            "was available; no example was fabricated."
        )
    return {
        "export_schema_version": DEMO_EXPORT_SCHEMA_VERSION,
        "selection_procedure": (
            "First row after registered deterministic sorting: comparable rows first, "
            "then maximum absolute score change, then sensitivity ID."
        ),
        "actual_count": len(examples),
        "examples": examples,
        "unavailable_categories": unavailable,
        "no_interpretive_decision": True,
    }


def _overview_payload(
    connection: duckdb.DuckDBPyConnection,
    *,
    metadata: Mapping[str, object],
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
    source_attribution: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    passage_counts = _rows(
        connection,
        """
        SELECT corpus, analysis_profile, analysis_reading, granularity, count(*) AS count
        FROM passages
        WHERE granularity='verse'
          AND (
            (corpus='hebrew' AND analysis_reading IN ('qere','ketiv'))
            OR (corpus='greek' AND analysis_reading='source')
          )
        GROUP BY ALL
        ORDER BY corpus, analysis_profile, analysis_reading
        """,
    )
    benchmark_counts = {
        "tier3_relationships": _scalar(
            connection,
            "SELECT count(*) FROM benchmark_relationships WHERE tier=3",
        ),
        "tier3_endpoints": _scalar(
            connection,
            """
            SELECT count(*)
            FROM benchmark_endpoints e
            JOIN benchmark_relationships r USING(relationship_id)
            WHERE r.tier=3
            """,
        ),
        "tier3_endpoint_mappings": _scalar(
            connection,
            """
            SELECT count(*)
            FROM benchmark_endpoint_mappings m
            JOIN benchmark_endpoints e USING(endpoint_id)
            JOIN benchmark_relationships r USING(relationship_id)
            WHERE r.tier=3
            """,
        ),
        "presumed_negatives": _scalar(
            connection,
            "SELECT count(*) FROM benchmark_presumed_negatives",
        ),
    }
    null_summary = _rows(
        connection,
        """
        SELECT null_family,
               count(*) AS replicate_threshold_rows,
               count(DISTINCT iteration) AS iteration_count,
               count(DISTINCT seed) AS unique_seed_count,
               count(DISTINCT corpus_pair) AS corpus_pair_count,
               count(DISTINCT detector) AS detector_count,
               count(DISTINCT threshold_id) AS threshold_count,
               min(passage_count) AS minimum_passage_count,
               max(passage_count) AS maximum_passage_count,
               min(token_count) AS minimum_token_count,
               max(token_count) AS maximum_token_count
        FROM lexical_null_replicates
        GROUP BY null_family
        ORDER BY null_family
        """,
    )
    candidate_counts = _rows(
        connection,
        """
        SELECT corpus_pair, known_link_status, count(*) AS candidate_count,
               count(*) FILTER (WHERE review_eligible) AS review_eligible_count
        FROM lexical_candidate_pairs
        GROUP BY corpus_pair, known_link_status
        ORDER BY corpus_pair, known_link_status
        """,
    )
    performance = _rows(
        connection,
        """
        SELECT analysis_profile, corpus_pair, detector, ranking_role,
               comparison_baseline, metric, k, value,
               bootstrap_interval_low, bootstrap_interval_high,
               eligible_query_count, eligible_relationship_count
        FROM lexical_evaluation_results
        WHERE analysis_profile='edition_complete'
          AND stratum_dimension='global'
          AND detector IN ('rrf_composite','random','unweighted_overlap')
          AND metric IN (
            'recall_at_20',
            'recall_at_20_difference_vs_random',
            'recall_at_20_difference_vs_unweighted_overlap'
          )
        ORDER BY corpus_pair, detector, metric
        """,
    )
    feature_coverage = _rows(
        connection,
        """
        SELECT language_namespace, feature_family, count(*) AS feature_count,
               sum(corpus_frequency) AS corpus_frequency_total,
               sum(CASE WHEN is_rare THEN 1 ELSE 0 END) AS rare_feature_count
        FROM lexical_feature_vocabulary
        WHERE feature_family IN ('lemma','root')
        GROUP BY language_namespace, feature_family
        ORDER BY language_namespace, feature_family
        """,
    )
    run_identity = {
        "lexical_run_id": metadata["experiment_run_id"],
        "lexical_experiment_version": metadata["experiment_version"],
        "passage_run_id": preregistration.inputs.passages.run_id,
        "benchmark_run_id": preregistration.inputs.benchmark.run_id,
        "benchmark_version": preregistration.inputs.benchmark.version,
        "configuration_sha256": metadata["configuration_hash"],
        "preregistration_sha256": metadata["preregistration_hash"],
        "input_corpus_hashes": _json_object(
            metadata["input_corpus_hashes_json"],
            label="metadata input corpus hashes",
        ),
        "passage_hashes": _json_object(
            metadata["passage_hashes_json"],
            label="metadata passage hashes",
        ),
        "benchmark_hashes": _json_object(
            metadata["benchmark_hashes_json"],
            label="metadata benchmark hashes",
        ),
        "acceptance_status": metadata["acceptance_status"],
    }
    return {
        "export_schema_version": DEMO_EXPORT_SCHEMA_VERSION,
        "export_name": "echoes-demo-v1",
        "run_identity": run_identity,
        "corpus_counts": {
            "hebrew_tokens": preregistration.inputs.hebrew.token_count,
            "greek_tokens": preregistration.inputs.greek.token_count,
        },
        "passage_counts": passage_counts,
        "benchmark_counts": benchmark_counts,
        "detectors": [*config.enabled_detectors, "rrf_composite"],
        "feature_coverage": feature_coverage,
        "null_model_summary": {
            "calibration_pair_sample_size": config.null_models.calibration_pair_sample_size,
            "calibration_pair_scope": config.null_models.calibration_pair_scope,
            "registered_iterations_per_family": config.null_models.iterations_per_family,
            "families": null_summary,
        },
        "candidate_counts": candidate_counts,
        "tier3_global_performance": performance,
        "source_attribution": list(source_attribution),
        "scientific_caveats": [
            "OpenBible is Tier 3 weak supervision, not scholarly ground truth.",
            "A recovered relationship is a retrieval result, not proof of quotation, "
            "dependence, intention, interpretation, or novelty.",
            "Public lexical evidence uses stable feature IDs because complete MACULA "
            "annotation values are not approved for tracked redistribution.",
            "The pinned full corpora contain no governed root annotations; zero production "
            "root evidence is reported rather than fabricated.",
            "Cross-testament English-gloss retrieval is excluded from the public pair lists.",
        ],
        "no_candidate_review": True,
    }


def _build_payloads(
    connection: duckdb.DuckDBPyConnection,
    *,
    metadata: Mapping[str, object],
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
    source_attribution: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    known_rows, unreviewed_rows = _selected_candidate_rows(connection)
    all_ids = [str(row["candidate_pair_id"]) for row in (*known_rows, *unreviewed_rows)]
    evidence = _selected_evidence(connection, all_ids)
    scores = _selected_detector_scores(connection, all_ids)
    thresholds = _selected_thresholds(connection)
    known_pairs = [
        _pair_payload(row, evidence=evidence, detector_scores=scores, thresholds=thresholds)
        for row in known_rows
    ]
    unreviewed_pairs = [
        _pair_payload(row, evidence=evidence, detector_scores=scores, thresholds=thresholds)
        for row in unreviewed_rows
    ]
    payloads: dict[str, object] = {
        "overview.json": _overview_payload(
            connection,
            metadata=metadata,
            config=config,
            preregistration=preregistration,
            source_attribution=source_attribution,
        ),
        "known-recoveries.json": {
            "export_schema_version": DEMO_EXPORT_SCHEMA_VERSION,
            "selection_procedure": (
                "Ten highest penalty-adjusted RRF original-language candidates per "
                "HB-HB and GNT-GNT corpus pair after filtering to pairs represented in "
                "the pinned OpenBible snapshot and requiring shared lemma/root evidence; "
                "ties use candidate ID."
            ),
            "requested_count": 20,
            "actual_count": len(known_pairs),
            "no_candidate_review": True,
            "scientific_caveat": (
                "These are Tier 3 weak-supervision recoveries, not verified quotations "
                "or interpretive judgments."
            ),
            "pairs": known_pairs,
        },
        "unreviewed-candidates.json": {
            "export_schema_version": DEMO_EXPORT_SCHEMA_VERSION,
            "selection_procedure": (
                "First fifty original-language, OpenBible-unrepresented rows in the "
                "frozen unreviewed candidate queue after requiring shared lemma/root "
                "evidence; order is queue rank then candidate ID."
            ),
            "requested_count": 50,
            "actual_count": len(unreviewed_pairs),
            "no_candidate_review": True,
            "scientific_caveat": (
                "Not represented in the pinned OpenBible snapshot is a bounded knownness "
                "statement, not a novelty claim."
            ),
            "pairs": unreviewed_pairs,
        },
        "textual-uncertainty-examples.json": _uncertainty_payload(connection),
    }
    validate_public_demo_payloads(payloads)
    return payloads


def _manifest_payload(
    *,
    metadata: Mapping[str, object],
    preregistration: LexicalExperimentPreregistration,
    source_attribution: Sequence[Mapping[str, object]],
    data_payloads: Mapping[str, bytes],
    known_count: int,
    unreviewed_count: int,
    uncertainty_count: int,
) -> dict[str, object]:
    return {
        "export_schema_version": DEMO_EXPORT_SCHEMA_VERSION,
        "export_name": "echoes-demo-v1",
        "lexical_run_id": metadata["experiment_run_id"],
        "passage_run_id": preregistration.inputs.passages.run_id,
        "benchmark_run_id": preregistration.inputs.benchmark.run_id,
        "configuration_sha256": metadata["configuration_hash"],
        "preregistration_sha256": metadata["preregistration_hash"],
        "source_attribution": list(source_attribution),
        "generated_file_sha256": {
            name: _sha256_bytes(payload) for name, payload in sorted(data_payloads.items())
        },
        "export_counts": {
            "known_recoveries": known_count,
            "unreviewed_candidates": unreviewed_count,
            "textual_uncertainty_examples": uncertainty_count,
        },
        "public_field_policy": (
            "References, stable IDs, token-relative positions, aggregate frequencies, "
            "scores, ranks, flags, hashes, and attribution only. Source lexical values, "
            "text, glosses, morphology strings, raw records, and local paths are prohibited."
        ),
        "no_candidate_review": True,
        "milestone_8_started": False,
    }


def _validate_output_root(path: Path) -> Path:
    resolved = path.resolve()
    expected = ("demo", "data", "echoes-demo-v1")
    if tuple(part.casefold() for part in resolved.parts[-3:]) != expected:
        raise BuildWeekDemoError(
            "demo output must be the governed demo/data/echoes-demo-v1 directory"
        )
    return resolved


def export_build_week_demo(
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_root: Path = DEFAULT_EXPORT_ROOT,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    force: bool = False,
) -> BuildWeekDemoArtifacts:
    """Generate and atomically publish the authenticated public demonstration bundle."""

    processed_from_directory(artifact_root)
    metadata_frame = read_artifact_frame(artifact_root, "lexical_metadata")
    if metadata_frame.height != 1:
        raise BuildWeekDemoError("lexical metadata must contain exactly one row")
    metadata = metadata_frame.row(0, named=True)
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    validate_preregistration_against_config(preregistration, config)
    _validate_metadata(metadata, config=config, preregistration=preregistration)
    attribution = _source_attribution(source_manifest_path)

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            connection.execute("SET threads=1")
            connection.execute("SET memory_limit='1GB'")
            database_run = connection.execute(
                "SELECT experiment_run_id FROM lexical_metadata"
            ).fetchall()
            if database_run != [(metadata["experiment_run_id"],)]:
                raise BuildWeekDemoError(
                    "DuckDB lexical views do not expose the authenticated artifact run"
                )
            payloads = _build_payloads(
                connection,
                metadata=metadata,
                config=config,
                preregistration=preregistration,
                source_attribution=attribution,
            )
    except duckdb.Error as exc:
        raise BuildWeekDemoError(f"could not query validated lexical artifacts: {exc}") from exc

    data_payloads = {name: _canonical_json_bytes(payloads[name]) for name in DEMO_DATA_FILENAMES}
    known_count = len(
        cast(dict[str, object], payloads["known-recoveries.json"])["pairs"]  # type: ignore[arg-type]
    )
    unreviewed_count = len(
        cast(dict[str, object], payloads["unreviewed-candidates.json"])["pairs"]  # type: ignore[arg-type]
    )
    uncertainty_count = len(
        cast(dict[str, object], payloads["textual-uncertainty-examples.json"])["examples"]  # type: ignore[arg-type]
    )
    manifest = _manifest_payload(
        metadata=metadata,
        preregistration=preregistration,
        source_attribution=attribution,
        data_payloads=data_payloads,
        known_count=known_count,
        unreviewed_count=unreviewed_count,
        uncertainty_count=uncertainty_count,
    )
    _validate_manifest(manifest, data_payloads)
    manifest_bytes = _canonical_json_bytes(manifest)

    destination = _validate_output_root(output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        raise BuildWeekDemoError(
            f"refusing to overwrite existing demo export at {destination}; pass force=True"
        )
    token = uuid4().hex
    staging = destination.parent / f".{destination.name}.writing-{token}"
    backup = destination.parent / f".{destination.name}.backup-{token}"
    staging.mkdir()
    try:
        for name, payload in data_payloads.items():
            (staging / name).write_bytes(payload)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        if destination.exists():
            destination.replace(backup)
        try:
            staging.replace(destination)
        except OSError:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise BuildWeekDemoError(f"could not publish demo export: {exc}") from exc

    sha256_by_name = {
        **{name: _sha256_bytes(payload) for name, payload in data_payloads.items()},
        "manifest.json": _sha256_bytes(manifest_bytes),
    }
    return BuildWeekDemoArtifacts(
        output_root=destination,
        lexical_run_id=str(metadata["experiment_run_id"]),
        known_recovery_count=known_count,
        unreviewed_candidate_count=unreviewed_count,
        uncertainty_example_count=uncertainty_count,
        sha256_by_name=sha256_by_name,
    )
