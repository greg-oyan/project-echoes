# ruff: noqa: E402
"""End-to-end deterministic Milestone 7 transparent lexical pipeline."""

from __future__ import annotations

import gc
import hashlib
import json
import math
import platform
import shutil
import time
import warnings
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from echoes.lexical.resources import (
    MEBIBYTE,
    LexicalResourceError,
    ProcessResourceGuard,
    configure_duckdb_connection,
    enforce_thread_controls,
    initialize_thread_controls,
)

# Numeric thread pools read these variables at import time.  The governed M7
# configuration is single-threaded; the runtime check below rejects any drift.
initialize_thread_controls(1)

import duckdb
import polars as pl

from echoes.corpus.storage import logical_frame_hash
from echoes.lexical.anchors import AnchorVerification, verify_upstream_anchors
from echoes.lexical.candidates import (
    CandidateEvidenceContext,
    build_feature_evidence_indexes,
    build_review_queue,
    candidate_q_values,
    iter_candidate_artifact_batches,
    load_known_pair_index,
)
from echoes.lexical.config import (
    LEXICAL_CONFIG_PATH,
    LEXICAL_PREREGISTRATION_PATH,
    AnalysisProfile,
    CorpusPair,
    FeatureFamily,
    Granularity,
    LexicalConfig,
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    validate_preregistration_against_config,
)
from echoes.lexical.evaluation import REQUIRED_BASELINES
from echoes.lexical.experiment import (
    LexicalExperimentError,
    Tier3EvaluationScope,
    governed_detectors_by_corpus_pair,
    run_null_calibration_experiment,
    run_tier3_evaluation_experiment,
)
from echoes.lexical.features import (
    build_feature_vocabulary,
    build_passage_feature_statistics,
    combine_feature_vocabularies,
)
from echoes.lexical.identity import (
    FeatureIdentityPayload,
    LanguageNamespace,
    RepresentationIdentityPayload,
    build_feature_identity,
    build_representation_identity,
)
from echoes.lexical.models import (
    CANDIDATE_REVIEW_QUEUE_SCHEMA,
    FEATURE_VOCABULARY_SCHEMA,
    LEXICAL_INDEX_METADATA_SCHEMA,
    LEXICAL_ISSUES_SCHEMA,
    LEXICAL_METADATA_SCHEMA,
    SENSITIVITY_RESULTS_SCHEMA,
)
from echoes.lexical.retrieval import (
    DETECTOR_FAMILIES,
    CandidateAggregate,
    CandidateDirection,
    iter_retrieval_batches,
)
from echoes.lexical.sequences import (
    PassageLexicalSequence,
    iter_passage_sequences,
    sequence_digest,
)
from echoes.lexical.sparse import (
    SparseIndexError,
    SparseLexicalIndex,
    build_sparse_index,
    load_sparse_index,
    persist_sparse_index,
)
from echoes.lexical.storage import (
    LexicalArtifactWriter,
    ProcessedLexical,
    load_lexical_duckdb,
)
from echoes.lexical.validation import sparse_index_physical_hash
from echoes.manifest import ExperimentExecutionRecorder, sha256_file
from echoes.manifests.sources import load_source_catalog
from echoes.settings import BenchmarkConfig, load_config

DEFAULT_DATABASE_PATH = Path("data/processed/project_echoes.duckdb")
DEFAULT_PASSAGE_ROOT = Path("data/processed/passages/schema-v1")
DEFAULT_BENCHMARK_ROOT = Path("data/processed/benchmarks/schema-v1")
DEFAULT_OSHB_ROOT = Path("data/processed/oshb-morphhb/master-3d15126")
DEFAULT_TIER1_PATH = Path("data/benchmarks/tier1_quotations.csv")
DEFAULT_LEXICAL_ROOT = Path("data/processed/lexical/schema-v1")

_M7_SOURCE_IDS = (
    "macula-hebrew",
    "macula-greek",
    "oshb-morphhb",
    "openbible-cross-references",
    "project-echoes-tier1-quotations",
)
_M7_DATASET_MANIFEST_PATH = Path("data/manifests/sources.yaml")
_M7_CONFIGURATION_FILES = {
    "benchmark_yaml": Path("config/benchmark.yaml"),
    "lexical_preregistration_yaml": LEXICAL_PREREGISTRATION_PATH,
    "lexical_yaml": LEXICAL_CONFIG_PATH,
    "models_yaml": Path("config/models.yaml"),
    "normalization_yaml": Path("config/normalization.yaml"),
    "scoring_yaml": Path("config/scoring.yaml"),
    "segmentation_yaml": Path("config/segmentation.yaml"),
}

_DUCKDB_PREFERRED_MEMORY_BYTES = 512 * MEBIBYTE
_SENSITIVITY_DUCKDB_PREFERRED_MEMORY_BYTES = 1024 * MEBIBYTE
_PROVENANCE_DUCKDB_PREFERRED_MEMORY_BYTES = 1536 * MEBIBYTE
_DUCKDB_PYTHON_RESERVE_BYTES = 512 * MEBIBYTE
_SEQUENCE_LOAD_RESERVATION_BYTES = 512 * MEBIBYTE
_FEATURE_VOCABULARY_RESERVATION_BYTES = 768 * MEBIBYTE
_PASSAGE_STATISTICS_RESERVATION_BYTES = 512 * MEBIBYTE
_CANDIDATE_EVIDENCE_RESERVATION_BYTES = 768 * MEBIBYTE
_REVIEW_QUEUE_READ_BATCH_SIZE = 10_000
_CANDIDATE_REVIEW_QUEUE_SPOOL_DIRECTORY = ".candidate-review-queue-spool"
_SENSITIVITY_MAX_SPILL_BYTES = 2 * 1024 * MEBIBYTE
_SENSITIVITY_SPILL_SAFETY_BYTES = 256 * MEBIBYTE
_SENSITIVITY_MINIMUM_SPILL_BYTES = 256 * MEBIBYTE
_SENSITIVITY_QUERY_REFERENCE_BUCKETS = (
    ("0", "1", "2", "3"),
    ("4", "5", "6", "7"),
    ("8", "9", "a", "b"),
    ("c", "d", "e", "f"),
)


class LexicalPipelineError(RuntimeError):
    """Raised when the governed Milestone 7 pipeline cannot finish safely."""


class _ResourceCheck(Protocol):
    def __call__(self, stage: str, *, estimated_additional_bytes: int = 0) -> None: ...


class _CandidateCheckpoint(Protocol):
    def write_updates(self, updates: Sequence[CandidateAggregate]) -> None: ...


@dataclass(frozen=True, slots=True)
class LexicalPipelineResult:
    """Report-ready result from one complete atomic lexical run."""

    experiment_run_id: str
    experiment_version: str
    configuration_hash: str
    preregistration_hash: str
    anchors: AnchorVerification
    processed: ProcessedLexical
    database_path: Path
    stage_runtime_seconds: dict[str, float]
    feature_counts: dict[str, int]
    index_summaries: dict[str, dict[str, object]]
    ranking_count: int
    candidate_count: int
    review_eligible_count: int
    queue_count: int
    null_iteration_count: int
    evaluation_count: int
    acceptance_status: str
    approximate_peak_memory_bytes: int


@dataclass(frozen=True, slots=True)
class _IndexDefinition:
    key: str
    sequences: Sequence[PassageLexicalSequence]
    family: str
    namespace: str
    corpus_scope: tuple[str, ...]
    reading: str
    analysis_profile: str
    granularity: str
    retain_for_retrieval: bool = True


@dataclass(frozen=True, slots=True)
class _RetrievalScopeResult:
    candidates: dict[str, CandidateAggregate]
    ranking_count: int
    next_ranking_part: int


_CANDIDATE_CHECKPOINT_SCHEMA = pl.Schema(
    {
        "candidate_pair_id": pl.String,
        "canonical_unordered_pair_id": pl.String,
        "passage_a_id": pl.String,
        "passage_b_id": pl.String,
        "corpus_pair": pl.String,
        "analysis_profile": pl.String,
        "granularity": pl.String,
        "direction": pl.String,
        "query_passage_id": pl.String,
        "target_passage_id": pl.String,
        "scores_json": pl.String,
        "ranks_json": pl.String,
        "rrf_score": pl.Float64,
        "proposal_detectors_json": pl.String,
        "alignment_evaluated": pl.Boolean,
        "score_trace_version": pl.String,
    }
)
_CANDIDATE_CHECKPOINT_DIRECTORY = ".resume-primary-candidates"
_CANDIDATE_CHECKPOINT_MANIFEST = "complete.json"
_TIER3_CHECKPOINT_DIRECTORY = "tier3-evaluation"
_TIER3_CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class _PrivateCheckpointQuarantine:
    """Keep private recovery state outside promotion until manifest success."""

    output_dir: Path
    staging_dir: Path | None = None
    quarantine_dir: Path | None = None

    def _expected_quarantine(self, staging_dir: Path) -> Path:
        token = hashlib.sha256(staging_dir.as_posix().encode("utf-8")).hexdigest()[:20]
        resolved_output = self.output_dir.resolve()
        return resolved_output.parent / f".{resolved_output.name}.checkpoint-quarantine-{token}"

    def register_staging(self, staging_dir: Path) -> None:
        resolved_output = self.output_dir.resolve()
        if staging_dir.is_symlink():
            raise LexicalPipelineError("private-checkpoint staging path is not governed")
        resolved_staging = staging_dir.resolve()
        if (
            resolved_staging.parent != resolved_output.parent
            or not resolved_staging.name.startswith(f".{resolved_output.name}.writing-")
        ):
            raise LexicalPipelineError("private-checkpoint staging path is not governed")
        if self.staging_dir is not None and self.staging_dir != resolved_staging:
            raise LexicalPipelineError("private-checkpoint staging path changed during execution")
        self.staging_dir = resolved_staging
        quarantine = self._expected_quarantine(resolved_staging)
        if quarantine.exists() or quarantine.is_symlink():
            destination = resolved_staging / _CANDIDATE_CHECKPOINT_DIRECTORY
            if (
                quarantine.is_symlink()
                or not quarantine.is_dir()
                or quarantine.resolve().parent != resolved_output.parent
            ):
                raise LexicalPipelineError(
                    f"private checkpoint quarantine is not governed: {quarantine}"
                )
            if destination.exists() or destination.is_symlink():
                raise LexicalPipelineError(
                    "both staging and quarantine contain private checkpoints"
                )
            quarantine.replace(destination)

    def quarantine_before_promotion(self) -> None:
        if self.staging_dir is None:
            raise LexicalPipelineError("private-checkpoint staging path is unavailable")
        checkpoint_root = self.staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY
        if not checkpoint_root.exists():
            return
        if checkpoint_root.is_symlink():
            raise LexicalPipelineError("private checkpoint path escaped staging")
        resolved_checkpoint = checkpoint_root.resolve()
        if resolved_checkpoint.parent != self.staging_dir or not resolved_checkpoint.is_dir():
            raise LexicalPipelineError("private checkpoint path escaped staging")
        quarantine = self._expected_quarantine(self.staging_dir)
        if quarantine.exists() or quarantine.is_symlink():
            raise LexicalPipelineError(
                f"private checkpoint quarantine already exists: {quarantine}"
            )
        resolved_checkpoint.replace(quarantine)
        self.quarantine_dir = quarantine

    def preserve_after_failure(self, error: BaseException) -> None:
        """Restore resumable state when possible and never mask the primary failure."""

        staging = self.staging_dir
        quarantine = self.quarantine_dir
        if quarantine is not None and quarantine.exists():
            destination = None if staging is None else staging / _CANDIDATE_CHECKPOINT_DIRECTORY
            if staging is not None and staging.is_dir() and destination is not None:
                if destination.exists() or destination.is_symlink():
                    error.add_note(
                        "private checkpoint quarantine was preserved because its staging "
                        f"destination already exists: {quarantine}"
                    )
                else:
                    try:
                        quarantine.replace(destination)
                    except OSError as restore_error:
                        error.add_note(
                            "private checkpoint quarantine could not be restored and remains "
                            f"at {quarantine}: {restore_error}"
                        )
                    else:
                        self.quarantine_dir = None
                        quarantine = None
            if quarantine is not None:
                error.add_note(f"preserved private checkpoint quarantine: {quarantine}")
        if staging is not None and staging.is_dir():
            error.add_note(f"preserved lexical staging directory: {staging}")

    def cleanup_after_success(self) -> str | None:
        """Remove quarantined state only after the successful manifest is durable."""

        quarantine = self.quarantine_dir
        if quarantine is None or not quarantine.exists():
            self.quarantine_dir = None
            return None
        if quarantine.is_symlink():
            return f"refusing to clean ungoverned checkpoint quarantine: {quarantine}"
        resolved_output = self.output_dir.resolve()
        resolved_quarantine = quarantine.resolve()
        expected_prefix = f".{resolved_output.name}.checkpoint-quarantine-"
        if (
            resolved_quarantine.parent != resolved_output.parent
            or not resolved_quarantine.name.startswith(expected_prefix)
        ):
            return f"refusing to clean ungoverned checkpoint quarantine: {quarantine}"
        try:
            shutil.rmtree(quarantine)
        except OSError as error:
            return f"could not clean successful checkpoint quarantine {quarantine}: {error}"
        self.quarantine_dir = None
        return None


