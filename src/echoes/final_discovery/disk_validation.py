"""Bounded strict validation for production final-discovery ledgers.

The small in-memory validator remains the readable scientific oracle.  This
module enforces the same contracts against canonical ordered JSONL ledgers
while retaining only one evidence pair or one output row in Python.  DuckDB
holds the cross-ledger state, performs external joins and BH ranking, and may
spill only to the caller-supplied temporary directory.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self, cast

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.final_discovery import validation as memory_validation
from echoes.final_discovery.config import (
    DetectorRegistration,
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
)
from echoes.final_discovery.features import candidate_pair_id, evidence_id
from echoes.final_discovery.knownness import KnownnessIndex, KnownRelationship
from echoes.final_discovery.models import (
    EvidenceRow,
    FinalCandidate,
    KnownnessStatus,
    PassageRecord,
    QualityFlags,
)
from echoes.final_discovery.nulls import EnsembleNullCalibrationRow
from echoes.final_discovery.stages import (
    FINAL_DISCOVERY_STAGE_IDS,
    StageRegistrationLike,
    StageStore,
    StageStoreError,
    assert_stage_registrations,
)
from echoes.final_discovery.storage import (
    FinalDiscoveryStorageError,
    inspect_jsonl_file,
    iter_canonical_jsonl,
    write_json_atomic_new,
)
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    ValidationFinding,
)

_MINIMUM_MEMORY_BYTES = 256 * 1024**2
_MINIMUM_TEMP_FREE_BYTES = 256 * 1024**2
_MAXIMUM_DECODED_FETCH_ROWS = 4_096
_REPORT_FILE_NAME = "validation-report.json"
_RECEIPT_FILE_NAME = "validation-receipt.json"


class DiskFinalDiscoveryValidationError(ValueError):
    """Raised when strict disk validation cannot execute safely."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiskValidationInputReceipt(_FrozenModel):
    """Physical identity and required ordering for one governed ledger."""

    role: Literal["evidence", "candidates", "full_null", "remove_all_english_null"]
    file_name: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ordering: str = Field(min_length=1)
    canonical_jsonl_required: Literal[True]


class DiskValidationResourceReceipt(_FrozenModel):
    """Declared and observed bounds for the validation execution."""

    duckdb_memory_limit_bytes: int = Field(ge=_MINIMUM_MEMORY_BYTES)
    duckdb_threads: int = Field(ge=1, le=64)
    ingestion_batch_size: int = Field(ge=1)
    maximum_decoded_rows_per_fetch: int = Field(ge=1, le=_MAXIMUM_DECODED_FETCH_ROWS)
    finding_limit: int = Field(ge=1)
    minimum_temp_free_bytes: int = Field(ge=_MINIMUM_TEMP_FREE_BYTES)
    initial_temp_free_bytes: int = Field(ge=0)
    duckdb_database_peak_bytes: int = Field(ge=0)
    maximum_evidence_rows_retained_per_pair: int = Field(ge=0)
    full_ledgers_retained_in_python: Literal[False]
    duckdb_state_persisted: Literal[False]


class DiskFinalDiscoveryValidationReceipt(_FrozenModel):
    """Portable identity for a completed strict validation attempt."""

    schema_version: Literal[1] = 1
    algorithm: Literal["disk-backed-final-discovery-strict-validation-v1"] = (
        "disk-backed-final-discovery-strict-validation-v1"
    )
    experiment_id: Literal["final-discovery-v1"]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inputs: tuple[DiskValidationInputReceipt, ...] = Field(min_length=4, max_length=4)
    passage_count: int = Field(ge=0)
    passage_logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    known_relationship_count: int = Field(ge=0)
    knownness_logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_pair_count: int = Field(ge=0)
    authenticated_stage_count: int = Field(ge=0, le=11)
    expected_authenticated_stage_count: int | None = Field(default=None, ge=0, le=11)
    validation_passed: bool
    retained_finding_count: int = Field(ge=0)
    total_finding_count: int = Field(ge=0)
    findings_truncated: bool
    report_file_name: Literal["validation-report.json"] = "validation-report.json"
    report_size_bytes: int = Field(ge=1)
    report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    resource_bounds: DiskValidationResourceReceipt

    @model_validator(mode="after")
    def counts_and_result_reconcile(self) -> Self:
        if tuple(item.role for item in self.inputs) != (
            "evidence",
            "candidates",
            "full_null",
            "remove_all_english_null",
        ):
            raise ValueError("disk validation input receipts are not in canonical role order")
        if self.retained_finding_count > self.total_finding_count:
            raise ValueError("retained findings cannot exceed total findings")
        if self.findings_truncated != (self.total_finding_count > self.retained_finding_count):
            raise ValueError("disk validation finding truncation flag is inconsistent")
        if self.validation_passed != (self.total_finding_count == 0):
            raise ValueError("disk validation pass state differs from its finding count")
        return self


@dataclass(frozen=True, slots=True)
class DiskFinalDiscoveryValidationResult:
    """Published report and receipt for one bounded validation execution."""

    output_directory: Path
    report_path: Path
    receipt_path: Path
    report: FinalDiscoveryValidationReport
    receipt: DiskFinalDiscoveryValidationReceipt


@dataclass(slots=True)
class _FindingCollector:
    limit: int
    findings: list[ValidationFinding]
    total_count: int = 0

    def add(self, code: str, message: str, pair_id: str | None = None) -> None:
        self.total_count += 1
        if len(self.findings) < self.limit:
            self.findings.append(
                ValidationFinding(
                    code=code,
                    message=message,
                    candidate_pair_id=pair_id,
                )
            )

    def extend(self, findings: Iterable[ValidationFinding]) -> None:
        for finding in findings:
            self.add(finding.code, finding.message, finding.candidate_pair_id)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _model_json(model: BaseModel) -> str:
    return _canonical_json_bytes(model.model_dump(mode="json", exclude_none=False)).decode("ascii")


def _quoted_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _input_receipt(
    path: Path,
    *,
    role: Literal["evidence", "candidates", "full_null", "remove_all_english_null"],
    ordering: str,
) -> DiskValidationInputReceipt:
    if not path.is_file() or path.is_symlink():
        raise DiskFinalDiscoveryValidationError(
            f"strict validation input is missing or unsafe: {path}"
        )
    inspected = inspect_jsonl_file(path)
    return DiskValidationInputReceipt(
        role=role,
        file_name=path.name,
        row_count=inspected.row_count,
        size_bytes=inspected.size_bytes,
        sha256=inspected.sha256,
        ordering=ordering,
        canonical_jsonl_required=True,
    )


def _sha256_rows(rows: Iterable[object]) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        payload = _canonical_json_bytes(row)
        digest.update(struct.pack(">Q", len(payload)))
        digest.update(payload)
        count += 1
    return count, digest.hexdigest()


def _flush_batch(
    connection: duckdb.DuckDBPyConnection,
    statement: str,
    rows: list[tuple[object, ...]],
) -> None:
    if rows:
        connection.executemany(statement, rows)
        rows.clear()


def _first_row(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] | None = None,
) -> tuple[object, ...] | None:
    row = connection.execute(query, parameters or []).fetchone()
    return cast(tuple[object, ...] | None, row)


