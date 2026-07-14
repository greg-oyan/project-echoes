"""Strict, bounded validation and read-only queries for Milestone 7 artifacts.

The validator treats the promoted Parquet tree as the authority and uses
DuckDB only for bounded relational checks.  It deliberately never reconstructs
or returns biblical text.  Runtime, local paths, and other non-deterministic
metadata are excluded from logical identity by the storage contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Literal, Self, cast

import duckdb
import numpy as np
import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.lexical.anchors import (
    BENCHMARK_LOGICAL_HASHES,
    CORPUS_ANALYTICAL_DIGESTS,
    CORPUS_CONTENT_DIGESTS,
    CORPUS_IDENTITY_DIGESTS,
    OSHB_LOGICAL_HASHES,
    PASSAGE_LOGICAL_HASHES,
    LexicalAnchorError,
    verify_upstream_anchors,
)
from echoes.lexical.config import (
    LexicalConfig,
    LexicalConfigError,
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
    LEXICAL_ARTIFACT_SCHEMAS,
    LEXICAL_ARTIFACT_SORT_COLUMNS,
    METADATA_NONDETERMINISTIC_COLUMNS,
    LexicalArtifactName,
    LexicalMetadataRow,
)
from echoes.lexical.resources import (
    LexicalResourceError,
    ProcessResourceGuard,
    configure_duckdb_connection,
)
from echoes.lexical.statistics import calibrate_null_counts, hypergeometric_upper_tail
from echoes.lexical.storage import (
    DUCKDB_ARTIFACT_NAMES,
    LEXICAL_CONVENIENCE_VIEWS,
    TABLE_HASH_FILE,
)
from echoes.manifest import sha256_file

Severity = Literal["error", "warning", "informational"]

DEFAULT_LEXICAL_ROOT = Path("data/processed/lexical/schema-v1")
DEFAULT_DATABASE_PATH = Path("data/processed/project_echoes.duckdb")
DEFAULT_PASSAGE_ROOT = Path("data/processed/passages/schema-v1")
DEFAULT_BENCHMARK_ROOT = Path("data/processed/benchmarks/schema-v1")
DEFAULT_TIER1_PATH = Path("data/benchmarks/tier1_quotations.csv")
DEFAULT_OSHB_ROOT = Path("data/processed/oshb-morphhb/master-3d15126")

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_LOCAL_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/](?:users|home)[\\/]|/(?:home|users)/)")
_KNOWN_LINK_STATUSES = {
    "represented_in_openbible_snapshot",
    "not_represented_in_openbible_snapshot",
    "mapping_unresolved",
}
_NULL_FAMILIES = {
    "within_book_reassignment",
    "frequency_preserving_synthetic",
}
_PRIMARY_CORPUS_PAIRS = {"hb_hb", "gnt_gnt"}
_CROSS_CORPUS_PAIR = "hb_gnt_english_bridge"
_ABLATION_NAMES = (
    "remove_tfidf",
    "remove_bm25",
    "remove_rare_evidence",
    "remove_phrase_evidence",
    "remove_ordered_sequence",
    "remove_formulaic_penalty",
    "remove_local_context_penalty",
    "remove_all_english_derived_features",
)
_DETECTOR_TRACE_ORDER = (
    "jaccard",
    "weighted_jaccard",
    "tfidf_cosine",
    "bm25",
    "rare_lemma_root",
    "phrase_association",
    "longest_common_subsequence",
    "weighted_sequence_alignment",
    "pos_morphology_support",
    "rrf_composite",
)
_REQUIRED_EVALUATION_STRATUM_DIMENSIONS = {
    "analysis_profile",
    "mapping_status",
    "corpus_pair",
    "split_strategy",
    "partition",
    "split_strategy_partition",
    "book",
    "broad_genre",
    "book_pair",
    "passage_length_bucket",
    "vote_stratum",
    "disputed_passage_status",
    "reference_gap_status",
    "corpus_pair_mapping_status",
}


class LexicalValidationError(RuntimeError):
    """Raised when the lexical artifact set cannot be inspected at all."""


class LexicalValidationIssue(BaseModel):
    """One aggregate, source-text-free validation finding."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifact: str | None = None
    record_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class LexicalValidationReport(BaseModel):
    """Machine-readable strict acceptance report."""

    model_config = ConfigDict(extra="forbid")

    output_dir: str
    experiment_run_id: str | None
    experiment_version: str | None
    configuration_hash: str | None
    preregistration_hash: str | None
    strict: bool
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    scientific_gate_passed: bool | None
    insufficient_primary_strata: list[str]
    issues: list[LexicalValidationIssue]
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    informational_count: int = Field(ge=0)
    passed: bool

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        observed = Counter(issue.severity for issue in self.issues)
        if self.error_count != observed["error"]:
            raise ValueError("lexical validation error count does not reconcile")
        if self.warning_count != observed["warning"]:
            raise ValueError("lexical validation warning count does not reconcile")
        if self.informational_count != observed["informational"]:
            raise ValueError("lexical validation informational count does not reconcile")
        expected = self.error_count == 0 and (not self.strict or self.warning_count == 0)
        if self.passed != expected:
            raise ValueError("lexical validation pass status does not reconcile")
        return self

    @property
    def exit_code(self) -> int:
        """Return the CLI-compatible process exit code."""

        return 0 if self.passed else 1


class LexicalSummary(BaseModel):
    """Sanitized aggregate summary used by ``lexical-summary``."""

    model_config = ConfigDict(extra="forbid")

    experiment_run_id: str
    experiment_version: str
    acceptance_status: str
    table_counts: dict[str, int]
    feature_counts_by_family: dict[str, int]
    passage_counts_by_corpus: dict[str, int]
    index_count: int
    index_nonzero_count: int
    ranking_counts_by_detector: dict[str, int]
    candidate_counts_by_corpus_pair: dict[str, int]
    known_link_status_counts: dict[str, int]
    review_eligible_count: int
    queue_count: int
    english_derived_candidate_count: int
    english_ablation_survival_count: int
    null_replicate_rows_by_family: dict[str, int]
    null_iterations_by_family: dict[str, int]
    evaluation_counts_by_detector: dict[str, int]
    table_logical_hashes: dict[str, str]
    storage_footprint_bytes: int


class LexicalDeterminismReport(BaseModel):
    """Logical comparison of two complete runs from identical frozen inputs."""

    model_config = ConfigDict(extra="forbid")

    first_run_id: str
    second_run_id: str
    run_id_matches: bool
    table_counts_match: bool
    logical_hashes_match: bool
    differing_tables: list[str]
    passed: bool


@dataclass(slots=True)
class _State:
    output_dir: Path
    strict: bool
    issues: list[LexicalValidationIssue] = field(default_factory=list)
    table_counts: dict[str, int] = field(default_factory=dict)
    logical_hashes: dict[str, str] = field(default_factory=dict)
    physical_hashes: dict[str, str] = field(default_factory=dict)
    experiment_run_id: str | None = None
    experiment_version: str | None = None
    configuration_hash: str | None = None
    preregistration_hash: str | None = None
    acceptance_status: str | None = None
    scientific_gate_passed: bool | None = None
    insufficient_primary_strata: list[str] = field(default_factory=list)

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: Severity = "error",
        artifact: str | None = None,
        record_id: str | None = None,
        **details: object,
    ) -> None:
        self.issues.append(
            LexicalValidationIssue(
                severity=severity,
                code=code,
                message=message,
                artifact=artifact,
                record_id=record_id,
                details=details,
            )
        )


def _canonical_aggregate(leaves: Mapping[str, Mapping[str, object]], key: str) -> str:
    payload = [
        {"path": path, "row_count": values["row_count"], key: values[key]}
        for path, values in sorted(leaves.items())
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        return {}
    return cast(dict[str, object], parsed)


def _json_array(value: object) -> list[object]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return cast(list[object], parsed) if isinstance(parsed, list) else []


def _recursive_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _recursive_strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _recursive_strings(item)


def _contains_all_hashes(value: object, expected: Mapping[str, str]) -> bool:
    observed = set(_recursive_strings(value))
    return set(expected.values()).issubset(observed)


def _logical_leaf_hash(path: Path, name: LexicalArtifactName) -> tuple[str, bool, int]:
    """Reproduce one writer leaf hash incrementally and check its stored ordering."""

    expected_columns = LEXICAL_ARTIFACT_COLUMNS[name]
    expected_schema = LEXICAL_ARTIFACT_SCHEMAS[name]
    logical_columns = tuple(
        column for column in expected_columns if column not in METADATA_NONDETERMINISTIC_COLUMNS
    )
    empty = pl.DataFrame(schema=expected_schema).select(logical_columns)
    digest = hashlib.sha256()
    digest.update("\0".join(empty.columns).encode("utf-8"))
    digest.update(b"\0")
    digest.update("\0".join(str(dtype) for dtype in empty.dtypes).encode("utf-8"))
    digest.update(b"\0")
    ordered = True
    count = 0
    previous_sort_row: pl.DataFrame | None = None
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=65_536,
        columns=list(expected_columns),
        use_threads=False,
    ):
        converted = pl.from_arrow(batch)
        if not isinstance(converted, pl.DataFrame):  # pragma: no cover - Arrow batch is tabular
            raise LexicalValidationError(f"could not read tabular Parquet batch from {path}")
        typed = converted.cast(expected_schema, strict=True)
        sort_columns = list(LEXICAL_ARTIFACT_SORT_COLUMNS[name])
        if typed.height and sort_columns:
            sort_frame = typed.select(sort_columns)
            ordered = ordered and sort_frame.equals(sort_frame.sort(sort_columns, nulls_last=True))
            if previous_sort_row is not None:
                boundary = pl.concat([previous_sort_row, sort_frame.head(1)])
                ordered = ordered and boundary.equals(boundary.sort(sort_columns, nulls_last=True))
            previous_sort_row = sort_frame.tail(1)
        logical = typed.select(logical_columns)
        for value in logical.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3):
            digest.update(int(value).to_bytes(8, byteorder="little", signed=False))
        count += typed.height
    return digest.hexdigest(), ordered, count


def _comparable_sort_key(values: tuple[object, ...]) -> tuple[tuple[bool, object], ...]:
    """Map a typed row key to the governed nulls-last ordering."""

    return tuple((value is None, 0 if value is None else value) for value in values)


