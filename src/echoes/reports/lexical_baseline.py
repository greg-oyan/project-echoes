"""Deterministic, sanitized Milestone 7 lexical-baseline reporting.

The report bundle is derived from the governed Parquet artifacts.  It never
reconstructs passages and never exports feature values or source-token text.
Missing artifacts, malformed schemas, unauthenticated preregistration, and
missing two-run evidence remain explicit failures rather than being inferred
away by presentation code.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

import polars as pl

from echoes.lexical.config import (
    LEXICAL_CONFIG_PATH,
    LEXICAL_PREREGISTRATION_PATH,
    LexicalConfig,
    LexicalExperimentPreregistration,
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    validate_preregistration_against_config,
)
from echoes.lexical.models import (
    LEXICAL_ARTIFACT_COLUMNS,
    LEXICAL_ARTIFACT_NAMES,
    LexicalArtifactName,
)
from echoes.lexical.storage import TABLE_HASH_FILE, processed_from_directory
from echoes.lexical.validation import LexicalValidationReport, validate_lexical_artifacts
from echoes.manifest import sha256_file

DEFAULT_LEXICAL_ARTIFACT_ROOT: Final = Path("data/processed/lexical/schema-v1")
DEFAULT_REPORT_DIRECTORY: Final = Path("outputs/reports")
DEFAULT_SPOT_CHECK_CONFIG: Final = Path("outputs/reports/m7-spot-check-config.json")
DEFAULT_FIRST_RUN_MANIFEST: Final = Path(
    "data/processed/lexical/m7-first-run-reference/table-hashes.json"
)
PR7_MERGE_COMMIT: Final = "b9637ee2de1840cbc2056dfcec6aea163d1e9194"

REPORT_OUTPUT_NAMES: Final[tuple[str, ...]] = (
    "milestone-7-lexical-baseline-report.md",
    "m7-feature-counts.csv",
    "m7-detector-performance.csv",
    "m7-performance-by-stratum.csv",
    "m7-null-calibration.csv",
    "m7-thresholds.csv",
    "m7-rare-rule-effects.csv",
    "m7-english-ablation.csv",
    "m7-unreviewed-candidate-queue.csv",
    "m7-spot-check-evidence.md",
)

REQUIRED_FEATURE_AUDIT: Final = "m7-lexical-feature-audit.md"

DETECTOR_FORMULAS: Final[tuple[tuple[str, str], ...]] = (
    ("jaccard", "|A intersection B| / |A union B| over binary lexical features"),
    (
        "weighted_jaccard",
        "sum IDF(f) min(tf_a,tf_b) / sum IDF(f) max(tf_a,tf_b)",
    ),
    ("tfidf_cosine", "cosine of L2-normalized sublinear-TF, smoothed-IDF CSR rows"),
    (
        "bm25",
        "BM25 with k1=1.2, b=0.75 and binary query term frequency",
    ),
    (
        "rare_lemma_root",
        "sum inverse corpus frequency for shared configured-rare lemmas or roots",
    ),
    ("phrase_association", "shared registered n-gram PMI/log-likelihood and skip-grams"),
    (
        "longest_common_subsequence",
        "ordered lexical LCS length normalized by the shorter eligible sequence",
    ),
    (
        "weighted_sequence_alignment",
        "local ordered alignment with rarity weights and registered gap/mismatch penalties",
    ),
    (
        "pos_morphology_support",
        "independent ordered POS/morphology support; never primary lexical equivalence",
    ),
    (
        "rrf_composite",
        "sum 1/(60+rank) using the best contribution per independent detector family",
    ),
)

REQUIRED_ABLATIONS: Final[frozenset[str]] = frozenset(
    {
        "remove_tfidf",
        "remove_bm25",
        "remove_rare_evidence",
        "remove_phrase_evidence",
        "remove_ordered_sequence",
        "remove_formulaic_penalty",
        "remove_local_context_penalty",
        "remove_all_english_derived_features",
    }
)
REQUIRED_SENSITIVITIES: Final[frozenset[str]] = frozenset(
    {"critical_core_profile", "hebrew_qere_ketiv"}
)

_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_COMMIT_RE: Final = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
_PASSAGE_REFERENCE_RE: Final = re.compile(
    r"^P_(?:HB|GNT)_.+?_VERSE_([A-Z0-9]{3})_(\d{3})_(\d{3})~[a-f0-9]{64}$"
)


class LexicalReportError(RuntimeError):
    """Raised when a truthful, complete report bundle cannot be generated."""


@dataclass(frozen=True, slots=True)
class SpotPredicate:
    """One strict predicate in the reproducible structural spot-check registry."""

    column: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "contains"]
    value: str | int | float | bool


@dataclass(frozen=True, slots=True)
class SpotCriterion:
    """A deterministic, non-interpretive candidate selection contract."""

    check_id: str
    category: str
    description: str
    predicates: tuple[SpotPredicate, ...]
    sort_column: str
    sort_order: Literal["ascending", "descending"]
    expected_presence: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class SpotSelection:
    """The result of applying one registered spot-check criterion."""

    criterion: SpotCriterion
    candidate: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class DeterminismEvidence:
    """Comparison of the first and second complete lexical artifact manifests."""

    status: Literal["passed", "failed", "not_verified"]
    logical_hashes_match: bool
    physical_hashes_match: bool
    first_manifest_path: str | None
    differing_logical_tables: tuple[str, ...]
    differing_physical_tables: tuple[str, ...]
    run_ids_match: bool
    first_run_id: str | None
    second_run_id: str | None
    first_runtime_seconds: float | None
    second_runtime_seconds: float | None
    first_stage_runtime_seconds: dict[str, float]
    second_stage_runtime_seconds: dict[str, float]
    first_peak_memory_bytes: int | None
    second_peak_memory_bytes: int | None
    first_storage_footprint_bytes: int | None
    second_storage_footprint_bytes: int | None


@dataclass(frozen=True, slots=True)
class RunTelemetry:
    """Nondeterministic runtime provenance retained outside logical identity."""

    experiment_run_id: str
    runtime_seconds: float
    stage_runtime_seconds: dict[str, float]
    peak_memory_bytes: int
    storage_footprint_bytes: int


@dataclass(frozen=True, slots=True)
class LexicalReportTables:
    """Sanitized frames and report-only aggregate evidence."""

    metadata: dict[str, object]
    feature_counts: pl.DataFrame
    indexes: pl.DataFrame
    detector_performance: pl.DataFrame
    performance_by_stratum: pl.DataFrame
    failed_performance: pl.DataFrame
    null_calibration: pl.DataFrame
    thresholds: pl.DataFrame
    rare_rule_effects: pl.DataFrame
    english_ablation: pl.DataFrame
    ablation_summary: pl.DataFrame
    sensitivity_summary: pl.DataFrame
    queue: pl.DataFrame
    candidate_counts: pl.DataFrame
    detector_score_distributions: pl.DataFrame
    issue_counts: pl.DataFrame
    spot_selections: tuple[SpotSelection, ...]
    spot_detector_scores: pl.DataFrame
    spot_shared_evidence: pl.DataFrame
    spot_calibration: pl.DataFrame


@dataclass(frozen=True, slots=True)
class LexicalReportArtifacts:
    """Paths, hashes, and the conservative gate result for one report bundle."""

    paths: tuple[Path, ...]
    sha256_by_name: dict[str, str]
    acceptance_gate_passed: bool
    determinism: DeterminismEvidence


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if not isinstance(value, str):
        raise LexicalReportError(f"{label} must be a JSON object string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LexicalReportError(f"{label} is malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LexicalReportError(f"{label} must encode a JSON object")
    return {str(key): item for key, item in parsed.items()}


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalReportError(f"could not read lexical hash manifest {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LexicalReportError(f"lexical hash manifest is not an object: {path}")
    for field in ("table_counts", "table_logical_sha256", "table_physical_sha256"):
        value = parsed.get(field)
        if not isinstance(value, dict) or set(value) != set(LEXICAL_ARTIFACT_NAMES):
            raise LexicalReportError(f"manifest {path} has an invalid {field} mapping")
        if field != "table_counts" and any(
            not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None
            for digest in value.values()
        ):
            raise LexicalReportError(f"manifest {path} has an invalid digest in {field}")
    return cast(dict[str, object], parsed)


def _artifact_scans(
    root: Path,
) -> tuple[dict[LexicalArtifactName, pl.LazyFrame], dict[str, object]]:
    try:
        processed_from_directory(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise LexicalReportError(f"governed lexical artifact set is unavailable: {exc}") from exc
    manifest = _read_manifest(root / TABLE_HASH_FILE)
    declared_files = manifest.get("file_sha256")
    if not isinstance(declared_files, dict) or not declared_files:
        raise LexicalReportError("lexical hash manifest has no physical file inventory")
    resolved_root = root.resolve()
    for relative, expected_digest in sorted(declared_files.items()):
        if not isinstance(relative, str) or not isinstance(expected_digest, str):
            raise LexicalReportError("lexical hash manifest file inventory is malformed")
        path = (resolved_root / relative).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise LexicalReportError(
                f"manifest file escapes lexical artifact root: {relative}"
            ) from exc
        if not path.is_file():
            raise LexicalReportError(f"manifest-declared lexical file is missing: {relative}")
        if sha256_file(path) != expected_digest:
            raise LexicalReportError(f"manifest-declared lexical file hash differs: {relative}")
    scans: dict[LexicalArtifactName, pl.LazyFrame] = {}
    for name in LEXICAL_ARTIFACT_NAMES:
        paths = sorted((root / name).glob("part-*.parquet"))
        if not paths:
            raise LexicalReportError(f"required lexical artifact has no Parquet leaves: {name}")
        try:
            scan = pl.scan_parquet(paths)
            actual = tuple(scan.collect_schema().names())
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalReportError(f"could not inspect lexical artifact {name}: {exc}") from exc
        expected = LEXICAL_ARTIFACT_COLUMNS[name]
        if actual != expected:
            raise LexicalReportError(
                f"lexical artifact {name} schema differs; expected={expected}, actual={actual}"
            )
        scans[name] = scan
    return scans, manifest


def _collect(frame: pl.LazyFrame, *, label: str) -> pl.DataFrame:
    try:
        return frame.collect(engine="streaming")
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalReportError(f"could not collect {label}: {exc}") from exc


def _feature_count_table(features: pl.LazyFrame) -> pl.DataFrame:
    corpus_scope = (
        pl.when(pl.col("language_namespace") == "hb")
        .then(pl.lit("hebrew"))
        .when(pl.col("language_namespace") == "gk")
        .then(pl.lit("greek"))
        .otherwise(pl.lit("english_derived_bridge"))
        .alias("corpus_scope")
    )
    return _collect(
        features.with_columns(corpus_scope)
        .group_by(["corpus_scope", "language_namespace", "feature_family"])
        .agg(
            pl.len().alias("vocabulary_size"),
            pl.col("corpus_frequency").sum().alias("corpus_frequency_total"),
            pl.col("document_frequency").sum().alias("document_frequency_total"),
            pl.col("is_rare").sum().alias("rare_feature_count"),
            pl.col("is_high_frequency").sum().alias("high_frequency_feature_count"),
            pl.col("is_formulaic").sum().alias("formulaic_feature_count"),
        )
        .sort(["corpus_scope", "language_namespace", "feature_family"]),
        label="feature-count report table",
    )


def _performance_tables(evaluation: pl.LazyFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    safe_columns = (
        "detector",
        "representation_id",
        "benchmark_version",
        "benchmark_tier",
        "label_quality",
        "analysis_profile",
        "ranking_name",
        "ranking_role",
        "comparison_baseline",
        "comparison_count",
        "stratum_dimension",
        "stratum_value",
        "mapping_status",
        "corpus_pair",
        "split_strategy",
        "partition",
        "vote_stratum",
        "metric",
        "k",
        "value",
        "bootstrap_interval_low",
        "bootstrap_interval_high",
        "bootstrap_iterations",
        "bootstrap_seed",
        "eligible_query_count",
        "eligible_relationship_count",
        "excluded_count",
        "exclusion_reasons_json",
        "config_hash",
        "preregistration_hash",
        "frozen_before_test",
        "notes",
    )
    by_stratum = _collect(
        evaluation.select(safe_columns).sort(
            [
                "corpus_pair",
                "analysis_profile",
                "detector",
                "ranking_role",
                "split_strategy",
                "partition",
                "stratum_dimension",
                "stratum_value",
                "mapping_status",
                "vote_stratum",
                "metric",
                "k",
            ],
            nulls_last=True,
        ),
        label="performance-by-stratum table",
    )
    if by_stratum.is_empty():
        return by_stratum, by_stratum
    summary = by_stratum.filter(
        (pl.col("stratum_dimension") == "global") & (pl.col("ranking_role") == "system")
    )
    if summary.is_empty():
        # Do not invent an aggregate from heterogeneous strata.  Preserve the
        # full rows and make the missing global slice visible in the report.
        summary = by_stratum.head(0)
    return summary, by_stratum


def _null_calibration_table(nulls: pl.LazyFrame) -> pl.DataFrame:
    keys = ["null_family", "corpus_pair", "representation_id", "detector", "threshold_id"]
    return _collect(
        nulls.group_by(keys)
        .agg(
            pl.col("iteration").n_unique().alias("iteration_count"),
            pl.col("seed").n_unique().alias("unique_seed_count"),
            pl.col("candidate_count").mean().alias("mean_candidate_count"),
            pl.col("candidate_count")
            .quantile(0.025, interpolation="linear")
            .alias("empirical_interval_low"),
            pl.col("candidate_count")
            .quantile(0.975, interpolation="linear")
            .alias("empirical_interval_high"),
            pl.col("candidate_count").min().alias("minimum_candidate_count"),
            pl.col("candidate_count").max().alias("maximum_candidate_count"),
            pl.col("passage_count").min().alias("passage_count"),
            pl.col("token_count").min().alias("token_count"),
            pl.col("runtime_seconds").mean().alias("mean_replicate_runtime_seconds"),
            pl.col("runtime_seconds").sum().alias("total_replicate_runtime_seconds"),
        )
        .sort(keys),
        label="null calibration report table",
    )


def _threshold_table(calibration: pl.LazyFrame) -> pl.DataFrame:
    columns = tuple(
        column
        for column in LEXICAL_ARTIFACT_COLUMNS["threshold_calibration"]
        if column not in {"experiment_run_id", "notes"}
    )
    return _collect(
        calibration.select(columns).sort(
            ["corpus_pair", "representation_id", "detector", "score_threshold"]
        ),
        label="threshold table",
    )


def _failed_performance_table(by_stratum: pl.DataFrame) -> pl.DataFrame:
    """Retain explicit failed paired-difference rows without judging raw metric zeros."""

    if by_stratum.is_empty():
        return by_stratum
    return by_stratum.filter(
        pl.col("metric").str.contains("difference_vs_", literal=True)
        & (
            (pl.col("value") <= 0.0)
            | (pl.col("bootstrap_interval_low") <= 0.0)
            | (pl.col("eligible_query_count") == 0)
        )
    )


def _candidate_summary_frame(pairs: pl.LazyFrame, evidence: pl.LazyFrame) -> pl.DataFrame:
    pair_columns = tuple(LEXICAL_ARTIFACT_COLUMNS["candidate_pairs"])
    evidence_columns = tuple(LEXICAL_ARTIFACT_COLUMNS["candidate_evidence"])
    return _collect(
        pairs.select(pair_columns)
        .join(evidence.select(evidence_columns), on="candidate_pair_id", how="inner")
        .sort("candidate_pair_id"),
        label="candidate report projection",
    )


def _candidate_count_table(candidates: pl.DataFrame) -> pl.DataFrame:
    return (
        candidates.group_by(["corpus_pair", "known_link_status"])
        .agg(
            pl.len().alias("candidate_count"),
            pl.col("review_eligible").sum().alias("review_eligible_count"),
            pl.col("rare_rule_passed").sum().alias("rare_rule_passed_count"),
            pl.col("english_ablation_survives").sum().alias("english_ablation_survives_count"),
        )
        .sort(["corpus_pair", "known_link_status"])
    )


def _rare_rule_effects_table(candidates: pl.DataFrame) -> pl.DataFrame:
    with_rare = candidates.with_columns(
        (pl.col("shared_rare_lemma_count") + pl.col("shared_rare_root_count"))
        .gt(0)
        .alias("rare_evidence_material")
    )
    return (
        with_rare.group_by(["corpus_pair", "rare_evidence_material", "rare_rule_passed"])
        .agg(
            pl.len().alias("candidate_count"),
            pl.col("review_eligible").sum().alias("review_eligible_count"),
            pl.col("independent_co_signal_count").min().alias("minimum_co_signal_count"),
            pl.col("independent_co_signal_count").max().alias("maximum_co_signal_count"),
            pl.col("formulaic_penalty").gt(0).sum().alias("formulaic_penalty_count"),
            pl.col("local_context_penalty").gt(0).sum().alias("local_context_penalty_count"),
            pl.col("short_passage_penalty").gt(0).sum().alias("short_passage_penalty_count"),
        )
        .sort(["corpus_pair", "rare_evidence_material", "rare_rule_passed"])
    )


def _english_ablation_table(candidates: pl.DataFrame) -> pl.DataFrame:
    bridge = candidates.filter(pl.col("corpus_pair") == "hb_gnt_english_bridge")
    columns = {
        "candidate_pair_id": pl.String,
        "corpus_pair": pl.String,
        "passage_a_gloss_feature_count": pl.Int64,
        "passage_b_gloss_feature_count": pl.Int64,
        "passage_a_gloss_coverage": pl.Float64,
        "passage_b_gloss_coverage": pl.Float64,
        "gloss_overlap_count": pl.Int64,
        "score_with_english_features": pl.Float64,
        "score_after_removing_all_english_features": pl.Float64,
        "rank_with_english_features": pl.Int64,
        "rank_after_removing_all_english_features": pl.Int64,
        "non_english_evidence_remains": pl.Boolean,
        "contains_english_derived_evidence": pl.Boolean,
        "english_ablation_survives": pl.Boolean,
        "review_eligible": pl.Boolean,
        "classification_after_ablation": pl.String,
    }
    if bridge.is_empty():
        return pl.DataFrame(schema=columns)
    if not bridge.get_column("contains_english_derived_evidence").all():
        raise LexicalReportError(
            "a cross-testament M7 candidate is missing its English-derived evidence flag"
        )
    inconsistent = bridge.filter(
        (pl.col("english_ablation_survives") != pl.col("non_english_evidence_remains"))
        | (
            ~pl.col("english_ablation_survives")
            & (pl.col("score_after_removing_all_english_features").fill_null(0.0) != 0.0)
        )
        | (
            ~pl.col("english_ablation_survives")
            & pl.col("rank_after_removing_all_english_features").is_not_null()
        )
    )
    if not inconsistent.is_empty():
        raise LexicalReportError(
            "persisted English-ablation scores, ranks, and survival flags are inconsistent"
        )
    return bridge.sort(["rank_with_english_features", "candidate_pair_id"], nulls_last=True).select(
        "candidate_pair_id",
        "corpus_pair",
        "passage_a_gloss_feature_count",
        "passage_b_gloss_feature_count",
        "passage_a_gloss_coverage",
        "passage_b_gloss_coverage",
        "gloss_overlap_count",
        "score_with_english_features",
        "score_after_removing_all_english_features",
        "rank_with_english_features",
        "rank_after_removing_all_english_features",
        "non_english_evidence_remains",
        "contains_english_derived_evidence",
        "english_ablation_survives",
        "review_eligible",
        pl.col("classification_after_english_ablation").alias("classification_after_ablation"),
    )


def _ablation_summary_table(ablations: pl.LazyFrame) -> pl.DataFrame:
    """Aggregate every preregistered ablation without exposing lexical values."""

    return _collect(
        ablations.group_by(["ablation_name", "subject_type", "corpus_pair"])
        .agg(
            pl.len().alias("result_count"),
            pl.col("changed").sum().alias("changed_count"),
            pl.col("score_before").mean().alias("mean_score_before"),
            pl.col("score_after").mean().alias("mean_score_after"),
            (pl.col("rank_before") != pl.col("rank_after"))
            .fill_null(False)
            .sum()
            .alias("rank_changed_count"),
            pl.col("review_eligible_before").sum().alias("eligible_before_count"),
            pl.col("review_eligible_after").sum().alias("eligible_after_count"),
            pl.col("downgrade_required").sum().alias("downgrade_required_count"),
            pl.col("evidence_digest").n_unique().alias("evidence_digest_count"),
        )
        .sort(["ablation_name", "subject_type", "corpus_pair"]),
        label="detector-ablation summary",
    )


def _sensitivity_summary_table(sensitivity: pl.LazyFrame) -> pl.DataFrame:
    """Aggregate the registered profile/reading comparisons without source text."""

    return _collect(
        sensitivity.group_by(
            [
                "sensitivity_type",
                "corpus_pair",
                "detector",
                "direction",
                "baseline_profile",
                "comparison_profile",
                "baseline_reading",
                "comparison_reading",
            ]
        )
        .agg(
            pl.len().alias("result_count"),
            pl.col("excluded_reason").is_null().sum().alias("comparable_result_count"),
            pl.col("excluded_reason").is_not_null().sum().alias("excluded_result_count"),
            pl.col("affected_locus_count").sum().alias("affected_locus_count"),
            pl.col("score_delta").mean().alias("mean_score_delta"),
            pl.col("score_delta").abs().max().alias("maximum_absolute_score_delta"),
            pl.col("rank_delta").mean().alias("mean_rank_delta"),
            pl.col("top_k_overlap").mean().alias("mean_top_k_overlap"),
            pl.col("baseline_sequence_digest").n_unique().alias("baseline_sequence_digest_count"),
            pl.col("comparison_sequence_digest")
            .n_unique()
            .alias("comparison_sequence_digest_count"),
        )
        .sort(["sensitivity_type", "corpus_pair", "detector", "direction"]),
        label="registered sensitivity summary",
    )


def _detector_score_distribution(scores: pl.LazyFrame) -> pl.DataFrame:
    return _collect(
        scores.group_by(["detector", "representation_id"])
        .agg(
            pl.len().alias("score_row_count"),
            pl.col("score").min().alias("minimum_score"),
            pl.col("score").median().alias("median_score"),
            pl.col("score").quantile(0.95, interpolation="linear").alias("p95_score"),
            pl.col("score").max().alias("maximum_score"),
            pl.col("score_contribution").sum().alias("rrf_contribution_total"),
            pl.col("penalty_contribution").sum().alias("penalty_contribution_total"),
        )
        .sort(["detector", "representation_id"]),
        label="detector score distributions",
    )


def _issue_count_table(issues: pl.LazyFrame) -> pl.DataFrame:
    return _collect(
        issues.group_by(["severity", "code"])
        .agg(pl.len().alias("issue_count"))
        .sort(["severity", "code"]),
        label="lexical issue counts",
    )


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LexicalReportError(f"{label} must be a nonempty string")
    return value


def _load_spot_criteria(path: Path) -> tuple[SpotCriterion, ...]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalReportError(f"could not read spot-check configuration {path}: {exc}") from exc
    if not isinstance(parsed, dict) or set(parsed) != {
        "schema_version",
        "selection_policy",
        "criteria",
    }:
        raise LexicalReportError("spot-check configuration has unexpected root fields")
    if parsed["schema_version"] != 1:
        raise LexicalReportError("spot-check configuration schema_version must be 1")
    if parsed["selection_policy"] != "first_after_registered_stable_sort":
        raise LexicalReportError("spot-check selection policy is not the registered stable policy")
    raw_criteria = parsed["criteria"]
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise LexicalReportError("spot-check configuration requires criteria")
    allowed_columns = {
        *LEXICAL_ARTIFACT_COLUMNS["candidate_pairs"],
        *LEXICAL_ARTIFACT_COLUMNS["candidate_evidence"],
    }
    output: list[SpotCriterion] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_criteria):
        required_fields = {
            "check_id",
            "category",
            "description",
            "predicates",
            "sort",
            "expected_presence",
        }
        if not isinstance(raw, dict) or not (
            set(raw) == required_fields or set(raw) == required_fields | {"unavailable_reason"}
        ):
            raise LexicalReportError(f"spot criterion {index} has unexpected fields")
        check_id = _require_string(raw["check_id"], label=f"criterion {index} check_id")
        if check_id in seen:
            raise LexicalReportError(f"duplicate spot-check ID: {check_id}")
        seen.add(check_id)
        raw_predicates = raw["predicates"]
        if not isinstance(raw_predicates, list) or not raw_predicates:
            raise LexicalReportError(f"spot criterion {check_id} requires predicates")
        predicates: list[SpotPredicate] = []
        for raw_predicate in raw_predicates:
            if not isinstance(raw_predicate, dict) or set(raw_predicate) != {
                "column",
                "operator",
                "value",
            }:
                raise LexicalReportError(f"spot criterion {check_id} has malformed predicate")
            column = _require_string(raw_predicate["column"], label="predicate column")
            operator = _require_string(raw_predicate["operator"], label="predicate operator")
            value = raw_predicate["value"]
            if column not in allowed_columns:
                raise LexicalReportError(f"spot criterion {check_id} uses unknown column {column}")
            if operator not in {"eq", "ne", "gt", "ge", "lt", "le", "contains"}:
                raise LexicalReportError(
                    f"spot criterion {check_id} uses unknown operator {operator}"
                )
            if isinstance(value, (dict, list)) or value is None:
                raise LexicalReportError(f"spot criterion {check_id} has invalid predicate value")
            predicates.append(
                SpotPredicate(
                    column=column,
                    operator=cast(
                        Literal["eq", "ne", "gt", "ge", "lt", "le", "contains"],
                        operator,
                    ),
                    value=cast(str | int | float | bool, value),
                )
            )
        raw_sort = raw["sort"]
        if not isinstance(raw_sort, dict) or set(raw_sort) != {"column", "order"}:
            raise LexicalReportError(f"spot criterion {check_id} has malformed sort")
        sort_column = _require_string(raw_sort["column"], label="sort column")
        sort_order = _require_string(raw_sort["order"], label="sort order")
        if sort_column not in allowed_columns:
            raise LexicalReportError(f"spot criterion {check_id} sorts unknown column")
        if sort_order not in {"ascending", "descending"}:
            raise LexicalReportError(f"spot criterion {check_id} has invalid sort order")
        if not isinstance(raw["expected_presence"], bool):
            raise LexicalReportError(f"spot criterion {check_id} expected_presence is not boolean")
        unavailable_reason = raw.get("unavailable_reason")
        if raw["expected_presence"]:
            if unavailable_reason is not None:
                raise LexicalReportError(
                    f"expected spot criterion {check_id} cannot declare unavailable_reason"
                )
        else:
            unavailable_reason = _require_string(
                unavailable_reason,
                label=f"criterion {check_id} unavailable_reason",
            )
        output.append(
            SpotCriterion(
                check_id=check_id,
                category=_require_string(raw["category"], label="criterion category"),
                description=_require_string(raw["description"], label="criterion description"),
                predicates=tuple(predicates),
                sort_column=sort_column,
                sort_order=cast(Literal["ascending", "descending"], sort_order),
                expected_presence=raw["expected_presence"],
                unavailable_reason=unavailable_reason,
            )
        )
    required_categories = {"positive_control", "lexical_evidence", "guardrail"}
    if {criterion.category for criterion in output} != required_categories:
        raise LexicalReportError(
            "spot checks must cover positive_control, lexical_evidence, and guardrail"
        )
    return tuple(output)


def _predicate_expression(predicate: SpotPredicate) -> pl.Expr:
    column = pl.col(predicate.column)
    if predicate.operator == "eq":
        return column == predicate.value
    if predicate.operator == "ne":
        return column != predicate.value
    if predicate.operator == "gt":
        return column > predicate.value
    if predicate.operator == "ge":
        return column >= predicate.value
    if predicate.operator == "lt":
        return column < predicate.value
    if predicate.operator == "le":
        return column <= predicate.value
    return column.cast(pl.String).str.contains(str(predicate.value), literal=True)


def _select_spot_checks(
    candidates: pl.DataFrame, criteria: Sequence[SpotCriterion]
) -> tuple[SpotSelection, ...]:
    output: list[SpotSelection] = []
    for criterion in criteria:
        expression = _predicate_expression(criterion.predicates[0])
        for predicate in criterion.predicates[1:]:
            expression &= _predicate_expression(predicate)
        matches = candidates.filter(expression).sort(
            [criterion.sort_column, "candidate_pair_id"],
            descending=[criterion.sort_order == "descending", False],
            nulls_last=True,
        )
        candidate = matches.row(0, named=True) if matches.height else None
        output.append(SpotSelection(criterion=criterion, candidate=candidate))
    return tuple(output)


def _selected_ids(selections: Sequence[SpotSelection]) -> list[str]:
    return sorted(
        {
            str(selection.candidate["candidate_pair_id"])
            for selection in selections
            if selection.candidate is not None
        }
    )


def _spot_detail_tables(
    scans: Mapping[LexicalArtifactName, pl.LazyFrame],
    selections: Sequence[SpotSelection],
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    selected = _selected_ids(selections)
    score_columns = (
        "candidate_pair_id",
        "detector",
        "representation_id",
        "score",
        "quantized_score",
        "direction",
        "query_rank",
        "reverse_rank",
        "score_contribution",
        "penalty_contribution",
    )
    evidence_columns = (
        "candidate_pair_id",
        "evidence_family",
        "feature_id",
        "passage_a_positions_json",
        "passage_b_positions_json",
        "corpus_frequency",
        "document_frequency",
        "association_score",
        "independence_expected_count",
        "contains_primary_rare_item",
        "counts_as_independent_co_signal",
        "english_derived",
    )
    if not selected:
        scores = _collect(
            scans["candidate_detector_scores"].select(score_columns).head(0),
            label="empty spot scores",
        )
        evidence = _collect(
            scans["shared_evidence"].select(evidence_columns).head(0), label="empty spot evidence"
        )
    else:
        scores = _collect(
            scans["candidate_detector_scores"]
            .filter(pl.col("candidate_pair_id").is_in(selected))
            .select(score_columns)
            .sort(["candidate_pair_id", "detector", "direction"]),
            label="spot detector scores",
        )
        evidence = _collect(
            scans["shared_evidence"]
            .filter(pl.col("candidate_pair_id").is_in(selected))
            .select(evidence_columns)
            .sort(["candidate_pair_id", "evidence_family", "feature_id"]),
            label="spot shared evidence",
        )
    corpus_pairs = sorted(
        {
            str(selection.candidate["corpus_pair"])
            for selection in selections
            if selection.candidate is not None
        }
    )
    calibration = _collect(
        scans["threshold_calibration"]
        .filter(pl.col("corpus_pair").is_in(corpus_pairs))
        .select(
            "corpus_pair",
            "representation_id",
            "detector",
            "score_threshold",
            "observed_candidate_count",
            "mean_null_candidate_count",
            "null_interval_low",
            "null_interval_high",
            "observed_to_null_enrichment",
            "empirical_tail_probability",
            "estimated_empirical_fdr",
            "eligible_candidate_count",
        )
        .sort(["corpus_pair", "detector", "score_threshold"]),
        label="spot calibration",
    )
    return scores, evidence, calibration


def _metadata_row(scans: Mapping[LexicalArtifactName, pl.LazyFrame]) -> dict[str, object]:
    frame = _collect(scans["lexical_metadata"], label="lexical metadata")
    if frame.height != 1:
        raise LexicalReportError("lexical_metadata must contain exactly one row")
    return frame.row(0, named=True)


def _validate_metadata(
    metadata: Mapping[str, object],
    manifest: Mapping[str, object],
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
) -> None:
    config_hash = lexical_config_sha256(config)
    prereg_hash = lexical_preregistration_sha256(preregistration)
    if metadata["configuration_hash"] != config_hash:
        raise LexicalReportError("metadata configuration hash differs from active governed config")
    if metadata["preregistration_hash"] != prereg_hash:
        raise LexicalReportError(
            "metadata preregistration hash differs from frozen preregistration"
        )
    if preregistration.preregistration_sha256 != prereg_hash:
        raise LexicalReportError(
            "declared preregistration digest does not authenticate its payload"
        )
    if metadata["experiment_version"] != preregistration.experiment_version:
        raise LexicalReportError("metadata experiment version differs from preregistration")
    input_hashes = _json_object(metadata["input_corpus_hashes_json"], label="input hashes")
    expected_input_hashes: dict[str, object] = {
        "identity": {
            "hebrew": preregistration.inputs.hebrew.identity_sha256,
            "greek": preregistration.inputs.greek.identity_sha256,
        },
        "content": {
            "hebrew": preregistration.inputs.hebrew.content_sha256,
            "greek": preregistration.inputs.greek.content_sha256,
        },
        "analytical": {
            "hebrew": preregistration.inputs.hebrew.analytical_sha256,
            "greek": preregistration.inputs.greek.analytical_sha256,
        },
        "oshb": preregistration.inputs.oshb_supplement_hashes,
    }
    if input_hashes != expected_input_hashes:
        raise LexicalReportError("metadata input corpus anchors differ from preregistration")
    passage_hashes = _json_object(metadata["passage_hashes_json"], label="passage hashes")
    if passage_hashes != preregistration.inputs.passages.logical_hashes:
        raise LexicalReportError("metadata passage anchors differ from preregistration")
    benchmark_hashes = _json_object(metadata["benchmark_hashes_json"], label="benchmark hashes")
    if benchmark_hashes != preregistration.inputs.benchmark.logical_hashes:
        raise LexicalReportError("metadata benchmark anchors differ from preregistration")
    declared_logical = _json_object(
        metadata["table_logical_hashes_json"], label="metadata table logical hashes"
    )
    declared_physical = _json_object(
        metadata["table_physical_hashes_json"], label="metadata table physical hashes"
    )
    manifest_logical = cast(dict[str, object], manifest["table_logical_sha256"])
    manifest_physical = cast(dict[str, object], manifest["table_physical_sha256"])
    manifest_counts = cast(dict[str, object], manifest["table_counts"])
    for name in LEXICAL_ARTIFACT_NAMES:
        if name == "lexical_metadata":
            continue
        if declared_logical.get(name) != manifest_logical.get(name):
            raise LexicalReportError(f"metadata and manifest logical hash differ for {name}")
        if declared_physical.get(name) != manifest_physical.get(name):
            raise LexicalReportError(f"metadata and manifest physical hash differ for {name}")
    for metadata_field, artifact in (
        ("ranking_count", "directional_rankings"),
        ("candidate_count", "candidate_pairs"),
        ("evaluation_count", "evaluation_results"),
    ):
        if int(cast(int, metadata[metadata_field])) != int(str(manifest_counts[artifact])):
            raise LexicalReportError(
                f"metadata {metadata_field} differs from manifest count for {artifact}"
            )


def _queue_table(queue: pl.LazyFrame) -> pl.DataFrame:
    columns = tuple(LEXICAL_ARTIFACT_COLUMNS["candidate_review_queue"])
    return _collect(queue.select(columns).sort("queue_rank"), label="unreviewed queue")


def collect_lexical_report_tables(
    *,
    artifact_root: Path = DEFAULT_LEXICAL_ARTIFACT_ROOT,
    spot_check_config: Path = DEFAULT_SPOT_CHECK_CONFIG,
    lexical_config_path: Path = LEXICAL_CONFIG_PATH,
    preregistration_path: Path = LEXICAL_PREREGISTRATION_PATH,
) -> tuple[LexicalReportTables, dict[str, object], LexicalExperimentPreregistration]:
    """Authenticate artifacts and collect only sanitized report projections."""

    try:
        config = load_lexical_config(lexical_config_path)
        preregistration = load_lexical_preregistration(preregistration_path)
        validate_preregistration_against_config(preregistration, config)
    except ValueError as exc:
        raise LexicalReportError(f"governed M7 configuration is invalid: {exc}") from exc
    scans, manifest = _artifact_scans(artifact_root)
    metadata = _metadata_row(scans)
    _validate_metadata(metadata, manifest, config, preregistration)
    candidates = _candidate_summary_frame(scans["candidate_pairs"], scans["candidate_evidence"])
    criteria = _load_spot_criteria(spot_check_config)
    selections = _select_spot_checks(candidates, criteria)
    spot_scores, spot_evidence, spot_calibration = _spot_detail_tables(scans, selections)
    detector_performance, by_stratum = _performance_tables(scans["evaluation_results"])
    tables = LexicalReportTables(
        metadata=metadata,
        feature_counts=_feature_count_table(scans["feature_vocabulary"]),
        indexes=_collect(
            scans["lexical_index_metadata"]
            .select(
                "index_id",
                "representation_id",
                "corpus_scope",
                "profile",
                "reading",
                "granularity",
                "feature_family",
                "matrix_shape_json",
                "nonzero_count",
                "vocabulary_size",
                "document_count",
                "logical_matrix_hash",
                "physical_file_hash",
                "dtype",
                "storage_format",
            )
            .sort("index_id"),
            label="index metadata report projection",
        ),
        detector_performance=detector_performance,
        performance_by_stratum=by_stratum,
        failed_performance=_failed_performance_table(by_stratum),
        null_calibration=_null_calibration_table(scans["null_replicate_summaries"]),
        thresholds=_threshold_table(scans["threshold_calibration"]),
        rare_rule_effects=_rare_rule_effects_table(candidates),
        english_ablation=_english_ablation_table(candidates),
        ablation_summary=_ablation_summary_table(scans["ablation_results"]),
        sensitivity_summary=_sensitivity_summary_table(scans["sensitivity_results"]),
        queue=_queue_table(scans["candidate_review_queue"]),
        candidate_counts=_candidate_count_table(candidates),
        detector_score_distributions=_detector_score_distribution(
            scans["candidate_detector_scores"]
        ),
        issue_counts=_issue_count_table(scans["lexical_issues"]),
        spot_selections=selections,
        spot_detector_scores=spot_scores,
        spot_shared_evidence=spot_evidence,
        spot_calibration=spot_calibration,
    )
    return tables, manifest, preregistration


def _run_telemetry(metadata: Mapping[str, object]) -> RunTelemetry:
    stage_values = _json_object(
        metadata.get("stage_runtime_seconds_json"), label="stage runtime telemetry"
    )
    stages: dict[str, float] = {}
    for name, value in stage_values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LexicalReportError(f"stage runtime {name} is not numeric")
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            raise LexicalReportError(f"stage runtime {name} is invalid")
        stages[name] = number
    return RunTelemetry(
        experiment_run_id=str(metadata["experiment_run_id"]),
        runtime_seconds=float(str(metadata["runtime_seconds"])),
        stage_runtime_seconds=stages,
        peak_memory_bytes=int(str(metadata["peak_memory_bytes"])),
        storage_footprint_bytes=int(str(metadata["storage_footprint_bytes"])),
    )


def _first_run_telemetry(comparison_manifest: Path) -> RunTelemetry | None:
    metadata_parts = sorted(
        (comparison_manifest.parent / "lexical_metadata").glob("part-*.parquet")
    )
    if not metadata_parts:
        return None
    try:
        frame = pl.read_parquet(
            metadata_parts,
            columns=[
                "experiment_run_id",
                "runtime_seconds",
                "stage_runtime_seconds_json",
                "peak_memory_bytes",
                "storage_footprint_bytes",
            ],
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalReportError(f"could not read first-run telemetry: {exc}") from exc
    if frame.height != 1:
        raise LexicalReportError("first-run reference must contain exactly one metadata row")
    return _run_telemetry(frame.row(0, named=True))


def compare_lexical_manifests(
    current: Mapping[str, object],
    comparison_manifest: Path | None,
    *,
    current_metadata: Mapping[str, object] | None = None,
) -> DeterminismEvidence:
    """Compare complete manifests and, when supplied, exact run identity/telemetry."""

    if comparison_manifest is None or not comparison_manifest.is_file():
        return DeterminismEvidence(
            status="not_verified",
            logical_hashes_match=False,
            physical_hashes_match=False,
            first_manifest_path=(
                None if comparison_manifest is None else comparison_manifest.as_posix()
            ),
            differing_logical_tables=tuple(LEXICAL_ARTIFACT_NAMES),
            differing_physical_tables=tuple(LEXICAL_ARTIFACT_NAMES),
            run_ids_match=False,
            first_run_id=None,
            second_run_id=(
                None if current_metadata is None else str(current_metadata["experiment_run_id"])
            ),
            first_runtime_seconds=None,
            second_runtime_seconds=None,
            first_stage_runtime_seconds={},
            second_stage_runtime_seconds={},
            first_peak_memory_bytes=None,
            second_peak_memory_bytes=None,
            first_storage_footprint_bytes=None,
            second_storage_footprint_bytes=None,
        )
    first = _read_manifest(comparison_manifest)
    current_logical = cast(dict[str, object], current["table_logical_sha256"])
    first_logical = cast(dict[str, object], first["table_logical_sha256"])
    current_physical = cast(dict[str, object], current["table_physical_sha256"])
    first_physical = cast(dict[str, object], first["table_physical_sha256"])
    logical_differences = tuple(
        name for name in LEXICAL_ARTIFACT_NAMES if current_logical[name] != first_logical[name]
    )
    physical_differences = tuple(
        name for name in LEXICAL_ARTIFACT_NAMES if current_physical[name] != first_physical[name]
    )
    first_telemetry = _first_run_telemetry(comparison_manifest)
    second_telemetry = None if current_metadata is None else _run_telemetry(current_metadata)
    run_ids_match = (
        True
        if current_metadata is None
        else first_telemetry is not None
        and second_telemetry is not None
        and first_telemetry.experiment_run_id == second_telemetry.experiment_run_id
    )
    complete_match = not logical_differences and run_ids_match
    return DeterminismEvidence(
        status="passed" if complete_match else "failed",
        logical_hashes_match=not logical_differences,
        physical_hashes_match=not physical_differences,
        first_manifest_path=comparison_manifest.as_posix(),
        differing_logical_tables=logical_differences,
        differing_physical_tables=physical_differences,
        run_ids_match=run_ids_match,
        first_run_id=(None if first_telemetry is None else first_telemetry.experiment_run_id),
        second_run_id=(None if second_telemetry is None else second_telemetry.experiment_run_id),
        first_runtime_seconds=(
            None if first_telemetry is None else first_telemetry.runtime_seconds
        ),
        second_runtime_seconds=(
            None if second_telemetry is None else second_telemetry.runtime_seconds
        ),
        first_stage_runtime_seconds=(
            {} if first_telemetry is None else first_telemetry.stage_runtime_seconds
        ),
        second_stage_runtime_seconds=(
            {} if second_telemetry is None else second_telemetry.stage_runtime_seconds
        ),
        first_peak_memory_bytes=(
            None if first_telemetry is None else first_telemetry.peak_memory_bytes
        ),
        second_peak_memory_bytes=(
            None if second_telemetry is None else second_telemetry.peak_memory_bytes
        ),
        first_storage_footprint_bytes=(
            None if first_telemetry is None else first_telemetry.storage_footprint_bytes
        ),
        second_storage_footprint_bytes=(
            None if second_telemetry is None else second_telemetry.storage_footprint_bytes
        ),
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LexicalReportError("report output cannot contain a non-finite float")
        return format(value, ".12g")
    return str(value)


def _csv_text(frame: pl.DataFrame) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(frame.columns)
    for row in frame.iter_rows():
        writer.writerow(_cell(value) for value in row)
    return buffer.getvalue()


def _markdown_cell(value: object) -> str:
    return _cell(value).replace("|", "\\|").replace("\n", " ")


def _markdown_frame(frame: pl.DataFrame, *, limit: int = 50) -> list[str]:
    if frame.is_empty():
        return ["No governed rows were available for this slice."]
    visible = frame.head(limit)
    lines = [
        "| " + " | ".join(visible.columns) + " |",
        "| " + " | ".join("---" for _ in visible.columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in visible.iter_rows()
    )
    if frame.height > limit:
        lines.append(
            f"\nDisplayed {limit:,} of {frame.height:,} rows; the complete CSV is retained."
        )
    return lines


def _mapping_lines(value: Mapping[str, object], heading: str) -> list[str]:
    lines = [f"### {heading}", "", "| Key | Value |", "|---|---|"]
    for key, item in sorted(value.items()):
        rendered = (
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            if isinstance(item, (dict, list))
            else _cell(item)
        )
        lines.append(f"| {_markdown_cell(key)} | `{_markdown_cell(rendered)}` |")
    return lines


def _reference_from_passage_id(passage_id: str) -> str:
    match = _PASSAGE_REFERENCE_RE.fullmatch(passage_id)
    if match is None:
        return "reference_unavailable_from_identifier"
    return f"{match.group(1)} {int(match.group(2))}:{int(match.group(3))}"


def _spot_check_markdown(tables: LexicalReportTables) -> str:
    lines = [
        "# Milestone 7 structural spot-check evidence",
        "",
        "These are deterministic structural checks of stored lexical evidence. They are not "
        "interpretive review, novelty review, or a human relationship decision. No Milestone 8 "
        "review has begun. Feature values and biblical text are intentionally omitted.",
        "",
    ]
    for selection in tables.spot_selections:
        criterion = selection.criterion
        lines.extend(
            [
                f"## {criterion.check_id}: {criterion.description}",
                "",
                f"- Category: `{criterion.category}`",
                f"- Expected presence: `{str(criterion.expected_presence).lower()}`",
            ]
        )
        if selection.candidate is None:
            status = (
                "missing_expected_match" if criterion.expected_presence else "governed_unavailable"
            )
            lines.extend(
                [
                    f"- Status: **{status}**",
                    *(
                        [f"- Governed unavailable reason: {criterion.unavailable_reason}"]
                        if criterion.unavailable_reason is not None
                        else []
                    ),
                    "- Evidence: no candidate in the governed artifact set satisfied the "
                    "registered predicate.",
                    "",
                ]
            )
            continue
        candidate = selection.candidate
        candidate_id = str(candidate["candidate_pair_id"])
        passage_a = str(candidate["passage_a_id"])
        passage_b = str(candidate["passage_b_id"])
        lines.extend(
            [
                "- Status: **observed_and_structurally_checked**",
                f"- Candidate pair ID: `{candidate_id}`",
                f"- Passage A: `{passage_a}` (`{_reference_from_passage_id(passage_a)}`)",
                f"- Passage B: `{passage_b}` (`{_reference_from_passage_id(passage_b)}`)",
                f"- Corpus pair: `{candidate['corpus_pair']}`",
                f"- Benchmark status: `{candidate['known_link_status']}`; mapping quality "
                f"`{candidate['mapping_quality']}`; highest descriptive vote "
                f"`{_cell(candidate['highest_openbible_vote'])}`",
                f"- Composite: RRF `{_cell(candidate['rrf_score'])}`; detector support "
                f"`{candidate['detector_support_count']}`; directional support "
                f"`{candidate['directional_support_count']}`",
                f"- Penalties: formulaic `{_cell(candidate['formulaic_penalty'])}`, local "
                f"`{_cell(candidate['local_context_penalty'])}`, short-passage "
                f"`{_cell(candidate['short_passage_penalty'])}`; overlap exclusion "
                f"`{_cell(candidate['overlap_exclusion'])}`",
                f"- Analytical baseline: expected overlap "
                f"`{_cell(candidate['expected_overlap_independence'])}`; hypergeometric p "
                f"`{_cell(candidate['hypergeometric_p_value'])}`; BH q "
                f"`{_cell(candidate['benjamini_hochberg_q_value'])}`",
                f"- Empirical calibration: null rate "
                f"`{_cell(candidate['null_model_empirical_rate'])}`; estimated FDR "
                f"`{_cell(candidate['estimated_empirical_fdr'])}`",
                f"- Rare conjunction: passed `{_cell(candidate['rare_rule_passed'])}`; "
                f"independent co-signals `{candidate['independent_co_signal_count']}`",
                f"- English-derived evidence: "
                f"`{_cell(candidate['contains_english_derived_evidence'])}`; all-English "
                f"ablation survives `{_cell(candidate['english_ablation_survives'])}`",
                f"- Review eligibility: `{_cell(candidate['review_eligible'])}`; reason "
                f"`{candidate['eligibility_reason']}`",
                "",
                "### Detector scores, ranks, contributions, and explicit penalties",
                "",
                *_markdown_frame(
                    tables.spot_detector_scores.filter(pl.col("candidate_pair_id") == candidate_id),
                    limit=30,
                ),
                "",
                "### Shared evidence positions and frequencies",
                "",
                *_markdown_frame(
                    tables.spot_shared_evidence.filter(pl.col("candidate_pair_id") == candidate_id),
                    limit=8,
                ),
                "",
                "### Registered calibration rows for this corpus pair",
                "",
                *_markdown_frame(
                    tables.spot_calibration.filter(
                        pl.col("corpus_pair") == str(candidate["corpus_pair"])
                    ),
                    limit=10,
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Content and review boundary",
            "",
            "No bulk biblical text, reconstructed passage text, feature value, interpretation, "
            "accept/reject decision, relationship classification, or novelty claim appears here.",
            "",
        ]
    )
    return "\n".join(lines)


def _acceptance_status_passes(value: object) -> bool:
    return str(value) in {
        "passed",
        "complete",
        "scientifically_complete",
        "milestone_7_complete",
    }


def _render_report(
    tables: LexicalReportTables,
    manifest: Mapping[str, object],
    preregistration: LexicalExperimentPreregistration,
    determinism: DeterminismEvidence,
    strict_validation: LexicalValidationReport,
    *,
    pr7_merge_commit: str,
) -> tuple[str, bool]:
    metadata = tables.metadata
    errors = strict_validation.error_count
    warnings = strict_validation.warning_count
    missing_expected = sum(
        selection.criterion.expected_presence and selection.candidate is None
        for selection in tables.spot_selections
    )
    observed_ablations = (
        set(tables.ablation_summary.get_column("ablation_name").to_list())
        if not tables.ablation_summary.is_empty()
        else set()
    )
    observed_sensitivities = (
        set(tables.sensitivity_summary.get_column("sensitivity_type").to_list())
        if not tables.sensitivity_summary.is_empty()
        else set()
    )
    critical_core_evaluated = (
        not tables.performance_by_stratum.is_empty()
        and tables.performance_by_stratum.filter(
            pl.col("analysis_profile") == "critical_core"
        ).height
        > 0
    )
    complete_ablation_text = str(observed_ablations == REQUIRED_ABLATIONS).lower()
    complete_sensitivity_text = str(observed_sensitivities == REQUIRED_SENSITIVITIES).lower()
    stage_names = sorted(
        set(determinism.first_stage_runtime_seconds).union(determinism.second_stage_runtime_seconds)
    )
    runtime_by_stage = pl.DataFrame(
        {
            "stage": stage_names,
            "first_run_seconds": [
                determinism.first_stage_runtime_seconds.get(stage) for stage in stage_names
            ],
            "second_run_seconds": [
                determinism.second_stage_runtime_seconds.get(stage) for stage in stage_names
            ],
        },
        schema={
            "stage": pl.String,
            "first_run_seconds": pl.Float64,
            "second_run_seconds": pl.Float64,
        },
    )
    gate_passed = (
        _acceptance_status_passes(metadata["acceptance_status"])
        and strict_validation.passed
        and strict_validation.scientific_gate_passed is True
        and determinism.logical_hashes_match
        and determinism.run_ids_match
        and errors == 0
        and warnings == 0
        and missing_expected == 0
        and not tables.detector_performance.is_empty()
        and not tables.null_calibration.is_empty()
        and not tables.thresholds.is_empty()
        and observed_ablations == REQUIRED_ABLATIONS
        and observed_sensitivities == REQUIRED_SENSITIVITIES
        and critical_core_evaluated
    )
    input_hashes = _json_object(metadata["input_corpus_hashes_json"], label="input hashes")
    passage_hashes = _json_object(metadata["passage_hashes_json"], label="passage hashes")
    benchmark_hashes = _json_object(metadata["benchmark_hashes_json"], label="benchmark hashes")
    vocabulary_hashes = _json_object(
        metadata["feature_vocabulary_hashes_json"], label="feature vocabulary hashes"
    )
    sparse_hashes = _json_object(metadata["sparse_index_hashes_json"], label="sparse hashes")
    logical_hashes = cast(dict[str, object], manifest["table_logical_sha256"])
    physical_hashes = cast(dict[str, object], manifest["table_physical_sha256"])
    queue_eligible = (
        int(tables.queue["review_eligible"].sum()) if not tables.queue.is_empty() else 0
    )
    represented = (
        int(
            tables.candidate_counts.filter(
                pl.col("known_link_status") == "represented_in_openbible_snapshot"
            )["candidate_count"].sum()
        )
        if not tables.candidate_counts.is_empty()
        else 0
    )
    unrepresented = (
        int(
            tables.candidate_counts.filter(
                pl.col("known_link_status") == "not_represented_in_openbible_snapshot"
            )["candidate_count"].sum()
        )
        if not tables.candidate_counts.is_empty()
        else 0
    )
    if gate_passed:
        next_task_lines = [
            "## Exact recommended Milestone 8 task",
            "",
            "After the unmerged Milestone 7 PR is reviewed and merged, execute Milestone 8 "
            "only: review the frozen top 100 eligible unrepresented candidates, retain accepted "
            "and rejected decisions, document the false-positive taxonomy and observed/null "
            "expected-noise display, and draft standalone Output J without changing the frozen "
            "Milestone 7 experiment in place.",
            "",
        ]
    else:
        next_task_lines = [
            "## Next required action",
            "",
            "**Milestone 8 is blocked.** Preserve this result unchanged and register a separate "
            "Milestone 7 follow-up experiment addressing the failed scientific or validation "
            "gate. Do not weaken a threshold, tune against the held-out result, overwrite this "
            "experiment, or begin top-100 review.",
            "",
        ]
    lines = [
        "# Milestone 7 transparent lexical-baseline report",
        "",
        f"Acceptance gate: **{'PASSED' if gate_passed else 'NOT PASSED'}**",
        "",
        "## Objective",
        "",
        "Build and evaluate a deterministic, sparse, interpretable lexical retrieval baseline "
        "for Hebrew/Aramaic and Greek verse passages, calibrate it against two registered "
        "repeated null families, and produce a fully traceable unreviewed queue. This report "
        "does not perform Milestone 8 review and makes no novelty or authorial-intent claim.",
        "",
        "## Repository and decision anchors",
        "",
        f"- PR #7 merge commit: `{pr7_merge_commit}`",
        "- Governing decision: ADR 0015, *Transparent lexical retrieval, calibration, and "
        "candidate evidence*.",
        f"- Experiment run ID: `{metadata['experiment_run_id']}`",
        f"- Experiment version: `{metadata['experiment_version']}`",
        f"- Configuration hash: `{metadata['configuration_hash']}`",
        f"- Frozen preregistration hash: `{metadata['preregistration_hash']}`",
        "- MACULA Hebrew: release `25.08.11`, commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`.",
        "- MACULA Greek: release `24.06.17`, commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`.",
        "- OSHB Ketiv/Qere supplement commit: `3d15126fb1ef74867fc1434be1942e837932691f`.",
        f"- Passage run: `{preregistration.inputs.passages.run_id}`.",
        f"- Benchmark run/version: `{preregistration.inputs.benchmark.run_id}` / "
        f"`{preregistration.inputs.benchmark.version}`.",
        "- Preregistration was frozen before held-out evaluation and authenticated against "
        "the active lexical configuration.",
        "",
        "## Verse-level v1 scope",
        "",
        "The fully retrieved and null-calibrated v1 scope is `edition_complete` verse passages: "
        "Hebrew/Aramaic Qere, Greek source reading, HB-HB, GNT-GNT, and a separately labeled "
        "HB-GNT English-gloss bridge. Clause, sentence, two-verse, and five-verse support is "
        "interface/smoke-test scope only; it is not exhaustive calibrated evidence.",
        "",
        *_mapping_lines(input_hashes, "Input corpus versions and hashes"),
        "",
        *_mapping_lines(passage_hashes, "Passage anchors"),
        "",
        *_mapping_lines(benchmark_hashes, "Benchmark anchors"),
        "",
        "## Feature representations and frequency method",
        "",
        "All original-language features have language-prefixed identities. Hebrew and Greek "
        "lemma namespaces never match directly. English glosses use an `en` namespace and are "
        "never mixed into an original-language composite. Corpus frequency and verse-document "
        "frequency are computed within language and representation. Formulaic status uses the "
        "registered document-frequency ratio and minimum corpus count; its penalty remains an "
        "explicit stored field rather than a hidden score transformation.",
        "",
        *_markdown_frame(tables.feature_counts),
        "",
        *_mapping_lines(vocabulary_hashes, "Feature-vocabulary logical hashes"),
        "",
        "## Sparse index architecture",
        "",
        "CSR matrices use stable passage and feature identity order, float64 values, bounded "
        "blockwise products, stable score quantization, and deterministic target-ID tie breaks. "
        "Dense all-pairs computation is prohibited.",
        "",
        *_markdown_frame(tables.indexes, limit=25),
        "",
        *_mapping_lines(sparse_hashes, "Sparse-index logical hashes"),
        "",
        "## Transparent detectors and composite",
        "",
        "| Detector | Registered formula or role |",
        "|---|---|",
        *(f"| `{name}` | {_markdown_cell(formula)} |" for name, formula in DETECTOR_FORMULAS),
        "",
        "Detector scores, ranks, RRF contributions, formulaic/local/short-passage penalties, "
        "and evidence positions remain decomposable. No opaque learned model is present.",
        "",
        *_markdown_frame(tables.detector_score_distributions, limit=30),
        "",
        "## Candidate identity and retrieval scope",
        "",
        "Candidate identity is the stable canonical unordered pair of passage identities plus "
        "profile/granularity, never a score or label. Retrieval persists directional top-k "
        "rankings, merges a bounded candidate union, excludes self/overlap as registered, and "
        "retains explicit nearby, formulaic, short-passage, disputed, reference-gap, Ketiv, "
        "knownness, rare-rule, and ablation evidence.",
        "",
        f"- Persisted directional rankings: `{metadata['ranking_count']}`",
        f"- Candidate pairs: `{metadata['candidate_count']}`",
        f"- OpenBible-represented pairs: `{represented}`",
        f"- Not represented in the OpenBible snapshot: `{unrepresented}`",
        "",
        *_markdown_frame(tables.candidate_counts),
        "",
        "## Benchmark evaluation design and caveats",
        "",
        "Every result is **Tier 3 weak-supervision recovery**. Tier 1 remains empty, so no "
        "high-confidence quotation-recovery claim has been tested. Same-label reference mappings "
        "remain provisional unless separately verified. OpenBible votes are descriptive source "
        "ranking strata, not confidence labels. Results are kept separate by corpus pair, mapping "
        "status, split strategy/partition, and vote stratum, with fixed query-bootstrap intervals.",
        "",
        "The registered comparators are random ranking, length-only ranking, unweighted lexical "
        "overlap, and presumed-negative discrimination where applicable. Held-out test results "
        "were not used to tune composite weights.",
        "",
        "### Detector, composite, and baseline results",
        "",
        *_markdown_frame(tables.detector_performance, limit=100),
        "",
        "### Performance by corpus pair, mapping, split, and vote stratum",
        "",
        *_markdown_frame(tables.performance_by_stratum, limit=100),
        "",
        "## English-gloss bridge and mandatory ablation",
        "",
        "Cross-testament retrieval is English-mediated infrastructure, not direct Hebrew-Greek "
        "lexical evidence. Removing all English-derived features removes the M7 bridge "
        "representation; English-only candidates cannot satisfy a future strong-candidate gate.",
        "",
        *_markdown_frame(tables.english_ablation, limit=30),
        "",
        "## Preregistered ablations",
        "",
        "Every one of the eight frozen removals is persisted as a typed result. Scores and "
        "ranks are recomputed from the retained detector families or penalties; these are "
        "diagnostic ablations, not post-test model selection.",
        "",
        *_markdown_frame(tables.ablation_summary, limit=100),
        "",
        "## Required profile and reading sensitivities",
        "",
        "Critical-core Greek retrieval/evaluation is a complete bounded sensitivity profile. "
        "Qere/Ketiv comparisons are restricted to OSHB-affected Hebrew verse references, use "
        "stable reference joins, and retain the full Hebrew target corpus. Neither sensitivity "
        "repeats the registered primary null simulations.",
        "",
        *_markdown_frame(tables.sensitivity_summary, limit=100),
        "",
        "## Registered null models and threshold calibration",
        "",
        "Both null families use 100 deterministic iterations per governed primary experiment. "
        "Within-book reassignment preserves book feature totals, passage counts, and exact length "
        "vectors while breaking within-passage sequence. Frequency-preserving synthetic passages "
        "preserve lengths and book conditioning when sufficient, otherwise registered broad-genre "
        "conditioning. Label or passage-order shuffle is not an accepted null.",
        "",
        "Calibration is scoped to the frozen deterministic 20,000-pair candidate-union sample. "
        "It is not a global all-pairs FDR claim. Every registered threshold reports observed and "
        "mean null counts, the empirical 95% interval, enrichment, corrected upper-tail "
        "probability, and estimated empirical FDR.",
        "",
        f"- Persisted null iteration metadata count: `{metadata['null_iteration_count']}`",
        "",
        *_markdown_frame(tables.null_calibration, limit=60),
        "",
        "### Threshold calibration",
        "",
        *_markdown_frame(tables.thresholds, limit=60),
        "",
        "## Analytical overlap baseline and multiple testing",
        "",
        "Hypergeometric probabilities are simple independence baselines, not probabilities of "
        "literary dependence and not substitutes for empirical null calibration. "
        "Benjamini-Hochberg "
        "q-values are computed within the registered corpus-pair hypothesis families; empirical "
        "book/genre-conditioned null results have priority for review eligibility.",
        "",
        "## Conjunctive rare-evidence rule and explicit penalties",
        "",
        "A single lemma or root at corpus frequency <=3 cannot independently qualify a candidate. "
        "At least one registered independent co-signal is required, and correlated duplicate "
        "evidence (including TF-IDF plus BM25 for the same item) does not count twice.",
        "",
        *_markdown_frame(tables.rare_rule_effects),
        "",
        "## Unreviewed Milestone 8 handoff queue",
        "",
        f"- Queue rows: `{tables.queue.height}`",
        f"- Review-eligible queue rows: `{queue_eligible}`",
        "- The threshold was not weakened to manufacture a quota.",
        "- The queue contains no reviewer, decision, interpretation, relationship class, or "
        "novelty field.",
        "",
        "## Determinism, runtime, memory, and storage",
        "",
        f"- Two-build logical determinism: **{determinism.status.upper()}**",
        f"- First run ID: `{_cell(determinism.first_run_id)}`",
        f"- Second run ID: `{_cell(determinism.second_run_id)}`",
        f"- Run IDs match: `{str(determinism.run_ids_match).lower()}`",
        f"- Logical hashes match: `{str(determinism.logical_hashes_match).lower()}`",
        f"- Physical hashes match: `{str(determinism.physical_hashes_match).lower()}`",
        f"- Differing logical tables: `{','.join(determinism.differing_logical_tables) or 'none'}`",
        "- Differing physical tables: "
        f"`{','.join(determinism.differing_physical_tables) or 'none'}`",
        f"- First persisted runtime: `{_cell(determinism.first_runtime_seconds)}` seconds",
        f"- Second persisted runtime: `{_cell(determinism.second_runtime_seconds)}` seconds",
        f"- First approximate peak RSS: `{_cell(determinism.first_peak_memory_bytes)}` bytes",
        f"- Second approximate peak RSS: `{_cell(determinism.second_peak_memory_bytes)}` bytes",
        "- First persisted storage footprint: "
        f"`{_cell(determinism.first_storage_footprint_bytes)}` bytes",
        "- Second persisted storage footprint: "
        f"`{_cell(determinism.second_storage_footprint_bytes)}` bytes",
        "",
        "### Runtime by stage",
        "",
        *_markdown_frame(runtime_by_stage, limit=100),
        "",
        "- Measured metadata and null-replicate runtimes are retained as provenance telemetry "
        "but excluded from logical identity. Their physical Parquet hashes may therefore differ "
        "between runs; every governed logical hash must still match exactly.",
        "",
        *_mapping_lines(logical_hashes, "Logical table hashes"),
        "",
        *_mapping_lines(physical_hashes, "Physical table hashes"),
        "",
        "## Validation and spot checks",
        "",
        f"- Metadata acceptance status: `{metadata['acceptance_status']}`",
        f"- Strict lexical validation passed: `{str(strict_validation.passed).lower()}`",
        f"- Strict validator scientific gate: `{_cell(strict_validation.scientific_gate_passed)}`",
        f"- Evaluation rows: `{metadata['evaluation_count']}`",
        f"- Strict validation error findings: `{errors}`",
        f"- Strict validation warning findings: `{warnings}`",
        f"- Expected structural spot checks without a match: `{missing_expected}`",
        f"- Complete preregistered ablation set: `{complete_ablation_text}`",
        f"- Complete required sensitivity set: `{complete_sensitivity_text}`",
        f"- Critical-core Tier 3 evaluation present: `{str(critical_core_evaluated).lower()}`",
        "- Detailed structural evidence: `m7-spot-check-evidence.md`.",
        "",
        *_markdown_frame(tables.issue_counts),
        "",
        "## Failed detectors or strata",
        "",
        "All persisted result rows remain in `m7-performance-by-stratum.csv`, including zero, "
        "insufficient-data, negative-difference, and failed slices. The report does not suppress "
        "a failed detector or replace it with a post-test tuned model.",
        "",
        *_markdown_frame(tables.failed_performance, limit=100),
        "",
        "## Known limitations",
        "",
        "- Tier 1 is empty; high-confidence quotation recovery remains untested.",
        "- OpenBible is Tier 3 weak supervision and its votes are descriptive.",
        "- Same-label mappings are provisional and versification risk remains explicit.",
        "- Full calibrated v1 coverage is verse-level; other granularities are smoke-tested "
        "interfaces.",
        "- Root coverage in the governed full corpora is absent; no root evidence is fabricated.",
        "- Cross-testament retrieval is English-gloss mediated and fails all-English ablation "
        "by design.",
        "- Hypergeometric values are analytical baselines; empirical null calibration is primary.",
        "- Calibration describes the deterministic candidate-union sample, not every possible "
        "pair.",
        "- The queue is unreviewed; no novelty claim or Milestone 8 review has begun.",
        "",
        "## Milestone 7 acceptance decision",
        "",
        "Milestone 7 is **"
        f"{'scientifically complete' if gate_passed else 'scientifically incomplete'}** "
        "under this report's fail-closed checks. The governed metadata science status, strict "
        "findings, required result tables, expected structural checks, and second-run logical "
        "hash comparison must all pass.",
        "",
        *next_task_lines,
    ]
    return "\n".join(lines), gate_passed


def _assert_existing_feature_audit(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LexicalReportError(
            "the full-corpus lexical feature audit must run before report generation: "
            f"{path}: {exc}"
        ) from exc
    if not content.startswith("# Milestone 7 lexical-feature and feasibility audit"):
        raise LexicalReportError("the lexical feature audit has an unexpected contract heading")
    if len(content.encode("utf-8")) > 1_000_000:
        raise LexicalReportError(
            "the tracked lexical feature audit exceeds the sanitized size limit"
        )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_atomic_text(path: Path, payload: str) -> None:
    normalized = payload if payload.endswith("\n") else payload + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(normalized, encoding="utf-8", newline="\n")
    temporary.replace(path)


def generate_lexical_baseline_reports(
    *,
    artifact_root: Path = DEFAULT_LEXICAL_ARTIFACT_ROOT,
    output_directory: Path = DEFAULT_REPORT_DIRECTORY,
    spot_check_config: Path = DEFAULT_SPOT_CHECK_CONFIG,
    comparison_manifest: Path | None = DEFAULT_FIRST_RUN_MANIFEST,
    lexical_config_path: Path = LEXICAL_CONFIG_PATH,
    preregistration_path: Path = LEXICAL_PREREGISTRATION_PATH,
    pr7_merge_commit: str = PR7_MERGE_COMMIT,
) -> LexicalReportArtifacts:
    """Generate the complete deterministic sanitized Milestone 7 report bundle."""

    if _COMMIT_RE.fullmatch(pr7_merge_commit) is None:
        raise LexicalReportError("PR #7 merge commit must be a complete lowercase SHA-1/256 hex")
    output_directory.mkdir(parents=True, exist_ok=True)
    audit_path = output_directory / REQUIRED_FEATURE_AUDIT
    _assert_existing_feature_audit(audit_path)
    tables, manifest, preregistration = collect_lexical_report_tables(
        artifact_root=artifact_root,
        spot_check_config=spot_check_config,
        lexical_config_path=lexical_config_path,
        preregistration_path=preregistration_path,
    )
    determinism = compare_lexical_manifests(
        manifest,
        comparison_manifest,
        current_metadata=tables.metadata,
    )
    production_root = artifact_root.resolve(strict=False) == DEFAULT_LEXICAL_ARTIFACT_ROOT.resolve(
        strict=False
    )
    strict_validation = validate_lexical_artifacts(
        artifact_root,
        database_path=Path("data/processed/project_echoes.duckdb") if production_root else None,
        config_path=lexical_config_path,
        preregistration_path=preregistration_path,
        verify_anchors=production_root,
        verify_duckdb=production_root,
        verify_sparse_indexes=production_root,
        strict=True,
    )
    report, gate_passed = _render_report(
        tables,
        manifest,
        preregistration,
        determinism,
        strict_validation,
        pr7_merge_commit=pr7_merge_commit,
    )
    payloads = {
        "milestone-7-lexical-baseline-report.md": report,
        "m7-feature-counts.csv": _csv_text(tables.feature_counts),
        "m7-detector-performance.csv": _csv_text(tables.detector_performance),
        "m7-performance-by-stratum.csv": _csv_text(tables.performance_by_stratum),
        "m7-null-calibration.csv": _csv_text(tables.null_calibration),
        "m7-thresholds.csv": _csv_text(tables.thresholds),
        "m7-rare-rule-effects.csv": _csv_text(tables.rare_rule_effects),
        "m7-english-ablation.csv": _csv_text(tables.english_ablation),
        "m7-unreviewed-candidate-queue.csv": _csv_text(tables.queue),
        "m7-spot-check-evidence.md": _spot_check_markdown(tables),
    }
    if tuple(payloads) != REPORT_OUTPUT_NAMES:
        raise LexicalReportError(
            "internal report output inventory differs from the governed bundle"
        )
    paths: list[Path] = [audit_path]
    hashes = {REQUIRED_FEATURE_AUDIT: hashlib.sha256(audit_path.read_bytes()).hexdigest()}
    for name, payload in payloads.items():
        target = output_directory / name
        _write_atomic_text(target, payload)
        paths.append(target)
        normalized = payload if payload.endswith("\n") else payload + "\n"
        hashes[name] = _sha256_text(normalized)
    return LexicalReportArtifacts(
        paths=tuple(paths),
        sha256_by_name=hashes,
        acceptance_gate_passed=gate_passed,
        determinism=determinism,
    )
