"""Authenticate M7 null execution separately from its threshold-selection sentinel.

The canonical candidate flag is false when no frozen RRF threshold qualified,
even though both source null experiments ran.  This read-only audit verifies the
actual retained null runs and binds every allowed trace to its canonical row.
Neither the canonical projection nor its million-row ordering receipt changes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import duckdb
import polars as pl

from echoes.lexical.config import LexicalConfig, lexical_config_sha256, load_lexical_config
from echoes.lexical.models import LEXICAL_ARTIFACT_SCHEMAS, LexicalArtifactName
from echoes.lexical.validation import (
    _candidate_calibration_provenance_mismatches,
    _State,
    _validate_nulls_and_calibration,
)
from echoes.manifest import sha256_file

_TABLES: tuple[LexicalArtifactName, ...] = (
    "candidate_pairs",
    "candidate_evidence",
    "candidate_detector_scores",
    "null_replicate_summaries",
    "threshold_calibration",
)
_PROJECTION_TABLES = ("candidate_pairs", "candidate_evidence", "shared_evidence")
_FAMILIES = ("frequency_preserving_synthetic", "within_book_reassignment")
_SENTINEL = "positive_infinity_no_qualified_threshold"
# SHA-256 membership keys keep the canonical 1,248,779-row population bounded.
_MAXIMUM_CANDIDATES = 2_000_000
_TRACE_FIELDS = (
    "m7_candidate_pair_id",
    "m7_passage_references",
    "raw_rrf_score",
    "rrf_score",
    "m7_empirical_fdr",
    "m7_bh_q_value",
    "m7_both_null_families_present",
    "m7_detector_trace_digest",
    "m7_evidence_digest",
    "m7_ablation_digest",
)


class M7NullProvenanceError(ValueError):
    """Source null execution or a candidate's retained outcome is unauthenticated."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _trace_key(trace: Mapping[str, object]) -> bytes:
    try:
        payload = {name: trace[name] for name in _TRACE_FIELDS}
        if type(payload["m7_both_null_families_present"]) is not bool:
            raise ValueError("source threshold flag must be a Boolean")
        return hashlib.sha256(_canonical(payload).encode("ascii")).digest()
    except (KeyError, TypeError, ValueError) as exc:
        raise M7NullProvenanceError("M7 trace omits valid canonical calibration facts") from exc


@dataclass(frozen=True, slots=True)
class M7NullProvenance:
    """Immutable, in-memory authentication context; receipts alone grant no trust."""

    source_manifest_sha256: str
    _logical_json: str = field(repr=False)
    _counts_json: str = field(repr=False)
    _membership: frozenset[bytes] = field(repr=False)
    _receipt_json: str = field(repr=False)

    @property
    def receipt(self) -> dict[str, object]:
        """Return a portable proof summary without mutable authentication state."""
        return cast(dict[str, object], json.loads(self._receipt_json))

    @property
    def provenance_sha256(self) -> str:
        """Identify the canonical portable receipt without its file formatting."""
        return hashlib.sha256(self._receipt_json.encode("ascii")).hexdigest()

    def validate_trace(self, trace: Mapping[str, object], source_artifact_sha256: str) -> None:
        """Require exact source bindings and a canonical candidate calibration row."""
        try:
            logical_json = _canonical(trace.get("m7_source_table_logical_sha256"))
            counts_json = _canonical(trace.get("m7_projection_audit_counts"))
        except (TypeError, ValueError) as exc:
            raise M7NullProvenanceError("M7 trace source bindings are not canonicalizable") from exc
        if (
            source_artifact_sha256 != self.source_manifest_sha256
            or trace.get("m7_source_manifest_sha256") != self.source_manifest_sha256
            or trace.get("representation") != "canonical_m7_reciprocal_rank_fusion"
            or logical_json != self._logical_json
            or counts_json != self._counts_json
        ):
            raise M7NullProvenanceError("M7 trace does not bind the authenticated source manifest")
        if _trace_key(trace) not in self._membership:
            raise M7NullProvenanceError(
                "M7 trace does not match an authenticated candidate outcome"
            )