def _close(left: float, right: float, *, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE evidence_identity (
            evidence_id VARCHAR NOT NULL,
            candidate_pair_id VARCHAR NOT NULL,
            detector_id VARCHAR NOT NULL,
            source_artifact_id VARCHAR NOT NULL,
            source_artifact_sha256 VARCHAR NOT NULL
        );
        CREATE TABLE drafts (
            candidate_pair_id VARCHAR NOT NULL,
            passage_a_id VARCHAR NOT NULL,
            passage_b_id VARCHAR NOT NULL,
            passage_a_reference VARCHAR NOT NULL,
            passage_b_reference VARCHAR NOT NULL,
            ensemble_score DOUBLE NOT NULL,
            score_without_english DOUBLE NOT NULL,
            evidence_ids_json VARCHAR NOT NULL,
            detector_ids_json VARCHAR NOT NULL,
            families_json VARCHAR NOT NULL,
            qualifying_groups_json VARCHAR NOT NULL,
            original_groups_json VARCHAR NOT NULL,
            original_families_json VARCHAR NOT NULL,
            contains_english BOOLEAN NOT NULL,
            quality_json VARCHAR NOT NULL,
            quality_basic_exclusion BOOLEAN NOT NULL,
            source_statuses_json VARCHAR NOT NULL,
            source_relationship_ids_json VARCHAR NOT NULL
        );
        CREATE TABLE candidates (
            row_index BIGINT NOT NULL,
            candidate_pair_id VARCHAR NOT NULL,
            ensemble_score DOUBLE NOT NULL,
            tier_a_eligible BOOLEAN NOT NULL,
            tier_b_rank BIGINT,
            raw_json VARCHAR NOT NULL
        );
        CREATE TABLE full_null (
            candidate_pair_id VARCHAR NOT NULL,
            calibration_scope VARCHAR NOT NULL,
            stratum VARCHAR NOT NULL,
            stratum_size BIGINT NOT NULL,
            observed_score DOUBLE NOT NULL,
            null_exceedance_count BIGINT NOT NULL,
            effective_null_cell_count BIGINT NOT NULL,
            empirical_p_value DOUBLE NOT NULL,
            null_discovery_count_sum BIGINT NOT NULL,
            mean_null_discovery_count DOUBLE NOT NULL,
            observed_discovery_count BIGINT NOT NULL,
            raw_empirical_fdr DOUBLE NOT NULL,
            empirical_fdr DOUBLE NOT NULL,
            minimum_attainable_p_value DOUBLE NOT NULL,
            minimum_effective_null_draws BIGINT NOT NULL,
            stratum_sufficient_for_bh BOOLEAN NOT NULL,
            hypothesis_count BIGINT NOT NULL,
            iterations BIGINT NOT NULL,
            seed BIGINT NOT NULL,
            null_method VARCHAR NOT NULL
        );
        CREATE TABLE ablated_null AS SELECT * FROM full_null WHERE false;
        CREATE TABLE known_relationships (
            relationship_id VARCHAR NOT NULL,
            source_passage_id VARCHAR NOT NULL,
            target_passage_id VARCHAR NOT NULL,
            low_passage_id VARCHAR NOT NULL,
            high_passage_id VARCHAR NOT NULL
        );
        CREATE TABLE expected_base (
            candidate_pair_id VARCHAR NOT NULL,
            ensemble_score DOUBLE NOT NULL,
            tier_a_eligible BOOLEAN NOT NULL,
            knownness_status VARCHAR NOT NULL,
            quality_basic_exclusion BOOLEAN NOT NULL,
            payload_json VARCHAR NOT NULL
        );
        CREATE TABLE expected_candidates (
            candidate_pair_id VARCHAR NOT NULL,
            raw_json VARCHAR NOT NULL
        );
        """
    )


def _quality(
    left: PassageRecord, right: PassageRecord, rows: Sequence[EvidenceRow]
) -> QualityFlags:
    source = tuple(row.source_quality for row in rows if row.source_quality is not None)

    def source_flag(name: str) -> bool:
        return any(bool(getattr(flags, name)) for flags in source)

    return QualityFlags(
        disputed_passage=(
            left.disputed_passage or right.disputed_passage or source_flag("disputed_passage")
        ),
        reference_gap=left.reference_gap or right.reference_gap or source_flag("reference_gap"),
        ketiv_uncertainty=(
            left.ketiv_uncertainty or right.ketiv_uncertainty or source_flag("ketiv_uncertainty")
        ),
        formulaic_language=(
            left.formulaic_language or right.formulaic_language or source_flag("formulaic_language")
        ),
        overlapping_passages=source_flag("overlapping_passages"),
        unresolved_data_error=source_flag("unresolved_data_error"),
        invalid_trace=source_flag("invalid_trace"),
        local_context=source_flag("local_context"),
        exact_or_near_duplicate=source_flag("exact_or_near_duplicate"),
        same_reference_sensitivity=(
            source_flag("same_reference_sensitivity")
            or (
                left.reference == right.reference
                and (
                    left.passage_id != right.passage_id
                    or left.analysis_profile != right.analysis_profile
                    or left.analysis_reading != right.analysis_reading
                )
            )
        ),
    )


def _group_scores(
    rows: Sequence[EvidenceRow],
    *,
    remove_all_english: bool,
) -> dict[str, float]:
    maxima: dict[str, float] = {}
    for row in rows:
        score = row.normalized_score
        if remove_all_english and row.contains_english_derived_evidence:
            if row.english_ablation_normalized_score is None:
                continue
            score = row.english_ablation_normalized_score
        maxima[row.independence_group] = max(maxima.get(row.independence_group, 0.0), score)
    return maxima


def _weighted_score(scores: Mapping[str, float], config: FinalDiscoveryConfig) -> float:
    return math.fsum(
        weight * scores.get(group, config.ensemble.missing_group_score)
        for group, weight in config.ensemble.group_weights.items()
    )


def _validate_evidence_row(
    row: EvidenceRow,
    *,
    config: FinalDiscoveryConfig,
    registrations: Mapping[str, DetectorRegistration],
    expected_source_artifact_sha256: Mapping[str, str] | None,
    collector: _FindingCollector,
) -> None:
    expected_pair_id = candidate_pair_id(row.passage_a_id, row.passage_b_id)
    if row.candidate_pair_id != expected_pair_id:
        collector.add(
            "evidence-candidate-pair-id",
            f"evidence {row.evidence_id} has a noncanonical candidate-pair ID",
            row.candidate_pair_id,
        )
    expected_evidence_id = evidence_id(
        row.candidate_pair_id,
        row.detector_id,
        row.source_artifact_sha256,
    )
    if row.evidence_id != expected_evidence_id:
        collector.add(
            "evidence-id",
            f"evidence {row.evidence_id} does not match its hashed identity payload",
            row.candidate_pair_id,
        )
    expected_hash = (
        expected_source_artifact_sha256.get(row.source_artifact_id)
        if expected_source_artifact_sha256 is not None
        else None
    )
    if expected_hash is not None and expected_hash != row.source_artifact_sha256:
        collector.add(
            "source-artifact-hash",
            f"source artifact {row.source_artifact_id} does not match its authenticated hash",
            row.candidate_pair_id,
        )
    registration = registrations.get(row.detector_id)
    if registration is None:
        collector.add(
            "unregistered-detector",
            f"evidence {row.evidence_id} uses unregistered detector {row.detector_id}",
            row.candidate_pair_id,
        )
    else:
        registered_values = (
            registration.family,
            registration.independence_group,
            registration.normalization,
            registration.null_family,
        )
        observed_values = (
            row.family,
            row.independence_group,
            row.normalization_method,
            row.null_method,
        )
        if observed_values != registered_values:
            collector.add(
                "detector-registration-lineage",
                f"evidence {row.evidence_id} disagrees with detector registration",
                row.candidate_pair_id,
            )
        expected_independence = registration.counts_for_independence and (
            not row.contains_english_derived_evidence or row.original_language_evidence_remains
        )
        if row.counts_for_independence != expected_independence:
            collector.add(
                "detector-independence-registration",
                f"evidence {row.evidence_id} has unregistered independence semantics",
                row.candidate_pair_id,
            )
        if (
            row.contains_english_derived_evidence
            and not registration.contains_english_derived_evidence
        ) or (
            row.original_language_evidence_remains and not registration.original_language_capable
        ):
            collector.add(
                "detector-language-registration",
                f"evidence {row.evidence_id} has unregistered language semantics",
                row.candidate_pair_id,
            )
    local_findings: list[ValidationFinding] = []
    trace = memory_validation._trace_object(
        row,
        require_canonical=True,
        findings=local_findings,
    )
    if trace is not None:
        if row.detector_id == "m7_lexical_rrf":
            memory_validation._validate_m7_trace(
                row,
                trace,
                config=config,
                findings=local_findings,
            )
        elif row.detector_id in {
            "multilingual_e5_original_language",
            "multilingual_e5_english_gloss",
        }:
            memory_validation._validate_embedding_trace(
                row,
                trace,
                config=config,
                findings=local_findings,
            )
    collector.extend(local_findings)


def _draft_tuple(
    pair_id: str,
    pair_rows: Sequence[EvidenceRow],
    passages: Mapping[str, PassageRecord],
    config: FinalDiscoveryConfig,
    collector: _FindingCollector,
) -> tuple[object, ...] | None:
    rows = tuple(sorted(pair_rows, key=lambda item: item.evidence_id))
    passage_pairs = {(row.passage_a_id, row.passage_b_id) for row in rows}
    if len(passage_pairs) != 1:
        collector.add(
            "evidence-passage-pair-conflict",
            "retained evidence for a candidate points to multiple passage pairs",
            pair_id,
        )
        return None
    passage_a_id, passage_b_id = next(iter(passage_pairs))
    left = passages.get(passage_a_id)
    right = passages.get(passage_b_id)
    if left is None or right is None:
        collector.add(
            "evidence-passage-missing",
            f"candidate evidence references absent passages {passage_a_id}/{passage_b_id}",
            pair_id,
        )
        return None
    if left.passage_id != passage_a_id or right.passage_id != passage_b_id:
        collector.add(
            "passage-index-key",
            "passage mapping keys disagree with persisted passage IDs",
            pair_id,
        )
        return None
    full_scores = _group_scores(rows, remove_all_english=False)
    ablated_scores = _group_scores(rows, remove_all_english=True)
    threshold = config.ensemble.qualifying_group_normalized_score
    qualifying = {
        row.independence_group
        for row in rows
        if row.counts_for_independence and row.normalized_score >= threshold
    }
    original: set[str] = set()
    for row in rows:
        ablated_row_score = (
            row.normalized_score
            if not row.contains_english_derived_evidence
            else row.english_ablation_normalized_score
        )
        if (
            row.counts_for_independence
            and row.original_language_evidence_remains
            and ablated_row_score is not None
            and ablated_row_score >= threshold
        ):
            original.add(row.independence_group)
    original_families = {
        row.family
        for row in rows
        if row.independence_group in original
        and row.counts_for_independence
        and row.original_language_evidence_remains
    }
    quality = _quality(left, right, rows)
    source_statuses = tuple(
        sorted(
            {
                row.source_knownness_status
                for row in rows
                if row.source_knownness_status not in {None, "unknown"}
            }
        )
    )
    source_relationship_ids = tuple(
        sorted(
            {
                relationship_id
                for row in rows
                for relationship_id in row.source_known_relationship_ids
            }
        )
    )
    return (
        pair_id,
        passage_a_id,
        passage_b_id,
        left.reference,
        right.reference,
        _weighted_score(full_scores, config),
        _weighted_score(ablated_scores, config),
        _canonical_json_bytes([row.evidence_id for row in rows]).decode("ascii"),
        _canonical_json_bytes(sorted({row.detector_id for row in rows})).decode("ascii"),
        _canonical_json_bytes(sorted({row.family for row in rows})).decode("ascii"),
        _canonical_json_bytes(sorted(qualifying)).decode("ascii"),
        _canonical_json_bytes(sorted(original)).decode("ascii"),
        _canonical_json_bytes(sorted(original_families)).decode("ascii"),
        any(row.contains_english_derived_evidence for row in rows),
        _model_json(quality),
        quality.basic_exclusion,
        _canonical_json_bytes(source_statuses).decode("ascii"),
        _canonical_json_bytes(source_relationship_ids).decode("ascii"),
    )


def _ingest_evidence(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    passages: Mapping[str, PassageRecord],
    config: FinalDiscoveryConfig,
    expected_source_artifact_sha256: Mapping[str, str] | None,
    collector: _FindingCollector,
    batch_size: int,
) -> tuple[int, int, int]:
    evidence_rows: list[tuple[object, ...]] = []
    draft_rows: list[tuple[object, ...]] = []
    registrations = {registration.detector_id: registration for registration in config.detectors}
    current_pair_id: str | None = None
    current_pair_rows: list[EvidenceRow] = []
    prior_key: tuple[str, str] | None = None
    evidence_count = 0
    pair_count = 0
    maximum_pair_rows = 0

    def finish_pair() -> None:
        nonlocal pair_count, maximum_pair_rows
        if current_pair_id is None:
            return
        pair_count += 1
        maximum_pair_rows = max(maximum_pair_rows, len(current_pair_rows))
        prepared = _draft_tuple(
            current_pair_id,
            current_pair_rows,
            passages,
            config,
            collector,
        )
        if prepared is not None:
            draft_rows.append(prepared)
            if len(draft_rows) >= batch_size:
                _flush_batch(
                    connection,
                    "INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    draft_rows,
                )

    for row in iter_canonical_jsonl(path, EvidenceRow):
        key = (row.candidate_pair_id, row.detector_id)
        if prior_key is not None and key <= prior_key:
            raise DiskFinalDiscoveryValidationError(
                "evidence ledger must be strictly ordered by candidate_pair_id,detector_id"
            )
        prior_key = key
        if current_pair_id is not None and row.candidate_pair_id != current_pair_id:
            finish_pair()
            current_pair_rows = []
        current_pair_id = row.candidate_pair_id
        current_pair_rows.append(row)
        _validate_evidence_row(
            row,
            config=config,
            registrations=registrations,
            expected_source_artifact_sha256=expected_source_artifact_sha256,
            collector=collector,
        )
        evidence_rows.append(
            (
                row.evidence_id,
                row.candidate_pair_id,
                row.detector_id,
                row.source_artifact_id,
                row.source_artifact_sha256,
            )
        )
        evidence_count += 1
        if len(evidence_rows) >= batch_size:
            _flush_batch(
                connection,
                "INSERT INTO evidence_identity VALUES (?,?,?,?,?)",
                evidence_rows,
            )
    finish_pair()
    _flush_batch(
        connection,
        "INSERT INTO evidence_identity VALUES (?,?,?,?,?)",
        evidence_rows,
    )
    _flush_batch(
        connection,
        "INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        draft_rows,
    )
    duplicate_evidence = _first_row(
        connection,
        """
        SELECT evidence_id,min(candidate_pair_id)
        FROM evidence_identity
        GROUP BY evidence_id HAVING count(*)<>1
        ORDER BY evidence_id LIMIT 1
        """,
    )
    if duplicate_evidence is not None:
        collector.add(
            "duplicate-evidence-id",
            "evidence IDs are not unique",
            str(duplicate_evidence[1]),
        )
    conflicting_source = _first_row(
        connection,
        """
        SELECT source_artifact_id,min(candidate_pair_id)
        FROM evidence_identity
        GROUP BY source_artifact_id
        HAVING count(DISTINCT source_artifact_sha256)<>1
        ORDER BY source_artifact_id LIMIT 1
        """,
    )
    if conflicting_source is not None:
        collector.add(
            "source-artifact-hash-conflict",
            f"source artifact {conflicting_source[0]} carries multiple SHA-256 values",
            str(conflicting_source[1]),
        )
    return evidence_count, pair_count, maximum_pair_rows


def _ingest_candidates(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    collector: _FindingCollector,
    batch_size: int,
) -> tuple[int, int, int]:
    rows: list[tuple[object, ...]] = []
    prior_key: tuple[float, str] | None = None
    candidate_count = 0
    tier_a_count = 0
    tier_b_count = 0
    for row_index, candidate in enumerate(iter_canonical_jsonl(path, FinalCandidate)):
        key = (-candidate.ensemble_score, candidate.candidate_pair_id)
        if prior_key is not None and key < prior_key:
            collector.add(
                "candidate-output-order",
                "candidate ledger is not sorted by descending score and stable pair ID",
                candidate.candidate_pair_id,
            )
        prior_key = key
        expected_id = candidate_pair_id(candidate.passage_a_id, candidate.passage_b_id)
        if candidate.candidate_pair_id != expected_id:
            collector.add(
                "candidate-id",
                "candidate-pair ID does not match the persisted passage identity",
                candidate.candidate_pair_id,
            )
        rows.append(
            (
                row_index,
                candidate.candidate_pair_id,
                candidate.ensemble_score,
                candidate.tier_a_eligible,
                candidate.tier_b_rank,
                _model_json(candidate),
            )
        )
        candidate_count += 1
        tier_a_count += int(candidate.tier_a_eligible)
        tier_b_count += int(candidate.tier_b_rank is not None)
        if len(rows) >= batch_size:
            _flush_batch(connection, "INSERT INTO candidates VALUES (?,?,?,?,?,?)", rows)
    _flush_batch(connection, "INSERT INTO candidates VALUES (?,?,?,?,?,?)", rows)
    duplicate = _first_row(
        connection,
        """
        SELECT candidate_pair_id FROM candidates
        GROUP BY candidate_pair_id HAVING count(*)<>1
        ORDER BY candidate_pair_id LIMIT 1
        """,
    )
    if duplicate is not None:
        collector.add("duplicate-candidate-id", "candidate IDs are not unique")
    return candidate_count, tier_a_count, tier_b_count


def _null_insert_tuple(row: EnsembleNullCalibrationRow) -> tuple[object, ...]:
    return (
        row.candidate_pair_id,
        row.calibration_scope,
        row.stratum,
        row.stratum_size,
        row.observed_score,
        row.null_exceedance_count,
        row.effective_null_cell_count,
        row.empirical_p_value,
        row.null_discovery_count_sum,
        row.mean_null_discovery_count,
        row.observed_discovery_count,
        row.raw_empirical_fdr,
        row.empirical_fdr,
        row.minimum_attainable_p_value,
        row.minimum_effective_null_draws,
        row.stratum_sufficient_for_bh,
        row.hypothesis_count,
        row.iterations,
        row.seed,
        row.null_method,
    )


def _ingest_null_ledger(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    table: Literal["full_null", "ablated_null"],
    batch_size: int,
) -> int:
    rows: list[tuple[object, ...]] = []
    previous_pair_id: str | None = None
    count = 0
    for row in iter_canonical_jsonl(path, EnsembleNullCalibrationRow):
        if previous_pair_id is not None and row.candidate_pair_id <= previous_pair_id:
            raise DiskFinalDiscoveryValidationError(
                f"{table} ledger must be strictly candidate_pair_id ordered"
            )
        previous_pair_id = row.candidate_pair_id
        rows.append(_null_insert_tuple(row))
        count += 1
        if len(rows) >= batch_size:
            _flush_batch(connection, f"INSERT INTO {table} VALUES ({','.join('?' * 20)})", rows)
    _flush_batch(connection, f"INSERT INTO {table} VALUES ({','.join('?' * 20)})", rows)
    return count


def _iter_index_relationships(index: KnownnessIndex) -> Iterator[tuple[str, str, str]]:
    state = vars(index).get("_directed")
    if not isinstance(state, Mapping):
        raise DiskFinalDiscoveryValidationError("knownness index has no readable directed state")
    directed = cast(Mapping[tuple[str, str], Sequence[str]], state)
    for (source_id, target_id), relationship_ids in directed.items():
        for relationship_id in relationship_ids:
            yield str(relationship_id), str(source_id), str(target_id)


def _ingest_knownness(
    connection: duckdb.DuckDBPyConnection,
    knownness: KnownnessIndex | Iterable[KnownRelationship],
    *,
    batch_size: int,
) -> None:
    rows: list[tuple[object, ...]] = []
    source_rows: Iterable[tuple[str, str, str]]
    if isinstance(knownness, KnownnessIndex):
        source_rows = _iter_index_relationships(knownness)
    else:
        source_rows = (
            (
                relationship.relationship_id,
                relationship.source_passage_id,
                relationship.target_passage_id,
            )
            for relationship in knownness
        )
    for relationship_id, source_id, target_id in source_rows:
        if not relationship_id or not source_id or not target_id or source_id == target_id:
            raise DiskFinalDiscoveryValidationError("knownness iterable contains an invalid row")
        low_id, high_id = sorted((source_id, target_id))
        rows.append((relationship_id, source_id, target_id, low_id, high_id))
        if len(rows) >= batch_size:
            _flush_batch(
                connection,
                "INSERT INTO known_relationships VALUES (?,?,?,?,?)",
                rows,
            )
    _flush_batch(
        connection,
        "INSERT INTO known_relationships VALUES (?,?,?,?,?)",
        rows,
    )
    duplicate = _first_row(
        connection,
        """
        SELECT relationship_id FROM known_relationships
        GROUP BY relationship_id
        HAVING count(DISTINCT (source_passage_id,target_passage_id))<>1
        ORDER BY relationship_id LIMIT 1
        """,
    )
    if duplicate is not None:
        raise DiskFinalDiscoveryValidationError(
            f"known relationship ID maps to multiple pairs: {duplicate[0]}"
        )
    connection.execute(
        """
        CREATE TEMP TABLE known_relationships_distinct AS
        SELECT DISTINCT * FROM known_relationships;
        DELETE FROM known_relationships;
        INSERT INTO known_relationships SELECT * FROM known_relationships_distinct;
        DROP TABLE known_relationships_distinct;
        """
    )


def _record_query_finding(
    connection: duckdb.DuckDBPyConnection,
    collector: _FindingCollector,
    *,
    query: str,
    code: str,
    message: str,
) -> None:
    row = _first_row(connection, query)
    if row is not None:
        pair_id = str(row[0]) if row and row[0] is not None else None
        collector.add(code, message, pair_id)


def _validate_null_table(
    connection: duckdb.DuckDBPyConnection,
    *,
    table: Literal["full_null", "ablated_null"],
    scope: Literal["full", "remove_all_english"],
    score_column: Literal["ensemble_score", "score_without_english"],
    config: FinalDiscoveryConfig,
    collector: _FindingCollector,
) -> None:
    scope_name = "full" if scope == "full" else "english-ablation"
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT coalesce(d.candidate_pair_id,n.candidate_pair_id)
            FROM drafts d FULL OUTER JOIN {table} n USING (candidate_pair_id)
            WHERE d.candidate_pair_id IS NULL OR n.candidate_pair_id IS NULL
            ORDER BY 1 LIMIT 1
        """,
        code=f"{scope_name}-null-coverage",
        message=f"{scope_name} null coverage differs from the exact evidence population",
    )
    expected_seed = config.calibration.seeds["stratified_permutation"]
    permitted = (
        config.calibration.fixture_iterations,
        config.calibration.production_iterations,
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            WITH population AS (SELECT count(*)::BIGINT AS n FROM drafts),
            stratum_counts AS (
                SELECT n.stratum,count(*)::BIGINT AS n
                FROM {table} n JOIN drafts d USING (candidate_pair_id)
                GROUP BY n.stratum
            )
            SELECT n.candidate_pair_id
            FROM {table} n
            JOIN drafts d USING (candidate_pair_id)
            JOIN stratum_counts s USING (stratum)
            CROSS JOIN population p
            WHERE n.calibration_scope<>'{scope}'
               OR n.null_method<>'{config.ensemble.final_null_method}'
               OR n.seed<>{expected_seed}
               OR n.iterations NOT IN ({permitted[0]},{permitted[1]})
               OR n.hypothesis_count<>p.n
               OR n.stratum_size<>s.n
            ORDER BY n.candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-provenance",
        message=f"{scope_name} null row has inconsistent registered provenance",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT n.candidate_pair_id
            FROM {table} n JOIN drafts d USING (candidate_pair_id)
            WHERE abs(n.observed_score-d.{score_column})>1e-15
               OR NOT isfinite(n.observed_score)
            ORDER BY n.candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-observed-score",
        message=f"{scope_name} null observed score differs from recomputed ensemble score",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT candidate_pair_id FROM {table}
            WHERE effective_null_cell_count<>stratum_size*iterations
               OR null_exceedance_count>effective_null_cell_count
               OR abs(
                    empirical_p_value-
                    (null_exceedance_count+1.0)/(effective_null_cell_count+1.0)
                  )>1e-15
               OR abs(
                    minimum_attainable_p_value-
                    1.0/(effective_null_cell_count+1.0)
                  )>1e-15
            ORDER BY candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-p-value-invariant",
        message=f"{scope_name} null p-value/count invariants fail",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT candidate_pair_id FROM {table}
            WHERE null_discovery_count_sum>iterations*hypothesis_count
               OR abs(
                    mean_null_discovery_count-
                    (null_discovery_count_sum+1.0)/(iterations+1.0)
                  )>1e-15
               OR abs(
                    raw_empirical_fdr-
                    least(mean_null_discovery_count/observed_discovery_count,1.0)
                  )>1e-15
               OR empirical_fdr+1e-15<raw_empirical_fdr
            ORDER BY candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-fdr-invariant",
        message=f"{scope_name} null discovery/FDR invariants fail",
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {table}_score_counts AS
        WITH bins AS (
            SELECT {score_column} AS score,count(*)::BIGINT AS bin_count
            FROM drafts GROUP BY {score_column}
        )
        SELECT score,
               sum(bin_count) OVER (
                   ORDER BY score DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               )::BIGINT AS observed_count
        FROM bins
        """
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT n.candidate_pair_id
            FROM {table} n
            LEFT JOIN {table}_score_counts counts ON counts.score=n.observed_score
            WHERE counts.observed_count IS NULL
               OR n.observed_discovery_count<>counts.observed_count
            ORDER BY n.candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-observed-discoveries",
        message=f"{scope_name} null observed discovery count is not reproducible",
    )
    minimum_draws = config.calibration.minimum_effective_null_draws
    production_iterations = config.calibration.production_iterations
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT candidate_pair_id FROM {table}
            WHERE minimum_effective_null_draws<>
                  CASE WHEN iterations={production_iterations}
                       THEN {minimum_draws} ELSE iterations END
               OR stratum_sufficient_for_bh<>
                  (effective_null_cell_count>=
                   CASE WHEN iterations={production_iterations}
                        THEN {minimum_draws} ELSE iterations END)
            ORDER BY candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-resolution",
        message=f"{scope_name} null BH-resolution fields violate the execution mode",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT min(candidate_pair_id) FROM {table}
            GROUP BY observed_score
            HAVING count(DISTINCT null_discovery_count_sum)>1
                OR min(mean_null_discovery_count)<>max(mean_null_discovery_count)
                OR count(DISTINCT observed_discovery_count)>1
                OR min(raw_empirical_fdr)<>max(raw_empirical_fdr)
                OR min(empirical_fdr)<>max(empirical_fdr)
            ORDER BY min(candidate_pair_id) LIMIT 1
        """,
        code=f"{scope_name}-null-threshold-global-state",
        message=f"equal {scope_name} thresholds carry different global null statistics",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            SELECT min(candidate_pair_id) FROM {table}
            GROUP BY stratum,observed_score
            HAVING count(DISTINCT null_exceedance_count)>1
                OR count(DISTINCT effective_null_cell_count)>1
                OR min(empirical_p_value)<>max(empirical_p_value)
            ORDER BY min(candidate_pair_id) LIMIT 1
        """,
        code=f"{scope_name}-null-threshold-stratum-state",
        message=f"equal stratum thresholds carry different {scope_name} p-value state",
    )
    _record_query_finding(
        connection,
        collector,
        query=f"""
            WITH thresholds AS (
                SELECT observed_score,min(raw_empirical_fdr) AS raw_fdr
                FROM {table} GROUP BY observed_score
            ), expected AS (
                SELECT observed_score,
                       max(raw_fdr) OVER (
                           ORDER BY observed_score DESC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS expected_fdr
                FROM thresholds
            )
            SELECT n.candidate_pair_id
            FROM {table} n JOIN expected USING (observed_score)
            WHERE abs(n.empirical_fdr-expected.expected_fdr)>1e-15
            ORDER BY n.candidate_pair_id LIMIT 1
        """,
        code=f"{scope_name}-null-monotone-fdr",
        message=f"{scope_name} null FDR is not the exact monotone envelope",
    )


def _create_knownness_and_q_state(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE known_pair_state AS
        SELECT
            d.candidate_pair_id,
            coalesce(
                bool_or(k.source_passage_id=d.passage_a_id)
                    FILTER (WHERE k.relationship_id IS NOT NULL),
                false
            ) AS known_forward,
            coalesce(
                bool_or(k.source_passage_id=d.passage_b_id)
                    FILTER (WHERE k.relationship_id IS NOT NULL),
                false
            ) AS known_reverse,
            coalesce(
                to_json(
                    list(DISTINCT k.relationship_id ORDER BY k.relationship_id)
                    FILTER (WHERE k.relationship_id IS NOT NULL)
                ),
                '[]'
            ) AS known_relationship_ids_json
        FROM drafts d
        LEFT JOIN known_relationships k
          ON k.low_passage_id=d.passage_a_id
         AND k.high_passage_id=d.passage_b_id
        GROUP BY d.candidate_pair_id;

        CREATE TABLE full_q AS
        WITH ranked AS (
            SELECT
                candidate_pair_id,
                empirical_p_value,
                row_number() OVER (
                    ORDER BY empirical_p_value,candidate_pair_id
                )::BIGINT AS bh_rank,
                count(*) OVER ()::BIGINT AS hypothesis_count
            FROM full_null
        ), candidates AS (
            SELECT *,least(
                empirical_p_value*hypothesis_count/bh_rank,
                1.0
            ) AS candidate_q
            FROM ranked
        )
        SELECT
            candidate_pair_id,
            min(candidate_q) OVER (
                ORDER BY bh_rank
                ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
            ) AS q_value
        FROM candidates;

        CREATE TABLE ablated_q AS
        WITH ranked AS (
            SELECT
                candidate_pair_id,
                empirical_p_value,
                row_number() OVER (
                    ORDER BY empirical_p_value,candidate_pair_id
                )::BIGINT AS bh_rank,
                count(*) OVER ()::BIGINT AS hypothesis_count
            FROM ablated_null
        ), candidates AS (
            SELECT *,least(
                empirical_p_value*hypothesis_count/bh_rank,
                1.0
            ) AS candidate_q
            FROM ranked
        )
        SELECT
            candidate_pair_id,
            min(candidate_q) OVER (
                ORDER BY bh_rank
                ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
            ) AS q_value
        FROM candidates;
        """
    )


def _json_tuple(value: object) -> tuple[str, ...]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise DiskFinalDiscoveryValidationError("internal disk validation JSON list is invalid")
    return tuple(parsed)


def _reconcile_knownness(
    source_statuses: Sequence[str],
    source_relationship_ids: Sequence[str],
    *,
    known_forward: bool,
    known_reverse: bool,
    indexed_relationship_ids: Sequence[str],
) -> tuple[KnownnessStatus, tuple[str, ...]]:
    statuses = set(source_statuses)
    if known_forward and known_reverse:
        statuses.add("known_both")
    elif known_forward:
        statuses.add("known_forward")
    elif known_reverse:
        statuses.add("known_reverse")
    relationship_ids = tuple(sorted({*source_relationship_ids, *indexed_relationship_ids}))
    if not statuses:
        return "unknown", ()
    if "known_both" in statuses or {"known_forward", "known_reverse"}.issubset(statuses):
        return "known_both", relationship_ids
    directional = statuses & {"known_forward", "known_reverse"}
    if directional == {"known_forward"}:
        return "known_forward", relationship_ids
    if directional == {"known_reverse"}:
        return "known_reverse", relationship_ids
    return "known_m7_snapshot", relationship_ids


def _quality_is_eligible(quality: QualityFlags, config: FinalDiscoveryConfig) -> bool:
    return not quality.basic_exclusion and not any(
        bool(getattr(quality, flag)) for flag in config.tiers.tier_a_quality_exclusions
    )


def _english_ablation_survives(
    *,
    contains_english: bool,
    ablated_null_sufficient: bool,
    knownness_status: KnownnessStatus,
    score_without_english: float,
    ablated_q_value: float,
    ablated_empirical_fdr: float,
    original_families: Sequence[str],
    quality: QualityFlags,
    config: FinalDiscoveryConfig,
) -> bool:
    if not contains_english:
        return True
    return (
        ablated_null_sufficient
        and knownness_status == "unknown"
        and score_without_english >= config.ensemble.minimum_tier_a_ensemble_score
        and ablated_q_value <= config.calibration.maximum_bh_q_value
        and ablated_empirical_fdr <= config.calibration.maximum_empirical_fdr
        and len(original_families) >= config.calibration.minimum_independent_families
        and _quality_is_eligible(quality, config)
    )


def _exclusion_reasons(
    *,
    knownness_status: KnownnessStatus,
    ensemble_score: float,
    q_value: float,
    empirical_fdr: float,
    full_null_sufficient: bool,
    original_families: Sequence[str],
    english_ablation_survives: bool,
    quality: QualityFlags,
    config: FinalDiscoveryConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if knownness_status != "unknown":
        reasons.append("known_relationship_either_direction")
    if ensemble_score < config.ensemble.minimum_tier_a_ensemble_score:
        reasons.append("ensemble_score_below_frozen_threshold")
    if q_value > config.calibration.maximum_bh_q_value:
        reasons.append("bh_q_value_above_frozen_limit")
    if empirical_fdr > config.calibration.maximum_empirical_fdr:
        reasons.append("empirical_fdr_above_frozen_limit")
    if not full_null_sufficient:
        reasons.append("null_stratum_insufficient_for_bh_resolution")
    if len(original_families) < config.calibration.minimum_independent_families:
        reasons.append("fewer_than_two_independent_original_language_families")
    if not english_ablation_survives:
        reasons.append("remove_all_english_ablation_failed")
    for flag in config.tiers.tier_a_quality_exclusions:
        if bool(getattr(quality, flag)):
            reasons.append(f"quality_{flag}")
    if quality.basic_exclusion:
        reasons.append("basic_data_quality_exclusion")
    return tuple(reasons)


_EXPECTED_BASE_INSERT = "INSERT INTO expected_base VALUES (?,?,?,?,?,?)"


def _create_expected_base(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: FinalDiscoveryConfig,
    batch_size: int,
) -> int:
    cursor = connection.cursor().execute(
        """
        SELECT
            d.candidate_pair_id,
            d.passage_a_id,
            d.passage_b_id,
            d.passage_a_reference,
            d.passage_b_reference,
            d.ensemble_score,
            d.score_without_english,
            d.evidence_ids_json,
            d.detector_ids_json,
            d.families_json,
            d.qualifying_groups_json,
            d.original_groups_json,
            d.original_families_json,
            d.contains_english,
            d.quality_json,
            d.quality_basic_exclusion,
            d.source_statuses_json,
            d.source_relationship_ids_json,
            f.empirical_p_value,
            f.empirical_fdr,
            f.stratum_sufficient_for_bh,
            a.empirical_p_value,
            a.empirical_fdr,
            a.stratum_sufficient_for_bh,
            fq.q_value,
            aq.q_value,
            k.known_forward,
            k.known_reverse,
            k.known_relationship_ids_json
        FROM drafts d
        JOIN full_null f USING (candidate_pair_id)
        JOIN ablated_null a USING (candidate_pair_id)
        JOIN full_q fq USING (candidate_pair_id)
        JOIN ablated_q aq USING (candidate_pair_id)
        JOIN known_pair_state k USING (candidate_pair_id)
        ORDER BY d.candidate_pair_id
        """
    )
    output_rows: list[tuple[object, ...]] = []
    count = 0
    fetch_size = min(batch_size, _MAXIMUM_DECODED_FETCH_ROWS)
    while batch := cursor.fetchmany(fetch_size):
        for row in batch:
            pair_id = str(row[0])
            original_families = _json_tuple(row[12])
            quality = QualityFlags.model_validate_json(str(row[14]))
            knownness_status, known_relationship_ids = _reconcile_knownness(
                _json_tuple(row[16]),
                _json_tuple(row[17]),
                known_forward=bool(row[26]),
                known_reverse=bool(row[27]),
                indexed_relationship_ids=_json_tuple(row[28]),
            )
            survives = _english_ablation_survives(
                contains_english=bool(row[13]),
                ablated_null_sufficient=bool(row[23]),
                knownness_status=knownness_status,
                score_without_english=float(row[6]),
                ablated_q_value=float(row[25]),
                ablated_empirical_fdr=float(row[22]),
                original_families=original_families,
                quality=quality,
                config=config,
            )
            reasons = _exclusion_reasons(
                knownness_status=knownness_status,
                ensemble_score=float(row[5]),
                q_value=float(row[24]),
                empirical_fdr=float(row[19]),
                full_null_sufficient=bool(row[20]),
                original_families=original_families,
                english_ablation_survives=survives,
                quality=quality,
                config=config,
            )
            payload = {
                "candidate_pair_id": pair_id,
                "passage_a_id": str(row[1]),
                "passage_b_id": str(row[2]),
                "passage_a_reference": str(row[3]),
                "passage_b_reference": str(row[4]),
                "ensemble_score": float(row[5]),
                "empirical_p_value": float(row[18]),
                "bh_q_value": float(row[24]),
                "empirical_fdr": float(row[19]),
                "knownness_status": knownness_status,
                "known_relationship_ids": known_relationship_ids,
                "quality": quality.model_dump(mode="json"),
                "evidence_ids": _json_tuple(row[7]),
                "detector_ids": _json_tuple(row[8]),
                "families": _json_tuple(row[9]),
                "qualifying_independence_groups": _json_tuple(row[10]),
                "original_language_independence_groups": _json_tuple(row[11]),
                "contains_english_derived_evidence": bool(row[13]),
                "score_without_english": float(row[6]),
                "english_ablation_empirical_p_value": float(row[21]),
                "english_ablation_bh_q_value": float(row[25]),
                "english_ablation_empirical_fdr": float(row[22]),
                "english_ablation_survives": survives,
                "tier_a_eligible": not reasons,
                "tier_a_exclusion_reasons": reasons,
            }
            output_rows.append(
                (
                    pair_id,
                    float(row[5]),
                    not reasons,
                    knownness_status,
                    bool(row[15]),
                    _canonical_json_bytes(payload).decode("ascii"),
                )
            )
            count += 1
        _flush_batch(connection, _EXPECTED_BASE_INSERT, output_rows)
    return count


def _create_expected_candidates(
    connection: duckdb.DuckDBPyConnection,
    *,
    tier_b_size: int,
    batch_size: int,
) -> None:
    connection.execute(
        f"""
        CREATE TABLE expected_tier_b AS
        SELECT candidate_pair_id,tier_b_rank
        FROM (
            SELECT
                candidate_pair_id,
                row_number() OVER (
                    ORDER BY ensemble_score DESC,candidate_pair_id
                )::BIGINT AS tier_b_rank
            FROM expected_base
            WHERE NOT tier_a_eligible
              AND knownness_status='unknown'
              AND NOT quality_basic_exclusion
        ) ranked
        WHERE tier_b_rank<={tier_b_size}
        """
    )
    cursor = connection.cursor().execute(
        """
        SELECT base.candidate_pair_id,base.payload_json,tier.tier_b_rank
        FROM expected_base base
        LEFT JOIN expected_tier_b tier USING (candidate_pair_id)
        ORDER BY base.candidate_pair_id
        """
    )
    output_rows: list[tuple[object, ...]] = []
    fetch_size = min(batch_size, _MAXIMUM_DECODED_FETCH_ROWS)
    while batch := cursor.fetchmany(fetch_size):
        for pair_id, payload_json, tier_b_rank in batch:
            parsed = json.loads(str(payload_json))
            if not isinstance(parsed, dict):
                raise DiskFinalDiscoveryValidationError("expected candidate payload is invalid")
            payload = cast(dict[str, Any], parsed)
            tier_a = bool(payload["tier_a_eligible"])
            payload["tier_b_rank"] = int(tier_b_rank) if tier_b_rank is not None else None
            payload["output_label"] = (
                "statistically_eligible"
                if tier_a
                else "exploratory_not_statistically_accepted"
                if tier_b_rank is not None
                else "retained_excluded"
            )
            expected = FinalCandidate.model_validate(payload)
            output_rows.append((str(pair_id), _model_json(expected)))
        _flush_batch(
            connection,
            "INSERT INTO expected_candidates VALUES (?,?)",
            output_rows,
        )


def _compare_candidate_field(
    collector: _FindingCollector,
    *,
    code: str,
    field: str,
    observed: object,
    expected: object,
    pair_id: str,
) -> None:
    equal = (
        _close(observed, expected)
        if isinstance(observed, float) and isinstance(expected, float)
        else observed == expected
    )
    if not equal:
        collector.add(
            code,
            f"stored {field}={observed!r} differs from recomputed {expected!r}",
            pair_id,
        )


def _validate_candidates_against_expected(
    connection: duckdb.DuckDBPyConnection,
    *,
    collector: _FindingCollector,
    batch_size: int,
) -> None:
    _record_query_finding(
        connection,
        collector,
        query="""
            SELECT coalesce(c.candidate_pair_id,e.candidate_pair_id)
            FROM candidates c FULL OUTER JOIN expected_candidates e USING (candidate_pair_id)
            WHERE c.candidate_pair_id IS NULL OR e.candidate_pair_id IS NULL
            ORDER BY 1 LIMIT 1
        """,
        code="candidate-population",
        message="candidate/evidence population mismatch",
    )
    _record_query_finding(
        connection,
        collector,
        query="""
            WITH expected_order AS (
                SELECT
                    candidate_pair_id,
                    row_number() OVER (
                        ORDER BY ensemble_score DESC,candidate_pair_id
                    )-1 AS expected_index
                FROM expected_base
            )
            SELECT c.candidate_pair_id
            FROM candidates c JOIN expected_order e USING (candidate_pair_id)
            WHERE c.row_index<>e.expected_index
            ORDER BY c.row_index LIMIT 1
        """,
        code="candidate-output-order",
        message="candidate ledger is not sorted by descending score and stable pair ID",
    )
    cursor = connection.execute(
        """
        SELECT c.raw_json,e.raw_json
        FROM candidates c JOIN expected_candidates e USING (candidate_pair_id)
        ORDER BY c.candidate_pair_id
        """
    )
    fetch_size = min(batch_size, _MAXIMUM_DECODED_FETCH_ROWS)
    while batch := cursor.fetchmany(fetch_size):
        for observed_json, expected_json in batch:
            observed = FinalCandidate.model_validate_json(str(observed_json))
            expected = FinalCandidate.model_validate_json(str(expected_json))
            pair_id = expected.candidate_pair_id
            comparisons = (
                ("candidate-id", "candidate_pair_id"),
                ("candidate-passage", "passage_a_id"),
                ("candidate-passage", "passage_b_id"),
                ("candidate-reference", "passage_a_reference"),
                ("candidate-reference", "passage_b_reference"),
                ("ensemble-score", "ensemble_score"),
                ("full-null-candidate-values", "empirical_p_value"),
                ("bh-reconciliation", "bh_q_value"),
                ("full-null-candidate-values", "empirical_fdr"),
                ("knownness-reconciliation", "knownness_status"),
                ("knownness-reconciliation", "known_relationship_ids"),
                ("quality-reconciliation", "quality"),
                ("evidence-trace", "evidence_ids"),
                ("detector-summary", "detector_ids"),
                ("family-summary", "families"),
                ("qualifying-group-reconciliation", "qualifying_independence_groups"),
                (
                    "original-group-reconciliation",
                    "original_language_independence_groups",
                ),
                ("english-evidence-reconciliation", "contains_english_derived_evidence"),
                ("english-ablation-score", "score_without_english"),
                (
                    "english-ablation-null-candidate-values",
                    "english_ablation_empirical_p_value",
                ),
                ("english-ablation-bh-reconciliation", "english_ablation_bh_q_value"),
                (
                    "english-ablation-null-candidate-values",
                    "english_ablation_empirical_fdr",
                ),
                ("english-ablation-survival", "english_ablation_survives"),
                ("tier-a-reconciliation", "tier_a_eligible"),
                ("tier-a-exclusion-reasons", "tier_a_exclusion_reasons"),
                ("tier-b-exact-membership", "tier_b_rank"),
                ("output-label-reconciliation", "output_label"),
            )
            for code, field in comparisons:
                _compare_candidate_field(
                    collector,
                    code=code,
                    field=field,
                    observed=getattr(observed, field),
                    expected=getattr(expected, field),
                    pair_id=pair_id,
                )
    expected_tier_b_row = _first_row(
        connection,
        "SELECT count(*) FROM expected_tier_b",
    )
    observed_tier_b_row = _first_row(
        connection,
        "SELECT count(*) FROM candidates WHERE tier_b_rank IS NOT NULL",
    )
    expected_tier_b = (
        int(cast(int, expected_tier_b_row[0])) if expected_tier_b_row is not None else 0
    )
    observed_tier_b = (
        int(cast(int, observed_tier_b_row[0])) if observed_tier_b_row is not None else 0
    )
    if expected_tier_b != observed_tier_b:
        collector.add(
            "tier-b-exact-size",
            f"Tier B has {observed_tier_b} rows; expected {expected_tier_b}",
        )


def _authenticate_stages(
    stage_store: StageStore | None,
    expected_count: int | None,
    collector: _FindingCollector,
) -> int:
    if stage_store is None:
        if expected_count not in {None, 0}:
            collector.add(
                "stage-store-missing",
                f"{expected_count} authenticated stages were requested",
            )
        return 0
    if expected_count == 11:
        try:
            completions = stage_store.authenticate_all_completions()
        except StageStoreError as exc:
            collector.add(
                "stage-authentication",
                f"the full stage graph is not authenticated: {exc}",
            )
            return 0
        authenticated = len(completions)
    else:
        authenticated = 0
        for stage_id in FINAL_DISCOVERY_STAGE_IDS:
            try:
                stage_store.authenticate_completion(stage_id)
            except StageStoreError:
                break
            authenticated += 1
    if expected_count is not None and authenticated != expected_count:
        collector.add(
            "stage-count",
            f"expected {expected_count} authenticated stages, found {authenticated}",
        )
    return authenticated


def _passage_identity(
    passages: Mapping[str, PassageRecord],
) -> tuple[int, str]:
    def rows() -> Iterator[object]:
        for key in sorted(passages):
            row = passages[key]
            yield {"index_key": key, "passage": row.model_dump(mode="json")}

    return _sha256_rows(rows())


def _knownness_identity(
    connection: duckdb.DuckDBPyConnection, *, batch_size: int
) -> tuple[int, str]:
    cursor = connection.execute(
        """
        SELECT relationship_id,source_passage_id,target_passage_id
        FROM known_relationships
        ORDER BY relationship_id,source_passage_id,target_passage_id
        """
    )

    def rows() -> Iterator[object]:
        fetch_size = min(batch_size, _MAXIMUM_DECODED_FETCH_ROWS)
        while batch := cursor.fetchmany(fetch_size):
            for relationship_id, source_id, target_id in batch:
                yield [str(relationship_id), str(source_id), str(target_id)]

    return _sha256_rows(rows())


def _database_size(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, path.with_name(f"{path.name}.wal"))
        if candidate.is_file()
    )


def _remove_database(path: Path, temp_directory: Path) -> None:
    resolved_temp = temp_directory.resolve()
    for candidate in (path, path.with_name(f"{path.name}.wal")):
        resolved = candidate.resolve()
        try:
            resolved.relative_to(resolved_temp)
        except ValueError as exc:
            raise DiskFinalDiscoveryValidationError(
                "refusing to remove validation state outside the declared temporary directory"
            ) from exc
        if resolved.is_file():
            resolved.unlink()


def _input_still_matches(path: Path, expected: DiskValidationInputReceipt) -> None:
    observed = inspect_jsonl_file(path)
    if (
        observed.row_count != expected.row_count
        or observed.size_bytes != expected.size_bytes
        or observed.sha256 != expected.sha256
    ):
        raise DiskFinalDiscoveryValidationError(
            f"strict validation input changed during execution: {expected.role}"
        )


def _run_validation(
    database_path: Path,
    staging: Path,
    *,
    evidence_path: Path,
    candidates_path: Path,
    full_null_path: Path,
    remove_all_english_null_path: Path,
    inputs: tuple[DiskValidationInputReceipt, ...],
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex | Iterable[KnownRelationship],
    config: FinalDiscoveryConfig,
    expected_source_artifact_sha256: Mapping[str, str] | None,
    stage_store: StageStore | None,
    expected_authenticated_stage_count: int | None,
    memory_limit_bytes: int,
    temp_directory: Path,
    threads: int,
    batch_size: int,
    finding_limit: int,
    minimum_temp_free_bytes: int,
    initial_temp_free_bytes: int,
) -> tuple[FinalDiscoveryValidationReport, DiskFinalDiscoveryValidationReceipt]:
    collector = _FindingCollector(limit=finding_limit, findings=[])
    try:
        assert_stage_registrations(cast(Sequence[StageRegistrationLike], config.stages))
    except ValueError as exc:
        collector.add("stage-registration", str(exc))
    passage_count, passage_sha256 = _passage_identity(passages)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
        connection.execute(f"SET threads={threads}")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute(f"SET temp_directory='{_quoted_path(temp_directory)}'")
        _create_tables(connection)
        evidence_count, evidence_pair_count, maximum_pair_rows = _ingest_evidence(
            connection,
            evidence_path,
            passages=passages,
            config=config,
            expected_source_artifact_sha256=expected_source_artifact_sha256,
            collector=collector,
            batch_size=batch_size,
        )
        candidate_count, tier_a_count, tier_b_count = _ingest_candidates(
            connection,
            candidates_path,
            collector=collector,
            batch_size=batch_size,
        )
        _ingest_null_ledger(
            connection,
            full_null_path,
            table="full_null",
            batch_size=batch_size,
        )
        _ingest_null_ledger(
            connection,
            remove_all_english_null_path,
            table="ablated_null",
            batch_size=batch_size,
        )
        _ingest_knownness(connection, knownness, batch_size=batch_size)
        known_relationship_count, knownness_sha256 = _knownness_identity(
            connection,
            batch_size=batch_size,
        )
        _validate_null_table(
            connection,
            table="full_null",
            scope="full",
            score_column="ensemble_score",
            config=config,
            collector=collector,
        )
        _validate_null_table(
            connection,
            table="ablated_null",
            scope="remove_all_english",
            score_column="score_without_english",
            config=config,
            collector=collector,
        )
        _create_knownness_and_q_state(connection)
        expected_count = _create_expected_base(
            connection,
            config=config,
            batch_size=batch_size,
        )
        _create_expected_candidates(
            connection,
            tier_b_size=config.tiers.tier_b_size,
            batch_size=batch_size,
        )
        if expected_count != evidence_pair_count:
            collector.add(
                "candidate-population",
                (
                    f"strict expected population has {expected_count} rows; "
                    f"evidence has {evidence_pair_count} pairs"
                ),
            )
        _validate_candidates_against_expected(
            connection,
            collector=collector,
            batch_size=batch_size,
        )
        authenticated_stage_count = _authenticate_stages(
            stage_store,
            expected_authenticated_stage_count,
            collector,
        )
        connection.execute("CHECKPOINT")
    database_peak_bytes = _database_size(database_path)
    for path, input_receipt in zip(
        (
            evidence_path,
            candidates_path,
            full_null_path,
            remove_all_english_null_path,
        ),
        inputs,
        strict=True,
    ):
        _input_still_matches(path, input_receipt)
    report = FinalDiscoveryValidationReport(
        experiment_id=config.experiment_id,
        evidence_count=evidence_count,
        candidate_count=candidate_count,
        tier_a_count=tier_a_count,
        tier_b_count=tier_b_count,
        authenticated_stage_count=authenticated_stage_count,
        findings=tuple(collector.findings),
    )
    report_file_receipt = write_json_atomic_new(staging / _REPORT_FILE_NAME, report)
    resource = DiskValidationResourceReceipt(
        duckdb_memory_limit_bytes=memory_limit_bytes,
        duckdb_threads=threads,
        ingestion_batch_size=batch_size,
        maximum_decoded_rows_per_fetch=min(batch_size, _MAXIMUM_DECODED_FETCH_ROWS),
        finding_limit=finding_limit,
        minimum_temp_free_bytes=minimum_temp_free_bytes,
        initial_temp_free_bytes=initial_temp_free_bytes,
        duckdb_database_peak_bytes=database_peak_bytes,
        maximum_evidence_rows_retained_per_pair=maximum_pair_rows,
        full_ledgers_retained_in_python=False,
        duckdb_state_persisted=False,
    )
    receipt = DiskFinalDiscoveryValidationReceipt(
        experiment_id=config.experiment_id,
        config_sha256=final_discovery_config_sha256(config),
        inputs=inputs,
        passage_count=passage_count,
        passage_logical_sha256=passage_sha256,
        known_relationship_count=known_relationship_count,
        knownness_logical_sha256=knownness_sha256,
        evidence_pair_count=evidence_pair_count,
        authenticated_stage_count=authenticated_stage_count,
        expected_authenticated_stage_count=expected_authenticated_stage_count,
        validation_passed=(collector.total_count == 0),
        retained_finding_count=len(collector.findings),
        total_finding_count=collector.total_count,
        findings_truncated=(collector.total_count > len(collector.findings)),
        report_size_bytes=report_file_receipt.size_bytes,
        report_sha256=report_file_receipt.sha256,
        resource_bounds=resource,
    )
    write_json_atomic_new(staging / _RECEIPT_FILE_NAME, receipt)
    return report, receipt


def validate_final_discovery_disk_backed(
    evidence_path: Path,
    candidates_path: Path,
    full_null_path: Path,
    remove_all_english_null_path: Path,
    output_directory: Path,
    *,
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex | Iterable[KnownRelationship],
    config: FinalDiscoveryConfig,
    memory_limit_bytes: int,
    temp_directory: Path,
    expected_source_artifact_sha256: Mapping[str, str] | None = None,
    stage_store: StageStore | None = None,
    expected_authenticated_stage_count: int | None = None,
    minimum_temp_free_bytes: int = 1024**3,
    threads: int = 1,
    batch_size: int = 65_536,
    finding_limit: int = 1_000,
) -> DiskFinalDiscoveryValidationResult:
    """Strictly validate canonical final-discovery ledgers in bounded state.

    The four input ledgers are never retained in Python.  Evidence is grouped
    only for its current candidate pair, candidate and null joins are external,
    and expected BH/tier state is persisted in a temporary DuckDB database.
    Fatal parsing, ordering, resource, or authentication errors publish no
    result directory.  Scientific failures publish a report whose receipt has
    ``validation_passed=false`` so downstream promotion fails closed.
    """

    if memory_limit_bytes < _MINIMUM_MEMORY_BYTES:
        raise DiskFinalDiscoveryValidationError(
            "disk validation requires a DuckDB memory limit of at least 256 MiB"
        )
    if threads < 1 or threads > 64:
        raise DiskFinalDiscoveryValidationError("DuckDB threads must be between 1 and 64")
    if batch_size < 1:
        raise DiskFinalDiscoveryValidationError("validation batch_size must be positive")
    if finding_limit < 1:
        raise DiskFinalDiscoveryValidationError("validation finding_limit must be positive")
    if minimum_temp_free_bytes < _MINIMUM_TEMP_FREE_BYTES:
        raise DiskFinalDiscoveryValidationError(
            "minimum temporary free-space requirement must be at least 256 MiB"
        )
    if expected_authenticated_stage_count is not None and not (
        0 <= expected_authenticated_stage_count <= 11
    ):
        raise DiskFinalDiscoveryValidationError(
            "expected authenticated stage count must be between zero and eleven"
        )
    if output_directory.exists():
        raise DiskFinalDiscoveryValidationError(
            f"disk validation refuses to replace output directory: {output_directory}"
        )
    resolved_inputs = tuple(
        path.resolve()
        for path in (
            evidence_path,
            candidates_path,
            full_null_path,
            remove_all_english_null_path,
        )
    )
    if len(set(resolved_inputs)) != 4:
        raise DiskFinalDiscoveryValidationError("validation input paths must be distinct")
    inputs = (
        _input_receipt(
            evidence_path,
            role="evidence",
            ordering="candidate_pair_id,detector_id",
        ),
        _input_receipt(
            candidates_path,
            role="candidates",
            ordering="ensemble_score_desc,candidate_pair_id",
        ),
        _input_receipt(
            full_null_path,
            role="full_null",
            ordering="candidate_pair_id",
        ),
        _input_receipt(
            remove_all_english_null_path,
            role="remove_all_english_null",
            ordering="candidate_pair_id",
        ),
    )
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    initial_temp_free_bytes = shutil.disk_usage(temp_directory).free
    if initial_temp_free_bytes < minimum_temp_free_bytes:
        raise DiskFinalDiscoveryValidationError(
            "temporary directory lacks the declared minimum free space"
        )
    staging = output_directory.with_name(f".{output_directory.name}.{uuid.uuid4().hex}.tmp")
    staging.mkdir(exist_ok=False)
    database_path = temp_directory / f"disk-validation-{uuid.uuid4().hex}.duckdb"
    try:
        report, receipt = _run_validation(
            database_path,
            staging,
            evidence_path=evidence_path,
            candidates_path=candidates_path,
            full_null_path=full_null_path,
            remove_all_english_null_path=remove_all_english_null_path,
            inputs=inputs,
            passages=passages,
            knownness=knownness,
            config=config,
            expected_source_artifact_sha256=expected_source_artifact_sha256,
            stage_store=stage_store,
            expected_authenticated_stage_count=expected_authenticated_stage_count,
            memory_limit_bytes=memory_limit_bytes,
            temp_directory=temp_directory,
            threads=threads,
            batch_size=batch_size,
            finding_limit=finding_limit,
            minimum_temp_free_bytes=minimum_temp_free_bytes,
            initial_temp_free_bytes=initial_temp_free_bytes,
        )
        _remove_database(database_path, temp_directory)
        if output_directory.exists():
            raise DiskFinalDiscoveryValidationError(
                f"validation output appeared during execution: {output_directory}"
            )
        staging.rename(output_directory)
    except BaseException as exc:
        # Deliberately preserve the uniquely named staging directory and DuckDB
        # state on fatal failure; neither can be mistaken for a published result.
        if isinstance(
            exc,
            (DiskFinalDiscoveryValidationError, KeyboardInterrupt, SystemExit),
        ):
            raise
        if isinstance(
            exc,
            (
                duckdb.Error,
                FinalDiscoveryStorageError,
                OSError,
                ValidationError,
                ValueError,
            ),
        ):
            raise DiskFinalDiscoveryValidationError(
                f"disk-backed strict validation failed: {exc}"
            ) from exc
        raise
    return DiskFinalDiscoveryValidationResult(
        output_directory=output_directory,
        report_path=output_directory / _REPORT_FILE_NAME,
        receipt_path=output_directory / _RECEIPT_FILE_NAME,
        report=report,
        receipt=receipt,
    )