class _CandidateCheckpointWriter:
    """Persist exact primary aggregate updates behind a completion marker."""

    def __init__(
        self,
        staging_dir: Path,
        *,
        experiment_run_id: str,
        configuration_hash: str,
    ) -> None:
        self.root = staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY
        if self.root.exists():
            if self.root.is_symlink():
                raise LexicalPipelineError("candidate checkpoint path escaped staging")
            resolved = self.root.resolve()
            if resolved.parent != staging_dir.resolve() or not resolved.is_dir():
                raise LexicalPipelineError("candidate checkpoint path escaped staging")
            for path in sorted(resolved.iterdir()):
                if path.name == _TIER3_CHECKPOINT_DIRECTORY:
                    if path.is_symlink() or not path.is_dir() or path.resolve().parent != resolved:
                        raise LexicalPipelineError(
                            "candidate checkpoint contains an unsafe Tier 3 checkpoint"
                        )
                    continue
                if path.name == "progress.txt":
                    if path.is_symlink() or not path.is_file() or path.resolve().parent != resolved:
                        raise LexicalPipelineError(
                            "candidate checkpoint contains an unsafe progress marker"
                        )
                    continue
                if path.is_symlink() or not path.is_file():
                    raise LexicalPipelineError(
                        f"candidate checkpoint contains ungoverned direct residue: {path.name}"
                    )
                if path.name != _CANDIDATE_CHECKPOINT_MANIFEST and not (
                    path.name.startswith("part-") and path.suffix == ".parquet"
                ):
                    raise LexicalPipelineError(
                        f"candidate checkpoint contains unexpected direct residue: {path.name}"
                    )
                path.unlink()
        self.root.mkdir(exist_ok=True)
        self.experiment_run_id = experiment_run_id
        self.configuration_hash = configuration_hash
        self.parts: list[dict[str, object]] = []
        self.row_count = 0

    def write_updates(self, updates: Sequence[CandidateAggregate]) -> None:
        rows: list[dict[str, object]] = []
        for candidate in updates:
            for direction in candidate.directions.values():
                rows.append(
                    {
                        "candidate_pair_id": candidate.candidate_pair_id,
                        "canonical_unordered_pair_id": candidate.canonical_unordered_pair_id,
                        "passage_a_id": candidate.passage_a_id,
                        "passage_b_id": candidate.passage_b_id,
                        "corpus_pair": candidate.corpus_pair,
                        "analysis_profile": candidate.analysis_profile,
                        "granularity": candidate.granularity,
                        "direction": direction.direction,
                        "query_passage_id": direction.query_passage_id,
                        "target_passage_id": direction.target_passage_id,
                        "scores_json": _canonical_json(direction.scores),
                        "ranks_json": _canonical_json(direction.ranks),
                        "rrf_score": direction.rrf_score,
                        "proposal_detectors_json": _canonical_json(
                            list(direction.proposal_detectors)
                        ),
                        "alignment_evaluated": direction.alignment_evaluated,
                        "score_trace_version": direction.score_trace_version,
                    }
                )
        frame = pl.DataFrame(rows, schema=_CANDIDATE_CHECKPOINT_SCHEMA, orient="row").sort(
            "candidate_pair_id",
            "direction",
            "query_passage_id",
            "target_passage_id",
        )
        part = len(self.parts)
        path = self.root / f"part-{part:05d}.parquet"
        frame.write_parquet(
            path,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        self.parts.append(
            {
                "path": path.name,
                "row_count": frame.height,
                "sha256": sha256_file(path),
            }
        )
        self.row_count += frame.height

    def finalize(self) -> None:
        if not self.parts or self.row_count < 1:
            raise LexicalPipelineError("primary candidate checkpoint is empty")
        payload = {
            "schema_version": 1,
            "experiment_run_id": self.experiment_run_id,
            "configuration_hash": self.configuration_hash,
            "row_count": self.row_count,
            "parts": self.parts,
        }
        (self.root / _CANDIDATE_CHECKPOINT_MANIFEST).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _load_candidate_checkpoint(
    staging_dir: Path,
    *,
    experiment_run_id: str,
    configuration_hash: str,
    resource_check: _ResourceCheck | None = None,
) -> dict[str, CandidateAggregate] | None:
    root = staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY
    manifest_path = root / _CANDIDATE_CHECKPOINT_MANIFEST
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir() or root.resolve().parent != staging_dir.resolve():
        raise LexicalPipelineError("candidate checkpoint path escaped staging")
    if not manifest_path.is_file():
        return None
    if manifest_path.is_symlink() or manifest_path.resolve().parent != root.resolve():
        raise LexicalPipelineError("candidate checkpoint manifest escaped its root")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalPipelineError(f"candidate checkpoint manifest is unreadable: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("experiment_run_id") != experiment_run_id
        or manifest.get("configuration_hash") != configuration_hash
        or not isinstance(manifest.get("parts"), list)
    ):
        raise LexicalPipelineError("candidate checkpoint identity does not match the resumed run")
    merged: dict[str, CandidateAggregate] = {}
    observed_rows = 0
    parts = cast(list[object], manifest["parts"])
    for part, item in enumerate(parts):
        if not isinstance(item, dict):
            raise LexicalPipelineError("candidate checkpoint part metadata is invalid")
        expected_name = f"part-{part:05d}.parquet"
        if item.get("path") != expected_name:
            raise LexicalPipelineError("candidate checkpoint parts are not contiguous")
        path = root / expected_name
        if (
            not path.is_file()
            or sha256_file(path) != item.get("sha256")
            or path.resolve().parent != root.resolve()
        ):
            raise LexicalPipelineError(
                f"candidate checkpoint physical hash mismatch: {expected_name}"
            )
        try:
            frame = pl.read_parquet(path, rechunk=True).cast(
                _CANDIDATE_CHECKPOINT_SCHEMA, strict=True
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalPipelineError(
                f"candidate checkpoint part is unreadable: {expected_name}: {exc}"
            ) from exc
        if tuple(frame.columns) != tuple(_CANDIDATE_CHECKPOINT_SCHEMA):
            raise LexicalPipelineError("candidate checkpoint schema differs")
        if frame.height != item.get("row_count"):
            raise LexicalPipelineError("candidate checkpoint row count differs")
        updates: list[CandidateAggregate] = []
        for row in frame.iter_rows(named=True):
            try:
                scores = json.loads(cast(str, row["scores_json"]))
                ranks = json.loads(cast(str, row["ranks_json"]))
                proposals = json.loads(cast(str, row["proposal_detectors_json"]))
            except json.JSONDecodeError as exc:
                raise LexicalPipelineError("candidate checkpoint contains invalid JSON") from exc
            if (
                not isinstance(scores, dict)
                or not isinstance(ranks, dict)
                or not isinstance(proposals, list)
            ):
                raise LexicalPipelineError("candidate checkpoint trace payload is invalid")
            direction_value = str(row["direction"])
            if direction_value not in {"a_to_b", "b_to_a"}:
                raise LexicalPipelineError("candidate checkpoint direction is invalid")
            candidate = CandidateAggregate(
                candidate_pair_id=cast(str, row["candidate_pair_id"]),
                canonical_unordered_pair_id=cast(str, row["canonical_unordered_pair_id"]),
                passage_a_id=cast(str, row["passage_a_id"]),
                passage_b_id=cast(str, row["passage_b_id"]),
                corpus_pair=cast(str, row["corpus_pair"]),
                analysis_profile=cast(str, row["analysis_profile"]),
                granularity=cast(str, row["granularity"]),
            )
            candidate.add_direction(
                CandidateDirection(
                    direction=cast(Literal["a_to_b", "b_to_a"], direction_value),
                    query_passage_id=cast(str, row["query_passage_id"]),
                    target_passage_id=cast(str, row["target_passage_id"]),
                    scores={str(key): float(value) for key, value in scores.items()},
                    ranks={str(key): int(value) for key, value in ranks.items()},
                    rrf_score=float(cast(float, row["rrf_score"])),
                    proposal_detectors=tuple(str(value) for value in proposals),
                    alignment_evaluated=bool(row["alignment_evaluated"]),
                    score_trace_version=cast(str, row["score_trace_version"]),
                )
            )
            updates.append(candidate)
        _merge_updates(merged, updates)
        observed_rows += frame.height
        if resource_check is not None:
            resource_check(f"candidate_checkpoint:part-{part}")
    if observed_rows != manifest.get("row_count") or not merged:
        raise LexicalPipelineError("candidate checkpoint completion count differs")
    return merged


@contextmanager
def _bounded_duckdb_connection(
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    database_path: Path | None = None,
    read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open one connection with explicit single-thread, memory, and spill limits."""

    if temp_directory.exists():
        raise LexicalPipelineError(f"DuckDB spill directory already exists: {temp_directory}")
    try:
        if database_path is None:
            connection = duckdb.connect()
        else:
            connection = duckdb.connect(str(database_path), read_only=read_only)
        try:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=memory_limit_bytes,
                temp_directory=temp_directory,
                thread_count=1,
            )
            yield connection
        finally:
            connection.close()
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


@contextmanager
def _managed_temp_directory(path: Path) -> Iterator[Path]:
    """Create one fail-closed pipeline spill directory and always remove it."""

    if path.exists():
        raise LexicalPipelineError(f"pipeline spill directory already exists: {path}")
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sparse_index_reservation_bytes(definition: _IndexDefinition) -> int:
    """Conservatively reserve transient Python/CSR construction memory."""

    occurrence_count = sum(
        len(passage.values(definition.family)) for passage in definition.sequences
    )
    estimated = occurrence_count * 384 + len(definition.sequences) * 4096
    return max(256 * MEBIBYTE, estimated)


def _retrieval_reservation_bytes(config: LexicalConfig) -> int:
    """Reserve a bounded query block plus detector/rerank working state."""

    hits_per_query = (
        config.retrieval.candidate_union_k
        + config.retrieval.persisted_top_k
        + config.retrieval.persisted_candidate_pool_k
        + config.retrieval.expensive_sequence_rerank_k
    )
    estimated = config.resource_limits.block_passage_count * hits_per_query * 128
    return max(256 * MEBIBYTE, estimated)


def _m7_source_versions() -> dict[str, str]:
    catalog = load_source_catalog(_M7_DATASET_MANIFEST_PATH)
    versions: dict[str, str] = {}
    for source_id in _M7_SOURCE_IDS:
        source = catalog.find(source_id)
        if source is None or source.version_or_commit is None:
            raise LexicalPipelineError(f"M7 source manifest lacks a pinned version for {source_id}")
        versions[f"source:{source_id}"] = source.version_or_commit
    return versions


def _prefixed_hashes(prefix: str, values: Mapping[str, str]) -> dict[str, str]:
    return {f"{prefix}:{key}": value for key, value in sorted(values.items())}


def _m7_anchor_input_hashes(anchors: AnchorVerification) -> dict[str, str]:
    return {
        **_prefixed_hashes("corpus_identity", anchors.corpus_identity_digests),
        **_prefixed_hashes("corpus_content", anchors.corpus_content_digests),
        **_prefixed_hashes("corpus_analytical", anchors.corpus_analytical_digests),
        **_prefixed_hashes("oshb", anchors.oshb_logical_hashes),
        **_prefixed_hashes("passage", anchors.passage_logical_hashes),
        **_prefixed_hashes("benchmark", anchors.benchmark_logical_hashes),
        "openbible:archive": anchors.openbible_archive_sha256,
        "openbible:canonical_stream": anchors.openbible_canonical_stream_sha256,
        "tier1:quotations": anchors.tier1_sha256,
    }


def _m7_anchor_dataset_versions(anchors: AnchorVerification) -> dict[str, str]:
    return {
        "benchmark:run_id": anchors.benchmark_run_id,
        "benchmark:version": anchors.benchmark_version,
        "openbible:snapshot": anchors.openbible_snapshot,
        "passages:run_id": anchors.passage_run_id,
    }


def _command_path(path: Path, *, project_root: Path) -> str:
    root = project_root.resolve()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _m7_reproduction_command(
    *,
    database_path: Path,
    output_dir: Path,
    force: bool,
    project_root: Path,
) -> list[str]:
    command = [
        "uv",
        "run",
        "echoes",
        "run-lexical-pipeline",
        "--primary",
        "--database",
        _command_path(database_path, project_root=project_root),
        "--output-dir",
        _command_path(output_dir, project_root=project_root),
    ]
    if force:
        command.append("--force")
    return command


def _validated_resume_file_hashes(
    staging_dir: Path,
    *,
    candidate_checkpoint_reused: bool,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    resolved = staging_dir.resolve()
    artifact_parts: dict[str, str] = {}
    for path in sorted(resolved.glob("*/part-*.parquet")):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.parent.name == _CANDIDATE_CHECKPOINT_DIRECTORY
        ):
            continue
        artifact_parts[path.relative_to(resolved).as_posix()] = sha256_file(path)

    checkpoint_manifests: dict[str, str] = {}
    checkpoint_parts: dict[str, str] = {}
    if candidate_checkpoint_reused:
        checkpoint_root = resolved / _CANDIDATE_CHECKPOINT_DIRECTORY
        manifest_path = checkpoint_root / _CANDIDATE_CHECKPOINT_MANIFEST
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise LexicalPipelineError("validated candidate checkpoint manifest disappeared")
        checkpoint_manifests[manifest_path.relative_to(resolved).as_posix()] = sha256_file(
            manifest_path
        )
        for path in sorted(checkpoint_root.glob("part-*.parquet")):
            if not path.is_file() or path.is_symlink():
                raise LexicalPipelineError("validated candidate checkpoint part disappeared")
            checkpoint_parts[path.relative_to(resolved).as_posix()] = sha256_file(path)
    if not artifact_parts:
        raise LexicalPipelineError("validated resume contains no reusable artifact parts")
    return artifact_parts, checkpoint_manifests, checkpoint_parts


def _expected_tier3_checkpoint_manifest_names(
    *,
    analysis_profiles: Sequence[str],
    enabled_detectors: Sequence[str],
) -> tuple[str, ...]:
    detectors = (*enabled_detectors, "rrf_composite")
    names = {
        f"{profile}-baseline-{baseline}.json"
        for profile in analysis_profiles
        for baseline in REQUIRED_BASELINES
    }
    names.update(
        f"{profile}-detector-{detector}.json"
        for profile in analysis_profiles
        for detector in detectors
    )
    return tuple(sorted(names))


def _validated_existing_tier3_checkpoint_hashes(
    staging_dir: Path,
    *,
    expected_manifest_names: Sequence[str],
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Authenticate the expected pre-existing Tier 3 checkpoint inventory."""

    resolved_staging = staging_dir.resolve()
    checkpoint_root = resolved_staging / _CANDIDATE_CHECKPOINT_DIRECTORY
    tier3_root = checkpoint_root / _TIER3_CHECKPOINT_DIRECTORY
    if not tier3_root.exists():
        return {}, {}
    if (
        checkpoint_root.is_symlink()
        or checkpoint_root.resolve().parent != resolved_staging
        or tier3_root.is_symlink()
        or not tier3_root.is_dir()
        or tier3_root.resolve().parent != checkpoint_root.resolve()
    ):
        raise LexicalPipelineError("Tier 3 checkpoint path escaped resumed staging")

    expected_names = set(expected_manifest_names)
    actual_entries = sorted(tier3_root.iterdir(), key=lambda path: path.name)
    unexpected_directories = [path.name for path in actual_entries if not path.is_file()]
    if unexpected_directories:
        raise LexicalPipelineError(
            f"Tier 3 checkpoint contains unexpected directories: {unexpected_directories[:5]}"
        )
    actual_manifests = {
        path.name for path in actual_entries if path.suffix == ".json" and not path.is_symlink()
    }
    unexpected_manifests = sorted(actual_manifests.difference(expected_names))
    if unexpected_manifests:
        raise LexicalPipelineError(
            f"Tier 3 checkpoint contains unexpected manifests: {unexpected_manifests[:5]}"
        )

    manifest_hashes: dict[str, str] = {}
    part_hashes: dict[str, str] = {}
    referenced_names: set[str] = set()
    for manifest_name in sorted(actual_manifests):
        manifest_path = tier3_root / manifest_name
        if manifest_path.is_symlink() or manifest_path.resolve().parent != tier3_root.resolve():
            raise LexicalPipelineError(f"Tier 3 checkpoint manifest is unsafe: {manifest_name}")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LexicalPipelineError(
                f"Tier 3 checkpoint manifest is unreadable: {manifest_name}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise LexicalPipelineError(
                f"Tier 3 checkpoint manifest is not an object: {manifest_name}"
            )
        expected_identity = {
            "schema_version": _TIER3_CHECKPOINT_SCHEMA_VERSION,
            "experiment_run_id": experiment_run_id,
            "configuration_hash": configuration_hash,
            "preregistration_hash": preregistration_hash,
        }
        if any(payload.get(field) != value for field, value in expected_identity.items()):
            raise LexicalPipelineError(f"Tier 3 checkpoint identity differs: {manifest_name}")
        part_name = payload.get("path")
        declared_hash = payload.get("sha256")
        if (
            not isinstance(part_name, str)
            or Path(part_name).name != part_name
            or not isinstance(declared_hash, str)
        ):
            raise LexicalPipelineError(f"Tier 3 checkpoint metadata is invalid: {manifest_name}")
        part_path = tier3_root / part_name
        if (
            not part_path.is_file()
            or part_path.is_symlink()
            or part_path.resolve().parent != tier3_root.resolve()
        ):
            raise LexicalPipelineError(f"Tier 3 checkpoint part is unsafe: {part_name}")
        observed_hash = sha256_file(part_path)
        if observed_hash != declared_hash:
            raise LexicalPipelineError(f"Tier 3 checkpoint physical hash differs: {part_name}")
        relative_manifest = manifest_path.relative_to(resolved_staging).as_posix()
        relative_part = part_path.relative_to(resolved_staging).as_posix()
        manifest_hashes[relative_manifest] = sha256_file(manifest_path)
        part_hashes[relative_part] = observed_hash
        referenced_names.add(part_name)

    actual_nonmanifest_files = {
        path.name
        for path in actual_entries
        if path.is_file() and path.suffix != ".json" and not path.is_symlink()
    }
    unexpected_parts = sorted(actual_nonmanifest_files.difference(referenced_names))
    missing_parts = sorted(referenced_names.difference(actual_nonmanifest_files))
    unsafe_symlinks = sorted(path.name for path in actual_entries if path.is_symlink())
    if unexpected_parts or missing_parts or unsafe_symlinks:
        raise LexicalPipelineError(
            "Tier 3 checkpoint inventory is not governed: "
            f"unexpected={unexpected_parts[:5]}, missing={missing_parts[:5]}, "
            f"symlinks={unsafe_symlinks[:5]}"
        )
    return manifest_hashes, part_hashes


def _confirmed_tier3_checkpoint_reuse(
    *,
    before_manifests: Mapping[str, str],
    before_parts: Mapping[str, str],
    after_manifests: Mapping[str, str],
    after_parts: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return only pre-existing Tier 3 files unchanged after successful reuse."""

    changed_manifests = sorted(
        path for path, digest in before_manifests.items() if after_manifests.get(path) != digest
    )
    changed_parts = sorted(
        path for path, digest in before_parts.items() if after_parts.get(path) != digest
    )
    if changed_manifests or changed_parts:
        raise LexicalPipelineError(
            "Tier 3 checkpoint changed while confirming reuse: "
            f"manifests={changed_manifests[:5]}, parts={changed_parts[:5]}"
        )
    return dict(sorted(before_manifests.items())), dict(sorted(before_parts.items()))


def build_experiment_run_id(
    *,
    configuration_hash: str,
    preregistration_hash: str,
    anchors: AnchorVerification,
) -> str:
    """Derive the run ID only from frozen methodology and anchored inputs."""

    digest = _sha256_json(
        {
            "schema": 1,
            "configuration_hash": configuration_hash,
            "preregistration_hash": preregistration_hash,
            "corpus_identity": anchors.corpus_identity_digests,
            "corpus_content": anchors.corpus_content_digests,
            "corpus_analytical": anchors.corpus_analytical_digests,
            "oshb": anchors.oshb_logical_hashes,
            "passages": anchors.passage_logical_hashes,
            "benchmark": anchors.benchmark_logical_hashes,
            "tier1": anchors.tier1_sha256,
        }
    )
    return f"lexical-v1-{digest[:20]}"


def _time_stage(
    timings: dict[str, float],
    name: str,
    operation: object,
) -> object:
    start = time.perf_counter()
    if not callable(operation):
        raise TypeError("stage operation must be callable")
    result = operation()
    timings[name] = time.perf_counter() - start
    return result


def _book_genres() -> dict[str, str]:
    loaded = load_config(Path("config/benchmark.yaml"))
    if not isinstance(loaded, BenchmarkConfig):
        raise LexicalPipelineError("config/benchmark.yaml did not load as BenchmarkConfig")
    return dict(loaded.book_genres)


def _load_split_provenance(
    database_path: Path,
    sequences: Sequence[PassageLexicalSequence | str],
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    resource_check: _ResourceCheck | None = None,
    targeted_lookup: bool = False,
) -> dict[str, str]:
    """Load compact, actual Tier-3 split/leakage facts for ranked passages once."""

    passage_ids = sorted({item if isinstance(item, str) else item.passage_id for item in sequences})
    if not passage_ids:
        return {}
    if resource_check is not None:
        resource_check(
            "benchmark_split_provenance:before",
            estimated_additional_bytes=(duckdb_memory_limit_bytes + 768 * MEBIBYTE),
        )
    mapped_query = (
        """
        WITH requested AS (
          SELECT unnest(?) AS passage_id
        ),
        mapped AS (
          SELECT requested.passage_id,
                 r.relationship_id,
                 m.mapping_status
          FROM requested
          JOIN benchmark_endpoint_mappings m
            ON json_contains(
                 m.target_passage_ids_json,
                 to_json(requested.passage_id)
               )
          JOIN benchmark_endpoints e USING (endpoint_id)
          JOIN benchmark_relationships r USING (relationship_id)
          WHERE r.tier=3
            AND m.target_granularity='verse'
        )
        """
        if targeted_lookup
        else """
        WITH mapped AS (
          SELECT json_extract_string(j.value, '$') AS passage_id,
                 r.relationship_id,
                 m.mapping_status
          FROM benchmark_endpoint_mappings m
          JOIN benchmark_endpoints e USING (endpoint_id)
          JOIN benchmark_relationships r USING (relationship_id),
          LATERAL json_each(m.target_passage_ids_json) j
          WHERE r.tier=3
            AND m.target_granularity='verse'
            AND json_extract_string(j.value, '$') = ANY(?)
        )
        """
    )
    query = (
        mapped_query
        + """
        SELECT mapped.passage_id,
               s.benchmark_version,
               s.split_strategy,
               s.partition,
               s.eligibility_status,
               coalesce(s.exclusion_reason, '') AS exclusion_reason,
               mapped.mapping_status,
               count(DISTINCT mapped.relationship_id) AS relationship_count,
               count(DISTINCT s.leakage_group_id) AS leakage_group_count,
               list_sort(
                 list(DISTINCT s.leakage_group_id)
                   FILTER (WHERE s.leakage_group_id IS NOT NULL)
               ) AS leakage_group_ids,
               bool_and(s.leakage_group_id IS NOT NULL) AS leakage_membership_complete
        FROM mapped
        JOIN benchmark_split_assignments s USING (relationship_id)
        GROUP BY mapped.passage_id, s.benchmark_version, s.split_strategy,
                 s.partition, s.eligibility_status, exclusion_reason,
                 mapped.mapping_status
        ORDER BY mapped.passage_id, s.split_strategy, s.partition,
                 s.eligibility_status, mapped.mapping_status
    """
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            if targeted_lookup:
                connection.execute("SET max_temp_directory_size='512MiB'")
            cursor = connection.execute(query, [passage_ids])
            while rows := cursor.fetchmany(50_000):
                for (
                    passage_id,
                    benchmark_version,
                    split_strategy,
                    partition,
                    eligibility_status,
                    exclusion_reason,
                    mapping_status,
                    relationship_count,
                    leakage_group_count,
                    leakage_group_ids,
                    leakage_membership_complete,
                ) in rows:
                    grouped[str(passage_id)].append(
                        {
                            "benchmark_version": str(benchmark_version),
                            "split_strategy": str(split_strategy),
                            "partition": str(partition),
                            "eligibility_status": str(eligibility_status),
                            "exclusion_reason": str(exclusion_reason),
                            "mapping_status": str(mapping_status),
                            "relationship_count": int(relationship_count),
                            "leakage_group_count": int(leakage_group_count),
                            "leakage_group_ids": sorted(
                                str(group_id) for group_id in (leakage_group_ids or [])
                            ),
                            "leakage_membership_complete": bool(leakage_membership_complete),
                        }
                    )
    except (duckdb.Error, OSError) as exc:
        raise LexicalPipelineError(
            f"could not load anchored benchmark split provenance: {exc}"
        ) from exc
    output: dict[str, str] = {}
    for passage_id, assignments in sorted(grouped.items()):
        # DuckDB's grouped result can contain rows tied on the human-facing
        # ORDER BY fields.  The digest commits to every field, so impose a total
        # canonical order in Python before hashing or deriving summaries.
        assignments = sorted(assignments, key=_canonical_json)
        has_eligible = any(
            item["eligibility_status"] == "eligible"
            and item["partition"] != "excluded"
            and item["leakage_membership_complete"] is True
            for item in assignments
        )
        eligible_partitions: dict[str, list[str]] = {}
        for strategy in sorted({str(item["split_strategy"]) for item in assignments}):
            eligible_partitions[strategy] = sorted(
                {
                    str(item["partition"])
                    for item in assignments
                    if item["split_strategy"] == strategy
                    and item["eligibility_status"] == "eligible"
                    and item["partition"] != "excluded"
                }
            )
        leakage_group_ids = sorted(
            {
                str(group_id)
                for item in assignments
                for group_id in cast(list[str], item["leakage_group_ids"])
            }
        )
        output[passage_id] = _canonical_json(
            {
                "assignment_digest": _sha256_json(assignments),
                "benchmark_versions": sorted(
                    {str(item["benchmark_version"]) for item in assignments}
                ),
                "eligible_partitions": eligible_partitions,
                "leakage_membership_complete": all(
                    item["leakage_membership_complete"] is True for item in assignments
                ),
                # Directional rankings repeat this payload tens of millions of times.
                # Retain a count and canonical digest instead of the potentially large
                # identifier list.  ``assignment_digest`` still commits to every grouped
                # assignment fact returned above, and strict validation reproduces both
                # digests from the anchored benchmark database, so the compact summary is
                # traceable without duplicating every leakage-group identifier per rank.
                "leakage_group_count": len(leakage_group_ids),
                "leakage_group_ids_digest": _sha256_json(leakage_group_ids),
                "mapping_statuses": sorted({str(item["mapping_status"]) for item in assignments}),
                "status": (
                    "eligible_benchmark_assignment_present"
                    if has_eligible
                    else "no_eligible_benchmark_assignment"
                ),
            }
        )
    if resource_check is not None:
        resource_check("benchmark_split_provenance:after")
    return output


def _oshb_affected_verse_references(
    database_path: Path,
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
) -> dict[str, int]:
    """Return stable verse references and locus multiplicities from the anchored registry."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            rows = connection.execute(
                "SELECT canonical_book || ' ' || chapter::VARCHAR || ':' || verse::VARCHAR, "
                "count(*) FROM hebrew_kq_locus_registry GROUP BY 1 ORDER BY 1"
            ).fetchall()
    except (duckdb.Error, OSError) as exc:
        raise LexicalPipelineError(f"could not load OSHB affected verse references: {exc}") from exc
    references = {str(reference): int(count) for reference, count in rows}
    if not references or any(count < 1 for count in references.values()):
        raise LexicalPipelineError("OSHB affected-verse registry is empty or invalid")
    return references


def _sequence_reference_frame(
    sequences: Sequence[PassageLexicalSequence],
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for passage in sorted(sequences, key=lambda item: item.passage_id):
        if passage.granularity != "verse" or passage.start_reference != passage.end_reference:
            raise LexicalPipelineError(
                "sensitivity comparison requires single-reference verse passages"
            )
        rows.append(
            {
                "passage_id": passage.passage_id,
                "corpus": passage.corpus,
                "reference": passage.start_reference,
                "lemma_digest": sequence_digest(passage.values("lemma")),
                "english_digest": sequence_digest(passage.values("english_gloss")),
            }
        )
    frame = pl.DataFrame(
        rows,
        schema={
            "passage_id": pl.String,
            "corpus": pl.String,
            "reference": pl.String,
            "lemma_digest": pl.String,
            "english_digest": pl.String,
        },
        orient="row",
    )
    if frame.get_column("passage_id").n_unique() != frame.height:
        raise LexicalPipelineError("sensitivity sequence passage IDs are not unique")
    if frame.select("corpus", "reference").unique().height != frame.height:
        raise LexicalPipelineError(
            "sensitivity sequence references are not unique within a corpus scope"
        )
    return frame


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _iter_sensitivity_result_frames(
    *,
    ranking_root: Path,
    baseline_scope: str,
    comparison_scope: str,
    sensitivity_type: str,
    corpus_pairs: Sequence[str],
    baseline_profile: str,
    comparison_profile: str,
    baseline_reading: str,
    comparison_reading: str,
    baseline_sequences: Sequence[PassageLexicalSequence],
    comparison_sequences: Sequence[PassageLexicalSequence],
    baseline_representation_ids: Mapping[str, str],
    comparison_representation_ids: Mapping[str, str],
    affected_references: Mapping[str, int],
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    resource_guard: ProcessResourceGuard,
    spill_directory: Path,
    minimum_free_disk_bytes: int,
) -> Iterator[pl.DataFrame]:
    """Externally join profile/reading top-K rankings on stable verse references."""

    if set(corpus_pairs) != set(baseline_representation_ids) or set(corpus_pairs) != set(
        comparison_representation_ids
    ):
        raise LexicalPipelineError(
            f"{sensitivity_type} representation maps do not match governed corpus pairs"
        )
    if minimum_free_disk_bytes < 0:
        raise LexicalPipelineError("sensitivity minimum free disk cannot be negative")
    try:
        reference_frame_reservation = max(
            128 * MEBIBYTE,
            (len(baseline_sequences) + len(comparison_sequences)) * 4096
            + len(affected_references) * 256,
        )
        resource_guard.check(
            f"sensitivity:{sensitivity_type}:reference_frames:before",
            estimated_additional_bytes=reference_frame_reservation,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    baseline_passages = _sequence_reference_frame(baseline_sequences)
    comparison_passages = _sequence_reference_frame(comparison_sequences)
    representations = pl.DataFrame(
        [
            {
                "corpus_pair": pair,
                "baseline_representation_id": baseline_representation_ids[pair],
                "comparison_representation_id": comparison_representation_ids[pair],
            }
            for pair in corpus_pairs
        ],
        schema={
            "corpus_pair": pl.String,
            "baseline_representation_id": pl.String,
            "comparison_representation_id": pl.String,
        },
        orient="row",
    )
    affected = pl.DataFrame(
        [
            {"reference": reference, "locus_count": count}
            for reference, count in sorted(affected_references.items())
        ],
        schema={"reference": pl.String, "locus_count": pl.Int64},
        orient="row",
    )
    ranking_glob = (ranking_root / "part-*.parquet").as_posix().replace("'", "''")
    affected_filter = (
        "AND q.reference IN (SELECT reference FROM affected_references)"
        if affected_references
        else ""
    )
    try:
        duckdb_limit = resource_guard.bounded_duckdb_memory_bytes(
            f"sensitivity:{sensitivity_type}:join:before",
            preferred_bytes=_SENSITIVITY_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    query_template = """
        WITH rankings AS (
          SELECT * FROM read_parquet('{ranking_glob}', union_by_name=true)
          WHERE corpus_pair={corpus_pair}
            AND detector={detector}
        ),
        baseline AS (
          SELECT r.*, q.corpus AS query_corpus, q.reference AS query_reference,
                 t.corpus AS target_corpus, t.reference AS target_reference,
                 sha256(
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN q.english_digest ELSE q.lemma_digest END || ':' ||
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN t.english_digest ELSE t.lemma_digest END
                 ) AS pair_sequence_digest
          FROM rankings r
          JOIN baseline_passages q ON q.passage_id=r.query_passage_id
          JOIN baseline_passages t ON t.passage_id=r.target_passage_id
          JOIN representation_pairs p USING (corpus_pair)
          WHERE r.experiment_scope={baseline_scope}
            AND r.analysis_profile={baseline_profile}
            AND r.representation_id=p.baseline_representation_id
            AND substr(sha256(q.reference),1,1) IN ({query_reference_bucket})
            {affected_filter}
        ),
        comparison AS (
          SELECT r.*, q.corpus AS query_corpus, q.reference AS query_reference,
                 t.corpus AS target_corpus, t.reference AS target_reference,
                 sha256(
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN q.english_digest ELSE q.lemma_digest END || ':' ||
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN t.english_digest ELSE t.lemma_digest END
                 ) AS pair_sequence_digest
          FROM rankings r
          JOIN comparison_passages q ON q.passage_id=r.query_passage_id
          JOIN comparison_passages t ON t.passage_id=r.target_passage_id
          JOIN representation_pairs p USING (corpus_pair)
          WHERE r.experiment_scope={comparison_scope}
            AND r.analysis_profile={comparison_profile}
            AND r.representation_id=p.comparison_representation_id
            AND substr(sha256(q.reference),1,1) IN ({query_reference_bucket})
            {affected_filter}
        ),
        paired AS (
          SELECT coalesce(b.corpus_pair,c.corpus_pair) AS corpus_pair,
                 coalesce(b.detector,c.detector) AS detector,
                 coalesce(b.query_corpus,c.query_corpus) AS query_corpus,
                 coalesce(b.target_corpus,c.target_corpus) AS target_corpus,
                 coalesce(b.query_reference,c.query_reference) AS query_reference,
                 coalesce(b.target_reference,c.target_reference) AS target_reference,
                 b.query_passage_id AS baseline_query_passage_id,
                 c.query_passage_id AS comparison_query_passage_id,
                 b.target_passage_id AS baseline_target_passage_id,
                 c.target_passage_id AS comparison_target_passage_id,
                 b.raw_score AS baseline_score,
                 c.raw_score AS comparison_score,
                 b.rank AS baseline_rank,
                 c.rank AS comparison_rank,
                 b.pair_sequence_digest AS ranked_baseline_digest,
                 c.pair_sequence_digest AS ranked_comparison_digest
          FROM baseline b FULL OUTER JOIN comparison c
            ON b.corpus_pair=c.corpus_pair
           AND b.detector=c.detector
           AND b.query_corpus=c.query_corpus
           AND b.target_corpus=c.target_corpus
           AND b.query_reference=c.query_reference
           AND b.target_reference=c.target_reference
        ),
        resolved AS (
          SELECT paired.*, p.baseline_representation_id,
                 p.comparison_representation_id,
                 bq.passage_id AS resolved_baseline_query_id,
                 bt.passage_id AS resolved_baseline_target_id,
                 cq.passage_id AS resolved_comparison_query_id,
                 ct.passage_id AS resolved_comparison_target_id,
                 coalesce(
                   ranked_baseline_digest,
                   sha256(
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN bq.english_digest ELSE bq.lemma_digest END || ':' ||
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN bt.english_digest ELSE bt.lemma_digest END
                   ),
                   sha256('')
                 ) AS baseline_sequence_digest,
                 coalesce(
                   ranked_comparison_digest,
                   sha256(
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN cq.english_digest ELSE cq.lemma_digest END || ':' ||
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN ct.english_digest ELSE ct.lemma_digest END
                   ),
                   sha256('')
                 ) AS comparison_sequence_digest,
                 coalesce(a.locus_count,0)::BIGINT AS affected_locus_count
          FROM paired
          JOIN representation_pairs p USING (corpus_pair)
          LEFT JOIN baseline_passages bq
            ON bq.corpus=paired.query_corpus AND bq.reference=paired.query_reference
          LEFT JOIN baseline_passages bt
            ON bt.corpus=paired.target_corpus AND bt.reference=paired.target_reference
          LEFT JOIN comparison_passages cq
            ON cq.corpus=paired.query_corpus AND cq.reference=paired.query_reference
          LEFT JOIN comparison_passages ct
            ON ct.corpus=paired.target_corpus AND ct.reference=paired.target_reference
          LEFT JOIN affected_references a ON a.reference=paired.query_reference
        ),
        measured AS (
          SELECT *,
                 count(baseline_rank) OVER comparison_window AS baseline_k,
                 count(comparison_rank) OVER comparison_window AS comparison_k,
                 count(*) FILTER (
                   WHERE baseline_rank IS NOT NULL AND comparison_rank IS NOT NULL
                 ) OVER comparison_window AS shared_k
          FROM resolved
          WINDOW comparison_window AS (
            PARTITION BY corpus_pair, detector, query_corpus, target_corpus, query_reference
          )
        )
        SELECT 'LXS_' || sha256(concat_ws(chr(31),
                 {sensitivity_type}, corpus_pair, detector,
                 query_corpus || '_to_' || target_corpus,
                 query_reference, target_reference)) AS sensitivity_id,
               {experiment_run_id} AS experiment_run_id,
               {sensitivity_type} AS sensitivity_type,
               corpus_pair,
               detector,
               query_corpus || '_to_' || target_corpus AS direction,
               {baseline_profile} AS baseline_profile,
               {comparison_profile} AS comparison_profile,
               CASE WHEN corpus_pair='gnt_gnt' THEN 'source'
                    ELSE {baseline_reading} END AS baseline_reading,
               CASE WHEN corpus_pair='gnt_gnt' THEN 'source'
                    ELSE {comparison_reading} END AS comparison_reading,
               query_reference,
               target_reference,
               coalesce(baseline_query_passage_id,resolved_baseline_query_id)
                 AS baseline_query_passage_id,
               coalesce(comparison_query_passage_id,resolved_comparison_query_id)
                 AS comparison_query_passage_id,
               coalesce(baseline_target_passage_id,resolved_baseline_target_id)
                 AS baseline_target_passage_id,
               coalesce(comparison_target_passage_id,resolved_comparison_target_id)
                 AS comparison_target_passage_id,
               baseline_representation_id,
               comparison_representation_id,
               baseline_score,
               comparison_score,
               CASE WHEN baseline_score IS NOT NULL AND comparison_score IS NOT NULL
                    THEN comparison_score-baseline_score END AS score_delta,
               baseline_rank,
               comparison_rank,
               CASE WHEN baseline_rank IS NOT NULL AND comparison_rank IS NOT NULL
                    THEN comparison_rank-baseline_rank END::BIGINT AS rank_delta,
               CASE WHEN greatest(baseline_k,comparison_k)>0
                    THEN shared_k::DOUBLE/greatest(baseline_k,comparison_k) END
                 AS top_k_overlap,
               affected_locus_count,
               CASE
                 WHEN resolved_baseline_query_id IS NULL THEN 'query_missing_from_baseline_scope'
                 WHEN resolved_baseline_target_id IS NULL THEN 'target_missing_from_baseline_scope'
                 WHEN resolved_comparison_query_id IS NULL
                   THEN 'query_missing_from_comparison_scope'
                 WHEN resolved_comparison_target_id IS NULL
                   THEN 'target_missing_from_comparison_scope'
               END AS excluded_reason,
               baseline_sequence_digest,
               comparison_sequence_digest,
               {configuration_hash} AS config_hash,
               {preregistration_hash} AS preregistration_hash
        FROM measured
        ORDER BY direction, sensitivity_id
    """
    try:
        output_part = 0
        detectors = (*sorted(DETECTOR_FAMILIES), "rrf_composite")
        for corpus_pair in sorted(corpus_pairs):
            for detector in detectors:
                for bucket_index, bucket in enumerate(_SENSITIVITY_QUERY_REFERENCE_BUCKETS):
                    stage = (
                        f"sensitivity:{sensitivity_type}:{corpus_pair}:{detector}:"
                        f"bucket-{bucket_index}"
                    )
                    resource_guard.check(f"{stage}:before")
                    free_bytes = shutil.disk_usage(spill_directory.parent).free
                    spill_headroom = (
                        free_bytes - minimum_free_disk_bytes - _SENSITIVITY_SPILL_SAFETY_BYTES
                    )
                    if spill_headroom < _SENSITIVITY_MINIMUM_SPILL_BYTES:
                        raise LexicalPipelineError(
                            "insufficient disk headroom for bounded sensitivity spill at "
                            f"{sensitivity_type}/{corpus_pair}/{detector}/"
                            f"bucket-{bucket_index}: free={free_bytes}, "
                            f"minimum={minimum_free_disk_bytes}, "
                            f"safety={_SENSITIVITY_SPILL_SAFETY_BYTES}, "
                            f"required_spill={_SENSITIVITY_MINIMUM_SPILL_BYTES}"
                        )
                    spill_limit = min(_SENSITIVITY_MAX_SPILL_BYTES, spill_headroom)
                    spill_limit = (spill_limit // MEBIBYTE) * MEBIBYTE
                    query = query_template.format(
                        ranking_glob=ranking_glob,
                        corpus_pair=_sql_string(corpus_pair),
                        detector=_sql_string(detector),
                        baseline_scope=_sql_string(baseline_scope),
                        baseline_profile=_sql_string(baseline_profile),
                        comparison_scope=_sql_string(comparison_scope),
                        comparison_profile=_sql_string(comparison_profile),
                        query_reference_bucket=",".join(_sql_string(value) for value in bucket),
                        affected_filter=affected_filter,
                        sensitivity_type=_sql_string(sensitivity_type),
                        experiment_run_id=_sql_string(experiment_run_id),
                        baseline_reading=_sql_string(baseline_reading),
                        comparison_reading=_sql_string(comparison_reading),
                        configuration_hash=_sql_string(configuration_hash),
                        preregistration_hash=_sql_string(preregistration_hash),
                    )
                    with _bounded_duckdb_connection(
                        memory_limit_bytes=duckdb_limit,
                        temp_directory=spill_directory,
                    ) as connection:
                        connection.execute(
                            f"SET max_temp_directory_size='{spill_limit // MEBIBYTE}MiB'"
                        )
                        connection.register("baseline_passages", baseline_passages.to_arrow())
                        connection.register("comparison_passages", comparison_passages.to_arrow())
                        connection.register("representation_pairs", representations.to_arrow())
                        connection.register("affected_references", affected.to_arrow())
                        reader = connection.execute(query).to_arrow_reader(50_000)
                        for batch in reader:
                            frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).cast(
                                SENSITIVITY_RESULTS_SCHEMA, strict=True
                            )
                            resource_guard.check(
                                f"sensitivity:{sensitivity_type}:part-{output_part}"
                            )
                            output_part += 1
                            yield frame
                    resource_guard.check(f"{stage}:after")
    except (duckdb.Error, OSError, pl.exceptions.PolarsError, LexicalResourceError) as exc:
        raise LexicalPipelineError(
            f"could not materialize {sensitivity_type} comparison: {exc}"
        ) from exc


def _derived_values(values: Sequence[str], family: FeatureFamily) -> tuple[str, ...]:
    if family in {"lemma_ngram", "root_ngram"}:
        output: list[str] = []
        for size in (2, 3):
            output.extend(
                "\u241f".join(item)
                for item in zip(*(values[i:] for i in range(size)), strict=False)
            )
        return tuple(output)
    if family in {"lemma_skipgram", "root_skipgram"}:
        return tuple(
            f"{values[first]}\u241f*\u241f{values[second]}"
            for first in range(len(values))
            for second in range(first + 2, min(len(values), first + 4))
        )
    raise LexicalPipelineError(f"unsupported derived family: {family}")


def _derived_vocabulary(
    sequences: Sequence[PassageLexicalSequence],
    *,
    family: FeatureFamily,
    namespace: LanguageNamespace,
    config: LexicalConfig,
    book_genres: Mapping[str, str],
) -> pl.DataFrame:
    source_family = "lemma" if family.startswith("lemma") else "root"
    corpus_frequency: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    books: dict[str, set[str]] = defaultdict(set)
    genres: dict[str, set[str]] = defaultdict(set)
    for passage in sequences:
        derived = _derived_values(passage.values(source_family), family)
        corpus_frequency.update(derived)
        for value in set(derived):
            document_frequency[value] += 1
            books[value].add(passage.book)
            genres[value].add(book_genres.get(passage.book, "unassigned"))
    minimum = config.phrases.minimum_corpus_count
    document_count = len(sequences)
    rows: list[dict[str, object]] = []
    for value in sorted(key for key, count in corpus_frequency.items() if count >= minimum):
        order = 2 if family.endswith("skipgram") else value.count("\u241f") + 1
        identity = build_feature_identity(
            FeatureIdentityPayload(
                feature_family=family,
                language_namespace=namespace,
                feature_value=value,
                feature_order=order,
            )
        )
        df = document_frequency[value]
        ratio = df / document_count if document_count else 0.0
        rows.append(
            {
                "feature_id": identity.identifier,
                "lexical_schema_version": 1,
                "feature_family": family,
                "language_namespace": namespace,
                "feature_value": value,
                "feature_order": order,
                "corpus_frequency": corpus_frequency[value],
                "document_frequency": df,
                "inverse_document_frequency": (math.log((1.0 + document_count) / (1.0 + df)) + 1.0),
                "book_frequency": len(books[value]),
                "genre_frequency": len(genres[value]),
                "is_rare": (
                    corpus_frequency[value] <= config.rare_evidence.maximum_corpus_frequency
                ),
                "is_high_frequency": (
                    ratio >= config.feature_frequency_thresholds.high_document_frequency_ratio
                ),
                "is_formulaic": (
                    ratio >= config.feature_frequency_thresholds.formulaic_document_frequency_ratio
                    and corpus_frequency[value]
                    >= config.feature_frequency_thresholds.formulaic_minimum_corpus_count
                ),
                "contains_english_derived_content": False,
                "normalization_method": "source_sequence_derived_no_cross_boundary-v1",
                "notes": "minimum_corpus_count=2; positions reproduce from source sequence",
            }
        )
    return pl.DataFrame(rows, schema=FEATURE_VOCABULARY_SCHEMA, orient="row")


def build_all_feature_vocabulary(
    hebrew: Sequence[PassageLexicalSequence],
    greek: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
    book_genres: Mapping[str, str],
) -> pl.DataFrame:
    """Build every governed source, structural, phrase, and English feature family."""

    frames: list[pl.DataFrame] = []
    for sequences, namespace in ((hebrew, "hb"), (greek, "gk")):
        for family in (
            "lemma",
            "root",
            "normalized_surface",
            "part_of_speech",
            "morphology",
        ):
            frames.append(
                build_feature_vocabulary(
                    sequences,
                    family=family,
                    namespace=cast(LanguageNamespace, namespace),
                    rare_maximum_corpus_frequency=(config.rare_evidence.maximum_corpus_frequency),
                    high_frequency_document_ratio=(
                        config.feature_frequency_thresholds.high_document_frequency_ratio
                    ),
                    formulaic_document_ratio=(
                        config.feature_frequency_thresholds.formulaic_document_frequency_ratio
                    ),
                    formulaic_minimum_corpus_count=(
                        config.feature_frequency_thresholds.formulaic_minimum_corpus_count
                    ),
                    book_genres=dict(book_genres),
                )
            )
        for family in (
            "lemma_ngram",
            "root_ngram",
            "lemma_skipgram",
            "root_skipgram",
        ):
            frames.append(
                _derived_vocabulary(
                    sequences,
                    family=cast(FeatureFamily, family),
                    namespace=cast(LanguageNamespace, namespace),
                    config=config,
                    book_genres=book_genres,
                )
            )
    frames.append(
        build_feature_vocabulary(
            [*hebrew, *greek],
            family="english_gloss",
            namespace="en",
            rare_maximum_corpus_frequency=config.rare_evidence.maximum_corpus_frequency,
            high_frequency_document_ratio=(
                config.feature_frequency_thresholds.high_document_frequency_ratio
            ),
            formulaic_document_ratio=(
                config.feature_frequency_thresholds.formulaic_document_frequency_ratio
            ),
            formulaic_minimum_corpus_count=(
                config.feature_frequency_thresholds.formulaic_minimum_corpus_count
            ),
            book_genres=dict(book_genres),
        )
    )
    return combine_feature_vocabularies(frames)


def _representation_id(
    *,
    config: LexicalConfig,
    family: FeatureFamily,
    corpus_scope: tuple[str, ...],
    reading: str,
    analysis_profile: str,
    granularity: str,
    configuration_hash: str,
) -> str:
    eligibility_hash = _sha256_json(config.token_eligibility.model_dump(mode="json"))
    normalization_hash = hashlib.sha256(Path("config/normalization.yaml").read_bytes()).hexdigest()
    return build_representation_identity(
        RepresentationIdentityPayload(
            representation_kind=(
                "english_derived" if family == "english_gloss" else "original_language"
            ),
            corpus_scope=cast(tuple[object, ...], corpus_scope),  # type: ignore[arg-type]
            analysis_profile=cast(AnalysisProfile, analysis_profile),
            analysis_reading=reading,
            granularity=cast(Granularity, granularity),
            feature_families=(family,),
            token_eligibility_policy_sha256=eligibility_hash,
            frequency_scope=f"language_and_representation:{configuration_hash}",
            normalization_config_sha256=normalization_hash,
        )
    ).identifier


def _primary_index_definitions(
    hebrew: Sequence[PassageLexicalSequence],
    greek: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    profile = config.primary_scope.analysis_profile
    granularity = config.primary_scope.granularity
    qere = config.primary_scope.hebrew_reading
    source = config.primary_scope.greek_reading
    return (
        _IndexDefinition("hb_hb", hebrew, "lemma", "hb", ("hebrew",), qere, profile, granularity),
        _IndexDefinition("gnt_gnt", greek, "lemma", "gk", ("greek",), source, profile, granularity),
        _IndexDefinition(
            "hb_gnt_english_bridge",
            [*hebrew, *greek],
            "english_gloss",
            "en",
            ("hebrew", "greek"),
            f"{qere}+{source}",
            profile,
            granularity,
        ),
        _IndexDefinition(
            "hb_root", hebrew, "root", "hb", ("hebrew",), qere, profile, granularity, False
        ),
        _IndexDefinition(
            "gnt_root", greek, "root", "gk", ("greek",), source, profile, granularity, False
        ),
        _IndexDefinition(
            "hb_surface",
            hebrew,
            "surface",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_surface",
            greek,
            "surface",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "hb_pos",
            hebrew,
            "part_of_speech",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_pos",
            greek,
            "part_of_speech",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "hb_morph",
            hebrew,
            "morphology",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_morph",
            greek,
            "morphology",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
    )


def _critical_index_definitions(
    *,
    critical_hebrew: Sequence[PassageLexicalSequence],
    critical_greek: Sequence[PassageLexicalSequence],
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    critical = config.sensitivity_scopes.critical_core_greek
    return (
        _IndexDefinition(
            "critical_gnt_gnt",
            critical_greek,
            "lemma",
            "gk",
            ("greek",),
            critical.greek_reading,
            critical.analysis_profile,
            critical.granularity,
        ),
        _IndexDefinition(
            "critical_hb_gnt_english_bridge",
            [*critical_hebrew, *critical_greek],
            "english_gloss",
            "en",
            ("hebrew", "greek"),
            f"{critical.hebrew_reading}+{critical.greek_reading}",
            critical.analysis_profile,
            critical.granularity,
        ),
    )


def _ketiv_index_definitions(
    ketiv_hebrew: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    reading = config.sensitivity_scopes.hebrew_qere_ketiv
    return (
        _IndexDefinition(
            "ketiv_hb_hb",
            ketiv_hebrew,
            "lemma",
            "hb",
            ("hebrew",),
            reading.comparison_reading,
            reading.analysis_profile,
            reading.granularity,
        ),
    )


def _build_indexes(
    *,
    writer: LexicalArtifactWriter,
    definitions: Sequence[_IndexDefinition],
    config: LexicalConfig,
    configuration_hash: str,
    experiment_run_id: str,
    resource_check: _ResourceCheck | None = None,
) -> tuple[dict[str, SparseLexicalIndex], pl.DataFrame, dict[str, dict[str, object]]]:
    indexes: dict[str, SparseLexicalIndex] = {}
    metadata_rows: list[dict[str, object]] = []
    summaries: dict[str, dict[str, object]] = {}
    family_identity: dict[str, FeatureFamily] = {
        "lemma": "lemma",
        "root": "root",
        "surface": "normalized_surface",
        "part_of_speech": "part_of_speech",
        "morphology": "morphology",
        "english_gloss": "english_gloss",
    }
    for definition in definitions:
        identity_family = family_identity[definition.family]
        if resource_check is not None:
            resource_check(
                f"sparse_index:{definition.key}:before",
                estimated_additional_bytes=_sparse_index_reservation_bytes(definition),
            )
        representation_id = _representation_id(
            config=config,
            family=identity_family,
            corpus_scope=definition.corpus_scope,
            reading=definition.reading,
            analysis_profile=definition.analysis_profile,
            granularity=definition.granularity,
            configuration_hash=configuration_hash,
        )
        index = build_sparse_index(
            definition.sequences,
            representation_id=representation_id,
            family=definition.family,
            namespace=definition.namespace,
            sublinear_tf=config.tfidf.sublinear_tf,
            smooth_idf=config.tfidf.smooth_idf,
            l2_normalize=config.tfidf.norm == "l2",
        )
        files = persist_sparse_index(index, writer.staging_dir / "indexes" / representation_id)
        physical_hash = sparse_index_physical_hash(files.root)
        index_id = "LXI_" + _sha256_json(
            {"run": experiment_run_id, "representation": representation_id}
        )
        metadata_rows.append(
            {
                "index_id": index_id,
                "experiment_run_id": experiment_run_id,
                "representation_id": representation_id,
                "corpus_scope": "+".join(definition.corpus_scope),
                "profile": definition.analysis_profile,
                "reading": definition.reading,
                "granularity": definition.granularity,
                "feature_family": identity_family,
                "matrix_shape_json": _canonical_json(list(index.counts.shape)),
                "nonzero_count": index.counts.nnz,
                "vocabulary_size": len(index.vocabulary),
                "document_count": len(index.passage_ids),
                "index_config_hash": configuration_hash,
                "logical_matrix_hash": index.logical_hash,
                "physical_file_hash": physical_hash,
                "dtype": "float64",
                "storage_format": "canonical-npy-csr-v1",
                "notes": (
                    "production root annotations unavailable; empty governed interface"
                    if definition.family == "root" and not index.vocabulary
                    else "deterministic CSR; no dense passage-by-feature matrix persisted"
                ),
            }
        )
        summaries[definition.key] = {
            "index_id": index_id,
            "representation_id": representation_id,
            "shape": list(index.counts.shape),
            "nonzero_count": int(index.counts.nnz),
            "logical_hash": index.logical_hash,
            "physical_hash": physical_hash,
        }
        if definition.retain_for_retrieval:
            indexes[definition.key] = index
        if resource_check is not None:
            resource_check(f"sparse_index:{definition.key}:after")
    return (
        indexes,
        pl.DataFrame(metadata_rows, schema=LEXICAL_INDEX_METADATA_SCHEMA, orient="row"),
        summaries,
    )


def _merge_updates(
    merged: dict[str, CandidateAggregate], updates: Iterable[CandidateAggregate]
) -> None:
    for update in updates:
        current = merged.get(update.candidate_pair_id)
        if current is None:
            current = CandidateAggregate(
                candidate_pair_id=update.candidate_pair_id,
                canonical_unordered_pair_id=update.canonical_unordered_pair_id,
                passage_a_id=update.passage_a_id,
                passage_b_id=update.passage_b_id,
                corpus_pair=update.corpus_pair,
                analysis_profile=update.analysis_profile,
                granularity=update.granularity,
            )
            merged[update.candidate_pair_id] = current
        for direction in update.directions.values():
            current.add_direction(direction)


def _run_retrieval(
    *,
    writer: LexicalArtifactWriter,
    indexes: Mapping[str, SparseLexicalIndex],
    sequences_by_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    experiment_run_id: str,
    configuration_hash: str,
    config: LexicalConfig,
    experiment_scope: str,
    corpus_pairs: Sequence[str],
    split_provenance_by_passage_id: Mapping[str, str],
    query_reference_filter: frozenset[str] | None = None,
    collect_candidates: bool = True,
    ranking_part_start: int = 0,
    resource_check: _ResourceCheck | None = None,
    candidate_checkpoint: _CandidateCheckpoint | None = None,
) -> _RetrievalScopeResult:
    candidates: dict[str, CandidateAggregate] = {}
    ranking_count = 0
    ranking_part = ranking_part_start
    for corpus_pair in corpus_pairs:
        index = indexes[corpus_pair]
        sequences = sorted(sequences_by_pair[corpus_pair], key=lambda item: item.passage_id)
        corpus_indices: dict[str, list[int]] = defaultdict(list)
        for position, passage in enumerate(sequences):
            corpus_indices[passage.corpus].append(position)
        directions: tuple[tuple[Sequence[int], Sequence[int]], ...]
        if corpus_pair == "hb_gnt_english_bridge":
            directions = (
                (corpus_indices["hebrew"], corpus_indices["greek"]),
                (corpus_indices["greek"], corpus_indices["hebrew"]),
            )
        else:
            all_indices = tuple(range(len(sequences)))
            selected_query_indices = (
                tuple(
                    index
                    for index, passage in enumerate(sequences)
                    if passage.start_reference in query_reference_filter
                    and passage.end_reference in query_reference_filter
                )
                if query_reference_filter is not None
                else all_indices
            )
            directions = ((selected_query_indices, all_indices),)
        if any(
            not query_indices or not target_indices for query_indices, target_indices in directions
        ):
            raise LexicalPipelineError(
                f"retrieval scope {experiment_scope}/{corpus_pair} has an empty query or target set"
            )
        maximum_df = max(
            1,
            math.floor(
                len(sequences)
                * config.feature_frequency_thresholds.proposal_maximum_document_frequency_ratio
            ),
        )
        for direction_query_indices, direction_target_indices in directions:
            if resource_check is not None:
                resource_check(
                    f"retrieval:{experiment_scope}:{corpus_pair}:direction:before",
                    estimated_additional_bytes=_retrieval_reservation_bytes(config),
                )
            for batch in iter_retrieval_batches(
                index,
                sequences,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                experiment_scope=experiment_scope,
                corpus_pair=cast(CorpusPair, corpus_pair),
                query_indices=direction_query_indices,
                target_indices=direction_target_indices,
                candidate_union_k=config.retrieval.candidate_union_k,
                persisted_top_k=config.retrieval.persisted_top_k,
                persisted_candidate_pool_k=config.retrieval.persisted_candidate_pool_k,
                expensive_sequence_rerank_k=config.retrieval.expensive_sequence_rerank_k,
                block_size=config.resource_limits.block_passage_count,
                maximum_proposal_document_frequency=maximum_df,
                score_quantization_decimals=config.statistics.score_quantization_decimals,
                bm25_k1=config.bm25.k1,
                bm25_b=config.bm25.b,
                rare_threshold=config.rare_evidence.maximum_corpus_frequency,
                rrf_k=config.composite.rrf_k,
                gap_penalty=config.sequence.gap_penalty,
                mismatch_score=config.sequence.mismatch_penalty,
                nearby_context_distance=config.penalties.nearby_verse_distance,
                phrase_ngram_sizes=config.phrases.lemma_ngram_sizes,
                phrase_minimum_corpus_count=config.phrases.minimum_corpus_count,
                phrase_pmi_cap=config.phrases.pmi_cap,
                skipgram_max_gap=config.skipgrams.maximum_gap,
                skipgram_minimum_corpus_count=config.skipgrams.minimum_corpus_count,
                split_provenance_by_passage_id={
                    passage_id: split_provenance_by_passage_id[passage_id]
                    for passage_id in index.passage_ids
                    if passage_id in split_provenance_by_passage_id
                },
                resource_check=resource_check,
            ):
                writer.write_frame("directional_rankings", batch.rankings, part=ranking_part)
                ranking_part += 1
                ranking_count += batch.rankings.height
                if collect_candidates:
                    if resource_check is not None:
                        resource_check(
                            f"retrieval:{experiment_scope}:{corpus_pair}:candidate-merge",
                            estimated_additional_bytes=max(
                                16 * MEBIBYTE, len(batch.candidates) * 4096
                            ),
                        )
                    _merge_updates(candidates, batch.candidates)
                    if candidate_checkpoint is not None:
                        candidate_checkpoint.write_updates(batch.candidates)
                if resource_check is not None:
                    resource_check(
                        f"retrieval:{experiment_scope}:{corpus_pair}:part-{ranking_part - 1}"
                    )
                del batch
    return _RetrievalScopeResult(
        candidates=candidates,
        ranking_count=ranking_count,
        next_ranking_part=ranking_part,
    )


def _iter_ranked_review_queue_frames(
    spool_directory: Path,
    *,
    expected_count: int,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    resource_check: _ResourceCheck | None = None,
) -> Iterator[pl.DataFrame]:
    """Globally rank disk-spooled eligible rows without retaining the queue in Python."""

    if expected_count < 0:
        raise LexicalPipelineError("review-queue expected count cannot be negative")
    if expected_count == 0:
        yield pl.DataFrame(schema=CANDIDATE_REVIEW_QUEUE_SCHEMA)
        return
    paths = sorted(spool_directory.glob("part-*.parquet"))
    if not paths:
        raise LexicalPipelineError("review-queue spool is empty despite eligible candidates")
    glob = (spool_directory / "part-*.parquet").as_posix().replace("'", "''")
    payload_columns = tuple(CANDIDATE_REVIEW_QUEUE_SCHEMA.names()[1:])
    selected_columns = ",".join(f'"{column}"' for column in payload_columns)
    if resource_check is not None:
        resource_check(
            "candidate_review_queue:sort:before",
            estimated_additional_bytes=duckdb_memory_limit_bytes + 64 * MEBIBYTE,
        )
    try:
        with _bounded_duckdb_connection(
            memory_limit_bytes=duckdb_memory_limit_bytes,
            temp_directory=duckdb_temp_directory,
        ) as connection:
            facts = connection.execute(
                "SELECT count(*),count(DISTINCT candidate_pair_id),"
                "count_if(NOT review_eligible),"
                "count_if(known_link_status <> "
                "'not_represented_in_openbible_snapshot'),"
                "count_if(contains_english_derived_evidence AND "
                "NOT english_ablation_survives) "
                f"FROM read_parquet('{glob}', union_by_name=true)"
            ).fetchone()
            if facts is None or tuple(int(value) for value in facts) != (
                expected_count,
                expected_count,
                0,
                0,
                0,
            ):
                raise LexicalPipelineError(
                    f"review-queue spool failed identity or eligibility checks: {facts}"
                )
            cursor = connection.execute(
                "SELECT CAST(row_number() OVER (ORDER BY rrf_score DESC,"
                "candidate_pair_id) AS BIGINT) AS queue_rank,"
                f"{selected_columns} FROM read_parquet('{glob}', union_by_name=true) "
                "ORDER BY queue_rank"
            )
            observed = 0
            for batch_number, batch in enumerate(
                cursor.to_arrow_reader(_REVIEW_QUEUE_READ_BATCH_SIZE), start=1
            ):
                if resource_check is not None:
                    resource_check(
                        f"candidate_review_queue:sort:batch-{batch_number}",
                        estimated_additional_bytes=64 * MEBIBYTE,
                    )
                frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).select(
                    CANDIDATE_REVIEW_QUEUE_SCHEMA.names()
                )
                frame = frame.cast(CANDIDATE_REVIEW_QUEUE_SCHEMA)
                observed += frame.height
                yield frame
            if observed != expected_count:
                raise LexicalPipelineError(
                    "review-queue sorted row count differs from its spool: "
                    f"expected={expected_count}, observed={observed}"
                )
    except (duckdb.Error, OSError, pl.exceptions.PolarsError, LexicalResourceError) as exc:
        raise LexicalPipelineError(f"could not rank the review-queue spool: {exc}") from exc


def _prepare_candidate_review_queue_spool(
    staging_dir: Path,
    *,
    resumed: bool,
) -> Path:
    """Create a fresh private queue spool, discarding only a verified empty resume remnant."""

    spool = staging_dir / _CANDIDATE_REVIEW_QUEUE_SPOOL_DIRECTORY
    if spool.is_symlink():
        raise LexicalPipelineError("candidate review-queue spool cannot be a symlink")
    if spool.exists():
        if not resumed:
            raise LexicalPipelineError("candidate review-queue spool already exists")
        if not spool.is_dir() or spool.resolve().parent != staging_dir.resolve():
            raise LexicalPipelineError("resumed candidate review-queue spool is not governed")
        residual = sorted(path.name for path in spool.iterdir())
        if residual:
            raise LexicalPipelineError(
                f"refusing to discard nonempty resumed candidate review-queue spool: {residual[:5]}"
            )
        spool.rmdir()
    spool.mkdir()
    return spool


def _issue_frame(
    experiment_run_id: str,
    *,
    scientific_gate_status: str,
    uncalibrated_corpus_pairs: Sequence[str],
    sensitivity_counts: Mapping[str, int],
) -> pl.DataFrame:
    facts: list[tuple[str, str]] = [
        (
            "root_coverage_unavailable",
            "Production Hebrew and Greek lexical-root coverage is zero; root interfaces are "
            "fixture-tested and no roots were fabricated.",
        ),
        (
            "null_scope_candidate_union_sample",
            "Null calibration is scoped to the frozen deterministic candidate-union sample; "
            "no global all-pairs FDR claim is made.",
        ),
        (
            "tier1_empty",
            "Tier 1 remains exactly zero rows; no high-confidence quotation recovery claim "
            "was tested.",
        ),
        (
            "bounded_nonprimary_scope",
            "Critical-core and Qere/Ketiv sensitivity rankings were evaluated without "
            "repeating primary null simulations; non-verse granularities remain bounded "
            "smoke-test interfaces only.",
        ),
        (
            "sensitivity_results_materialized",
            "Required reproducible comparison rows were materialized: "
            + ", ".join(f"{name}={count}" for name, count in sorted(sensitivity_counts.items()))
            + ".",
        ),
    ]
    if scientific_gate_status != "passed":
        facts.append(
            (
                "scientific_gate_not_complete",
                "The frozen Tier 3 scientific recovery gate did not pass; the result is "
                "preserved and Milestone 7 remains scientifically incomplete.",
            )
        )
    if uncalibrated_corpus_pairs:
        facts.append(
            (
                "null_threshold_not_selected",
                "No preregistered RRF threshold met both-family empirical-FDR policy for: "
                + ", ".join(sorted(uncalibrated_corpus_pairs))
                + ". Thresholds were not weakened.",
            )
        )
    rows = [
        {
            "issue_id": f"LI_{_sha256_json({'code': code, 'run': experiment_run_id})}",
            "severity": "informational",
            "code": code,
            "message": message,
            "artifact": "lexical_metadata",
            "record_id": experiment_run_id,
            "experiment_run_id": experiment_run_id,
            "details_json": "{}",
        }
        for code, message in facts
    ]
    return pl.DataFrame(rows, schema=LEXICAL_ISSUES_SCHEMA, orient="row")


@dataclass(frozen=True, slots=True)
class _ResumeArtifactInventory:
    ranking_rows_by_scope: dict[str, int]
    ranking_parts_by_scope: dict[str, int]
    sensitivity_rows_by_type: dict[str, int]
    sensitivity_parts_by_type: dict[str, int]

    @property
    def ranking_count(self) -> int:
        return sum(self.ranking_rows_by_scope.values())


def _resume_artifact_inventory(
    staging_dir: Path,
    *,
    experiment_run_id: str,
) -> _ResumeArtifactInventory:
    ranking_rows: Counter[str] = Counter()
    ranking_parts: Counter[str] = Counter()
    observed_scope_order: list[str] = []
    ranking_paths = sorted((staging_dir / "directional_rankings").glob("part-*.parquet"))
    if not ranking_paths:
        raise LexicalPipelineError("resume staging has no directional rankings")
    for part, path in enumerate(ranking_paths):
        if path.name != f"part-{part:05d}.parquet":
            raise LexicalPipelineError("resume ranking parts are not contiguous")
        try:
            frame = pl.read_parquet(
                path,
                columns=["experiment_run_id", "experiment_scope"],
                rechunk=False,
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalPipelineError(
                f"could not inventory resume ranking leaf {path.name}: {exc}"
            ) from exc
        identities = frame.select("experiment_run_id", "experiment_scope").unique()
        if identities.height != 1:
            raise LexicalPipelineError(
                f"resume ranking leaf mixes run or scope identities: {path.name}"
            )
        run_id, scope = identities.row(0)
        if run_id != experiment_run_id:
            raise LexicalPipelineError(
                f"resume ranking leaf belongs to a different run: {path.name}"
            )
        scope_text = str(scope)
        ranking_rows[scope_text] += frame.height
        ranking_parts[scope_text] += 1
        if not observed_scope_order or observed_scope_order[-1] != scope_text:
            observed_scope_order.append(scope_text)
    expected_scopes = [
        "primary",
        "critical_core_greek_sensitivity",
        "hebrew_qere_ketiv_sensitivity",
    ]
    if observed_scope_order != expected_scopes:
        raise LexicalPipelineError(
            f"resume ranking scope order is incomplete or invalid: observed={observed_scope_order}"
        )

    sensitivity_rows: Counter[str] = Counter()
    sensitivity_parts: Counter[str] = Counter()
    observed_type_order: list[str] = []
    sensitivity_paths = sorted((staging_dir / "sensitivity_results").glob("part-*.parquet"))
    if not sensitivity_paths:
        raise LexicalPipelineError("resume staging has no sensitivity results")
    for part, path in enumerate(sensitivity_paths):
        if path.name != f"part-{part:05d}.parquet":
            raise LexicalPipelineError("resume sensitivity parts are not contiguous")
        try:
            frame = pl.read_parquet(
                path,
                columns=["experiment_run_id", "sensitivity_type"],
                rechunk=False,
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalPipelineError(
                f"could not inventory resume sensitivity leaf {path.name}: {exc}"
            ) from exc
        identities = frame.select("experiment_run_id", "sensitivity_type").unique()
        if identities.height != 1:
            raise LexicalPipelineError(
                f"resume sensitivity leaf mixes run or type identities: {path.name}"
            )
        run_id, sensitivity_type = identities.row(0)
        if run_id != experiment_run_id:
            raise LexicalPipelineError(
                f"resume sensitivity leaf belongs to a different run: {path.name}"
            )
        type_text = str(sensitivity_type)
        sensitivity_rows[type_text] += frame.height
        sensitivity_parts[type_text] += 1
        if not observed_type_order or observed_type_order[-1] != type_text:
            observed_type_order.append(type_text)
    expected_types = ["critical_core_profile", "hebrew_qere_ketiv"]
    if observed_type_order != expected_types or any(
        sensitivity_rows[name] < 1 for name in expected_types
    ):
        raise LexicalPipelineError(
            f"resume sensitivity scopes are incomplete or invalid: observed={observed_type_order}"
        )
    return _ResumeArtifactInventory(
        ranking_rows_by_scope=dict(ranking_rows),
        ranking_parts_by_scope=dict(ranking_parts),
        sensitivity_rows_by_type=dict(sensitivity_rows),
        sensitivity_parts_by_type=dict(sensitivity_parts),
    )


def _resume_split_provenance(
    staging_dir: Path,
    *,
    database_path: Path,
    experiment_run_id: str,
    expected_passage_ids: set[str],
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    resource_check: _ResourceCheck | None = None,
) -> dict[str, str]:
    """Reconcile exact primary split payloads from bounded persisted ranking leaves."""

    provenance: dict[str, str] = {}

    def register(passage_id: object, payload: object, *, leaf: str) -> None:
        passage_text = str(passage_id)
        payload_text = str(payload)
        previous = provenance.setdefault(passage_text, payload_text)
        if previous != payload_text:
            raise LexicalPipelineError(
                f"resumed split provenance conflicts for {passage_text} in {leaf}"
            )

    paths = sorted((staging_dir / "directional_rankings").glob("part-*.parquet"))
    for part, path in enumerate(paths):
        try:
            frame = pl.read_parquet(
                path,
                columns=[
                    "experiment_run_id",
                    "experiment_scope",
                    "query_passage_id",
                    "target_passage_id",
                    "query_split",
                    "target_split",
                ],
                rechunk=False,
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalPipelineError(
                f"could not read resumed split provenance from {path.name}: {exc}"
            ) from exc
        identities = frame.select("experiment_run_id", "experiment_scope").unique()
        if identities.height != 1:
            raise LexicalPipelineError(
                f"resume ranking leaf mixes run or scope identities: {path.name}"
            )
        run_id, scope = identities.row(0)
        if run_id != experiment_run_id:
            raise LexicalPipelineError(
                f"resume ranking leaf belongs to a different run: {path.name}"
            )
        if scope != "primary":
            continue
        for query_id, target_id, query_split, target_split in frame.select(
            "query_passage_id",
            "target_passage_id",
            "query_split",
            "target_split",
        ).iter_rows():
            register(query_id, query_split, leaf=path.name)
            register(target_id, target_split, leaf=path.name)
        if resource_check is not None and part % 32 == 0:
            resource_check(f"resume_split_provenance:part-{part}")
    missing = sorted(expected_passage_ids.difference(provenance))
    if missing:
        recovered = _load_split_provenance(
            database_path,
            missing,
            duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
            duckdb_temp_directory=duckdb_temp_directory,
            resource_check=resource_check,
            targeted_lookup=True,
        )
        default_payload = _canonical_json({"status": "no_eligible_benchmark_assignment"})
        for passage_id in missing:
            register(
                passage_id,
                recovered.get(passage_id, default_payload),
                leaf="anchored benchmark targeted recovery",
            )
    missing = sorted(expected_passage_ids.difference(provenance))
    unexpected = sorted(set(provenance).difference(expected_passage_ids))
    if missing or unexpected:
        raise LexicalPipelineError(
            "resumed split provenance passage coverage differs: "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}"
        )
    return provenance


def _resume_index_state(
    staging_dir: Path,
    *,
    experiment_run_id: str,
    configuration_hash: str,
) -> tuple[
    dict[str, str],
    dict[str, str],
    str,
    dict[str, dict[str, object]],
]:
    paths = sorted((staging_dir / "lexical_index_metadata").glob("part-*.parquet"))
    if not paths:
        raise LexicalPipelineError("resume staging has no lexical index metadata")
    try:
        metadata = pl.read_parquet(paths, rechunk=True).cast(
            LEXICAL_INDEX_METADATA_SCHEMA, strict=True
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalPipelineError(f"could not read resumed index metadata: {exc}") from exc
    if metadata.get_column("experiment_run_id").unique().to_list() != [
        experiment_run_id
    ] or metadata.get_column("index_config_hash").unique().to_list() != [configuration_hash]:
        raise LexicalPipelineError("resumed index metadata identity differs from the run")

    def representation(
        *,
        corpus_scope: str,
        profile: str,
        reading: str,
        feature_family: str,
    ) -> str:
        selected = metadata.filter(
            (pl.col("corpus_scope") == corpus_scope)
            & (pl.col("profile") == profile)
            & (pl.col("reading") == reading)
            & (pl.col("feature_family") == feature_family)
        )
        if selected.height != 1:
            raise LexicalPipelineError(
                "resumed index metadata does not expose exactly one governed "
                f"{profile}/{corpus_scope}/{reading}/{feature_family} representation"
            )
        return str(selected.item(0, "representation_id"))

    primary = {
        "hb_hb": representation(
            corpus_scope="hebrew",
            profile="edition_complete",
            reading="qere",
            feature_family="lemma",
        ),
        "gnt_gnt": representation(
            corpus_scope="greek",
            profile="edition_complete",
            reading="source",
            feature_family="lemma",
        ),
        "hb_gnt_english_bridge": representation(
            corpus_scope="hebrew+greek",
            profile="edition_complete",
            reading="qere+source",
            feature_family="english_gloss",
        ),
    }
    critical = {
        "gnt_gnt": representation(
            corpus_scope="greek",
            profile="critical_core",
            reading="source",
            feature_family="lemma",
        ),
        "hb_gnt_english_bridge": representation(
            corpus_scope="hebrew+greek",
            profile="critical_core",
            reading="qere+source",
            feature_family="english_gloss",
        ),
    }
    ketiv = representation(
        corpus_scope="hebrew",
        profile="edition_complete",
        reading="ketiv",
        feature_family="lemma",
    )
    summaries = {
        str(row["index_id"]): {
            "index_id": str(row["index_id"]),
            "representation_id": str(row["representation_id"]),
            "shape": json.loads(str(row["matrix_shape_json"])),
            "nonzero_count": int(row["nonzero_count"]),
            "logical_hash": str(row["logical_matrix_hash"]),
            "physical_hash": str(row["physical_file_hash"]),
        }
        for row in metadata.iter_rows(named=True)
    }
    return primary, critical, ketiv, summaries


def _run_lexical_pipeline_impl(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
    force: bool = False,
    resume_staging_dir: Path | None = None,
    execution_recorder: ExperimentExecutionRecorder | None = None,
    checkpoint_quarantine: _PrivateCheckpointQuarantine | None = None,
) -> LexicalPipelineResult:
    """Run every frozen verse-level M7 stage and atomically replace lexical artifacts."""

    timings: dict[str, float] = {}
    start = time.perf_counter()
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    validate_preregistration_against_config(preregistration, config)
    thread_controls = enforce_thread_controls(config.resource_limits.thread_count)
    observed_polars_threads = pl.thread_pool_size()
    if observed_polars_threads > config.resource_limits.thread_count:
        raise LexicalPipelineError(
            "Polars initialized before the governed thread control: "
            f"observed={observed_polars_threads}, maximum={config.resource_limits.thread_count}"
        )
    try:
        resource_guard = ProcessResourceGuard(config.resource_limits.maximum_memory_bytes)
    except LexicalResourceError as exc:
        raise LexicalPipelineError(f"could not initialize resource guard: {exc}") from exc

    resume_progress_path: Path | None = None
    last_resume_progress_stage: str | None = None

    def resource_check(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        nonlocal last_resume_progress_stage
        if (
            resume_progress_path is not None
            and stage != last_resume_progress_stage
            and stage.startswith(("evaluation:", "null:", "candidates:", "finalize:"))
        ):
            try:
                resume_progress_path.write_text(stage + "\n", encoding="utf-8")
            except OSError as exc:
                raise LexicalPipelineError(
                    f"could not write private resume progress marker: {exc}"
                ) from exc
            last_resume_progress_stage = stage
        try:
            resource_guard.check(
                stage,
                estimated_additional_bytes=estimated_additional_bytes,
            )
        except LexicalResourceError as exc:
            raise LexicalPipelineError(str(exc)) from exc

    resource_check("pipeline:start")
    configuration_hash = lexical_config_sha256(config)
    preregistration_hash = lexical_preregistration_sha256(preregistration)
    if execution_recorder is not None:
        execution_recorder.bind_configuration(
            canonical_hashes={
                "lexical_canonical": configuration_hash,
                "lexical_preregistration_canonical": preregistration_hash,
            },
            random_seed=config.statistics.bootstrap_seed,
            random_seeds={
                "bootstrap": config.statistics.bootstrap_seed,
                "frequency_preserving_synthetic": (
                    config.null_models.frequency_preserving_synthetic.seed
                ),
                "within_book_reassignment": (config.null_models.within_book_reassignment.seed),
            },
            dataset_versions=_m7_source_versions(),
        )
    try:
        database_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
            "pipeline_database:duckdb-budget",
            preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    anchor_spill_directory = output_dir.parent / f".{output_dir.name}.anchor-spill"
    with _managed_temp_directory(anchor_spill_directory):
        anchors = cast(
            AnchorVerification,
            _time_stage(
                timings,
                "verify_anchors",
                lambda: verify_upstream_anchors(
                    database_path=database_path,
                    passage_root=DEFAULT_PASSAGE_ROOT,
                    benchmark_root=DEFAULT_BENCHMARK_ROOT,
                    tier1_path=DEFAULT_TIER1_PATH,
                    oshb_root=DEFAULT_OSHB_ROOT,
                    duckdb_memory_limit_bytes=database_duckdb_memory,
                    duckdb_temp_directory=anchor_spill_directory / "duckdb",
                ),
            ),
        )
    resource_check("verify_anchors:after")
    experiment_run_id = build_experiment_run_id(
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        anchors=anchors,
    )
    if execution_recorder is not None:
        execution_recorder.bind_run(
            run_id=experiment_run_id,
            input_table_hashes=_m7_anchor_input_hashes(anchors),
            dataset_versions=_m7_anchor_dataset_versions(anchors),
            evaluation_split_lineage=_prefixed_hashes(
                "benchmark",
                anchors.benchmark_logical_hashes,
            ),
        )
    database_spill_directory = (
        output_dir.parent / f".{output_dir.name}.{experiment_run_id}.duckdb-spill"
    )
    if resume_staging_dir is not None and database_spill_directory.exists():
        resolved_spill = database_spill_directory.resolve()
        expected_parent = output_dir.resolve().parent
        spill_entries = list(resolved_spill.rglob("*"))
        if (
            resolved_spill.parent != expected_parent
            or resolved_spill.is_symlink()
            or any(path.is_file() or path.is_symlink() for path in spill_entries)
        ):
            raise LexicalPipelineError(
                "resume found a nonempty or ungoverned prior DuckDB spill directory"
            )
        shutil.rmtree(resolved_spill)

    with (
        _managed_temp_directory(database_spill_directory),
        LexicalArtifactWriter(
            output_dir,
            force=force,
            duckdb_memory_limit_bytes=database_duckdb_memory,
            resume_staging_dir=resume_staging_dir,
            preserve_staging_on_error=True,
            required_free_bytes=(
                config.resource_limits.minimum_free_disk_bytes
                if config.resource_limits.check_disk_before_build
                else 0
            ),
        ) as writer,
    ):
        if checkpoint_quarantine is not None:
            checkpoint_quarantine.register_staging(writer.staging_dir)
        if resume_staging_dir is not None:
            resume_progress_path = (
                writer.staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY / "progress.txt"
            )
        primary = config.primary_scope
        critical_scope = config.sensitivity_scopes.critical_core_greek
        reading_scope = config.sensitivity_scopes.hebrew_qere_ketiv
        resume_inventory: _ResumeArtifactInventory | None = None
        resumed_primary_representation_ids: dict[str, str] | None = None
        resumed_critical_representation_ids: dict[str, str] | None = None
        resumed_ketiv_representation_id: str | None = None
        resumed_index_summaries: dict[str, dict[str, object]] | None = None
        reused_tier3_manifest_hashes: dict[str, str] = {}
        reused_tier3_part_hashes: dict[str, str] = {}
        if resume_staging_dir is not None:
            resume_inventory = _resume_artifact_inventory(
                writer.staging_dir,
                experiment_run_id=experiment_run_id,
            )
            (
                resumed_primary_representation_ids,
                resumed_critical_representation_ids,
                resumed_ketiv_representation_id,
                resumed_index_summaries,
            ) = _resume_index_state(
                writer.staging_dir,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
            )
            timings["resume_existing_artifacts_validated"] = time.perf_counter() - start
            resource_check("resume_existing_artifacts:validated")

        def load_sequences(
            *, corpus: str, profile: str, reading: str, stage: str
        ) -> list[PassageLexicalSequence]:
            resource_check(
                f"{stage}:before",
                estimated_additional_bytes=(
                    _SEQUENCE_LOAD_RESERVATION_BYTES + database_duckdb_memory
                ),
            )
            loaded = cast(
                list[PassageLexicalSequence],
                _time_stage(
                    timings,
                    stage,
                    lambda: list(
                        iter_passage_sequences(
                            database_path,
                            corpus=corpus,
                            analysis_profile=profile,
                            analysis_reading=reading,
                            granularity="verse",
                            duckdb_memory_limit_bytes=database_duckdb_memory,
                            duckdb_temp_directory=database_spill_directory / "sequences",
                        )
                    ),
                ),
            )
            if not loaded:
                raise LexicalPipelineError(f"{stage} produced no governed verse sequences")
            resource_check(f"{stage}:after")
            return loaded

        hebrew = load_sequences(
            corpus="hebrew",
            profile=primary.analysis_profile,
            reading=primary.hebrew_reading,
            stage="load_primary_hebrew_sequences",
        )
        greek = load_sequences(
            corpus="greek",
            profile=primary.analysis_profile,
            reading=primary.greek_reading,
            stage="load_primary_greek_sequences",
        )
        critical_hebrew = load_sequences(
            corpus="hebrew",
            profile=critical_scope.analysis_profile,
            reading=critical_scope.hebrew_reading,
            stage="load_critical_hebrew_sequences",
        )
        critical_greek = load_sequences(
            corpus="greek",
            profile=critical_scope.analysis_profile,
            reading=critical_scope.greek_reading,
            stage="load_critical_greek_sequences",
        )
        ketiv_hebrew = (
            []
            if resume_inventory is not None
            else load_sequences(
                corpus="hebrew",
                profile=reading_scope.analysis_profile,
                reading=reading_scope.comparison_reading,
                stage="load_ketiv_hebrew_sequences",
            )
        )
        all_sequences = [*hebrew, *greek]
        critical_all_sequences = [*critical_hebrew, *critical_greek]
        book_genres = _book_genres()
        if resume_inventory is not None:
            try:
                vocabulary = pl.read_parquet(
                    sorted((writer.staging_dir / "feature_vocabulary").glob("part-*.parquet")),
                    rechunk=True,
                ).cast(FEATURE_VOCABULARY_SCHEMA, strict=True)
            except (OSError, pl.exceptions.PolarsError) as exc:
                raise LexicalPipelineError(
                    f"could not load resumed feature vocabulary: {exc}"
                ) from exc
            timings["feature_vocabulary"] = 0.0
            timings["passage_feature_statistics"] = 0.0
        else:
            resource_check(
                "feature_vocabulary:before",
                estimated_additional_bytes=_FEATURE_VOCABULARY_RESERVATION_BYTES,
            )
            vocabulary = cast(
                pl.DataFrame,
                _time_stage(
                    timings,
                    "feature_vocabulary",
                    lambda: build_all_feature_vocabulary(
                        hebrew, greek, config=config, book_genres=book_genres
                    ),
                ),
            )
            resource_check("feature_vocabulary:after")
            passage_statistics_start = time.perf_counter()
            resource_check(
                "passage_feature_statistics:before",
                estimated_additional_bytes=_PASSAGE_STATISTICS_RESERVATION_BYTES,
            )
            passage_statistics = build_passage_feature_statistics(all_sequences, vocabulary)
            timings["passage_feature_statistics"] = time.perf_counter() - passage_statistics_start
            resource_check("passage_feature_statistics:after")
            writer.write_frame("feature_vocabulary", vocabulary)
            writer.write_frame("passage_feature_statistics", passage_statistics)
            del passage_statistics
            gc.collect()
            resource_check("passage_feature_statistics:released")
        feature_counts = {
            f"{namespace}:{family}": int(group.height)
            for (namespace, family), group in vocabulary.group_by(
                "language_namespace", "feature_family", maintain_order=False
            )
        }

        resumed_candidates = (
            _load_candidate_checkpoint(
                writer.staging_dir,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                resource_check=resource_check,
            )
            if resume_inventory is not None
            else None
        )
        if resume_inventory is not None and execution_recorder is not None:
            (
                resumed_artifact_hashes,
                resumed_checkpoint_manifest_hashes,
                resumed_checkpoint_part_hashes,
            ) = _validated_resume_file_hashes(
                writer.staging_dir,
                candidate_checkpoint_reused=resumed_candidates is not None,
            )
            execution_recorder.bind_resume_lineage(
                artifact_part_hashes=resumed_artifact_hashes,
                checkpoint_manifest_hashes=resumed_checkpoint_manifest_hashes,
                checkpoint_part_hashes=resumed_checkpoint_part_hashes,
            )
            (
                reused_tier3_manifest_hashes,
                reused_tier3_part_hashes,
            ) = _validated_existing_tier3_checkpoint_hashes(
                writer.staging_dir,
                expected_manifest_names=_expected_tier3_checkpoint_manifest_names(
                    analysis_profiles=(
                        primary.analysis_profile,
                        critical_scope.analysis_profile,
                    ),
                    enabled_detectors=config.enabled_detectors,
                ),
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
            )
        provenance_start = time.perf_counter()
        if resume_inventory is not None and resumed_candidates is not None:
            split_provenance: dict[str, str] = {}
            affected_references: dict[str, int] = {}
            qere_references: set[str] = set()
            ketiv_references: set[str] = set()
        elif resume_inventory is not None:
            try:
                provenance_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
                    "resume_split_provenance:duckdb-budget",
                    preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
                    reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
                )
            except LexicalResourceError as exc:
                raise LexicalPipelineError(str(exc)) from exc
            split_provenance = _resume_split_provenance(
                writer.staging_dir,
                database_path=database_path,
                experiment_run_id=experiment_run_id,
                expected_passage_ids={item.passage_id for item in all_sequences},
                duckdb_memory_limit_bytes=provenance_duckdb_memory,
                duckdb_temp_directory=database_spill_directory,
                resource_check=resource_check,
            )
            affected_references = {}
            qere_references = set()
            ketiv_references = set()
        else:
            try:
                provenance_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
                    "benchmark_split_provenance:duckdb-budget",
                    preferred_bytes=_PROVENANCE_DUCKDB_PREFERRED_MEMORY_BYTES,
                    reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
                )
            except LexicalResourceError as exc:
                raise LexicalPipelineError(str(exc)) from exc
            split_provenance = _load_split_provenance(
                database_path,
                [*all_sequences, *critical_all_sequences, *ketiv_hebrew],
                duckdb_memory_limit_bytes=provenance_duckdb_memory,
                duckdb_temp_directory=database_spill_directory,
                resource_check=resource_check,
            )
            affected_references = _oshb_affected_verse_references(
                database_path,
                duckdb_memory_limit_bytes=provenance_duckdb_memory,
                duckdb_temp_directory=database_spill_directory,
            )
            qere_references = {item.start_reference for item in hebrew}
            ketiv_references = {item.start_reference for item in ketiv_hebrew}
            missing_affected = sorted(
                set(affected_references).difference(qere_references.intersection(ketiv_references))
            )
            if missing_affected:
                raise LexicalPipelineError(
                    "OSHB sensitivity references do not resolve in both Qere and Ketiv "
                    f"verse streams: {missing_affected[:10]}"
                )
        timings["split_provenance_and_sensitivity_scope"] = time.perf_counter() - provenance_start

        primary_sequences_by_pair = {
            "hb_hb": hebrew,
            "gnt_gnt": greek,
            "hb_gnt_english_bridge": all_sequences,
        }
        index_seconds = 0.0
        retrieval_seconds = 0.0

        if resume_inventory is not None:
            if resumed_primary_representation_ids is None or resumed_index_summaries is None:
                raise LexicalPipelineError("resume primary index state is unavailable")
            primary_representation_ids = resumed_primary_representation_ids
            index_summaries = resumed_index_summaries
            primary_ranking_count = resume_inventory.ranking_rows_by_scope["primary"]
            next_ranking_part = resume_inventory.ranking_parts_by_scope["primary"]
            if resumed_candidates is not None:
                candidates = resumed_candidates
                timings["resume_primary_candidate_checkpoint"] = 0.0
            else:
                checkpoint_writer = _CandidateCheckpointWriter(
                    writer.staging_dir,
                    experiment_run_id=experiment_run_id,
                    configuration_hash=configuration_hash,
                )
                retrieval_start = time.perf_counter()
                try:
                    primary_indexes = {
                        pair: load_sparse_index(writer.staging_dir / "indexes" / representation_id)
                        for pair, representation_id in primary_representation_ids.items()
                    }
                except (OSError, ValueError, SparseIndexError) as exc:
                    raise LexicalPipelineError(
                        f"could not load resumed primary sparse indexes: {exc}"
                    ) from exc
                primary_retrieval = _run_retrieval(
                    writer=writer,
                    indexes=primary_indexes,
                    sequences_by_pair=primary_sequences_by_pair,
                    experiment_run_id=experiment_run_id,
                    configuration_hash=configuration_hash,
                    config=config,
                    experiment_scope="primary",
                    corpus_pairs=("hb_hb", "gnt_gnt", "hb_gnt_english_bridge"),
                    split_provenance_by_passage_id=split_provenance,
                    resource_check=resource_check,
                    candidate_checkpoint=checkpoint_writer,
                )
                if (
                    primary_retrieval.ranking_count != primary_ranking_count
                    or primary_retrieval.next_ranking_part != next_ranking_part
                ):
                    raise LexicalPipelineError(
                        "regenerated primary ranking inventory differs from resumed artifacts"
                    )
                checkpoint_writer.finalize()
                candidates = primary_retrieval.candidates
                timings["resume_primary_candidate_reconstruction"] = (
                    time.perf_counter() - retrieval_start
                )
                del primary_indexes, primary_retrieval
                gc.collect()
                resource_check("resume_primary_sparse_indexes:released")
        else:
            index_start = time.perf_counter()
            primary_indexes, primary_index_metadata, index_summaries = _build_indexes(
                writer=writer,
                definitions=_primary_index_definitions(hebrew, greek, config=config),
                config=config,
                configuration_hash=configuration_hash,
                experiment_run_id=experiment_run_id,
                resource_check=resource_check,
            )
            index_seconds += time.perf_counter() - index_start
            writer.write_frame("lexical_index_metadata", primary_index_metadata, part=0)
            primary_representation_ids = {
                pair: primary_indexes[pair].representation_id
                for pair in ("hb_hb", "gnt_gnt", "hb_gnt_english_bridge")
            }
            retrieval_start = time.perf_counter()
            primary_retrieval = _run_retrieval(
                writer=writer,
                indexes=primary_indexes,
                sequences_by_pair=primary_sequences_by_pair,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                config=config,
                experiment_scope="primary",
                corpus_pairs=("hb_hb", "gnt_gnt", "hb_gnt_english_bridge"),
                split_provenance_by_passage_id=split_provenance,
                resource_check=resource_check,
            )
            retrieval_seconds += time.perf_counter() - retrieval_start
            candidates = primary_retrieval.candidates
            primary_ranking_count = primary_retrieval.ranking_count
            next_ranking_part = primary_retrieval.next_ranking_part
            del primary_indexes, primary_index_metadata, primary_retrieval
            gc.collect()
            resource_check("primary_sparse_indexes:released")

        critical_sequences_by_pair = {
            "gnt_gnt": critical_greek,
            "hb_gnt_english_bridge": critical_all_sequences,
        }
        if resume_inventory is not None:
            if resumed_critical_representation_ids is None:
                raise LexicalPipelineError("resume critical index state is unavailable")
            critical_representation_ids = resumed_critical_representation_ids
            critical_ranking_count = resume_inventory.ranking_rows_by_scope[
                "critical_core_greek_sensitivity"
            ]
            next_ranking_part += resume_inventory.ranking_parts_by_scope[
                "critical_core_greek_sensitivity"
            ]
        else:
            index_start = time.perf_counter()
            critical_indexes, critical_index_metadata, critical_summaries = _build_indexes(
                writer=writer,
                definitions=_critical_index_definitions(
                    critical_hebrew=critical_hebrew,
                    critical_greek=critical_greek,
                    config=config,
                ),
                config=config,
                configuration_hash=configuration_hash,
                experiment_run_id=experiment_run_id,
                resource_check=resource_check,
            )
            index_seconds += time.perf_counter() - index_start
            index_summaries.update(critical_summaries)
            writer.write_frame("lexical_index_metadata", critical_index_metadata, part=1)
            critical_index_by_pair = {
                "gnt_gnt": critical_indexes["critical_gnt_gnt"],
                "hb_gnt_english_bridge": critical_indexes["critical_hb_gnt_english_bridge"],
            }
            critical_representation_ids = {
                pair: index.representation_id for pair, index in critical_index_by_pair.items()
            }
            retrieval_start = time.perf_counter()
            critical_retrieval = _run_retrieval(
                writer=writer,
                indexes=critical_index_by_pair,
                sequences_by_pair=critical_sequences_by_pair,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                config=config,
                experiment_scope="critical_core_greek_sensitivity",
                corpus_pairs=critical_scope.corpus_pairs,
                split_provenance_by_passage_id=split_provenance,
                collect_candidates=False,
                ranking_part_start=next_ranking_part,
                resource_check=resource_check,
            )
            retrieval_seconds += time.perf_counter() - retrieval_start
            critical_ranking_count = critical_retrieval.ranking_count
            next_ranking_part = critical_retrieval.next_ranking_part
            del critical_indexes, critical_index_by_pair, critical_index_metadata
            del critical_summaries, critical_retrieval
            gc.collect()
            resource_check("critical_sparse_indexes:released")

        if resume_inventory is not None:
            if resumed_ketiv_representation_id is None:
                raise LexicalPipelineError("resume Qere/Ketiv index state is unavailable")
            ketiv_representation_id = resumed_ketiv_representation_id
            ketiv_ranking_count = resume_inventory.ranking_rows_by_scope[
                "hebrew_qere_ketiv_sensitivity"
            ]
            next_ranking_part += resume_inventory.ranking_parts_by_scope[
                "hebrew_qere_ketiv_sensitivity"
            ]
        else:
            index_start = time.perf_counter()
            ketiv_indexes, ketiv_index_metadata, ketiv_summaries = _build_indexes(
                writer=writer,
                definitions=_ketiv_index_definitions(ketiv_hebrew, config=config),
                config=config,
                configuration_hash=configuration_hash,
                experiment_run_id=experiment_run_id,
                resource_check=resource_check,
            )
            index_seconds += time.perf_counter() - index_start
            index_summaries.update(ketiv_summaries)
            writer.write_frame("lexical_index_metadata", ketiv_index_metadata, part=2)
            ketiv_representation_id = ketiv_indexes["ketiv_hb_hb"].representation_id
            retrieval_start = time.perf_counter()
            ketiv_retrieval = _run_retrieval(
                writer=writer,
                indexes={"hb_hb": ketiv_indexes["ketiv_hb_hb"]},
                sequences_by_pair={"hb_hb": ketiv_hebrew},
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                config=config,
                experiment_scope="hebrew_qere_ketiv_sensitivity",
                corpus_pairs=("hb_hb",),
                split_provenance_by_passage_id=split_provenance,
                query_reference_filter=frozenset(affected_references),
                collect_candidates=False,
                ranking_part_start=next_ranking_part,
                resource_check=resource_check,
            )
            retrieval_seconds += time.perf_counter() - retrieval_start
            ketiv_ranking_count = ketiv_retrieval.ranking_count
            del ketiv_indexes, ketiv_index_metadata, ketiv_summaries, ketiv_retrieval
        del split_provenance
        gc.collect()
        resource_check("ketiv_sparse_indexes_and_split_provenance:released")

        ranking_count = primary_ranking_count + critical_ranking_count + ketiv_ranking_count
        timings["sparse_indexes"] = index_seconds
        timings["retrieval_and_reranking"] = retrieval_seconds

        sensitivity_start = time.perf_counter()
        ranking_root = writer.staging_dir / "directional_rankings"
        if resume_inventory is not None:
            sensitivity_counts = dict(resume_inventory.sensitivity_rows_by_type)
        else:
            sensitivity_part = 0
            sensitivity_counts = {
                "critical_core_profile": 0,
                "hebrew_qere_ketiv": 0,
            }
            for frame in _iter_sensitivity_result_frames(
                ranking_root=ranking_root,
                baseline_scope="primary",
                comparison_scope="critical_core_greek_sensitivity",
                sensitivity_type="critical_core_profile",
                corpus_pairs=critical_scope.corpus_pairs,
                baseline_profile=primary.analysis_profile,
                comparison_profile=critical_scope.analysis_profile,
                baseline_reading=f"{primary.hebrew_reading}+{primary.greek_reading}",
                comparison_reading=(
                    f"{critical_scope.hebrew_reading}+{critical_scope.greek_reading}"
                ),
                baseline_sequences=all_sequences,
                comparison_sequences=critical_all_sequences,
                baseline_representation_ids={
                    pair: primary_representation_ids[pair] for pair in critical_scope.corpus_pairs
                },
                comparison_representation_ids=critical_representation_ids,
                affected_references={},
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                resource_guard=resource_guard,
                spill_directory=writer.staging_dir / ".critical-sensitivity-spill",
                minimum_free_disk_bytes=config.resource_limits.minimum_free_disk_bytes,
            ):
                writer.write_frame("sensitivity_results", frame, part=sensitivity_part)
                sensitivity_part += 1
                sensitivity_counts["critical_core_profile"] += frame.height
            for frame in _iter_sensitivity_result_frames(
                ranking_root=ranking_root,
                baseline_scope="primary",
                comparison_scope="hebrew_qere_ketiv_sensitivity",
                sensitivity_type="hebrew_qere_ketiv",
                corpus_pairs=("hb_hb",),
                baseline_profile=primary.analysis_profile,
                comparison_profile=reading_scope.analysis_profile,
                baseline_reading=reading_scope.baseline_reading,
                comparison_reading=reading_scope.comparison_reading,
                baseline_sequences=hebrew,
                comparison_sequences=ketiv_hebrew,
                baseline_representation_ids={"hb_hb": primary_representation_ids["hb_hb"]},
                comparison_representation_ids={"hb_hb": ketiv_representation_id},
                affected_references=affected_references,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                resource_guard=resource_guard,
                spill_directory=writer.staging_dir / ".qere-ketiv-sensitivity-spill",
                minimum_free_disk_bytes=config.resource_limits.minimum_free_disk_bytes,
            ):
                writer.write_frame("sensitivity_results", frame, part=sensitivity_part)
                sensitivity_part += 1
                sensitivity_counts["hebrew_qere_ketiv"] += frame.height
        if any(count < 1 for count in sensitivity_counts.values()):
            raise LexicalPipelineError(
                f"required sensitivity comparison produced no rows: {sensitivity_counts}"
            )
        timings["sensitivity_comparisons"] = time.perf_counter() - sensitivity_start

        del ketiv_hebrew, qere_references, ketiv_references, affected_references
        gc.collect()
        resource_check("pre_tier3_ketiv_working_set:released")

        experiment_start = time.perf_counter()
        try:
            detectors_by_pair = governed_detectors_by_corpus_pair(
                ranking_root,
                experiment_run_id=experiment_run_id,
                representation_ids=primary_representation_ids,
            )
            tier3_start = time.perf_counter()
            evaluation_artifacts = run_tier3_evaluation_experiment(
                ranking_root,
                sequences_by_corpus_pair=primary_sequences_by_pair,
                representation_ids=primary_representation_ids,
                config=config,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                benchmark_database_path=database_path,
                book_genres=book_genres,
                additional_evaluation_scopes=(
                    Tier3EvaluationScope(
                        analysis_profile=cast(AnalysisProfile, critical_scope.analysis_profile),
                        experiment_scope="critical_core_greek_sensitivity",
                        directional_rankings=ranking_root,
                        sequences_by_corpus_pair=critical_sequences_by_pair,
                        representation_ids=critical_representation_ids,
                    ),
                ),
                resource_check=resource_check,
                duckdb_memory_limit_bytes=database_duckdb_memory,
                duckdb_temp_directory=database_spill_directory / "experiment",
                checkpoint_directory=(
                    writer.staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY / "tier3-evaluation"
                ),
            )
            timings["tier3_evaluation"] = time.perf_counter() - tier3_start
            if (
                resume_inventory is not None
                and execution_recorder is not None
                and (reused_tier3_manifest_hashes or reused_tier3_part_hashes)
            ):
                (
                    observed_tier3_manifest_hashes,
                    observed_tier3_part_hashes,
                ) = _validated_existing_tier3_checkpoint_hashes(
                    writer.staging_dir,
                    expected_manifest_names=_expected_tier3_checkpoint_manifest_names(
                        analysis_profiles=(
                            primary.analysis_profile,
                            critical_scope.analysis_profile,
                        ),
                        enabled_detectors=config.enabled_detectors,
                    ),
                    experiment_run_id=experiment_run_id,
                    configuration_hash=configuration_hash,
                    preregistration_hash=preregistration_hash,
                )
                (
                    confirmed_tier3_manifest_hashes,
                    confirmed_tier3_part_hashes,
                ) = _confirmed_tier3_checkpoint_reuse(
                    before_manifests=reused_tier3_manifest_hashes,
                    before_parts=reused_tier3_part_hashes,
                    after_manifests=observed_tier3_manifest_hashes,
                    after_parts=observed_tier3_part_hashes,
                )
                # bind_resume_lineage is additive: this second bind occurs only after
                # run_tier3_evaluation_experiment has authenticated and assembled the
                # pre-existing checkpoint files, so newly-created files are excluded.
                execution_recorder.bind_resume_lineage(
                    artifact_part_hashes={},
                    checkpoint_manifest_hashes=confirmed_tier3_manifest_hashes,
                    checkpoint_part_hashes=confirmed_tier3_part_hashes,
                )
            evaluation_frame = evaluation_artifacts.evaluation_results
            evaluation_count = evaluation_frame.height
            scientific_gate_status = evaluation_artifacts.scientific_gate_status
            writer.write_frame("evaluation_results", evaluation_frame)
            del evaluation_frame, evaluation_artifacts
            del critical_hebrew, critical_greek, critical_all_sequences
            del critical_sequences_by_pair, critical_representation_ids
            gc.collect()
            resource_check("post_tier3_sensitivity_sequences:released")

            null_start = time.perf_counter()
            calibration_artifacts = run_null_calibration_experiment(
                candidates,
                sequences_by_corpus_pair=primary_sequences_by_pair,
                representation_ids=primary_representation_ids,
                config=config,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                book_genres=book_genres,
                detectors_by_corpus_pair=detectors_by_pair,
                resource_check=resource_check,
            )
            timings["null_calibration"] = time.perf_counter() - null_start
        except LexicalExperimentError as exc:
            raise LexicalPipelineError(f"lexical calibration/evaluation failed: {exc}") from exc
        timings["null_calibration_and_tier3_evaluation"] = time.perf_counter() - experiment_start
        null_frame = calibration_artifacts.null_replicate_summaries
        calibration_frame = calibration_artifacts.threshold_calibration
        calibration = dict(calibration_artifacts.selected_calibration)
        null_iteration_count = int(null_frame.get_column("null_run_id").n_unique())
        writer.write_frame("null_replicate_summaries", null_frame)
        writer.write_frame("threshold_calibration", calibration_frame)
        resource_check("experiment_artifacts:written")

        del calibration_artifacts, null_frame, calibration_frame
        hebrew.clear()
        greek.clear()
        book_genres.clear()
        del primary_sequences_by_pair
        gc.collect()
        resource_check("post_tier3_evaluation_working_sets:released")

        evidence_start = time.perf_counter()
        resource_check(
            "candidate_evidence_indexes:before",
            estimated_additional_bytes=_CANDIDATE_EVIDENCE_RESERVATION_BYTES,
        )
        feature_statistics, feature_passages = build_feature_evidence_indexes(
            all_sequences, vocabulary
        )
        feature_vocabulary_logical_hash = logical_frame_hash(vocabulary, sort_by=["feature_id"])
        del vocabulary
        gc.collect()
        resource_check("candidate_evidence_indexes:after")
        try:
            candidate_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
                "candidate_materialization:duckdb-budget",
                preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
                reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
            )
        except LexicalResourceError as exc:
            raise LexicalPipelineError(str(exc)) from exc
        known_pairs = load_known_pair_index(
            database_path,
            duckdb_memory_limit_bytes=candidate_duckdb_memory,
            duckdb_temp_directory=database_spill_directory,
            resource_check=resource_check,
        )
        context = CandidateEvidenceContext(
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            sequences={item.passage_id: item for item in all_sequences},
            feature_statistics=feature_statistics,
            feature_passages=feature_passages,
            representation_ids=primary_representation_ids,
            known_pairs=known_pairs,
            calibration=calibration,
            config=config,
        )
        resource_check(
            "candidate_q_values:before",
            estimated_additional_bytes=max(64 * MEBIBYTE, len(candidates) * 256),
        )
        q_values = candidate_q_values(candidates, context)
        resource_check("candidate_q_values:after")
        queue_spool_directory = _prepare_candidate_review_queue_spool(
            writer.staging_dir,
            resumed=resume_inventory is not None,
        )
        queue_input_count = 0
        candidate_parts = 0
        ablation_part = 0
        candidate_count = len(candidates)
        candidate_batches = iter_candidate_artifact_batches(
            candidates,
            context=context,
            q_values=q_values,
            duckdb_memory_limit_bytes=candidate_duckdb_memory,
            resource_check=resource_check,
        )
        for part, batch in enumerate(candidate_batches):
            writer.write_frame("candidate_pairs", batch.candidate_pairs, part=part)
            writer.write_frame("candidate_detector_scores", batch.detector_scores, part=part)
            writer.write_frame("candidate_evidence", batch.candidate_evidence, part=part)
            writer.write_frame("shared_evidence", batch.shared_evidence, part=part)
            if batch.ablation_results.height:
                writer.write_frame("ablation_results", batch.ablation_results, part=ablation_part)
                ablation_part += 1
            if batch.queue_candidates:
                queue_input = build_review_queue(batch.queue_candidates).drop("queue_rank")
                writer.check_free_disk(f"candidate_queue_spool:part-{part}:before")
                queue_input.write_parquet(
                    queue_spool_directory / f"part-{part:05d}.parquet",
                    compression="zstd",
                    compression_level=6,
                    statistics=True,
                )
                writer.check_free_disk(f"candidate_queue_spool:part-{part}:after")
                queue_input_count += queue_input.height
            candidate_parts += 1
            resource_check(f"candidate_artifacts:part-{part}")
            del batch
        if candidate_parts == 0:
            raise LexicalPipelineError("primary retrieval produced no persisted candidates")
        del candidate_batches, candidates, context, q_values, known_pairs
        del feature_statistics, feature_passages
        all_sequences.clear()
        gc.collect()
        resource_check("candidate_aggregate_working_sets:released")
        queue_count = 0
        for queue_part, queue_frame in enumerate(
            _iter_ranked_review_queue_frames(
                queue_spool_directory,
                expected_count=queue_input_count,
                duckdb_memory_limit_bytes=candidate_duckdb_memory,
                duckdb_temp_directory=writer.staging_dir / ".candidate-review-queue-sort-spill",
                resource_check=resource_check,
            )
        ):
            writer.write_frame("candidate_review_queue", queue_frame, part=queue_part)
            queue_count += queue_frame.height
        if queue_count != queue_input_count:
            raise LexicalPipelineError(
                "review-queue count differs after bounded global ranking: "
                f"spooled={queue_input_count}, ranked={queue_count}"
            )
        review_eligible_count = queue_input_count
        shutil.rmtree(queue_spool_directory)
        gc.collect()
        resource_check("candidate_review_queue:released")
        uncalibrated_pairs: list[str] = []
        for pair in primary_representation_ids:
            selection = calibration.get(pair)
            if selection is None or not (
                selection.both_null_families_present
                and math.isfinite(selection.score_threshold)
                and math.isfinite(selection.estimated_empirical_fdr)
                and selection.estimated_empirical_fdr
                <= config.candidate_thresholds.maximum_empirical_fdr
            ):
                uncalibrated_pairs.append(pair)
        writer.write_frame(
            "lexical_issues",
            _issue_frame(
                experiment_run_id,
                scientific_gate_status=scientific_gate_status,
                uncalibrated_corpus_pairs=uncalibrated_pairs,
                sensitivity_counts=sensitivity_counts,
            ),
        )
        timings["candidate_evidence_and_queue"] = time.perf_counter() - evidence_start

        candidate_checkpoint_root = writer.staging_dir / _CANDIDATE_CHECKPOINT_DIRECTORY
        resume_progress_path = None
        if candidate_checkpoint_root.exists():
            if checkpoint_quarantine is None:
                raise LexicalPipelineError(
                    "private checkpoint quarantine is required before artifact promotion"
                )
            checkpoint_quarantine.quarantine_before_promotion()
        resource_check(
            "finalize:before_hashes",
            estimated_additional_bytes=database_duckdb_memory,
        )
        content_hash_start = time.perf_counter()
        logical_hashes, physical_hashes = writer.content_hashes()
        staging_footprint = sum(
            path.stat().st_size for path in writer.staging_dir.rglob("*") if path.is_file()
        )
        timings["content_hashes_and_footprint"] = time.perf_counter() - content_hash_start
        acceptance_status = (
            "scientifically_complete"
            if scientific_gate_status == "passed" and not uncalibrated_pairs
            else "scientifically_incomplete"
        )
        resource_check("finalize:metadata")
        timings["pre_finalize_total"] = time.perf_counter() - start
        metadata = pl.DataFrame(
            [
                {
                    "experiment_run_id": experiment_run_id,
                    "experiment_version": config.experiment_version,
                    "lexical_schema_version": 1,
                    "candidate_pair_schema_version": 1,
                    "configuration_hash": configuration_hash,
                    "preregistration_hash": preregistration_hash,
                    "input_corpus_hashes_json": _canonical_json(
                        {
                            "identity": anchors.corpus_identity_digests,
                            "content": anchors.corpus_content_digests,
                            "analytical": anchors.corpus_analytical_digests,
                            "oshb": anchors.oshb_logical_hashes,
                        }
                    ),
                    "passage_hashes_json": _canonical_json(anchors.passage_logical_hashes),
                    "benchmark_hashes_json": _canonical_json(anchors.benchmark_logical_hashes),
                    "feature_vocabulary_hashes_json": _canonical_json(
                        {"all": feature_vocabulary_logical_hash}
                    ),
                    "sparse_index_hashes_json": _canonical_json(
                        {
                            str(value["index_id"]): value["logical_hash"]
                            for value in index_summaries.values()
                        }
                    ),
                    "table_logical_hashes_json": _canonical_json(logical_hashes),
                    "table_physical_hashes_json": _canonical_json(physical_hashes),
                    "ranking_count": ranking_count,
                    "candidate_count": candidate_count,
                    "null_iteration_count": null_iteration_count,
                    "evaluation_count": evaluation_count,
                    "runtime_seconds": time.perf_counter() - start,
                    "stage_runtime_seconds_json": _canonical_json(dict(sorted(timings.items()))),
                    "peak_memory_bytes": resource_guard.peak_rss_bytes,
                    "storage_footprint_bytes": staging_footprint,
                    "numerical_environment_json": _canonical_json(
                        {
                            "python": platform.python_version(),
                            "platform": platform.system(),
                            "polars": pl.__version__,
                            "rss_probe": "os_native_current_working_set",
                        }
                    ),
                    "thread_controls_json": _canonical_json(
                        {**thread_controls, "POLARS_OBSERVED_THREADS": observed_polars_threads}
                    ),
                    "acceptance_status": acceptance_status,
                    "notes": (
                        "Tier 3 weak-supervision only; primary nulls are edition-complete "
                        "verse/Qere/source only; critical-core and Qere/Ketiv are explicit "
                        "non-null sensitivity scopes; English bridge separate; Milestone 8 "
                        "review not begun"
                    ),
                }
            ],
            schema=LEXICAL_METADATA_SCHEMA,
            orient="row",
        )
        processed = writer.finalize(metadata)
        if execution_recorder is not None:
            execution_recorder.bind_outputs(
                output_table_hashes=processed.table_logical_hashes,
                output_table_physical_hashes=processed.table_physical_hashes,
                output_hash_manifest_path=processed.output_dir / "table-hashes.json",
            )

    try:
        final_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
            "duckdb_load:budget",
            preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    final_spill_directory = (
        output_dir.parent / f".{output_dir.name}.{experiment_run_id}.duckdb-load-spill"
    )
    if final_spill_directory.exists():
        raise LexicalPipelineError(
            f"DuckDB load spill directory already exists: {final_spill_directory}"
        )
    try:
        load_lexical_duckdb(
            processed,
            database_path,
            duckdb_memory_limit_bytes=final_duckdb_memory,
            duckdb_temp_directory=final_spill_directory,
        )
    finally:
        shutil.rmtree(final_spill_directory, ignore_errors=True)
    resource_check("duckdb_load:after")
    timings["total"] = time.perf_counter() - start
    gc.collect()
    return LexicalPipelineResult(
        experiment_run_id=experiment_run_id,
        experiment_version=config.experiment_version,
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        anchors=anchors,
        processed=processed,
        database_path=database_path,
        stage_runtime_seconds=timings,
        feature_counts=feature_counts,
        index_summaries=index_summaries,
        ranking_count=ranking_count,
        candidate_count=candidate_count,
        review_eligible_count=review_eligible_count,
        queue_count=queue_count,
        null_iteration_count=null_iteration_count,
        evaluation_count=evaluation_count,
        acceptance_status=acceptance_status,
        approximate_peak_memory_bytes=resource_guard.peak_rss_bytes,
    )


def run_lexical_pipeline(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
    force: bool = False,
    resume_staging_dir: Path | None = None,
) -> LexicalPipelineResult:
    """Run M7 with an execution-attempt sidecar outside lexical schema-v1."""
    project_root = Path.cwd().resolve()
    recorder = ExperimentExecutionRecorder.begin(
        experiment_name="m7-lexical-baseline",
        experiment_version="m7-lexical-baseline-v1",
        project_root=project_root,
        output_dir=output_dir,
        configuration_files=_M7_CONFIGURATION_FILES,
        dataset_manifest_path=_M7_DATASET_MANIFEST_PATH,
        runtime_versions={
            "duckdb": duckdb.__version__,
            "polars": pl.__version__,
        },
        reproduction_command=_m7_reproduction_command(
            database_path=database_path,
            output_dir=output_dir,
            force=force,
            project_root=project_root,
        ),
        resume_staging_dir=resume_staging_dir,
    )
    checkpoint_quarantine = _PrivateCheckpointQuarantine(output_dir=output_dir)
    try:
        result = _run_lexical_pipeline_impl(
            database_path=database_path,
            output_dir=output_dir,
            force=force,
            resume_staging_dir=resume_staging_dir,
            execution_recorder=recorder,
            checkpoint_quarantine=checkpoint_quarantine,
        )
        completion_warnings = (
            []
            if result.acceptance_status == "scientifically_complete"
            else [
                "pipeline execution completed, but the frozen scientific "
                f"acceptance status is {result.acceptance_status}"
            ]
        )
        recorder.finalize_success(
            stage_runtime_seconds=result.stage_runtime_seconds,
            warnings=completion_warnings,
        )
    except BaseException as error:
        try:
            checkpoint_quarantine.preserve_after_failure(error)
        except Exception as preservation_error:
            error.add_note(
                "private checkpoint failure preservation could not be completed: "
                f"{type(preservation_error).__name__}: {preservation_error}"
            )
        try:
            recorder.finalize_failure(error)
        except Exception as provenance_error:
            error.add_note(
                "execution failure provenance could not be finalized: "
                f"{type(provenance_error).__name__}: {provenance_error}"
            )
        raise
    cleanup_warning = checkpoint_quarantine.cleanup_after_success()
    if cleanup_warning is not None:
        warnings.warn(cleanup_warning, RuntimeWarning, stacklevel=2)
    return result