def _manifest(
    root: Path, expected_sha256: str
) -> tuple[dict[str, Any], dict[str, list[Path]], dict[str, str]]:
    path = root / "table-hashes.json"
    if root.is_symlink() or path.is_symlink() or not path.is_file():
        raise M7NullProvenanceError("M7 null provenance requires a regular source manifest")
    if sha256_file(path) != expected_sha256:
        raise M7NullProvenanceError("M7 null source manifest SHA-256 mismatch")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise M7NullProvenanceError("M7 null source manifest schema is invalid")
    for key in ("table_counts", "table_logical_sha256", "file_sha256"):
        if not isinstance(value.get(key), dict):
            raise M7NullProvenanceError(f"M7 source manifest omits {key}")
    for name in {*_TABLES, *_PROJECTION_TABLES}:
        count = value["table_counts"].get(name)
        digest = value["table_logical_sha256"].get(name)
        if type(count) is not int or count < 0 or not _is_sha256(digest):
            raise M7NullProvenanceError(f"M7 source manifest has invalid bindings for {name}")
    files: dict[str, list[Path]] = {name: [] for name in _TABLES}
    verified: dict[str, str] = {}
    for name in _TABLES:
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            raise M7NullProvenanceError(f"M7 source table directory is invalid: {name}")
        names = {
            relative: digest
            for relative, digest in value["file_sha256"].items()
            if isinstance(relative, str) and relative.startswith(name + "/")
        }
        actual = {item.relative_to(root).as_posix() for item in directory.rglob("*.parquet")}
        if not names or set(names) != actual:
            raise M7NullProvenanceError(f"M7 source Parquet inventory mismatch: {name}")
        for relative, digest in sorted(names.items()):
            leaf = root / relative
            if (
                not _is_sha256(digest)
                or leaf.is_symlink()
                or leaf.parent != directory
                or not leaf.name.startswith("part-")
                or leaf.suffix != ".parquet"
                or not leaf.is_file()
                or not leaf.resolve().is_relative_to(root)
            ):
                raise M7NullProvenanceError(f"M7 source leaf is not canonical: {relative}")
            if sha256_file(leaf) != digest:
                raise M7NullProvenanceError(f"M7 source file hash mismatch: {relative}")
            if pl.scan_parquet(leaf).collect_schema() != LEXICAL_ARTIFACT_SCHEMAS[name]:
                raise M7NullProvenanceError(f"M7 source schema mismatch: {relative}")
            files[name].append(leaf)
            verified[relative] = digest
    return value, files, verified


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise M7NullProvenanceError("M7 provenance audit returned no result")
    return int(row[0])


def _audit_candidates(
    connection: duckdb.DuckDBPyConnection, expected_count: int, config: LexicalConfig
) -> None:
    for name in ("candidate_pairs", "candidate_evidence"):
        if (
            _scalar(
                connection,
                f"SELECT count(DISTINCT candidate_pair_id) FROM {name} "
                "WHERE candidate_pair_id IS NOT NULL AND candidate_pair_id<>''",
            )
            != expected_count
        ):
            raise M7NullProvenanceError(f"M7 source candidate identities are invalid: {name}")
    invalid = _scalar(
        connection,
        f"""
        SELECT count(*) FROM candidate_pairs p
        FULL JOIN candidate_evidence e USING(candidate_pair_id)
        WHERE p.candidate_pair_id IS NULL OR e.candidate_pair_id IS NULL
           OR p.passage_a_id IS NULL OR p.passage_b_id IS NULL
           OR p.passage_a_id>=p.passage_b_id
           OR p.passage_a_reference IS NULL OR p.passage_b_reference IS NULL
           OR p.corpus_pair IS NULL OR p.corpus_pair=''
           OR p.analysis_profile IS DISTINCT FROM '{config.primary_scope.analysis_profile}'
           OR p.review_eligible IS NULL OR e.both_null_families_present IS NULL
           OR e.selected_score_threshold IS NULL OR e.estimated_empirical_fdr IS NULL
           OR e.null_model_empirical_rate IS NULL OR e.calibration_selection_scope IS NULL
           OR p.passage_a_reference='' OR p.passage_b_reference=''
           OR e.raw_rrf_score IS NULL OR NOT isfinite(e.raw_rrf_score) OR e.raw_rrf_score<0
           OR e.rrf_score IS NULL OR NOT isfinite(e.rrf_score) OR e.rrf_score<0
           OR e.benjamini_hochberg_q_value IS NULL
           OR NOT isfinite(e.benjamini_hochberg_q_value)
           OR e.benjamini_hochberg_q_value<0 OR e.benjamini_hochberg_q_value>1
           OR e.detector_trace_digest IS NULL OR e.evidence_digest IS NULL
           OR e.ablation_digest IS NULL
           OR NOT regexp_full_match(e.detector_trace_digest,'[a-f0-9]{{64}}')
           OR NOT regexp_full_match(e.evidence_digest,'[a-f0-9]{{64}}')
           OR NOT regexp_full_match(e.ablation_digest,'[a-f0-9]{{64}}')
        """,
    )
    invalid += _scalar(
        connection,
        """
        SELECT count(*) FROM (
            SELECT p.candidate_pair_id, count(s.candidate_pair_id) AS n
            FROM candidate_pairs p FULL JOIN (
                SELECT candidate_pair_id FROM candidate_detector_scores
                WHERE detector='rrf_composite'
            ) s ON p.candidate_pair_id=s.candidate_pair_id
            GROUP BY p.candidate_pair_id
            HAVING p.candidate_pair_id IS NULL OR n<>1
        )
        """,
    )
    invalid += _scalar(
        connection,
        "SELECT count(*) FROM candidate_detector_scores WHERE detector='rrf_composite' "
        "AND (representation_id IS NULL OR representation_id='')",
    )
    if invalid:
        raise M7NullProvenanceError("M7 candidate-to-RRF calibration membership is inconsistent")