def _logical_table_hash(paths: Sequence[Path], name: LexicalArtifactName) -> str:
    """Reproduce the writer's global, part-boundary-independent table hash.

    Most production leaves are already globally ordered and can be hashed in one
    bounded streaming pass.  If a leaf boundary is out of order, use the same
    bounded DuckDB external merge sort as the writer before hashing.
    """

    if not paths:
        raise LexicalValidationError(f"no Parquet leaves exist for {name}")
    expected_columns = LEXICAL_ARTIFACT_COLUMNS[name]
    expected_schema = LEXICAL_ARTIFACT_SCHEMAS[name]
    logical_columns = tuple(
        column for column in expected_columns if column not in METADATA_NONDETERMINISTIC_COLUMNS
    )
    sort_columns = list(LEXICAL_ARTIFACT_SORT_COLUMNS[name])

    def initialized_digest() -> hashlib._Hash:
        empty = pl.DataFrame(schema=expected_schema).select(logical_columns)
        digest = hashlib.sha256()
        digest.update("\0".join(empty.columns).encode("utf-8"))
        digest.update(b"\0")
        digest.update("\0".join(str(dtype) for dtype in empty.dtypes).encode("utf-8"))
        digest.update(b"\0")
        return digest

    digest = initialized_digest()
    previous_key: tuple[tuple[bool, object], ...] | None = None
    globally_ordered = True
    for path in paths:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=65_536,
            columns=list(expected_columns),
            use_threads=False,
        ):
            converted = pl.from_arrow(batch)
            if not isinstance(converted, pl.DataFrame):  # pragma: no cover
                raise LexicalValidationError(f"could not read tabular Parquet batch from {path}")
            typed = converted.cast(expected_schema, strict=True)
            if typed.height and sort_columns:
                keys = typed.select(sort_columns)
                first_key = _comparable_sort_key(keys.row(0))
                if previous_key is not None and first_key < previous_key:
                    globally_ordered = False
                    break
                previous_key = _comparable_sort_key(keys.row(-1))
            logical = typed.select(logical_columns)
            for value in logical.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3):
                digest.update(int(value).to_bytes(8, byteorder="little", signed=False))
        if not globally_ordered:
            break
    if globally_ordered:
        return digest.hexdigest()

    escaped_glob = (paths[0].parent / "part-*.parquet").as_posix().replace("'", "''")
    order = ", ".join(f'"{column}" NULLS LAST' for column in sort_columns)
    digest = initialized_digest()
    try:
        with (
            TemporaryDirectory(prefix="echoes-lexical-logical-sort-") as temporary,
            duckdb.connect() as connection,
        ):
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=2 * 1024**3,
                temp_directory=Path(temporary) / "spill",
                thread_count=1,
            )
            connection.execute("SET preserve_insertion_order=false")
            reader = connection.execute(
                f"SELECT * FROM read_parquet('{escaped_glob}') ORDER BY {order}"
            ).to_arrow_reader(65_536)
            for batch in reader:
                frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).select(
                    logical_columns
                )
                for value in frame.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3):
                    digest.update(int(value).to_bytes(8, byteorder="little", signed=False))
    except (duckdb.Error, OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalValidationError(
            f"could not externally sort {name} for logical hashing: {exc}"
        ) from exc
    return digest.hexdigest()


def sparse_index_physical_hash(index_directory: Path) -> str:
    """Hash one index directory as a deterministic aggregate of physical files."""

    files = [path for path in sorted(index_directory.iterdir()) if path.is_file()]
    payload = [
        {"path": path.name, "sha256": sha256_file(path), "size": path.stat().st_size}
        for path in files
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def shared_evidence_digest(rows: Sequence[Mapping[str, object]]) -> str:
    """Return the governed digest for all detailed evidence supporting one pair.

    Notes are included: silently changing an evidence caveat must change the digest.
    Input row order is immaterial.
    """

    canonical_rows = [
        {column: row[column] for column in LEXICAL_ARTIFACT_COLUMNS["shared_evidence"]}
        for row in rows
    ]
    canonical_rows.sort(
        key=lambda row: (
            str(row["evidence_family"]),
            str(row["feature_id"]),
            str(row["evidence_id"]),
        )
    )
    canonical = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def score_trace_digest(score_components_json: str) -> str:
    """Hash one canonical, decomposed detector-score trace."""

    parsed = json.loads(score_components_json)
    if not isinstance(parsed, dict):
        raise ValueError("detector score components must be a JSON object")
    canonical = json.dumps(
        parsed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    if canonical != score_components_json:
        raise ValueError("detector score components must use canonical JSON")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def detector_trace_digest(rows: Sequence[Mapping[str, object]]) -> str:
    """Hash the governed detector trace inventory for one candidate."""

    order = {name: index for index, name in enumerate(_DETECTOR_TRACE_ORDER)}
    unknown = sorted({str(row["detector"]) for row in rows}.difference(order))
    if unknown:
        raise ValueError(f"unknown detector trace names: {unknown}")
    payload = [
        {
            "detector": row["detector"],
            "direction": row["direction"],
            "score_trace_digest": row["score_trace_digest"],
        }
        for row in sorted(rows, key=lambda row: order[str(row["detector"])])
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def ablation_result_digest(row: Mapping[str, object]) -> str:
    """Hash one typed ablation result without its identity or self-digest."""

    payload = {
        column: row[column]
        for column in LEXICAL_ARTIFACT_COLUMNS["ablation_results"]
        if column not in {"ablation_result_id", "evidence_digest"}
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def ablation_family_digest(rows: Sequence[Mapping[str, object]]) -> str:
    """Hash the eight governed candidate ablations in frozen order."""

    order = {name: index for index, name in enumerate(_ABLATION_NAMES)}
    unknown = sorted({str(row["ablation_name"]) for row in rows}.difference(order))
    if unknown:
        raise ValueError(f"unknown ablation names: {unknown}")
    payload = [
        {
            "ablation_name": row["ablation_name"],
            "evidence_digest": row["evidence_digest"],
        }
        for row in sorted(rows, key=lambda row: order[str(row["ablation_name"])])
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def candidate_evidence_digest(
    evidence_row: Mapping[str, object],
    *,
    shared_digest: str,
    detector_digest: str,
    ablation_digest: str,
) -> str:
    """Hash a complete candidate proof, including scores, penalties, and ablations."""

    candidate_evidence = {
        column: evidence_row[column]
        for column in LEXICAL_ARTIFACT_COLUMNS["candidate_evidence"]
        if column != "evidence_digest"
    }
    payload = {
        "candidate_evidence": candidate_evidence,
        "shared_evidence_digest": shared_digest,
        "detector_trace_digest": detector_digest,
        "ablation_digest": ablation_digest,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def null_replicate_logical_hash(row: Mapping[str, object]) -> str:
    """Hash one null summary without its self-hash or measured runtime."""

    columns = (
        column
        for column in LEXICAL_ARTIFACT_COLUMNS["null_replicate_summaries"]
        if column not in {"logical_output_hash", "runtime_seconds"}
    )
    payload = {column: row[column] for column in columns}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _derived_null_seed(base_seed: int, stratum_key: str, family: str, iteration: int) -> int:
    payload = "\x1f".join((str(base_seed), stratum_key, family, str(iteration))).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)
    return seed or 1


def _audit_storage(state: _State) -> dict[str, object] | None:
    manifest_path = state.output_dir / TABLE_HASH_FILE
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        state.add("hash_manifest_invalid", f"Could not read lexical hash manifest: {exc}.")
        return None
    if not isinstance(manifest_raw, dict):
        state.add("hash_manifest_invalid", "Lexical hash manifest is not a JSON object.")
        return None
    manifest = cast(dict[str, object], manifest_raw)
    if manifest.get("schema_version") != 1:
        state.add("hash_manifest_schema", "Lexical hash manifest schema version must be 1.")
    if manifest.get("metadata_nondeterministic_columns") != sorted(
        METADATA_NONDETERMINISTIC_COLUMNS
    ):
        state.add(
            "hash_manifest_nondeterminism",
            "Manifest does not exclude exactly the governed measured and physical-provenance "
            "fields from logical identity.",
        )
    expected_names = set(LEXICAL_ARTIFACT_NAMES)
    raw_artifacts = manifest.get("artifacts")
    artifacts = raw_artifacts if isinstance(raw_artifacts, dict) else {}
    raw_counts = manifest.get("table_counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    raw_logical = manifest.get("table_logical_sha256")
    logical = raw_logical if isinstance(raw_logical, dict) else {}
    raw_physical = manifest.get("table_physical_sha256")
    physical = raw_physical if isinstance(raw_physical, dict) else {}
    for field_name, values in (
        ("artifacts", artifacts),
        ("table_counts", counts),
        ("table_logical_sha256", logical),
        ("table_physical_sha256", physical),
    ):
        if set(values) != expected_names:
            state.add(
                "hash_manifest_artifact_set",
                f"{field_name} must name exactly all governed lexical artifacts.",
            )
    observed_files: set[str] = set()
    for name in LEXICAL_ARTIFACT_NAMES:
        directory = state.output_dir / name
        paths = sorted(directory.glob("part-*.parquet"))
        if not paths:
            state.add("artifact_missing", "No Parquet leaves found.", artifact=name)
            continue
        raw_leaves = artifacts.get(name)
        expected_leaves = raw_leaves if isinstance(raw_leaves, dict) else {}
        actual_leaf_names = {path.relative_to(state.output_dir).as_posix() for path in paths}
        if set(expected_leaves) != actual_leaf_names:
            state.add(
                "artifact_leaf_set",
                "Parquet leaf set differs from the hash manifest.",
                artifact=name,
            )
        leaf_values: dict[str, dict[str, object]] = {}
        table_count = 0
        for path in paths:
            relative = path.relative_to(state.output_dir).as_posix()
            observed_files.add(relative)
            try:
                observed_schema = pl.scan_parquet(path).collect_schema()
            except (OSError, pl.exceptions.PolarsError) as exc:
                state.add(
                    "parquet_unreadable",
                    f"Could not inspect Parquet schema: {exc}.",
                    artifact=name,
                )
                continue
            if observed_schema != LEXICAL_ARTIFACT_SCHEMAS[name]:
                state.add(
                    "parquet_schema",
                    "Parquet columns or dtypes differ from the governed schema.",
                    artifact=name,
                    path=relative,
                )
                continue
            try:
                logical_hash, is_ordered, row_count = _logical_leaf_hash(path, name)
                physical_hash = sha256_file(path)
            except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                state.add(
                    "parquet_hash_failure",
                    f"Could not reproduce Parquet hashes: {exc}.",
                    artifact=name,
                    path=relative,
                )
                continue
            if not is_ordered:
                state.add(
                    "parquet_order",
                    "A Parquet leaf is not in governed deterministic sort order.",
                    artifact=name,
                    path=relative,
                )
            table_count += row_count
            leaf_values[relative] = {
                "row_count": row_count,
                "logical_sha256": logical_hash,
                "parquet_sha256": physical_hash,
            }
            expected_leaf = expected_leaves.get(relative)
            if not isinstance(expected_leaf, dict) or any(
                expected_leaf.get(key) != value for key, value in leaf_values[relative].items()
            ):
                state.add(
                    "leaf_hash_mismatch",
                    "Leaf count, logical hash, or physical hash differs from manifest.",
                    artifact=name,
                    path=relative,
                )
        state.table_counts[name] = table_count
        if leaf_values:
            try:
                state.logical_hashes[name] = _logical_table_hash(paths, name)
            except (LexicalValidationError, OSError, ValueError, pl.exceptions.PolarsError) as exc:
                state.add(
                    "table_logical_hash_failure",
                    f"Could not reproduce the global logical table hash: {exc}.",
                    artifact=name,
                )
            state.physical_hashes[name] = _canonical_aggregate(leaf_values, "parquet_sha256")
        if counts.get(name) != table_count:
            state.add(
                "table_count_mismatch",
                "Observed table count differs from the hash manifest.",
                artifact=name,
            )
        if logical.get(name) != state.logical_hashes.get(name):
            state.add(
                "table_logical_hash_mismatch",
                "Reproduced logical hash differs from the hash manifest.",
                artifact=name,
            )
        if physical.get(name) != state.physical_hashes.get(name):
            state.add(
                "table_physical_hash_mismatch",
                "Reproduced physical hash differs from the hash manifest.",
                artifact=name,
            )
    raw_file_hashes = manifest.get("file_sha256")
    file_hashes = raw_file_hashes if isinstance(raw_file_hashes, dict) else {}
    for relative_raw, expected_hash in file_hashes.items():
        relative = str(relative_raw)
        path = state.output_dir / Path(relative)
        observed_files.add(relative)
        if not path.is_file():
            state.add("manifest_file_missing", "Manifest-listed file is absent.", path=relative)
        elif sha256_file(path) != expected_hash:
            state.add("manifest_file_hash", "Manifest-listed file hash differs.", path=relative)
    actual_files = {
        path.relative_to(state.output_dir).as_posix()
        for path in state.output_dir.rglob("*")
        if path.is_file() and path.name != TABLE_HASH_FILE
    }
    if actual_files != set(str(key) for key in file_hashes):
        state.add(
            "manifest_file_set",
            "The promoted artifact file set differs from file_sha256.",
            missing=sorted(actual_files.difference(file_hashes)),
            unexpected=sorted(set(file_hashes).difference(actual_files)),
        )
    return manifest


@contextmanager
def _artifact_connection(output_dir: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with (
        TemporaryDirectory(prefix="echoes-lexical-validation-") as temporary,
        duckdb.connect(":memory:") as connection,
    ):
        configure_duckdb_connection(
            connection,
            memory_limit_bytes=2 * 1024**3,
            temp_directory=Path(temporary) / "spill",
            thread_count=1,
        )
        connection.execute("SET preserve_insertion_order=false")
        for name in LEXICAL_ARTIFACT_NAMES:
            glob = (output_dir / name / "part-*.parquet").as_posix().replace("'", "''")
            connection.execute(
                f'CREATE VIEW "{name}" AS '
                f"SELECT * FROM read_parquet('{glob}', union_by_name=true)"
            )
        yield connection


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    if row is None:
        raise LexicalValidationError("validation scalar query returned no row")
    return int(row[0])


def _fetchmany(
    cursor: duckdb.DuckDBPyConnection, batch_size: int = 65_536
) -> Iterator[tuple[object, ...]]:
    """Yield query rows without materializing an unbounded result set."""

    while rows := cursor.fetchmany(batch_size):
        yield from cast(list[tuple[object, ...]], rows)


def _count_check(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    *,
    artifact: str,
    code: str,
    message: str,
    sql: str,
    severity: Severity = "error",
) -> int:
    try:
        count = _scalar(connection, sql)
    except duckdb.Error as exc:
        state.add(
            "validation_query_failure",
            f"Validation query for {code} failed: {exc}.",
            artifact=artifact,
        )
        return -1
    if count:
        state.add(code, f"{message} Count={count}.", severity=severity, artifact=artifact)
    return count


def _validate_generic_tables(state: _State, connection: duckdb.DuckDBPyConnection) -> None:
    nullable_columns: dict[str, set[str]] = {
        "directional_rankings": {"rank_after_removing_all_english_features"},
        "candidate_pairs": {
            "highest_openbible_vote",
            "benchmark_tier",
            "score_with_english_features",
            "score_after_removing_all_english_features",
            "rank_with_english_features",
            "rank_after_removing_all_english_features",
        },
        "candidate_detector_scores": {"query_rank", "reverse_rank"},
        "threshold_calibration": {
            "observed_to_null_enrichment",
            "estimated_empirical_fdr",
        },
        "evaluation_results": {"k"},
        "ablation_results": {
            "candidate_pair_id",
            "ranking_id",
            "rank_after",
        },
        "sensitivity_results": {
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
            "excluded_reason",
        },
    }
    unique_keys: dict[str, tuple[str, ...]] = {
        "feature_vocabulary": ("feature_id",),
        "passage_feature_statistics": ("passage_id",),
        "lexical_index_metadata": ("index_id",),
        "directional_rankings": ("ranking_id",),
        "candidate_pairs": ("candidate_pair_id",),
        "candidate_detector_scores": (
            "candidate_pair_id",
            "detector",
            "representation_id",
            "direction",
        ),
        "candidate_evidence": ("candidate_pair_id",),
        "shared_evidence": ("evidence_id",),
        "null_replicate_summaries": (
            "null_family",
            "corpus_pair",
            "representation_id",
            "detector",
            "threshold_id",
            "iteration",
        ),
        "threshold_calibration": (
            "corpus_pair",
            "representation_id",
            "detector",
            "threshold_id",
        ),
        "evaluation_results": ("evaluation_id",),
        "ablation_results": ("ablation_result_id",),
        "sensitivity_results": ("sensitivity_id",),
        "candidate_review_queue": ("queue_rank",),
        "lexical_issues": ("issue_id",),
    }
    for name, columns in unique_keys.items():
        rendered = ", ".join(f'"{column}"' for column in columns)
        _count_check(
            state,
            connection,
            artifact=name,
            code="duplicate_key",
            message=f"Rows do not have a unique key ({', '.join(columns)}).",
            sql=(
                f'SELECT count(*) FROM (SELECT {rendered}, count(*) AS n FROM "{name}" '
                f"GROUP BY {rendered} HAVING n > 1)"
            ),
        )
    for name, schema in LEXICAL_ARTIFACT_SCHEMAS.items():
        required_columns = [
            column for column in schema if column not in nullable_columns.get(name, set())
        ]
        null_predicate = " OR ".join(f'"{column}" IS NULL' for column in required_columns)
        _count_check(
            state,
            connection,
            artifact=name,
            code="null_required_field",
            message="A governed non-null field contains null.",
            sql=f'SELECT count(*) FROM "{name}" WHERE {null_predicate}',
        )
        float_columns = [
            column for column, dtype in schema.items() if dtype in {pl.Float32, pl.Float64}
        ]
        if float_columns:
            predicate = " OR ".join(f'NOT isfinite("{column}")' for column in float_columns)
            _count_check(
                state,
                connection,
                artifact=name,
                code="nonfinite_numeric",
                message="NaN or infinite numeric values are forbidden.",
                sql=f'SELECT count(*) FROM "{name}" WHERE {predicate}',
            )
        json_columns = [column for column in schema if column.endswith("_json")]
        if json_columns:
            predicate = " OR ".join(f'NOT json_valid("{column}")' for column in json_columns)
            _count_check(
                state,
                connection,
                artifact=name,
                code="invalid_json",
                message="Persisted JSON is invalid.",
                sql=f'SELECT count(*) FROM "{name}" WHERE {predicate}',
            )
        string_columns = [column for column, dtype in schema.items() if dtype == pl.String]
        if string_columns:
            path_predicate = " OR ".join(
                f'regexp_matches("{column}", '
                "'(?i)([a-z]:[/\\\\](users|home)[/\\\\]|/(home|users)/)')"
                for column in string_columns
            )
            _count_check(
                state,
                connection,
                artifact=name,
                code="local_path_leak",
                message="Logical artifacts contain a local absolute path.",
                sql=f'SELECT count(*) FROM "{name}" WHERE {path_predicate}',
            )


def _validate_metadata(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    manifest: Mapping[str, object],
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
) -> LexicalMetadataRow | None:
    rows = connection.execute("SELECT * FROM lexical_metadata").fetchall()
    columns = [description[0] for description in connection.description]
    if len(rows) != 1:
        state.add("metadata_cardinality", "Lexical metadata must contain exactly one row.")
        return None
    raw = dict(zip(columns, rows[0], strict=True))
    try:
        metadata = LexicalMetadataRow.model_validate(raw)
    except ValidationError as exc:
        state.add("metadata_row", f"Lexical metadata row is invalid: {exc}.")
        return None
    state.experiment_run_id = metadata.experiment_run_id
    state.experiment_version = metadata.experiment_version
    state.configuration_hash = metadata.configuration_hash
    state.preregistration_hash = metadata.preregistration_hash
    state.acceptance_status = metadata.acceptance_status
    expected_config_hash = lexical_config_sha256(config)
    expected_preregistration_hash = lexical_preregistration_sha256(preregistration)
    if metadata.experiment_version != config.experiment_version:
        state.add("metadata_experiment_version", "Metadata experiment version differs from config.")
    if metadata.configuration_hash != expected_config_hash:
        state.add("metadata_config_hash", "Metadata configuration hash differs from config.")
    if metadata.preregistration_hash != expected_preregistration_hash:
        state.add(
            "metadata_preregistration_hash",
            "Metadata preregistration hash differs from the frozen preregistration.",
        )
    expected_counts = cast(Mapping[str, object], manifest.get("table_counts", {}))
    count_fields = {
        "directional_rankings": metadata.ranking_count,
        "candidate_pairs": metadata.candidate_count,
        "evaluation_results": metadata.evaluation_count,
    }
    for artifact, recorded in count_fields.items():
        if recorded != expected_counts.get(artifact):
            state.add(
                "metadata_count_mismatch",
                f"Metadata count differs for {artifact}.",
                artifact=artifact,
            )
    distinct_null_iterations = _scalar(
        connection,
        "SELECT count(*) FROM (SELECT DISTINCT null_run_id FROM null_replicate_summaries)",
    )
    if metadata.null_iteration_count != distinct_null_iterations:
        state.add(
            "metadata_count_mismatch",
            "Metadata null-iteration count differs from retained distinct null runs.",
            artifact="null_replicate_summaries",
        )
    for field_name, manifest_name in (
        ("table_logical_hashes_json", "table_logical_sha256"),
        ("table_physical_hashes_json", "table_physical_sha256"),
    ):
        recorded_hashes = _json_object(getattr(metadata, field_name))
        expected = cast(Mapping[str, object], manifest.get(manifest_name, {}))
        expected_without_metadata = {
            str(key): value for key, value in expected.items() if key != "lexical_metadata"
        }
        if recorded_hashes != expected_without_metadata and recorded_hashes != dict(expected):
            state.add(
                "metadata_table_hashes",
                f"Metadata {field_name} differs from the promoted manifest.",
            )
    sparse_hashes = _json_object(metadata.sparse_index_hashes_json)
    index_rows = connection.execute(
        "SELECT index_id, logical_matrix_hash FROM lexical_index_metadata"
    ).fetchall()
    expected_sparse = {str(index_id): str(logical_hash) for index_id, logical_hash in index_rows}
    if sparse_hashes != expected_sparse:
        state.add(
            "metadata_sparse_hashes",
            "Metadata sparse-index hashes differ from index metadata.",
        )
    feature_hashes = _json_object(metadata.feature_vocabulary_hashes_json)
    if not feature_hashes or any(
        not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
        for value in feature_hashes.values()
    ):
        state.add(
            "metadata_feature_hashes",
            "Feature-vocabulary hash registry is empty or contains invalid hashes.",
        )
    anchors = (
        (_json_object(metadata.input_corpus_hashes_json), CORPUS_IDENTITY_DIGESTS),
        (_json_object(metadata.input_corpus_hashes_json), CORPUS_CONTENT_DIGESTS),
        (_json_object(metadata.input_corpus_hashes_json), CORPUS_ANALYTICAL_DIGESTS),
        (_json_object(metadata.input_corpus_hashes_json), OSHB_LOGICAL_HASHES),
        (_json_object(metadata.passage_hashes_json), PASSAGE_LOGICAL_HASHES),
        (_json_object(metadata.benchmark_hashes_json), BENCHMARK_LOGICAL_HASHES),
    )
    if any(not _contains_all_hashes(observed, expected) for observed, expected in anchors):
        state.add(
            "metadata_input_anchors",
            "Metadata does not retain every fixed corpus, OSHB, passage, and benchmark hash.",
        )
    if not _json_object(metadata.numerical_environment_json):
        state.add("metadata_numerical_environment", "Numerical environment metadata is empty.")
    if not _json_object(metadata.thread_controls_json):
        state.add("metadata_thread_controls", "Thread-control metadata is empty.")
    for value in (
        metadata.input_corpus_hashes_json,
        metadata.passage_hashes_json,
        metadata.benchmark_hashes_json,
        metadata.feature_vocabulary_hashes_json,
        metadata.sparse_index_hashes_json,
        metadata.table_logical_hashes_json,
        metadata.table_physical_hashes_json,
        metadata.numerical_environment_json,
        metadata.thread_controls_json,
        metadata.notes,
    ):
        if _LOCAL_PATH_RE.search(value):
            state.add("metadata_local_path", "Metadata contains a local absolute path.")
            break
    run_tables = (
        "lexical_index_metadata",
        "directional_rankings",
        "candidate_pairs",
        "null_replicate_summaries",
        "threshold_calibration",
        "evaluation_results",
        "lexical_issues",
    )
    for table in run_tables:
        _count_check(
            state,
            connection,
            artifact=table,
            code="experiment_run_mismatch",
            message="Rows do not share the metadata experiment run ID.",
            sql=(
                f'SELECT count(*) FROM "{table}" WHERE experiment_run_id IS DISTINCT FROM ?'
            ).replace("?", "'" + metadata.experiment_run_id.replace("'", "''") + "'"),
        )
    return metadata


def _validate_feature_integrity(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
) -> None:
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="feature_namespace_family",
        message="Feature language namespace does not match its family.",
        sql=(
            "SELECT count(*) FROM feature_vocabulary WHERE "
            "(feature_family='english_gloss') <> (language_namespace='en')"
        ),
    )
    high_ratio = config.feature_frequency_thresholds.high_document_frequency_ratio
    formulaic_ratio = config.feature_frequency_thresholds.formulaic_document_frequency_ratio
    formulaic_minimum = config.feature_frequency_thresholds.formulaic_minimum_corpus_count
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="feature_frequency_flags",
        message="Document-frequency bounds, IDF, high-frequency, or formulaic flags differ.",
        sql=(
            "WITH documents AS (SELECT 'hb' AS namespace,count(*) AS n FROM "
            "passage_feature_statistics WHERE corpus='hebrew' UNION ALL SELECT 'gk',count(*) "
            "FROM passage_feature_statistics WHERE corpus='greek' UNION ALL SELECT 'en',count(*) "
            "FROM passage_feature_statistics) SELECT count(*) FROM feature_vocabulary f "
            "JOIN documents d ON d.namespace=f.language_namespace WHERE "
            "f.document_frequency>d.n OR f.book_frequency>f.document_frequency OR "
            "f.genre_frequency>f.document_frequency OR abs(f.inverse_document_frequency-"
            "(ln((1.0+d.n)/(1.0+f.document_frequency))+1.0))>1e-12 OR "
            f"f.is_high_frequency<>(f.document_frequency/d.n>={high_ratio!r}) OR "
            "f.is_formulaic<>"
            f"(f.corpus_frequency>={formulaic_minimum} AND "
            f"f.document_frequency/d.n>={formulaic_ratio!r})"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="feature_corpus_frequency_reconciliation",
        message="Unigram corpus frequencies do not reconcile to nonduplicated passage streams.",
        sql=(
            "WITH observed AS (SELECT language_namespace,feature_family,sum(corpus_frequency) "
            "AS n FROM feature_vocabulary WHERE feature_family IN ('lemma','root','english_gloss') "
            "GROUP BY ALL), expected AS (SELECT 'hb' AS language_namespace,'lemma' AS "
            "feature_family,sum(lemma_sequence_length) AS n FROM passage_feature_statistics "
            "WHERE corpus='hebrew' UNION ALL SELECT 'gk','lemma',sum(lemma_sequence_length) "
            "FROM passage_feature_statistics WHERE corpus='greek' UNION ALL SELECT 'hb','root',"
            "sum(root_sequence_length) FROM passage_feature_statistics WHERE corpus='hebrew' "
            "UNION ALL SELECT 'gk','root',sum(root_sequence_length) FROM "
            "passage_feature_statistics WHERE corpus='greek' UNION ALL SELECT 'en',"
            "'english_gloss',sum(english_gloss_sequence_length) FROM passage_feature_statistics) "
            "SELECT count(*) FROM expected e LEFT JOIN observed o "
            "USING(language_namespace,feature_family) WHERE coalesce(o.n,0)<>coalesce(e.n,0)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="english_feature_label",
        message="English-derived feature marker is incorrect.",
        sql=(
            "SELECT count(*) FROM feature_vocabulary WHERE "
            "contains_english_derived_content <> (language_namespace='en')"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="feature_frequency",
        message="Feature frequencies are internally impossible.",
        sql=(
            "SELECT count(*) FROM feature_vocabulary WHERE corpus_frequency < document_frequency "
            "OR document_frequency < 1 OR book_frequency < 1 OR genre_frequency < 1"
        ),
    )
    threshold = config.rare_evidence.maximum_corpus_frequency
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="rare_flag",
        message="Rare flags do not reproduce from the configured threshold.",
        sql=(
            "SELECT count(*) FROM feature_vocabulary WHERE "
            f"is_rare <> (corpus_frequency <= {threshold})"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="feature_identity",
        message="Feature identities do not reproduce from canonical payloads.",
        sql=(
            "SELECT count(*) FROM feature_vocabulary WHERE feature_id <> 'LF_' || sha256("
            "to_json(struct_pack(feature_family := feature_family, "
            "feature_order := feature_order, feature_schema_version := 1, "
            "feature_value := feature_value, language_namespace := language_namespace)))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="feature_vocabulary",
        code="cross_language_feature_collision",
        message="One feature ID is associated with multiple language namespaces.",
        sql=(
            "SELECT count(*) FROM (SELECT feature_id FROM feature_vocabulary "
            "GROUP BY feature_id HAVING count(DISTINCT language_namespace)>1)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="passage_feature_statistics",
        code="passage_feature_count",
        message="Passage feature counts are internally inconsistent.",
        sql=(
            "SELECT count(*) FROM passage_feature_statistics WHERE "
            "eligible_token_count > token_count OR distinct_lemma_count > lemma_sequence_length "
            "OR distinct_root_count > root_sequence_length "
            "OR lemma_sequence_length > eligible_token_count "
            "OR root_sequence_length > eligible_token_count"
        ),
    )


def _validate_sparse_indexes(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = connection.execute("SELECT * FROM lexical_index_metadata ORDER BY index_id").fetchall()
    columns = [description[0] for description in connection.description]
    for values in rows:
        row = dict(zip(columns, values, strict=True))
        index_id = str(row["index_id"])
        try:
            shape_values = _json_array(row["matrix_shape_json"])
            if len(shape_values) != 2:
                raise ValueError("matrix shape must have two dimensions")
            shape = (int(str(shape_values[0])), int(str(shape_values[1])))
        except (TypeError, ValueError) as exc:
            state.add(
                "index_shape_json",
                f"Index matrix shape is invalid: {exc}.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
            continue
        if shape != (int(row["document_count"]), int(row["vocabulary_size"])):
            state.add(
                "index_shape_metadata",
                "Index shape does not match document and vocabulary counts.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        if str(row["dtype"]) != "float64":
            state.add(
                "index_dtype",
                "Governed sparse indexes must use float64.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        index_directory = state.output_dir / "indexes" / str(row["representation_id"])
        required = {
            "counts-data.npy",
            "counts-indices.npy",
            "counts-indptr.npy",
            "shape.npy",
            "corpus-frequency.npy",
            "document-frequency.npy",
            "idf.npy",
            "metadata.json",
        }
        observed_index_files = (
            {path.name for path in index_directory.iterdir() if path.is_file()}
            if index_directory.is_dir()
            else set()
        )
        if observed_index_files != required:
            state.add(
                "index_files_missing",
                "Sparse index directory does not contain exactly the canonical CSR files.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
            continue
        try:
            disk_shape = tuple(
                int(value) for value in np.load(index_directory / "shape.npy", allow_pickle=False)
            )
            data = np.load(index_directory / "counts-data.npy", mmap_mode="r", allow_pickle=False)
            indices = np.load(
                index_directory / "counts-indices.npy", mmap_mode="r", allow_pickle=False
            )
            indptr = np.load(
                index_directory / "counts-indptr.npy", mmap_mode="r", allow_pickle=False
            )
            corpus_frequency = np.load(
                index_directory / "corpus-frequency.npy", mmap_mode="r", allow_pickle=False
            )
            document_frequency = np.load(
                index_directory / "document-frequency.npy", mmap_mode="r", allow_pickle=False
            )
            idf = np.load(index_directory / "idf.npy", mmap_mode="r", allow_pickle=False)
            metadata = json.loads((index_directory / "metadata.json").read_text("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            state.add(
                "index_files_invalid",
                f"Sparse index files are invalid: {exc}.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
            continue
        if disk_shape != shape or len(data) != int(row["nonzero_count"]):
            state.add(
                "index_shape_nonzero",
                "Sparse array shape or nonzero count differs from metadata.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        if (
            len(indices) != len(data)
            or len(indptr) != shape[0] + 1
            or len(corpus_frequency) != shape[1]
            or len(document_frequency) != shape[1]
            or len(idf) != shape[1]
        ):
            state.add(
                "index_array_dimensions",
                "Canonical CSR side-array dimensions do not reconcile.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        elif (
            data.dtype != np.dtype("<f8")
            or indices.dtype != np.dtype("<i8")
            or indptr.dtype != np.dtype("<i8")
            or corpus_frequency.dtype != np.dtype("<i8")
            or document_frequency.dtype != np.dtype("<i8")
            or idf.dtype != np.dtype("<f8")
        ):
            state.add(
                "index_array_dtype",
                "Canonical sparse arrays do not use governed little-endian dtypes.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        elif (
            (len(indptr) and (int(indptr[0]) != 0 or int(indptr[-1]) != len(data)))
            or np.any(np.diff(indptr) < 0)
            or np.any(indices < 0)
            or (len(indices) and np.any(indices >= shape[1]))
            or np.any(~np.isfinite(data))
            or np.any(~np.isfinite(idf))
        ):
            state.add(
                "index_csr_integrity",
                "CSR offsets, columns, or values are invalid.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        if not isinstance(metadata, dict):
            state.add(
                "index_metadata_json",
                "Sparse index metadata.json is not an object.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
            continue
        passage_ids = metadata.get("passage_ids")
        vocabulary = metadata.get("vocabulary")
        if not isinstance(passage_ids, list) or not isinstance(vocabulary, list):
            state.add(
                "index_axis_metadata",
                "Sparse index passage and vocabulary axes are absent.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
            continue
        if len(passage_ids) != shape[0] or len(vocabulary) != shape[1]:
            state.add(
                "index_axis_count",
                "Sparse index axis labels differ from the matrix shape.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        namespace = str(metadata.get("namespace", ""))
        storage_family = str(metadata.get("family", ""))
        identity_family = "normalized_surface" if storage_family == "surface" else storage_family
        if (
            identity_family != str(row["feature_family"])
            or str(metadata.get("representation_id", "")) != str(row["representation_id"])
            or any(
                not isinstance(value, str) or not value.startswith(f"{namespace}:{storage_family}:")
                for value in vocabulary
            )
        ):
            state.add(
                "index_vocabulary_namespace",
                "Sparse vocabulary values do not match index family and namespace.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        escaped_metadata = (index_directory / "metadata.json").as_posix().replace("'", "''")
        missing_vocabulary = _scalar(
            connection,
            "SELECT count(*) FROM read_text('"
            + escaped_metadata
            + "') r,json_each(r.content,'$.vocabulary') j "
            "LEFT JOIN feature_vocabulary f ON f.language_namespace='"
            + namespace.replace("'", "''")
            + "' AND f.feature_family='"
            + identity_family.replace("'", "''")
            + "' AND f.feature_value=substr(json_extract_string(j.value,'$'),"
            + str(len(namespace) + len(storage_family) + 3)
            + ") WHERE f.feature_id IS NULL",
        )
        if missing_vocabulary:
            state.add(
                "index_vocabulary_feature",
                f"Sparse vocabulary columns lack feature identities. Count={missing_vocabulary}.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        missing_passages = _scalar(
            connection,
            "SELECT count(*) FROM read_text('"
            + escaped_metadata
            + "') r,json_each(r.content,'$.passage_ids') j "
            "LEFT JOIN passage_feature_statistics p ON "
            "p.passage_id=json_extract_string(j.value,'$') WHERE p.passage_id IS NULL",
        )
        if missing_passages:
            state.add(
                "index_passage_axis",
                f"Sparse row-axis passage IDs are absent from feature statistics. "
                f"Count={missing_passages}.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        if passage_ids != sorted(passage_ids) or vocabulary != sorted(vocabulary):
            state.add(
                "index_axis_order",
                "Sparse index axes are not deterministically sorted.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        digest = hashlib.sha256()
        digest.update(json.dumps(passage_ids, ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(json.dumps(vocabulary, ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(np.asarray(shape, dtype="<i8").tobytes())
        digest.update(np.asarray(indptr, dtype="<i8").tobytes())
        digest.update(np.asarray(indices, dtype="<i8").tobytes())
        digest.update(np.asarray(data, dtype="<f8").tobytes())
        logical_hash = digest.hexdigest()
        if (
            logical_hash != row["logical_matrix_hash"]
            or metadata.get("logical_hash") != row["logical_matrix_hash"]
        ):
            state.add(
                "index_logical_hash",
                "Sparse index logical hash does not reproduce.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )
        if sparse_index_physical_hash(index_directory) != row["physical_file_hash"]:
            state.add(
                "index_physical_hash",
                "Sparse index physical aggregate hash does not reproduce.",
                artifact="lexical_index_metadata",
                record_id=index_id,
            )


def _validate_directional_english_ablation(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Require complete inline English counterfactuals and normalized storage."""

    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_english_ablation",
        message="Directional English-removal fields do not reproduce the governed result.",
        sql=(
            "SELECT count(*) FROM directional_rankings WHERE "
            f"(corpus_pair='{_CROSS_CORPUS_PAIR}')<>contains_english_derived_evidence OR "
            f"(corpus_pair='{_CROSS_CORPUS_PAIR}' AND "
            "(score_after_removing_all_english_features IS DISTINCT FROM 0.0 OR "
            "rank_after_removing_all_english_features IS NOT NULL OR "
            "non_english_evidence_remains OR english_ablation_survives OR "
            "classification_after_english_ablation<>"
            "'english_mediated_lead_without_non_english_score')) OR "
            f"(corpus_pair<>'{_CROSS_CORPUS_PAIR}' AND "
            "(score_after_removing_all_english_features IS DISTINCT FROM raw_score OR "
            "rank_after_removing_all_english_features IS DISTINCT FROM rank OR "
            "NOT non_english_evidence_remains OR NOT english_ablation_survives OR "
            "classification_after_english_ablation<>"
            "'original_language_ranking_unchanged'))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="ablation_results",
        code="directional_ablation_storage_normalization",
        message=(
            "Directional English ablations must be stored inline on content-hashed "
            "rankings, not duplicated as candidate ablation rows."
        ),
        sql="SELECT count(*) FROM ablation_results WHERE subject_type='directional_ranking'",
    )


def _validate_rankings(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
    database_path: Path | None,
) -> None:
    decimals = config.statistics.score_quantization_decimals
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_self_pair",
        message="Directional rankings contain self-pairs or an incorrect self flag.",
        sql=(
            "SELECT count(*) FROM directional_rankings WHERE query_passage_id=target_passage_id "
            "OR is_self"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_quantization",
        message="Quantized scores do not reproduce from raw scores.",
        sql=(
            "SELECT count(*) FROM directional_rankings WHERE "
            f"quantized_score IS DISTINCT FROM round(raw_score, {decimals})"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_depth",
        message="Directional rank lies outside the configured persistence depth.",
        sql=(
            "SELECT count(*) FROM directional_rankings WHERE rank < 1 "
            f"OR rank > {config.retrieval.persisted_top_k}"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_sequence",
        message="Directional ranks are not contiguous from one.",
        sql=(
            "SELECT count(*) FROM (SELECT query_passage_id,representation_id,detector, "
            "count(*) AS n,min(rank) AS lo,max(rank) AS hi,count(DISTINCT rank) AS distinct_n "
            "FROM directional_rankings GROUP BY ALL HAVING lo<>1 OR hi<>n OR distinct_n<>n)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_tie_break",
        message="Ranking order or tie breaking differs from score-descending/passage-ID order.",
        sql=(
            "WITH ordered AS (SELECT *,lag(quantized_score) OVER w AS previous_score, "
            "lag(target_passage_id) OVER w AS previous_target FROM directional_rankings "
            "WINDOW w AS (PARTITION BY query_passage_id,representation_id,detector ORDER BY rank)) "
            "SELECT count(*) FROM ordered WHERE tie_break_key<>target_passage_id "
            "OR (previous_score < quantized_score) "
            "OR (previous_score=quantized_score AND previous_target>target_passage_id)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="ranking_identity",
        message="Directional ranking identities do not reproduce from canonical payloads.",
        sql=(
            "SELECT count(*) FROM directional_rankings WHERE ranking_id <> 'LRK_' || sha256("
            "to_json(struct_pack(detector := detector, direction := CASE WHEN "
            "query_passage_id<target_passage_id THEN 'forward' ELSE 'reverse' END, "
            "experiment_run_id := experiment_run_id, query_passage_id := query_passage_id, "
            "ranking_schema_version := 1, representation_id := representation_id, "
            "target_passage_id := target_passage_id)))"
        ),
    )
    representation_consumers = (
        ("directional_rankings", "representation_id"),
        ("candidate_detector_scores", "representation_id"),
        ("null_replicate_summaries", "representation_id"),
        ("threshold_calibration", "representation_id"),
        ("evaluation_results", "representation_id"),
        ("ablation_results", "representation_id"),
    )
    for table, column in representation_consumers:
        _count_check(
            state,
            connection,
            artifact=table,
            code="representation_orphan",
            message="Representation is absent from lexical index metadata.",
            sql=(
                f'SELECT count(*) FROM "{table}" t LEFT JOIN '
                f"(SELECT DISTINCT representation_id FROM lexical_index_metadata) i "
                f'ON t."{column}"=i.representation_id WHERE i.representation_id IS NULL'
            ),
        )
    _count_check(
        state,
        connection,
        artifact="directional_rankings",
        code="representation_provenance",
        message="English and original-language representation provenance is mixed.",
        sql=(
            "WITH families AS (SELECT representation_id,"
            "bool_or(feature_family='english_gloss') AS has_english "
            "FROM lexical_index_metadata GROUP BY representation_id) "
            "SELECT count(*) FROM directional_rankings r JOIN families f USING(representation_id) "
            f"WHERE (r.corpus_pair='{_CROSS_CORPUS_PAIR}')<>f.has_english"
        ),
    )
    _validate_directional_english_ablation(state, connection)
    _validate_ranking_split_provenance(state, connection, database_path)


def _validate_ranking_split_provenance(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    database_path: Path | None,
) -> None:
    """Validate canonical split JSON and reconcile it to anchored benchmark rows."""

    observed: dict[str, str] = {}
    errors = 0
    full_keys = {
        "assignment_digest",
        "benchmark_versions",
        "eligible_partitions",
        "leakage_membership_complete",
        "leakage_group_count",
        "leakage_group_ids_digest",
        "mapping_statuses",
        "status",
    }
    observed_rows = 0
    for (
        passage_id_raw,
        minimum_raw,
        maximum_raw,
        occurrence_count_raw,
        nonnull_count_raw,
    ) in _iter_collapsed_ranking_split_provenance(connection):
        observed_rows += 1
        passage_id = str(passage_id_raw)
        encoded = str(minimum_raw)
        occurrence_count = int(str(occurrence_count_raw))
        nonnull_count = int(str(nonnull_count_raw))
        if (
            minimum_raw is None
            or maximum_raw is None
            or minimum_raw != maximum_raw
            or nonnull_count != occurrence_count
        ):
            errors += 1
        observed[passage_id] = encoded
        try:
            parsed = json.loads(encoded)
        except json.JSONDecodeError:
            errors += 1
            continue
        if not isinstance(parsed, dict) or not parsed:
            errors += 1
            continue
        canonical = json.dumps(parsed, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        status = parsed.get("status")
        if canonical != encoded or status not in {
            "eligible_benchmark_assignment_present",
            "no_eligible_benchmark_assignment",
        }:
            errors += 1
            continue
        if set(parsed) == {"status"}:
            if status != "no_eligible_benchmark_assignment":
                errors += 1
            continue
        partitions = parsed.get("eligible_partitions")
        if (
            set(parsed) != full_keys
            or not _SHA256_RE.fullmatch(str(parsed.get("assignment_digest", "")))
            or not isinstance(parsed.get("benchmark_versions"), list)
            or not isinstance(partitions, dict)
            or not isinstance(parsed.get("leakage_membership_complete"), bool)
            or isinstance(parsed.get("leakage_group_count"), bool)
            or not isinstance(parsed.get("leakage_group_count"), int)
            or int(parsed.get("leakage_group_count", -1)) < 0
            or not _SHA256_RE.fullmatch(str(parsed.get("leakage_group_ids_digest", "")))
            or not isinstance(parsed.get("mapping_statuses"), list)
        ):
            errors += 1
            continue
        if status == "eligible_benchmark_assignment_present" and (
            parsed["leakage_membership_complete"] is not True
            or int(parsed["leakage_group_count"]) < 1
            or not any(values for values in cast(dict[str, object], partitions).values())
        ):
            errors += 1
    if errors:
        state.add(
            "ranking_split_provenance",
            f"Directional ranking split provenance is noncanonical or invalid. Count={errors}.",
            artifact="directional_rankings",
        )
    if not observed_rows:
        return
    if database_path is None or not database_path.is_file():
        state.add(
            "ranking_split_reconciliation_unavailable",
            "Could not reconcile persisted split provenance to the benchmark database.",
            artifact="directional_rankings",
        )
        return
    try:
        from echoes.lexical.pipeline import _load_split_provenance

        stubs = [SimpleNamespace(passage_id=passage_id) for passage_id in sorted(observed)]
        with TemporaryDirectory(prefix="echoes-split-provenance-validation-") as temporary:
            expected = _load_split_provenance(
                database_path,
                stubs,  # type: ignore[arg-type]
                duckdb_memory_limit_bytes=512 * 1024**2,
                duckdb_temp_directory=Path(temporary) / "spill",
            )
    except (ImportError, OSError, ValueError, RuntimeError, duckdb.Error) as exc:
        state.add(
            "ranking_split_reconciliation_failure",
            f"Could not reproduce benchmark split provenance: {exc}.",
            artifact="directional_rankings",
        )
        return
    no_assignment = '{"status":"no_eligible_benchmark_assignment"}'
    mismatches = sum(
        encoded != expected.get(passage_id, no_assignment)
        for passage_id, encoded in observed.items()
    )
    if mismatches:
        state.add(
            "ranking_split_reconciliation",
            f"Persisted split provenance disagrees with anchored assignments. Count={mismatches}.",
            artifact="directional_rankings",
        )


def _iter_collapsed_ranking_split_provenance(
    connection: duckdb.DuckDBPyConnection,
) -> Iterator[tuple[object, ...]]:
    """Yield one bounded split-provenance fact per ranked passage.

    Directional rankings intentionally repeat the same passage provenance for every
    detector, rank, and direction.  Collapse those repetitions inside DuckDB so the
    Python validator never materializes a result proportional to ranking volume.
    Minimum/maximum retain the exact consistency check without collecting distinct
    JSON values, and the two counts preserve null detection.
    """

    cursor = connection.execute(
        "WITH passage_provenance AS ("
        "SELECT query_passage_id AS passage_id,query_split AS provenance "
        "FROM directional_rankings UNION ALL "
        "SELECT target_passage_id AS passage_id,target_split AS provenance "
        "FROM directional_rankings) "
        "SELECT passage_id,min(provenance) AS minimum_provenance,"
        "max(provenance) AS maximum_provenance,count(*) AS occurrence_count,"
        "count(provenance) AS nonnull_count FROM passage_provenance "
        "GROUP BY passage_id ORDER BY passage_id"
    )
    yield from _fetchmany(cursor)


def _validate_candidates(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
) -> None:
    decimals = config.statistics.score_quantization_decimals
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="candidate_identity",
        message="Candidate pair identities do not reproduce from canonical payloads.",
        sql=(
            "SELECT count(*) FROM candidate_pairs WHERE passage_a_id>=passage_b_id OR "
            "candidate_pair_id<>canonical_unordered_pair_id OR candidate_pair_id <> "
            "'LCP_' || sha256(to_json(struct_pack(analysis_profile := analysis_profile, "
            "candidate_pair_schema_version := 1, granularity := granularity, "
            "passage_id_a := least(passage_a_id,passage_b_id), "
            "passage_id_b := greatest(passage_a_id,passage_b_id))))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="candidate_known_link_status",
        message="Candidate uses unapproved known-link terminology.",
        sql=(
            "SELECT count(*) FROM candidate_pairs WHERE known_link_status NOT IN "
            "('represented_in_openbible_snapshot','not_represented_in_openbible_snapshot',"
            "'mapping_unresolved')"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="openbible_status_evidence",
        message="OpenBible status does not reconcile with retained relationship IDs.",
        sql=(
            "SELECT count(*) FROM candidate_pairs WHERE "
            "(known_link_status='represented_in_openbible_snapshot') <> "
            "(json_array_length(openbible_relationship_ids_json)>0) OR "
            "(known_link_status='not_represented_in_openbible_snapshot' AND "
            "json_array_length(openbible_relationship_ids_json)>0)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_detector_scores",
        code="candidate_score_orphan",
        message="Detector-score row has no candidate pair.",
        sql=(
            "SELECT count(*) FROM candidate_detector_scores s LEFT JOIN candidate_pairs p "
            "USING(candidate_pair_id) WHERE p.candidate_pair_id IS NULL"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_detector_scores",
        code="candidate_score_quantization",
        message="Candidate detector score quantization does not reproduce.",
        sql=(
            "SELECT count(*) FROM candidate_detector_scores WHERE "
            f"quantized_score IS DISTINCT FROM round(score, {decimals})"
        ),
    )
    config_hash = lexical_config_sha256(config).replace("'", "''")
    _count_check(
        state,
        connection,
        artifact="candidate_detector_scores",
        code="candidate_score_config",
        message="Candidate score does not retain the active config hash.",
        sql=(f"SELECT count(*) FROM candidate_detector_scores WHERE config_hash<>'{config_hash}'"),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_evidence",
        code="candidate_evidence_cardinality",
        message="Every candidate must have exactly one evidence summary.",
        sql=(
            "SELECT count(*) FROM (SELECT p.candidate_pair_id,count(e.candidate_pair_id) AS n "
            "FROM candidate_pairs p LEFT JOIN candidate_evidence e USING(candidate_pair_id) "
            "GROUP BY p.candidate_pair_id HAVING n<>1)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="shared_evidence",
        code="shared_evidence_orphan",
        message="Detailed evidence has no candidate or vocabulary feature.",
        sql=(
            "SELECT count(*) FROM shared_evidence e LEFT JOIN candidate_pairs p "
            "USING(candidate_pair_id) LEFT JOIN feature_vocabulary f USING(feature_id) "
            "WHERE p.candidate_pair_id IS NULL OR ((f.feature_id IS NULL "
            "OR e.feature_value<>f.feature_value) AND e.evidence_family NOT IN "
            "('longest_common_subsequence_trace','weighted_sequence_alignment_trace'))"
        ),
    )
    shared_columns = LEXICAL_ARTIFACT_COLUMNS["shared_evidence"]
    rendered_shared = ",".join(f's."{column}" AS "shared_{column}"' for column in shared_columns)
    cursor = connection.execute(
        "SELECT e.candidate_pair_id,p.passage_a_id,p.passage_b_id,"
        "a.eligible_token_count AS passage_a_length,b.eligible_token_count AS passage_b_length,"
        f"{rendered_shared} FROM candidate_evidence e JOIN candidate_pairs p "
        "USING(candidate_pair_id) LEFT JOIN passage_feature_statistics a "
        "ON a.passage_id=p.passage_a_id LEFT JOIN passage_feature_statistics b "
        "ON b.passage_id=p.passage_b_id LEFT JOIN shared_evidence s "
        "ON s.candidate_pair_id=e.candidate_pair_id ORDER BY e.candidate_pair_id,"
        "s.evidence_family,s.evidence_id"
    )
    result_columns = [description[0] for description in cursor.description]
    invalid_positions = 0
    shared_digests: dict[str, str] = {}
    current_candidate: str | None = None
    current_rows: list[dict[str, object]] = []

    def finish_candidate() -> None:
        if current_candidate is not None:
            shared_digests[current_candidate] = shared_evidence_digest(current_rows)

    for raw in _fetchmany(cursor):
        result = dict(zip(result_columns, raw, strict=True))
        candidate_id = str(result["candidate_pair_id"])
        if current_candidate != candidate_id:
            finish_candidate()
            current_candidate = candidate_id
            current_rows = []
        if result["shared_evidence_id"] is None:
            continue
        row = {column: result[f"shared_{column}"] for column in shared_columns}
        current_rows.append(row)
        for offset, field_name in enumerate(
            ("passage_a_positions_json", "passage_b_positions_json")
        ):
            values = _json_array(row[field_name])
            local_frequency = int(
                str(
                    row["passage_a_local_frequency" if offset == 0 else "passage_b_local_frequency"]
                )
            )
            if (
                not values
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in values
                )
                or len(values) != local_frequency
            ):
                invalid_positions += 1
                continue
            length_raw = result["passage_a_length" if offset == 0 else "passage_b_length"]
            if length_raw is None or any(
                int(str(value)) >= int(str(length_raw)) for value in values
            ):
                invalid_positions += 1
    finish_candidate()
    if invalid_positions:
        state.add(
            "evidence_positions",
            f"Evidence positions must be nonempty arrays of nonnegative integers. "
            f"Count={invalid_positions}.",
            artifact="shared_evidence",
        )
    detector_digests: dict[str, str] = {}
    detector_digest_errors = 0
    detector_columns = LEXICAL_ARTIFACT_COLUMNS["candidate_detector_scores"]
    detector_rows: list[dict[str, object]] = []
    current_candidate = None

    def finish_detector_candidate() -> None:
        nonlocal detector_digest_errors
        if current_candidate is None:
            return
        try:
            for row in detector_rows:
                if (
                    score_trace_digest(str(row["score_components_json"]))
                    != row["score_trace_digest"]
                ):
                    detector_digest_errors += 1
            detector_digests[current_candidate] = detector_trace_digest(detector_rows)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            detector_digest_errors += 1

    cursor = connection.execute(
        "SELECT * FROM candidate_detector_scores ORDER BY candidate_pair_id,detector"
    )
    result_columns = [description[0] for description in cursor.description]
    for raw in _fetchmany(cursor):
        row = dict(zip(result_columns, raw, strict=True))
        candidate_id = str(row["candidate_pair_id"])
        if current_candidate != candidate_id:
            finish_detector_candidate()
            current_candidate = candidate_id
            detector_rows = []
        detector_rows.append({column: row[column] for column in detector_columns})
    finish_detector_candidate()
    if detector_digest_errors:
        state.add(
            "detector_trace_digest",
            f"Detector score traces or their aggregate digest do not reproduce. "
            f"Count={detector_digest_errors}.",
            artifact="candidate_detector_scores",
        )

    ablation_digests: dict[str, str] = {}
    ablation_digest_errors = 0
    ablation_columns = LEXICAL_ARTIFACT_COLUMNS["ablation_results"]
    ablation_rows: list[dict[str, object]] = []
    current_candidate = None

    def finish_ablation_candidate() -> None:
        nonlocal ablation_digest_errors
        if current_candidate is None:
            return
        names = tuple(str(row["ablation_name"]) for row in ablation_rows)
        if len(ablation_rows) != len(_ABLATION_NAMES) or set(names) != set(_ABLATION_NAMES):
            ablation_digest_errors += 1
            return
        try:
            for row in ablation_rows:
                expected = ablation_result_digest(row)
                if row["evidence_digest"] != expected or row["ablation_result_id"] != (
                    "LXA_" + expected
                ):
                    ablation_digest_errors += 1
            ablation_digests[current_candidate] = ablation_family_digest(ablation_rows)
        except (KeyError, TypeError, ValueError):
            ablation_digest_errors += 1

    cursor = connection.execute(
        "SELECT * FROM ablation_results WHERE subject_type='candidate_pair' "
        "ORDER BY candidate_pair_id,ablation_name"
    )
    result_columns = [description[0] for description in cursor.description]
    for raw in _fetchmany(cursor):
        row = dict(zip(result_columns, raw, strict=True))
        candidate_id = str(row["candidate_pair_id"])
        if current_candidate != candidate_id:
            finish_ablation_candidate()
            current_candidate = candidate_id
            ablation_rows = []
        ablation_rows.append({column: row[column] for column in ablation_columns})
    finish_ablation_candidate()
    candidate_count = _scalar(connection, "SELECT count(*) FROM candidate_pairs")
    if len(ablation_digests) != candidate_count:
        ablation_digest_errors += abs(candidate_count - len(ablation_digests))
    if ablation_digest_errors:
        state.add(
            "candidate_ablation_family",
            f"Candidate ablation identities, digests, or eight-name families do not reproduce. "
            f"Count={ablation_digest_errors}.",
            artifact="ablation_results",
        )

    evidence_digest_errors = 0
    evidence_columns = LEXICAL_ARTIFACT_COLUMNS["candidate_evidence"]
    cursor = connection.execute("SELECT * FROM candidate_evidence ORDER BY candidate_pair_id")
    result_columns = [description[0] for description in cursor.description]
    for raw in _fetchmany(cursor):
        row = dict(zip(result_columns, raw, strict=True))
        candidate_id = str(row["candidate_pair_id"])
        try:
            expected = candidate_evidence_digest(
                {column: row[column] for column in evidence_columns},
                shared_digest=shared_digests[candidate_id],
                detector_digest=detector_digests[candidate_id],
                ablation_digest=ablation_digests[candidate_id],
            )
        except (KeyError, TypeError, ValueError):
            evidence_digest_errors += 1
            continue
        if (
            row["detector_trace_digest"] != detector_digests[candidate_id]
            or row["ablation_digest"] != ablation_digests[candidate_id]
            or row["evidence_digest"] != expected
        ):
            evidence_digest_errors += 1
    if evidence_digest_errors:
        state.add(
            "evidence_digest",
            f"Complete candidate evidence digests do not reproduce. "
            f"Count={evidence_digest_errors}.",
            artifact="candidate_evidence",
        )
    _count_check(
        state,
        connection,
        artifact="candidate_evidence",
        code="rare_rule_conjunction",
        message="Rare-rule status is inconsistent with independent co-signals.",
        sql=(
            "SELECT count(*) FROM candidate_evidence WHERE "
            "rare_rule_passed <> ((shared_rare_lemma_count+shared_rare_root_count=0) "
            "OR independent_co_signal_count>0)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="candidate_eligibility",
        message="A review-eligible candidate violates a frozen exclusion or calibration rule.",
        sql=(
            "SELECT count(*) FROM candidate_pairs p JOIN candidate_evidence e "
            "USING(candidate_pair_id) WHERE p.review_eligible AND "
            "(p.passage_a_id=p.passage_b_id OR e.overlap_exclusion OR "
            "p.known_link_status<>'not_represented_in_openbible_snapshot' OR "
            "NOT e.rare_rule_passed OR "
            f"e.estimated_empirical_fdr>{config.candidate_thresholds.maximum_empirical_fdr!r} OR "
            "(p.contains_english_derived_evidence AND NOT p.english_ablation_survives))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="english_candidate_guardrail",
        message="English-derived candidate is mislabeled or bypasses ablation.",
        sql=(
            "SELECT count(*) FROM candidate_pairs WHERE "
            f"(corpus_pair='{_CROSS_CORPUS_PAIR}')<>contains_english_derived_evidence "
            "OR (contains_english_derived_evidence AND NOT english_ablation_survives "
            "AND review_eligible)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="candidate_context_annotations",
        message="Context, duplicate, formula, or proper-name annotations are inconsistent.",
        sql=(
            "SELECT count(*) FROM candidate_pairs p JOIN candidate_evidence e "
            "USING(candidate_pair_id) WHERE "
            "(p.direct_adjacency AND (NOT p.nearby_context OR NOT p.same_book)) OR "
            "(p.exact_duplicate AND p.near_exact_duplicate) OR "
            "p.formulaic_evidence_flag<>(e.formulaic_penalty>0.0) OR "
            "p.nearby_context<>(e.local_context_penalty>0.0) OR "
            "(p.proper_name_only_flag AND p.proper_name_annotation_status<>'available') OR "
            "(p.genealogical_formula_pattern_flag OR p.legal_formula_pattern_flag) AND "
            "p.formula_pattern_annotation_status NOT LIKE 'available%'"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_pairs",
        code="candidate_english_ablation",
        message="Candidate English-removal fields do not reproduce the typed result.",
        sql=(
            "SELECT count(*) FROM candidate_pairs WHERE "
            f"(corpus_pair='{_CROSS_CORPUS_PAIR}')<>contains_english_derived_evidence OR "
            f"(corpus_pair='{_CROSS_CORPUS_PAIR}' AND "
            "(score_with_english_features IS NULL OR "
            "score_after_removing_all_english_features<>0.0 OR "
            "rank_with_english_features IS NULL OR "
            "rank_after_removing_all_english_features IS NOT NULL OR "
            "non_english_evidence_remains OR english_ablation_survives OR review_eligible)) OR "
            f"(corpus_pair<>'{_CROSS_CORPUS_PAIR}' AND "
            "(NOT non_english_evidence_remains OR NOT english_ablation_survives))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_detector_scores",
        code="rrf_contribution",
        message="Stored RRF contribution total does not reconcile to evidence score.",
        sql=(
            "WITH totals AS (SELECT candidate_pair_id,sum(score_contribution+penalty_contribution) "
            "AS total FROM candidate_detector_scores GROUP BY candidate_pair_id) "
            "SELECT count(*) FROM totals t JOIN candidate_evidence e USING(candidate_pair_id) "
            "WHERE abs(t.total-e.rrf_score)>1e-10"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_evidence",
        code="candidate_penalty_reconciliation",
        message="Raw RRF, adjusted RRF, and penalty totals do not reconcile.",
        sql=(
            "SELECT count(*) FROM candidate_evidence WHERE total_penalty_contribution>0.0 OR "
            "abs(raw_rrf_score+total_penalty_contribution-rrf_score)>1e-12 OR "
            "abs(total_penalty_contribution)>raw_rrf_score+1e-12"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_detector_scores",
        code="candidate_adjusted_score",
        message="Detector adjusted scores or penalty placement are inconsistent.",
        sql=(
            "SELECT count(*) FROM candidate_detector_scores s JOIN candidate_evidence e "
            "USING(candidate_pair_id) WHERE "
            "(s.detector='rrf_composite' AND (s.adjusted_score IS DISTINCT FROM e.rrf_score "
            "OR s.score IS DISTINCT FROM e.raw_rrf_score OR "
            "s.penalty_contribution IS DISTINCT FROM e.total_penalty_contribution)) OR "
            "(s.detector<>'rrf_composite' AND (s.adjusted_score IS DISTINCT FROM s.score OR "
            "s.penalty_contribution<>0.0))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_evidence",
        code="candidate_calibration_provenance",
        message="Candidate calibration provenance is incomplete or disagrees with selection.",
        sql=(
            "SELECT count(*) FROM candidate_evidence e JOIN candidate_pairs p "
            "USING(candidate_pair_id) LEFT JOIN candidate_detector_scores s ON "
            "s.candidate_pair_id=e.candidate_pair_id AND s.detector='rrf_composite' "
            "LEFT JOIN threshold_calibration t ON t.corpus_pair=p.corpus_pair AND "
            "t.representation_id=s.representation_id AND t.detector='rrf_composite' AND t.selected "
            "WHERE NOT e.both_null_families_present OR "
            "e.calibration_selection_scope<>'frozen_corpus_pair_rrf_threshold' OR "
            "t.threshold_id IS NULL OR "
            "e.selected_score_threshold IS DISTINCT FROM t.score_threshold OR "
            "e.estimated_empirical_fdr IS DISTINCT FROM t.estimated_empirical_fdr"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="ablation_results",
        code="candidate_ablation_reconciliation",
        message="Typed candidate ablations disagree with candidate evidence or pair policy.",
        sql=(
            "SELECT count(*) FROM ablation_results a LEFT JOIN candidate_pairs p "
            "ON a.candidate_pair_id=p.candidate_pair_id LEFT JOIN candidate_evidence e "
            "ON a.candidate_pair_id=e.candidate_pair_id WHERE a.subject_type='candidate_pair' AND "
            "(p.candidate_pair_id IS NULL OR a.subject_id<>a.candidate_pair_id OR "
            "a.ranking_id IS NOT NULL OR a.score_before IS DISTINCT FROM e.rrf_score OR "
            "a.review_eligible_before<>p.review_eligible OR "
            "a.contains_english_derived_evidence<>p.contains_english_derived_evidence OR "
            "(a.ablation_name='remove_formulaic_penalty' AND "
            "(a.score_after<a.score_before OR a.penalty_after>a.penalty_before)) OR "
            "(a.ablation_name='remove_local_context_penalty' AND "
            "(a.score_after<a.score_before OR a.penalty_after>a.penalty_before)) OR "
            "(a.ablation_name='remove_all_english_derived_features' AND "
            "p.contains_english_derived_evidence AND (a.score_after<>0.0 OR "
            "a.rank_after IS NOT NULL OR a.non_english_evidence_remains OR "
            "a.review_eligible_after OR NOT a.downgrade_required)))"
        ),
    )
    hypergeometric_errors = 0
    cursor = connection.execute(
        "SELECT candidate_pair_id,hypergeometric_population_size,"
        "hypergeometric_success_states,hypergeometric_draws,"
        "hypergeometric_observed_overlap,hypergeometric_p_value,"
        "expected_overlap_independence FROM candidate_evidence"
    )
    for (
        _candidate_id,
        population,
        success_states,
        draws,
        observed,
        persisted_p,
        persisted_expected,
    ) in _fetchmany(cursor):
        try:
            reproduced = hypergeometric_upper_tail(
                int(str(population)),
                int(str(success_states)),
                int(str(draws)),
                int(str(observed)),
            ).upper_tail_p_value
            expected_overlap = (
                float(str(success_states)) * float(str(draws)) / float(str(population))
                if population
                else 0.0
            )
        except (TypeError, ValueError):
            hypergeometric_errors += 1
            continue
        p_mismatch = not math.isclose(
            reproduced, float(str(persisted_p)), rel_tol=0.0, abs_tol=1e-12
        )
        expected_mismatch = not math.isclose(
            expected_overlap,
            float(str(persisted_expected)),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        if p_mismatch or expected_mismatch:
            hypergeometric_errors += 1
    if hypergeometric_errors:
        state.add(
            "hypergeometric_provenance",
            f"Hypergeometric inputs or derived values do not reproduce. "
            f"Count={hypergeometric_errors}.",
            artifact="candidate_evidence",
        )
    _validate_bh_q_values(state, connection)


def _validate_bh_q_values(state: _State, connection: duckdb.DuckDBPyConnection) -> None:
    _count_check(
        state,
        connection,
        artifact="candidate_evidence",
        code="hypothesis_family_provenance",
        message="Hypergeometric/BH hypothesis family provenance does not reconcile.",
        sql=(
            "WITH families AS (SELECT e.hypothesis_family_id,"
            "min(e.hypothesis_family_size) AS lo,max(e.hypothesis_family_size) AS hi,"
            "count(*) AS n,count(DISTINCT p.corpus_pair) AS pair_n,"
            "count(DISTINCT s.representation_id) AS representation_n,"
            "min(e.hypothesis_selection_scope) AS scope_lo,"
            "max(e.hypothesis_selection_scope) AS scope_hi "
            "FROM candidate_evidence e JOIN candidate_pairs p USING(candidate_pair_id) "
            "JOIN candidate_detector_scores s ON s.candidate_pair_id=e.candidate_pair_id "
            "AND s.detector='rrf_composite' GROUP BY e.hypothesis_family_id) "
            "SELECT count(*) FROM families WHERE lo<>hi OR lo<>n OR pair_n<>1 OR "
            "representation_n<>1 OR scope_lo<>scope_hi OR "
            "scope_lo<>'persisted_candidate_union_only_not_global_all_pairs'"
        ),
    )
    errors = _scalar(
        connection,
        "WITH ranked AS (SELECT e.hypothesis_family_id,e.candidate_pair_id,"
        "e.hypergeometric_p_value AS p_value,e.benjamini_hochberg_q_value AS q_value,"
        "row_number() OVER (PARTITION BY e.hypothesis_family_id ORDER BY "
        "e.hypergeometric_p_value,e.candidate_pair_id) AS rank,"
        "count(*) OVER (PARTITION BY e.hypothesis_family_id) AS hypotheses "
        "FROM candidate_evidence e),"
        "adjusted AS (SELECT *,least(1.0,min(p_value*hypotheses/rank) OVER "
        "(PARTITION BY hypothesis_family_id ORDER BY rank DESC ROWS BETWEEN UNBOUNDED PRECEDING "
        "AND CURRENT ROW)) AS expected_q FROM ranked) SELECT count(*) FROM adjusted "
        "WHERE abs(q_value-expected_q)>1e-12",
    )
    if errors:
        state.add(
            "benjamini_hochberg",
            f"BH q-values do not reproduce within registered corpus-pair families. Count={errors}.",
            artifact="candidate_evidence",
        )


def _governed_null_scoring_strata(
    connection: duckdb.DuckDBPyConnection,
) -> set[tuple[str, str, str]]:
    """Return only primary edition-complete strata registered for repeated nulls."""

    return {
        (str(pair), str(representation), str(detector))
        for pair, representation, detector in connection.execute(
            "SELECT DISTINCT corpus_pair,representation_id,detector "
            "FROM directional_rankings WHERE experiment_scope='primary' "
            "AND analysis_profile='edition_complete'"
        ).fetchall()
    }


def _validate_nulls_and_calibration(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
) -> None:
    observed_families = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT null_family FROM null_replicate_summaries"
        ).fetchall()
    }
    if observed_families != _NULL_FAMILIES:
        state.add(
            "null_family_set",
            "Exactly both registered null families must be retained.",
            artifact="null_replicate_summaries",
            observed=sorted(observed_families),
        )
    governed_scoring = _governed_null_scoring_strata(connection)
    null_scoring = {
        (str(pair), str(representation), str(detector))
        for pair, representation, detector in connection.execute(
            "SELECT DISTINCT corpus_pair,representation_id,detector FROM null_replicate_summaries"
        ).fetchall()
    }
    if null_scoring != governed_scoring:
        state.add(
            "null_scoring_coverage",
            "Null experiments do not cover exactly every governed persisted scoring stratum.",
            artifact="null_replicate_summaries",
            missing=sorted(governed_scoring.difference(null_scoring)),
            unexpected=sorted(null_scoring.difference(governed_scoring)),
        )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_iteration_count",
        message="A governed null experiment does not retain the configured iteration count.",
        sql=(
            "SELECT count(*) FROM (SELECT null_family,corpus_pair,representation_id,detector,"
            "threshold_id,count(DISTINCT iteration) AS n FROM null_replicate_summaries "
            f"GROUP BY ALL HAVING n<>{config.null_models.iterations_per_family})"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_seed_consistency",
        message="Null seeds are duplicated across iterations or inconsistent within one iteration.",
        sql=(
            "SELECT count(*) FROM (SELECT null_family,corpus_pair,representation_id,"
            "iteration,count(DISTINCT seed) AS seeds FROM null_replicate_summaries GROUP BY ALL "
            "HAVING seeds<>1)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_seed_uniqueness",
        message="Null iterations do not have unique seeds.",
        sql=(
            "SELECT count(*) FROM (SELECT null_family,corpus_pair,representation_id,"
            "count(DISTINCT iteration) AS iterations,count(DISTINCT seed) AS seeds "
            "FROM null_replicate_summaries GROUP BY ALL HAVING iterations<>seeds)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_seed_global_uniqueness",
        message="Derived null replicate seeds are not globally unique.",
        sql=(
            "WITH replicates AS (SELECT DISTINCT null_family,corpus_pair,representation_id,"
            "iteration,seed FROM null_replicate_summaries) SELECT count(*)-"
            "count(DISTINCT seed) FROM replicates"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_run_identity",
        message="Null run IDs do not map one-to-one to a conditioned replicate.",
        sql=(
            "SELECT count(*) FROM (SELECT null_family,corpus_pair,representation_id,"
            "iteration,count(DISTINCT null_run_id) AS ids FROM "
            "null_replicate_summaries GROUP BY ALL "
            "HAVING ids<>1)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="null_replicate_summaries",
        code="null_conservation_digest",
        message="Passage, token, or conservation digests vary across equivalent null runs.",
        sql=(
            "SELECT count(*) FROM (SELECT corpus_pair,representation_id,"
            "count(DISTINCT passage_count) AS passages,count(DISTINCT token_count) AS tokens,"
            "count(DISTINCT length_digest) AS lengths FROM null_replicate_summaries GROUP BY ALL "
            "HAVING passages<>1 OR tokens<>1 OR lengths<>1)"
        ),
    )
    cursor = connection.execute(
        "SELECT * FROM null_replicate_summaries ORDER BY null_family,corpus_pair,"
        "representation_id,iteration,detector,threshold_id"
    )
    null_columns = [description[0] for description in cursor.description]
    invalid_conditioning = 0
    invalid_logical_hash = 0
    seen_replicates: set[tuple[str, str, str, int]] = set()
    for values in _fetchmany(cursor):
        row = dict(zip(null_columns, values, strict=True))
        family = str(row["null_family"])
        iteration = int(str(row["iteration"]))
        seed = int(str(row["seed"]))
        if null_replicate_logical_hash(row) != str(row["logical_output_hash"]):
            invalid_logical_hash += 1
        replicate_key = (
            family,
            str(row["corpus_pair"]),
            str(row["representation_id"]),
            iteration,
        )
        if replicate_key in seen_replicates:
            continue
        seen_replicates.add(replicate_key)
        conditioning = _json_object(row["conditioning_json"])
        quantiles = _json_object(row["score_quantiles_json"])
        required_true = {
            "passage_count_preserved",
            "passage_lengths_preserved",
            "conditioning_labels_preserved",
            "representation_isolation_preserved",
        }
        if (
            int(str(row["passage_count"])) < 1
            or int(str(row["token_count"])) < 1
            or not all(conditioning.get(key) is True for key in required_true)
            or conditioning.get("label_or_order_shuffle") is not False
            or conditioning.get("candidate_sample_size")
            != config.null_models.calibration_pair_sample_size
            or conditioning.get("calibration_pair_scope")
            != config.null_models.calibration_pair_scope
            or conditioning.get("global_all_pairs_claim_allowed") is not False
        ):
            invalid_conditioning += 1
        quantile_values = tuple(quantiles.get(key) for key in ("q025", "q50", "q975"))
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in quantile_values
        ) or not (
            float(str(quantile_values[0]))
            <= float(str(quantile_values[1]))
            <= float(str(quantile_values[2]))
        ):
            invalid_conditioning += 1
        if (
            family == "within_book_reassignment"
            and conditioning.get("exact_feature_totals_preserved") is not True
        ):
            invalid_conditioning += 1
        frequency_deviation_count = conditioning.get("frequency_deviation_count")
        if family == "frequency_preserving_synthetic" and (
            conditioning.get("no_original_sequences_copied") is not True
            or conditioning.get("conditioning_scope") != "book_then_genre_when_sparse"
            or conditioning.get("minimum_book_token_count")
            != config.null_models.synthetic_minimum_book_token_count
            or isinstance(frequency_deviation_count, bool)
            or not isinstance(frequency_deviation_count, int)
            or frequency_deviation_count < 1
            or not isinstance(
                conditioning.get("maximum_absolute_frequency_deviation"), (int, float)
            )
            or not isinstance(conditioning.get("mean_absolute_frequency_deviation"), (int, float))
        ):
            invalid_conditioning += 1
        base_seed = (
            config.null_models.within_book_reassignment.seed
            if family == "within_book_reassignment"
            else config.null_models.frequency_preserving_synthetic.seed
        )
        stratum_key = "|".join((str(row["corpus_pair"]), str(row["representation_id"])))
        if seed != _derived_null_seed(base_seed, stratum_key, family, iteration):
            invalid_conditioning += 1
    if invalid_conditioning:
        state.add(
            "null_conservation",
            f"Null seed derivation or conservation evidence is invalid. "
            f"Count={invalid_conditioning}.",
            artifact="null_replicate_summaries",
        )
    if invalid_logical_hash:
        state.add(
            "null_logical_hash",
            f"Null replicate logical hashes do not reproduce. Count={invalid_logical_hash}.",
            artifact="null_replicate_summaries",
        )
    threshold_values = tuple(config.candidate_thresholds.rrf_score_grid)
    observed_thresholds = {
        float(row[0])
        for row in connection.execute(
            "SELECT DISTINCT score_threshold FROM threshold_calibration "
            "WHERE detector='rrf_composite'"
        ).fetchall()
    }
    if observed_thresholds != set(threshold_values):
        state.add(
            "threshold_grid",
            "RRF threshold calibration does not contain the frozen grid exactly.",
            artifact="threshold_calibration",
        )
    calibration_scoring = {
        (str(pair), str(representation), str(detector))
        for pair, representation, detector in connection.execute(
            "SELECT DISTINCT corpus_pair,representation_id,detector FROM threshold_calibration"
        ).fetchall()
    }
    if calibration_scoring != governed_scoring:
        state.add(
            "threshold_scoring_coverage",
            "Threshold calibration does not cover every governed persisted scoring stratum.",
            artifact="threshold_calibration",
            missing=sorted(governed_scoring.difference(calibration_scoring)),
            unexpected=sorted(calibration_scoring.difference(governed_scoring)),
        )
    grid_checks = " OR ".join(
        f"count(*) FILTER (WHERE score_threshold={value!r})<>1" for value in threshold_values
    )
    _count_check(
        state,
        connection,
        artifact="threshold_calibration",
        code="threshold_grid_per_stratum",
        message="A scoring stratum does not contain the frozen threshold grid exactly.",
        sql=(
            "SELECT count(*) FROM (SELECT corpus_pair,representation_id,detector FROM "
            f"threshold_calibration GROUP BY ALL HAVING count(*)<>{len(threshold_values)} OR "
            f"{grid_checks})"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="threshold_calibration",
        code="threshold_freeze",
        message="A calibrated threshold was not frozen before held-out evaluation.",
        sql="SELECT count(*) FROM threshold_calibration WHERE NOT frozen_before_test",
    )
    _count_check(
        state,
        connection,
        artifact="threshold_calibration",
        code="threshold_scope",
        message="Threshold calibration scope or interval/count facts are invalid.",
        sql=(
            "SELECT count(*) FROM threshold_calibration WHERE threshold_selection_scope<>"
            f"'{config.null_models.calibration_pair_scope}' OR null_interval_low>"
            "mean_null_candidate_count OR mean_null_candidate_count>null_interval_high OR "
            "eligible_candidate_count>observed_candidate_count"
        ),
    )
    calibration_rows = connection.execute(
        "SELECT * FROM threshold_calibration ORDER BY corpus_pair,representation_id,detector,"
        "threshold_id"
    ).fetchall()
    calibration_columns = [description[0] for description in connection.description]
    calibration_errors = 0
    calibration_by_stratum: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for raw in calibration_rows:
        row = dict(zip(calibration_columns, raw, strict=True))
        calibration_by_stratum.setdefault(
            (
                str(row["corpus_pair"]),
                str(row["representation_id"]),
                str(row["detector"]),
            ),
            [],
        ).append(row)
        retained_null_rows = connection.execute(
            "SELECT null_family,candidate_count FROM null_replicate_summaries WHERE "
            "corpus_pair=? AND representation_id=? AND detector=? AND threshold_id=? "
            "ORDER BY null_family,iteration",
            [
                row["corpus_pair"],
                row["representation_id"],
                row["detector"],
                row["threshold_id"],
            ],
        ).fetchall()
        null_counts = [int(value[1]) for value in retained_null_rows]
        expected_count = 2 * config.null_models.iterations_per_family
        if len(null_counts) != expected_count:
            calibration_errors += 1
            continue
        expected = calibrate_null_counts(
            float(str(row["score_threshold"])),
            int(str(row["observed_candidate_count"])),
            null_counts,
        )
        expected_values = (
            ("mean_null_candidate_count", expected.null_mean_count),
            ("null_interval_low", expected.null_interval_low),
            ("null_interval_high", expected.null_interval_high),
            ("empirical_tail_probability", expected.empirical_upper_tail_probability),
        )
        for name, expected_value in expected_values:
            if not math.isclose(
                float(str(row[name])), float(expected_value), rel_tol=0.0, abs_tol=1e-12
            ):
                calibration_errors += 1
        observed_fdr = row["estimated_empirical_fdr"]
        if expected.raw_empirical_fdr is None:
            if observed_fdr is not None:
                calibration_errors += 1
        elif observed_fdr is None or not math.isclose(
            float(str(observed_fdr)),
            expected.raw_empirical_fdr,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            calibration_errors += 1
        observed_enrichment = row["observed_to_null_enrichment"]
        if expected.enrichment is None or not math.isfinite(expected.enrichment):
            if observed_enrichment is not None:
                calibration_errors += 1
        elif observed_enrichment is None or not math.isclose(
            float(str(observed_enrichment)), expected.enrichment, rel_tol=0.0, abs_tol=1e-12
        ):
            calibration_errors += 1
        counts_by_family = {
            family: [
                int(count)
                for observed_family, count in retained_null_rows
                if observed_family == family
            ]
            for family in _NULL_FAMILIES
        }
        observed_count = int(str(row["observed_candidate_count"]))
        qualifies = observed_count > 0 and all(
            len(counts) == config.null_models.iterations_per_family
            and math.fsum(counts) / len(counts) / observed_count
            <= config.candidate_thresholds.maximum_empirical_fdr
            for counts in counts_by_family.values()
        )
        if bool(row["qualifies_empirical_fdr"]) is not qualifies:
            calibration_errors += 1
    for (_, _, detector), stratum_rows in calibration_by_stratum.items():
        ordered = sorted(stratum_rows, key=lambda row: float(str(row["score_threshold"])))
        qualifying = [row for row in ordered if bool(row["qualifies_empirical_fdr"])]
        selected_rows = [row for row in ordered if bool(row["selected"])]
        expected_selected = qualifying[:1] if detector == "rrf_composite" else []
        if [row["threshold_id"] for row in selected_rows] != [
            row["threshold_id"] for row in expected_selected
        ]:
            calibration_errors += 1
        for row in ordered:
            selected = bool(row["selected"])
            qualifies = bool(row["qualifies_empirical_fdr"])
            observed_count = int(str(row["observed_candidate_count"]))
            if detector != "rrf_composite":
                expected_reason = "detector_threshold_reported_not_review_selection"
            elif selected:
                expected_reason = "lowest_registered_threshold_qualifying_both_null_families"
            elif observed_count == 0:
                expected_reason = "zero_observed_candidates"
            elif qualifies:
                expected_reason = "qualifies_but_not_lowest_selected_threshold"
            else:
                expected_reason = "exceeds_maximum_empirical_fdr_in_at_least_one_null_family"
            if row["selection_reason"] != expected_reason:
                calibration_errors += 1
    if calibration_errors:
        state.add(
            "threshold_calibration_reproduction",
            f"Threshold calibration does not reproduce from retained null counts. "
            f"Count={calibration_errors}.",
            artifact="threshold_calibration",
        )


def _validate_evaluation(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
    preregistration: LexicalExperimentPreregistration,
) -> None:
    config_hash = lexical_config_sha256(config).replace("'", "''")
    preregistration_hash = lexical_preregistration_sha256(preregistration).replace("'", "''")
    benchmark_version = preregistration.inputs.benchmark.version.replace("'", "''")
    _count_check(
        state,
        connection,
        artifact="evaluation_results",
        code="evaluation_governance",
        message="Evaluation row violates Tier 3, benchmark-version, or config-hash governance.",
        sql=(
            "SELECT count(*) FROM evaluation_results WHERE benchmark_tier<>3 "
            f"OR benchmark_version<>'{benchmark_version}' OR config_hash<>'{config_hash}' "
            f"OR preregistration_hash<>'{preregistration_hash}' "
            "OR label_quality<>'tier3_weak_supervision_recovery' "
            "OR analysis_profile NOT IN ('edition_complete','critical_core') "
            "OR NOT frozen_before_test "
            f"OR bootstrap_iterations<>{config.statistics.bootstrap_iterations} "
            "OR bootstrap_seed<1 "
            "OR ranking_name<>detector "
            "OR ranking_role<>(CASE WHEN detector IN ('random','length_matched',"
            "'unweighted_overlap') THEN 'baseline' ELSE 'system' END)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="evaluation_results",
        code="evaluation_interval",
        message="Evaluation interval or metric count is invalid.",
        sql=(
            "SELECT count(*) FROM evaluation_results WHERE "
            "bootstrap_interval_low>bootstrap_interval_high "
            "OR (metric IN ('recall_at_5','recall_at_10','recall_at_20','ndcg_at_20',"
            "'precision_at_10','coverage','mean_reciprocal_rank','presumed_negative_auroc') "
            "AND (value<0 OR value>1)) "
            "OR (metric LIKE '%_difference_vs_%' AND (value < -1 OR value > 1))"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="evaluation_results",
        code="evaluation_query_count",
        message="Evaluation eligible-relationship count exceeds its eligible query instances.",
        sql=(
            "SELECT count(*) FROM evaluation_results "
            "WHERE eligible_relationship_count>eligible_query_count"
        ),
    )
    detectors = {
        str(row[0])
        for row in connection.execute("SELECT DISTINCT detector FROM evaluation_results").fetchall()
    }
    required_baselines = {"random", "length_matched", "unweighted_overlap"}
    if not required_baselines.issubset(detectors):
        state.add(
            "evaluation_baselines",
            "Random, length-matched, and unweighted-overlap baselines must all be present.",
            artifact="evaluation_results",
            missing=sorted(required_baselines.difference(detectors)),
        )
    dimensions = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT stratum_dimension FROM evaluation_results"
        ).fetchall()
    }
    missing_dimensions = _REQUIRED_EVALUATION_STRATUM_DIMENSIONS.difference(dimensions)
    if missing_dimensions:
        state.add(
            "evaluation_stratum_dimensions",
            "Evaluation omits required governed stratum dimensions.",
            artifact="evaluation_results",
            missing=sorted(missing_dimensions),
        )
    profile_pairs = {
        (str(profile), str(pair))
        for profile, pair in connection.execute(
            "SELECT DISTINCT analysis_profile,corpus_pair FROM evaluation_results"
        ).fetchall()
    }
    observed_profile_pair_dimensions = {
        (str(profile), str(pair), str(dimension))
        for profile, pair, dimension in connection.execute(
            "SELECT DISTINCT analysis_profile,corpus_pair,stratum_dimension FROM evaluation_results"
        ).fetchall()
    }
    missing_profile_pair_dimensions = sorted(
        (profile, pair, dimension)
        for profile, pair in profile_pairs
        for dimension in _REQUIRED_EVALUATION_STRATUM_DIMENSIONS
        if (profile, pair, dimension) not in observed_profile_pair_dimensions
    )
    if missing_profile_pair_dimensions:
        state.add(
            "evaluation_stratum_scope_coverage",
            "An evaluated profile/corpus pair omits a required stratum dimension.",
            artifact="evaluation_results",
            missing=missing_profile_pair_dimensions,
        )
    profiles = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT analysis_profile FROM evaluation_results"
        ).fetchall()
    }
    if not {"edition_complete", "critical_core"}.issubset(profiles):
        state.add(
            "evaluation_profile_sensitivity",
            "Evaluation omits edition-complete or critical-core sensitivity results.",
            artifact="evaluation_results",
            observed=sorted(profiles),
        )
    _count_check(
        state,
        connection,
        artifact="evaluation_results",
        code="evaluation_presumed_negative_status",
        message=(
            "Every edition-complete corpus pair must report governed presumed-negative "
            "discrimination with explicit counts and caveat."
        ),
        sql=(
            "SELECT count(*) FROM (SELECT DISTINCT analysis_profile,corpus_pair "
            "FROM evaluation_results WHERE analysis_profile='edition_complete') p LEFT JOIN "
            "evaluation_results n ON n.analysis_profile=p.analysis_profile "
            "AND n.corpus_pair=p.corpus_pair AND n.metric='presumed_negative_auroc' "
            "AND n.comparison_baseline='presumed_negatives' "
            "AND n.stratum_dimension='split_strategy_partition' "
            "AND n.comparison_count>0 AND n.notes LIKE '%not proven%' "
            "WHERE n.evaluation_id IS NULL"
        ),
    )
    edition_pairs = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT corpus_pair FROM evaluation_results "
            "WHERE analysis_profile='edition_complete'"
        ).fetchall()
    }
    presumed_coverage = {
        (str(pair), str(detector))
        for pair, detector in connection.execute(
            "SELECT DISTINCT corpus_pair,detector FROM evaluation_results "
            "WHERE analysis_profile='edition_complete' "
            "AND comparison_baseline='presumed_negatives' "
            "AND metric='presumed_negative_auroc' AND comparison_count>0"
        ).fetchall()
    }
    expected_presumed_coverage = {
        (pair, detector)
        for pair in edition_pairs
        for detector in (*config.enabled_detectors, "rrf_composite")
    }
    missing_presumed_coverage = sorted(expected_presumed_coverage.difference(presumed_coverage))
    if missing_presumed_coverage:
        state.add(
            "evaluation_presumed_negative_detector_coverage",
            "Presumed-negative discrimination omits an edition-complete detector/corpus pair.",
            artifact="evaluation_results",
            missing=missing_presumed_coverage,
        )
    required_detectors = set(config.enabled_detectors).union({"rrf_composite"}, required_baselines)
    if not required_detectors.issubset(detectors):
        state.add(
            "evaluation_detector_coverage",
            "Evaluation omits a governed detector or transparent baseline.",
            artifact="evaluation_results",
            missing=sorted(required_detectors.difference(detectors)),
        )
    metrics = {
        str(row[0])
        for row in connection.execute("SELECT DISTINCT metric FROM evaluation_results").fetchall()
    }
    required_metrics = set(preregistration.benchmark.metrics).union(
        {
            "recall_at_20_difference_vs_random",
            "recall_at_20_difference_vs_unweighted_overlap",
            "presumed_negative_auroc",
        }
    )
    if not required_metrics.issubset(metrics):
        state.add(
            "evaluation_metric_coverage",
            "Evaluation omits a frozen metric or paired baseline-difference interval.",
            artifact="evaluation_results",
            missing=sorted(required_metrics.difference(metrics)),
        )
    split_strategies = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT split_strategy FROM evaluation_results"
        ).fetchall()
    }
    missing_splits = set(config.benchmark_evaluation.split_strategies).difference(split_strategies)
    if missing_splits:
        state.add(
            "evaluation_split_coverage",
            "Evaluation omits a governed split strategy.",
            artifact="evaluation_results",
            missing=sorted(missing_splits),
        )
    split_without_test = {
        str(row[0])
        for row in connection.execute(
            "SELECT split_strategy FROM evaluation_results WHERE split_strategy IN "
            "('held_out_book','held_out_book_pair','held_out_source_passage','held_out_genre') "
            "GROUP BY split_strategy "
            "HAVING count(*) FILTER (WHERE partition='test')=0"
        ).fetchall()
    }
    if split_without_test:
        state.add(
            "evaluation_test_partition",
            "A governed split strategy has no eligible held-out test partition; its available "
            "partitions remain descriptive and no test-recovery claim is made.",
            severity="informational",
            artifact="evaluation_results",
            split_strategies=sorted(split_without_test),
        )
    mapping_statuses = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT mapping_status FROM evaluation_results"
        ).fetchall()
    }
    if not set(config.benchmark_evaluation.eligible_mapping_statuses).issubset(mapping_statuses):
        state.add(
            "evaluation_mapping_strata",
            "Eligible mapping-quality strata are not reported separately.",
            artifact="evaluation_results",
        )
    vote_strata = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT vote_stratum FROM evaluation_results"
        ).fetchall()
    }
    if not set(preregistration.benchmark.vote_strata).issubset(vote_strata):
        state.add(
            "evaluation_vote_strata",
            "Configured descriptive OpenBible vote strata are not reported separately.",
            artifact="evaluation_results",
        )
    corpus_pairs = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT corpus_pair FROM evaluation_results"
        ).fetchall()
    }
    if not set(preregistration.scope.corpus_pairs).issubset(corpus_pairs):
        state.add(
            "evaluation_corpus_pair_strata",
            "Evaluation omits a preregistered corpus-pair stratum.",
            artifact="evaluation_results",
        )
    _evaluate_scientific_gate(state, connection, config)


def _aggregate_gate_row(
    connection: duckdb.DuckDBPyConnection,
    corpus_pair: str,
    detector: str,
) -> tuple[float, float, float, int, int] | None:
    row = connection.execute(
        "SELECT value,bootstrap_interval_low,bootstrap_interval_high,eligible_query_count,"
        "eligible_relationship_count FROM evaluation_results WHERE corpus_pair=? "
        "AND detector=? AND metric='recall_at_20' AND split_strategy='held_out_genre' "
        "AND partition='test' AND analysis_profile='edition_complete' "
        "AND stratum_dimension='split_strategy_partition' "
        "AND stratum_value='held_out_genre|test' ORDER BY "
        "(mapping_status IN ('all','all_eligible','eligible')) DESC,"
        "(vote_stratum IN ('all','all_votes')) DESC,eligible_query_count DESC LIMIT 1",
        [corpus_pair, detector],
    ).fetchone()
    if row is None:
        return None
    return (float(row[0]), float(row[1]), float(row[2]), int(row[3]), int(row[4]))


def _difference_gate_row(
    connection: duckdb.DuckDBPyConnection,
    corpus_pair: str,
    comparison: Literal["random", "unweighted_overlap"],
) -> tuple[float, float, float, int, int] | None:
    metric = f"recall_at_20_difference_vs_{comparison}"
    row = connection.execute(
        "SELECT value,bootstrap_interval_low,bootstrap_interval_high,eligible_query_count,"
        "eligible_relationship_count FROM evaluation_results WHERE corpus_pair=? "
        "AND detector='rrf_composite' AND metric=? AND split_strategy='held_out_genre' "
        "AND partition='test' AND analysis_profile='edition_complete' "
        "AND stratum_dimension='split_strategy_partition' "
        "AND stratum_value='held_out_genre|test' ORDER BY "
        "(mapping_status IN ('all','all_eligible','eligible')) DESC,"
        "(vote_stratum IN ('all','all_votes')) DESC,eligible_query_count DESC LIMIT 1",
        [corpus_pair, metric],
    ).fetchone()
    if row is None:
        return None
    return (float(row[0]), float(row[1]), float(row[2]), int(row[3]), int(row[4]))


def _evaluate_scientific_gate(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
) -> None:
    eligible: list[str] = []
    successful: list[str] = []
    insufficient: list[str] = []
    for corpus_pair in sorted(_PRIMARY_CORPUS_PAIRS):
        composite = _aggregate_gate_row(connection, corpus_pair, "rrf_composite")
        random = _aggregate_gate_row(connection, corpus_pair, "random")
        overlap = _aggregate_gate_row(connection, corpus_pair, "unweighted_overlap")
        random_difference = _difference_gate_row(connection, corpus_pair, "random")
        overlap_difference = _difference_gate_row(connection, corpus_pair, "unweighted_overlap")
        if (
            composite is None
            or random is None
            or overlap is None
            or random_difference is None
            or overlap_difference is None
        ):
            state.add(
                "scientific_gate_evidence_missing",
                f"Primary scientific-gate rows are missing for {corpus_pair}.",
                artifact="evaluation_results",
            )
            continue
        if (
            composite[3] < config.benchmark_evaluation.minimum_eligible_queries_per_primary_stratum
            or composite[4]
            < config.benchmark_evaluation.minimum_eligible_relationships_per_primary_stratum
        ):
            insufficient.append(corpus_pair)
            state.add(
                "scientific_gate_insufficient",
                f"{corpus_pair} is below the frozen sufficiency threshold; "
                "no recovery claim is made.",
                severity="informational",
                artifact="evaluation_results",
            )
            continue
        eligible.append(corpus_pair)
        point_exceeds = composite[0] > random[0] and composite[0] > overlap[0]
        positive_bootstrap = (
            random_difference[0] > 0.0
            and random_difference[1] > 0.0
            and overlap_difference[0] > 0.0
            and overlap_difference[1] > 0.0
        )
        if point_exceeds and positive_bootstrap:
            successful.append(corpus_pair)
        else:
            state.add(
                "scientific_gate_not_met",
                f"Composite does not exceed random and unweighted overlap with positive "
                f"bootstrap separation in {corpus_pair}; the failure is retained.",
                severity="informational",
                artifact="evaluation_results",
            )
    state.insufficient_primary_strata = insufficient
    state.scientific_gate_passed = bool(eligible) and set(successful) == set(eligible)
    acceptance = (state.acceptance_status or "").casefold()
    claims_incomplete = "incomplete" in acceptance or "failed" in acceptance
    claims_complete = not claims_incomplete and (
        "complete" in acceptance or acceptance in {"passed", "pass"}
    )
    if state.scientific_gate_passed is False and claims_complete:
        state.add(
            "scientific_gate_status",
            "Metadata claims acceptance although the frozen scientific gate is not met.",
            artifact="lexical_metadata",
        )


def _validate_queue(
    state: _State,
    connection: duckdb.DuckDBPyConnection,
    config: LexicalConfig,
) -> None:
    _count_check(
        state,
        connection,
        artifact="candidate_review_queue",
        code="queue_candidate_mismatch",
        message="Queue row differs from its candidate/evidence facts.",
        sql=(
            "SELECT count(*) FROM candidate_review_queue q LEFT JOIN candidate_pairs p "
            "USING(candidate_pair_id) LEFT JOIN candidate_evidence e USING(candidate_pair_id) "
            "WHERE p.candidate_pair_id IS NULL OR NOT q.review_eligible OR NOT p.review_eligible "
            "OR q.corpus_pair<>p.corpus_pair OR q.detector_support_count<>p.detector_support_count "
            "OR q.rare_rule_passed<>e.rare_rule_passed "
            "OR abs(q.rrf_score-e.rrf_score)>1e-12 "
            "OR abs(q.estimated_empirical_fdr-e.estimated_empirical_fdr)>1e-12 "
            "OR q.known_link_status<>p.known_link_status "
            "OR q.contains_english_derived_evidence<>p.contains_english_derived_evidence "
            "OR q.english_ablation_survives<>p.english_ablation_survives "
            "OR q.disputed_passage_flag<>p.disputed_passage_flag "
            "OR q.reference_gap<>p.reference_gap OR "
            "q.ketiv_structural_uncertainty<>p.ketiv_structural_uncertainty"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_review_queue",
        code="queue_eligibility",
        message="Unreviewed queue contains an excluded candidate.",
        sql=(
            "SELECT count(*) FROM candidate_review_queue WHERE "
            "known_link_status<>'not_represented_in_openbible_snapshot' OR NOT rare_rule_passed "
            f"OR estimated_empirical_fdr>{config.candidate_thresholds.maximum_empirical_fdr!r} "
            "OR (contains_english_derived_evidence AND NOT english_ablation_survives)"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_review_queue",
        code="queue_rank_sequence",
        message="Queue ranks are not contiguous from one.",
        sql=(
            "SELECT CASE WHEN count(*)=0 THEN 0 WHEN min(queue_rank)=1 "
            "AND max(queue_rank)=count(*) AND count(DISTINCT queue_rank)=count(*) "
            "THEN 0 ELSE 1 END "
            "FROM candidate_review_queue"
        ),
    )
    _count_check(
        state,
        connection,
        artifact="candidate_review_queue",
        code="queue_sort",
        message="Queue order is not RRF-descending with candidate-ID tie breaking.",
        sql=(
            "WITH q AS (SELECT *,lag(rrf_score) OVER (ORDER BY queue_rank) AS previous_score,"
            "lag(candidate_pair_id) OVER (ORDER BY queue_rank) AS previous_id "
            "FROM candidate_review_queue) SELECT count(*) FROM q WHERE "
            "previous_score<rrf_score OR "
            "(previous_score=rrf_score AND previous_id>candidate_pair_id)"
        ),
    )
    queue_columns = set(LEXICAL_ARTIFACT_COLUMNS["candidate_review_queue"])
    forbidden = {column for column in queue_columns if "decision" in column or "reviewer" in column}
    if forbidden:
        state.add(
            "queue_review_decision",
            "Milestone 7 queue schema contains human-review decision fields.",
            artifact="candidate_review_queue",
            fields=sorted(forbidden),
        )


def _validate_persisted_issues(state: _State, connection: duckdb.DuckDBPyConnection) -> None:
    rows = connection.execute(
        "SELECT severity,code,message,artifact,record_id FROM lexical_issues "
        "ORDER BY severity,code,issue_id"
    ).fetchall()
    for severity, code, message, artifact, record_id in rows:
        state.add(
            f"persisted_{code}",
            str(message),
            severity=cast(Severity, str(severity)),
            artifact=str(artifact) or "lexical_issues",
            record_id=str(record_id) or None,
        )


def _validate_no_source_text(state: _State, connection: duckdb.DuckDBPyConnection) -> None:
    governed_columns = {name: set(columns) for name, columns in LEXICAL_ARTIFACT_COLUMNS.items()}
    forbidden_names = {
        "surface_text",
        "normalized_text",
        "unpointed_text",
        "folded_text",
        "source_text",
        "reconstructed_text",
        "quotation_text",
        "verse_text",
    }
    for name, columns in governed_columns.items():
        overlap = columns.intersection(forbidden_names)
        if overlap:
            state.add(
                "stored_source_text_column",
                "Lexical artifacts must not persist reconstructed source text.",
                artifact=name,
                fields=sorted(overlap),
            )
    text_fields = (
        ("feature_vocabulary", "notes"),
        ("shared_evidence", "notes"),
        ("threshold_calibration", "notes"),
        ("lexical_metadata", "notes"),
        ("lexical_issues", "message"),
        ("lexical_issues", "details_json"),
    )
    for table, column in text_fields:
        _count_check(
            state,
            connection,
            artifact=table,
            code="bulk_text_payload",
            message="Free-text metadata is too large and may contain bulk source text.",
            sql=f'SELECT count(*) FROM "{table}" WHERE length("{column}")>4096',
        )


def _validate_duckdb_exposure(state: _State, database_path: Path, config: LexicalConfig) -> None:
    if not database_path.is_file():
        state.add("duckdb_missing", "Project DuckDB database does not exist.")
        return
    try:
        with (
            TemporaryDirectory(prefix="echoes-lexical-exposure-") as temporary,
            duckdb.connect(str(database_path), read_only=True) as connection,
        ):
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=2 * 1024**3,
                temp_directory=Path(temporary) / "spill",
                thread_count=1,
            )
            connection.execute("SET preserve_insertion_order=false")
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            expected_tables = set(DUCKDB_ARTIFACT_NAMES.values())
            expected_views = set(LEXICAL_CONVENIENCE_VIEWS)
            missing = expected_tables.union(expected_views).difference(relations)
            if missing:
                state.add(
                    "duckdb_relation_missing",
                    "DuckDB lacks governed lexical tables or convenience views.",
                    missing=sorted(missing),
                )
            for artifact, relation in DUCKDB_ARTIFACT_NAMES.items():
                if relation not in relations:
                    continue
                observed = _scalar(connection, f'SELECT count(*) FROM "{relation}"')
                if observed != state.table_counts.get(artifact):
                    state.add(
                        "duckdb_count_mismatch",
                        "DuckDB lexical relation count differs from Parquet.",
                        artifact=relation,
                    )
            if expected_tables.issubset(relations) and "passages" in relations:
                provenance = _scalar(
                    connection,
                    "SELECT count(*) FROM lexical_passage_feature_statistics s "
                    "LEFT JOIN passages p USING(passage_id) WHERE p.passage_id IS NULL OR "
                    "s.corpus<>p.corpus OR s.analysis_profile<>p.analysis_profile OR "
                    "s.analysis_reading<>p.analysis_reading OR s.granularity<>p.granularity "
                    "OR s.book<>p.book OR s.token_count<>p.token_count",
                )
                if provenance:
                    state.add(
                        "passage_provenance",
                        f"Lexical passage provenance differs from governed passages. "
                        f"Count={provenance}.",
                        artifact="lexical_passage_feature_statistics",
                    )
                ranking_passages = _scalar(
                    connection,
                    "SELECT count(*) FROM lexical_directional_rankings r "
                    "LEFT JOIN passages q ON q.passage_id=r.query_passage_id "
                    "LEFT JOIN passages t ON t.passage_id=r.target_passage_id "
                    "WHERE q.passage_id IS NULL OR t.passage_id IS NULL",
                )
                if ranking_passages:
                    state.add(
                        "ranking_passage_orphan",
                        f"Rankings reference absent passages. Count={ranking_passages}.",
                        artifact="lexical_directional_rankings",
                    )
                candidate_facts = _scalar(
                    connection,
                    "SELECT count(*) FROM lexical_candidate_pairs c "
                    "LEFT JOIN passages a ON a.passage_id=c.passage_a_id "
                    "LEFT JOIN passages b ON b.passage_id=c.passage_b_id "
                    "WHERE a.passage_id IS NULL OR b.passage_id IS NULL "
                    "OR c.disputed_passage_flag<>(a.disputed_passage_flag OR "
                    "b.disputed_passage_flag) OR c.reference_gap<>(a.reference_gap OR "
                    "b.reference_gap) OR c.ketiv_structural_uncertainty<>"
                    "(a.ketiv_structural_uncertainty OR b.ketiv_structural_uncertainty)",
                )
                if candidate_facts:
                    state.add(
                        "candidate_passage_facts",
                        f"Candidate passage flags do not reconcile. Count={candidate_facts}.",
                        artifact="lexical_candidate_pairs",
                    )
                queue_references = _scalar(
                    connection,
                    "SELECT count(*) FROM lexical_candidate_review_queue q JOIN "
                    "lexical_candidate_pairs c USING(candidate_pair_id) JOIN passages a "
                    "ON a.passage_id=c.passage_a_id JOIN passages b ON "
                    "b.passage_id=c.passage_b_id WHERE q.passage_a_reference<>a.start_reference "
                    "OR q.passage_b_reference<>b.start_reference",
                )
                if queue_references:
                    state.add(
                        "queue_reference",
                        f"Queue references differ from governed passages. "
                        f"Count={queue_references}.",
                        artifact="lexical_candidate_review_queue",
                    )
                nearby = _scalar(
                    connection,
                    "WITH facts AS (SELECT passage_id,corpus,analysis_profile,analysis_reading,"
                    "granularity,book,row_number() OVER (PARTITION BY corpus,analysis_profile,"
                    "analysis_reading,granularity ORDER BY start_stream_position_in_corpus,"
                    "passage_id) AS ordinal FROM passages), pairs AS (SELECT r.*,q.corpus AS qc,"
                    'q.book AS qb,q.ordinal AS qo,t.corpus AS tc,t.book AS tb,t.ordinal AS "to" '
                    "FROM lexical_directional_rankings r JOIN facts q ON q.passage_id="
                    "r.query_passage_id JOIN facts t ON t.passage_id=r.target_passage_id) "
                    "SELECT count(*) FROM pairs WHERE same_book<>(qc=tc AND qb=tb) OR "
                    'nearby_context<>(qc=tc AND qb=tb AND abs(qo-"to")<='
                    f"{config.penalties.nearby_verse_distance})",
                )
                if nearby:
                    state.add(
                        "ranking_context_flags",
                        f"Ranking same-book or nearby-context flags differ. Count={nearby}.",
                        artifact="lexical_directional_rankings",
                    )
            if "benchmark_relationships" in relations:
                openbible_ids = _scalar(
                    connection,
                    "WITH ids AS (SELECT c.candidate_pair_id,trim(CAST(j.value AS VARCHAR),"
                    "'\"') AS relationship_id FROM lexical_candidate_pairs c,"
                    "json_each(c.openbible_relationship_ids_json) j) SELECT count(*) FROM ids i "
                    "LEFT JOIN benchmark_relationships r USING(relationship_id) "
                    "WHERE r.relationship_id IS NULL",
                )
                if openbible_ids:
                    state.add(
                        "openbible_relationship_orphan",
                        f"Candidate OpenBible relationship IDs are absent. Count={openbible_ids}.",
                        artifact="lexical_candidate_pairs",
                    )
            if {
                "benchmark_relationships",
                "benchmark_endpoints",
                "benchmark_endpoint_mappings",
                "benchmark_mapping_target_passages",
            }.issubset(relations):
                known_pair_mismatches = _scalar(
                    connection,
                    "WITH endpoint_targets AS (SELECT e.relationship_id,e.endpoint_side,"
                    "t.target_passage_id FROM benchmark_endpoints e JOIN "
                    "benchmark_endpoint_mappings m USING(endpoint_id) JOIN "
                    "benchmark_mapping_target_passages t USING(mapping_id,endpoint_id) "
                    "WHERE m.target_analysis_profile='edition_complete' AND m.mapping_status IN "
                    "('mapped_verified','mapped_provisional','mapped_partial')), mapped AS "
                    "(SELECT DISTINCT a.relationship_id,least(a.target_passage_id,"
                    "b.target_passage_id) AS passage_a_id,greatest(a.target_passage_id,"
                    "b.target_passage_id) AS passage_b_id FROM endpoint_targets a JOIN "
                    "endpoint_targets b USING(relationship_id) WHERE a.endpoint_side='a' AND "
                    "b.endpoint_side='b'), expected AS (SELECT m.passage_a_id,m.passage_b_id,"
                    "to_json(list(m.relationship_id ORDER BY m.relationship_id)) AS ids,"
                    "max(r.source_weight_max) AS highest_vote FROM mapped m JOIN "
                    "benchmark_relationships r USING(relationship_id) GROUP BY 1,2) "
                    "SELECT count(*) FROM lexical_candidate_pairs c LEFT JOIN expected e "
                    "USING(passage_a_id,passage_b_id) WHERE "
                    "(c.known_link_status='represented_in_openbible_snapshot')<>"
                    "(e.passage_a_id IS NOT NULL) OR "
                    "(e.passage_a_id IS NOT NULL AND "
                    "(c.openbible_relationship_ids_json<>e.ids OR "
                    "c.highest_openbible_vote IS DISTINCT FROM e.highest_vote)) OR "
                    "(e.passage_a_id IS NULL AND c.highest_openbible_vote IS NOT NULL)",
                )
                if known_pair_mismatches:
                    state.add(
                        "openbible_pair_reconciliation",
                        f"Candidate OpenBible status, IDs, or votes do not reconcile in both "
                        f"directions. Count={known_pair_mismatches}.",
                        artifact="lexical_candidate_pairs",
                    )
            if "benchmark_split_assignments" in relations:
                leakage_crossings = _scalar(
                    connection,
                    "SELECT count(*) FROM (SELECT split_strategy,leakage_group_id,"
                    "count(DISTINCT partition) AS partitions FROM benchmark_split_assignments "
                    "WHERE leakage_group_id IS NOT NULL AND partition<>'excluded' GROUP BY ALL "
                    "HAVING partitions>1)",
                )
                if leakage_crossings:
                    state.add(
                        "benchmark_leakage_crossing",
                        f"Governed leakage groups cross evaluation partitions. "
                        f"Count={leakage_crossings}.",
                        artifact="benchmark_split_assignments",
                    )
    except (duckdb.Error, OSError) as exc:
        state.add("duckdb_unavailable", f"Could not validate lexical DuckDB exposure: {exc}.")


def _validate_upstream_anchors(
    state: _State,
    *,
    database_path: Path,
    passage_root: Path,
    benchmark_root: Path,
    tier1_path: Path,
    oshb_root: Path,
    config: LexicalConfig,
) -> None:
    try:
        resource_guard = ProcessResourceGuard(config.resource_limits.maximum_memory_bytes)
        duckdb_memory_limit = resource_guard.bounded_duckdb_memory_bytes(
            "validate:anchors:duckdb-budget",
            preferred_bytes=1024**3,
            reserve_for_python_bytes=1024**3,
        )
        with TemporaryDirectory(prefix="echoes-lexical-anchor-validation-") as temporary:
            verification = verify_upstream_anchors(
                database_path=database_path,
                passage_root=passage_root,
                benchmark_root=benchmark_root,
                tier1_path=tier1_path,
                oshb_root=oshb_root,
                duckdb_memory_limit_bytes=duckdb_memory_limit,
                duckdb_temp_directory=Path(temporary) / "spill",
            )
    except (
        LexicalAnchorError,
        LexicalResourceError,
        OSError,
        json.JSONDecodeError,
        KeyError,
    ) as exc:
        state.add("upstream_anchor", f"Upstream invariance check failed: {exc}.")
        return
    if verification.tier1_row_count != 0:
        state.add("tier1_nonempty", "Tier 1 must remain empty during Milestone 7.")


def validate_lexical_artifacts(
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
    *,
    database_path: Path | None = DEFAULT_DATABASE_PATH,
    config_path: Path = Path("config/lexical.yaml"),
    preregistration_path: Path = Path("config/experiments/m7-lexical-baseline.yaml"),
    passage_root: Path = DEFAULT_PASSAGE_ROOT,
    benchmark_root: Path = DEFAULT_BENCHMARK_ROOT,
    tier1_path: Path = DEFAULT_TIER1_PATH,
    oshb_root: Path = DEFAULT_OSHB_ROOT,
    verify_anchors: bool = True,
    verify_duckdb: bool = True,
    verify_sparse_indexes: bool = True,
    determinism_reference_root: Path | None = None,
    strict: bool = False,
) -> LexicalValidationReport:
    """Validate one complete promoted lexical artifact set.

    ``verify_anchors=False`` and ``verify_duckdb=False`` exist only for legally
    safe synthetic tests.  Production CLI calls must retain both defaults.
    """

    resolved = output_dir.resolve(strict=False)
    state = _State(output_dir=resolved, strict=strict)
    try:
        config = load_lexical_config(config_path)
        preregistration = load_lexical_preregistration(preregistration_path)
        validate_preregistration_against_config(preregistration, config)
    except LexicalConfigError as exc:
        state.add("configuration", f"Lexical configuration/preregistration failed: {exc}.")
        return _report(state)
    manifest = _audit_storage(state)
    if manifest is None or any(not (resolved / name).is_dir() for name in LEXICAL_ARTIFACT_NAMES):
        return _report(state)
    try:
        with _artifact_connection(resolved) as connection:
            _validate_generic_tables(state, connection)
            _validate_metadata(state, connection, manifest, config, preregistration)
            _validate_feature_integrity(state, connection, config)
            if verify_sparse_indexes:
                _validate_sparse_indexes(state, connection)
            _validate_rankings(state, connection, config, database_path)
            _validate_candidates(state, connection, config)
            _validate_nulls_and_calibration(state, connection, config)
            _validate_evaluation(state, connection, config, preregistration)
            _validate_queue(state, connection, config)
            _validate_persisted_issues(state, connection)
            _validate_no_source_text(state, connection)
    except (duckdb.Error, OSError, ValueError, TypeError) as exc:
        state.add("validation_runtime", f"Lexical relational validation failed: {exc}.")
    if database_path is not None and verify_duckdb:
        _validate_duckdb_exposure(state, database_path, config)
    if database_path is not None and verify_anchors:
        _validate_upstream_anchors(
            state,
            database_path=database_path,
            passage_root=passage_root,
            benchmark_root=benchmark_root,
            tier1_path=tier1_path,
            oshb_root=oshb_root,
            config=config,
        )
    if determinism_reference_root is not None:
        try:
            determinism = compare_lexical_runs(determinism_reference_root, resolved)
        except (LexicalValidationError, OSError, json.JSONDecodeError) as exc:
            state.add("determinism_comparison", f"Could not compare complete runs: {exc}.")
        else:
            if not determinism.passed:
                state.add(
                    "determinism_mismatch",
                    "Complete reruns differ in run identity, counts, or logical hashes.",
                    differing_tables=determinism.differing_tables,
                )
    return _report(state)


def _report(state: _State) -> LexicalValidationReport:
    errors = sum(issue.severity == "error" for issue in state.issues)
    warnings = sum(issue.severity == "warning" for issue in state.issues)
    informationals = sum(issue.severity == "informational" for issue in state.issues)
    return LexicalValidationReport(
        output_dir=str(state.output_dir),
        experiment_run_id=state.experiment_run_id,
        experiment_version=state.experiment_version,
        configuration_hash=state.configuration_hash,
        preregistration_hash=state.preregistration_hash,
        strict=state.strict,
        table_counts=state.table_counts,
        table_logical_hashes=state.logical_hashes,
        table_physical_hashes=state.physical_hashes,
        scientific_gate_passed=state.scientific_gate_passed,
        insufficient_primary_strata=state.insufficient_primary_strata,
        issues=state.issues,
        error_count=errors,
        warning_count=warnings,
        informational_count=informationals,
        passed=errors == 0 and (not state.strict or warnings == 0),
    )


def _rows_as_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: Sequence[object] | None = None,
) -> list[dict[str, object]]:
    cursor = connection.execute(sql, parameters or [])
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def lexical_summary(output_dir: Path = DEFAULT_LEXICAL_ROOT) -> LexicalSummary:
    """Collect a sanitized, text-free aggregate of one lexical run."""

    processed_manifest = json.loads((output_dir / TABLE_HASH_FILE).read_text("utf-8"))
    with _artifact_connection(output_dir.resolve()) as connection:
        metadata_rows = _rows_as_dicts(connection, "SELECT * FROM lexical_metadata")
        if len(metadata_rows) != 1:
            raise LexicalValidationError("lexical summary requires exactly one metadata row")
        metadata = LexicalMetadataRow.model_validate(metadata_rows[0])

        def grouped(sql: str) -> dict[str, int]:
            return {str(key): int(value) for key, value in connection.execute(sql).fetchall()}

        index_totals = connection.execute(
            "SELECT count(*),coalesce(sum(nonzero_count),0) FROM lexical_index_metadata"
        ).fetchone()
        assert index_totals is not None
        table_counts = {
            str(key): int(str(value))
            for key, value in cast(dict[str, object], processed_manifest["table_counts"]).items()
        }
        logical_hashes = {
            str(key): str(value)
            for key, value in cast(
                dict[str, object], processed_manifest["table_logical_sha256"]
            ).items()
        }
        return LexicalSummary(
            experiment_run_id=metadata.experiment_run_id,
            experiment_version=metadata.experiment_version,
            acceptance_status=metadata.acceptance_status,
            table_counts=table_counts,
            feature_counts_by_family=grouped(
                "SELECT feature_family,count(*) FROM feature_vocabulary GROUP BY 1 ORDER BY 1"
            ),
            passage_counts_by_corpus=grouped(
                "SELECT corpus,count(*) FROM passage_feature_statistics GROUP BY 1 ORDER BY 1"
            ),
            index_count=int(index_totals[0]),
            index_nonzero_count=int(index_totals[1]),
            ranking_counts_by_detector=grouped(
                "SELECT detector,count(*) FROM directional_rankings GROUP BY 1 ORDER BY 1"
            ),
            candidate_counts_by_corpus_pair=grouped(
                "SELECT corpus_pair,count(*) FROM candidate_pairs GROUP BY 1 ORDER BY 1"
            ),
            known_link_status_counts=grouped(
                "SELECT known_link_status,count(*) FROM candidate_pairs GROUP BY 1 ORDER BY 1"
            ),
            review_eligible_count=_scalar(
                connection, "SELECT count(*) FROM candidate_pairs WHERE review_eligible"
            ),
            queue_count=_scalar(connection, "SELECT count(*) FROM candidate_review_queue"),
            english_derived_candidate_count=_scalar(
                connection,
                "SELECT count(*) FROM candidate_pairs WHERE contains_english_derived_evidence",
            ),
            english_ablation_survival_count=_scalar(
                connection,
                "SELECT count(*) FROM candidate_pairs WHERE contains_english_derived_evidence "
                "AND english_ablation_survives",
            ),
            null_replicate_rows_by_family=grouped(
                "SELECT null_family,count(*) FROM null_replicate_summaries GROUP BY 1 ORDER BY 1"
            ),
            null_iterations_by_family=grouped(
                "SELECT null_family,count(DISTINCT iteration) FROM null_replicate_summaries "
                "GROUP BY 1 ORDER BY 1"
            ),
            evaluation_counts_by_detector=grouped(
                "SELECT detector,count(*) FROM evaluation_results GROUP BY 1 ORDER BY 1"
            ),
            table_logical_hashes=logical_hashes,
            storage_footprint_bytes=metadata.storage_footprint_bytes,
        )


def compare_lexical_runs(first_root: Path, second_root: Path) -> LexicalDeterminismReport:
    """Compare all logical outputs from two complete governed pipeline runs."""

    try:
        first_manifest_raw = json.loads((first_root / TABLE_HASH_FILE).read_text("utf-8"))
        second_manifest_raw = json.loads((second_root / TABLE_HASH_FILE).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalValidationError(f"could not read determinism manifests: {exc}") from exc
    if not isinstance(first_manifest_raw, dict) or not isinstance(second_manifest_raw, dict):
        raise LexicalValidationError("determinism manifests must be JSON objects")
    first_manifest = cast(dict[str, object], first_manifest_raw)
    second_manifest = cast(dict[str, object], second_manifest_raw)
    first_counts = cast(dict[str, object], first_manifest.get("table_counts", {}))
    second_counts = cast(dict[str, object], second_manifest.get("table_counts", {}))
    first_hashes = cast(dict[str, object], first_manifest.get("table_logical_sha256", {}))
    second_hashes = cast(dict[str, object], second_manifest.get("table_logical_sha256", {}))
    names = set(first_hashes).union(second_hashes)
    differing = sorted(name for name in names if first_hashes.get(name) != second_hashes.get(name))

    def run_id(root: Path) -> str:
        paths = sorted((root / "lexical_metadata").glob("part-*.parquet"))
        if not paths:
            raise LexicalValidationError(f"lexical metadata is absent from {root}")
        frame = pl.read_parquet(paths, columns=["experiment_run_id"])
        if frame.height != 1:
            raise LexicalValidationError("determinism comparison requires one metadata row")
        return str(frame.item())

    first_run = run_id(first_root)
    second_run = run_id(second_root)
    run_matches = first_run == second_run
    count_matches = first_counts == second_counts
    hashes_match = not differing and set(first_hashes) == set(LEXICAL_ARTIFACT_NAMES)
    return LexicalDeterminismReport(
        first_run_id=first_run,
        second_run_id=second_run,
        run_id_matches=run_matches,
        table_counts_match=count_matches,
        logical_hashes_match=hashes_match,
        differing_tables=differing,
        passed=run_matches and count_matches and hashes_match,
    )


def show_lexical_candidate(
    candidate_pair_id: str,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
) -> dict[str, object] | None:
    """Return one fully decomposed candidate without source-text fields."""

    with _artifact_connection(output_dir.resolve()) as connection:
        candidates = _rows_as_dicts(
            connection,
            "SELECT * FROM candidate_pairs WHERE candidate_pair_id=?",
            [candidate_pair_id],
        )
        if not candidates:
            return None
        evidence = _rows_as_dicts(
            connection,
            "SELECT * FROM candidate_evidence WHERE candidate_pair_id=?",
            [candidate_pair_id],
        )
        scores = _rows_as_dicts(
            connection,
            "SELECT * FROM candidate_detector_scores WHERE candidate_pair_id=? "
            "ORDER BY detector,representation_id,direction",
            [candidate_pair_id],
        )
        shared = _rows_as_dicts(
            connection,
            "SELECT * FROM shared_evidence WHERE candidate_pair_id=? "
            "ORDER BY evidence_family,evidence_id",
            [candidate_pair_id],
        )
        queue = _rows_as_dicts(
            connection,
            "SELECT * FROM candidate_review_queue WHERE candidate_pair_id=?",
            [candidate_pair_id],
        )
        corpus_pair = str(candidates[0]["corpus_pair"])
        calibration = _rows_as_dicts(
            connection,
            "SELECT * FROM threshold_calibration WHERE corpus_pair=? "
            "ORDER BY detector,score_threshold",
            [corpus_pair],
        )
        return {
            "candidate": candidates[0],
            "evidence_summary": evidence[0] if evidence else None,
            "detector_scores": scores,
            "shared_evidence": shared,
            "threshold_calibration": calibration,
            "queue": queue[0] if queue else None,
        }


def show_lexical_evidence(
    candidate_pair_id: str,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
) -> dict[str, object] | None:
    """Return only the evidence and calibration portion of one candidate."""

    candidate = show_lexical_candidate(candidate_pair_id, output_dir)
    if candidate is None:
        return None
    return {
        key: candidate[key]
        for key in (
            "evidence_summary",
            "detector_scores",
            "shared_evidence",
            "threshold_calibration",
        )
    }


def compare_lexical_ablation(
    candidate_pair_id: str,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
) -> dict[str, object] | None:
    """Return the English bridge/ablation facts for one candidate."""

    with _artifact_connection(output_dir.resolve()) as connection:
        rows = _rows_as_dicts(
            connection,
            "SELECT candidate_pair_id,corpus_pair,contains_english_derived_evidence,"
            "english_ablation_survives,review_eligible,eligibility_reason "
            "FROM candidate_pairs WHERE candidate_pair_id=?",
            [candidate_pair_id],
        )
        if not rows:
            return None
        scores = _rows_as_dicts(
            connection,
            "SELECT detector,representation_id,direction,score,quantized_score,"
            "score_contribution,penalty_contribution FROM candidate_detector_scores "
            "WHERE candidate_pair_id=? ORDER BY representation_id,detector,direction",
            [candidate_pair_id],
        )
        return {"ablation": rows[0], "component_scores": scores}


__all__ = [
    "LexicalDeterminismReport",
    "LexicalSummary",
    "LexicalValidationError",
    "LexicalValidationIssue",
    "LexicalValidationReport",
    "compare_lexical_ablation",
    "compare_lexical_runs",
    "lexical_summary",
    "null_replicate_logical_hash",
    "shared_evidence_digest",
    "show_lexical_candidate",
    "show_lexical_evidence",
    "sparse_index_physical_hash",
    "validate_lexical_artifacts",
]