def authenticate_m7_null_provenance(
    input_root: Path,
    *,
    expected_manifest_sha256: str,
    memory_limit_bytes: int = 1024**3,
    temp_directory: Path,
) -> M7NullProvenance:
    """Authenticate source RRF nulls and all canonical candidate outcomes once.

    Only the five relevant canonical tables are read.  Physical hashes against
    the pinned manifest authenticate their declared logical identities; the
    source null validator reproduces RRF outcomes from retained replicate counts.
    All writes are DuckDB scratch under the caller's separate temporary directory.
    """
    if memory_limit_bytes < 256 * 1024**2:
        raise M7NullProvenanceError("M7 null audit requires at least 256 MiB DuckDB memory")
    if input_root.is_symlink():
        raise M7NullProvenanceError("M7 null input root must not be a symlink")
    root = input_root.resolve()
    scratch = temp_directory.resolve()
    if scratch == root or scratch.is_relative_to(root):
        raise M7NullProvenanceError("M7 null audit scratch must be outside the source tree")
    manifest, files, verified = _manifest(root, expected_manifest_sha256)
    count = manifest["table_counts"]["candidate_pairs"]
    if not 1 <= count <= _MAXIMUM_CANDIDATES:
        raise M7NullProvenanceError("M7 candidate population exceeds bounded authentication scope")
    if manifest["table_counts"]["candidate_evidence"] != count:
        raise M7NullProvenanceError("M7 source candidate and evidence counts differ")
    scratch.mkdir(parents=True, exist_ok=True)
    config = load_lexical_config()
    membership: set[bytes] = set()
    membership_digest = hashlib.sha256()
    with duckdb.connect() as connection:
        connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
        connection.execute("SET threads=1")
        connection.execute("SET temp_directory=?", [scratch.as_posix()])
        for name in _TABLES:
            connection.read_parquet([path.as_posix() for path in files[name]]).create_view(name)
            if (
                _scalar(connection, f"SELECT count(*) FROM {name}")
                != manifest["table_counts"][name]
            ):
                raise M7NullProvenanceError(f"M7 source table count mismatch: {name}")
        _audit_candidates(connection, count, config)
        # Reuse the existing scientific validator for the consumed RRF detector.
        # Candidate lineage supplies the independently authenticated required strata.
        connection.execute(
            "CREATE VIEW directional_rankings AS SELECT DISTINCT p.corpus_pair, "
            "s.representation_id,s.detector,p.analysis_profile,'primary' AS experiment_scope "
            "FROM candidate_pairs p JOIN candidate_detector_scores s USING(candidate_pair_id) "
            "WHERE s.detector='rrf_composite'"
        )
        for name in ("null_replicate_summaries", "threshold_calibration"):
            connection.execute(f"CREATE TEMP TABLE source_{name} AS SELECT * FROM {name}")
            connection.execute(f"DROP VIEW {name}")
            connection.execute(
                f"CREATE VIEW {name} AS SELECT * FROM source_{name} WHERE detector='rrf_composite'"
            )
        invalid_iterations = _scalar(
            connection,
            "SELECT count(*) FROM null_replicate_summaries WHERE iteration IS NULL "
            f"OR iteration<1 OR iteration>{config.null_models.iterations_per_family}",
        )
        if invalid_iterations:
            raise M7NullProvenanceError("M7 source null iteration identities are invalid")
        expected_replicates = 2 * config.null_models.iterations_per_family
        if _scalar(connection, "SELECT count(*) FROM null_replicate_summaries") != (
            expected_replicates * _scalar(connection, "SELECT count(*) FROM threshold_calibration")
        ):
            raise M7NullProvenanceError("M7 source null threshold coverage is not exact")
        incomplete_families = _scalar(
            connection,
            f"""
            WITH required AS (
                SELECT t.*,f.null_family FROM threshold_calibration t
                CROSS JOIN (VALUES ('within_book_reassignment'),
                                   ('frequency_preserving_synthetic')) f(null_family)
            ), observed AS (
                SELECT corpus_pair,representation_id,detector,threshold_id,null_family,
                       count(*) AS n,count(DISTINCT iteration) AS iterations
                FROM null_replicate_summaries GROUP BY ALL
            )
            SELECT count(*) FROM required r LEFT JOIN observed o
            USING(corpus_pair,representation_id,detector,threshold_id,null_family)
            WHERE o.n IS DISTINCT FROM {config.null_models.iterations_per_family}
               OR o.iterations IS DISTINCT FROM {config.null_models.iterations_per_family}
            """,
        )
        if incomplete_families:
            raise M7NullProvenanceError(
                "M7 source must retain both complete null families per threshold"
            )
        state = _State(output_dir=root, strict=True)
        _validate_nulls_and_calibration(state, connection, config)
        if state.issues:
            codes = ",".join(sorted({issue.code for issue in state.issues}))
            raise M7NullProvenanceError(f"M7 source RRF null calibration failed: {codes}")
        if _candidate_calibration_provenance_mismatches(connection, config):
            raise M7NullProvenanceError(
                "M7 candidate threshold outcome contradicts source calibration"
            )
        strata = [
            {
                "corpus_pair": pair,
                "representation_id": representation,
                "threshold_count": thresholds,
                "selected_threshold_count": selected,
            }
            for pair, representation, thresholds, selected in connection.execute(
                "SELECT corpus_pair,representation_id,count(*),count(*) FILTER(WHERE selected) "
                "FROM threshold_calibration GROUP BY ALL ORDER BY corpus_pair,representation_id"
            ).fetchall()
        ]
        source_rows = connection.execute(
            "SELECT p.candidate_pair_id,p.passage_a_id,p.passage_b_id,"
            "p.passage_a_reference,p.passage_b_reference,e.raw_rrf_score,e.rrf_score,"
            "e.estimated_empirical_fdr,e.benjamini_hochberg_q_value,"
            "e.both_null_families_present,e.detector_trace_digest,e.evidence_digest,"
            "e.ablation_digest FROM candidate_pairs p JOIN candidate_evidence e "
            "USING(candidate_pair_id) ORDER BY p.candidate_pair_id"
        ).to_arrow_reader(batch_size=8192)
        false_count = 0
        for batch in source_rows:
            for row in batch.to_pylist():
                fdr = row["estimated_empirical_fdr"]
                facts = dict(
                    zip(
                        _TRACE_FIELDS,
                        (
                            row["candidate_pair_id"],
                            {
                                row["passage_a_id"]: row["passage_a_reference"],
                                row["passage_b_id"]: row["passage_b_reference"],
                            },
                            row["raw_rrf_score"],
                            row["rrf_score"],
                            fdr if math.isfinite(fdr) else _SENTINEL,
                            row["benjamini_hochberg_q_value"],
                            row["both_null_families_present"],
                            row["detector_trace_digest"],
                            row["evidence_digest"],
                            row["ablation_digest"],
                        ),
                        strict=True,
                    )
                )
                key = _trace_key(facts)
                membership.add(key)
                membership_digest.update(key)
                false_count += not row["both_null_families_present"]
    if len(membership) != count:
        raise M7NullProvenanceError("M7 authenticated candidate membership count differs")
    logical = {name: manifest["table_logical_sha256"][name] for name in _PROJECTION_TABLES}
    counts = {name: manifest["table_counts"][name] for name in _PROJECTION_TABLES}
    receipt = {
        "schema_version": "m7-source-null-provenance-v1",
        "source_manifest_sha256": expected_manifest_sha256,
        "lexical_configuration_sha256": lexical_config_sha256(config),
        "source_null_families": _FAMILIES,
        "iterations_per_family": config.null_models.iterations_per_family,
        "verified_file_sha256": verified,
        "table_counts": {name: manifest["table_counts"][name] for name in _TABLES},
        "table_logical_sha256": {name: manifest["table_logical_sha256"][name] for name in _TABLES},
        "rrf_strata": strata,
        "candidate_count": count,
        "no_qualified_threshold_candidate_count": false_count,
        "candidate_membership_sha256": membership_digest.hexdigest(),
        "membership_ordering": "canonical_m7_candidate_pair_id",
        "source_null_execution_authenticated": True,
        "canonical_candidate_values_preserved": True,
    }
    return M7NullProvenance(
        expected_manifest_sha256,
        _canonical(logical),
        _canonical(counts),
        frozenset(membership),
        _canonical(receipt),
    )
