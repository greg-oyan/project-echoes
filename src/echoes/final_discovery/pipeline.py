"""Restartable eleven-stage execution for ``final-discovery-v1``.

The runner is deliberately transport-agnostic.  Production callers inject an
authenticated M7 object store and a distinct final-output object store; this
module neither provisions infrastructure nor discovers credentials.  The
bounded fixture path uses the same stage graph with local object stores and an
explicit synthetic M7 detector projection.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import platform
import re
import shutil
import stat
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import numpy as np
from pydantic import BaseModel

from echoes.benchmarks.positive_controls import (
    PositiveControlDataset,
    validate_positive_controls,
)
from echoes.final_discovery.anomaly import PairFamilyScores, anomaly_evidence
from echoes.final_discovery.checkpoints import (
    StageCheckpointReceipt,
    package_and_upload_stage_checkpoint,
    validate_checkpoint_store_mapping,
)
from echoes.final_discovery.compact_nulls import (
    CompactGroupScoreRow,
    calibrate_compact_ensemble_nulls,
    write_compact_group_scores,
)
from echoes.final_discovery.config import (
    FINAL_DISCOVERY_EXPERIMENT,
    DetectorRegistration,
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
)
from echoes.final_discovery.disk_calibration import (
    DiskDetectorCalibrationReceipt,
    PairStratum,
    calibrate_anomaly_evidence_disk_backed,
    calibrate_detector_evidence_disk_backed,
    project_anomaly_pair_scores_disk_backed,
)
from echoes.final_discovery.disk_ensemble import (
    DiskEnsembleReceipt,
    build_final_candidates_disk_backed,
)
from echoes.final_discovery.disk_validation import (
    DiskFinalDiscoveryValidationReceipt,
    DiskFinalDiscoveryValidationResult,
    validate_final_discovery_disk_backed,
)
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    calibrate_detector_evidence,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.evaluation import evaluate_positive_controls
from echoes.final_discovery.evidence_index import (
    EvidenceOffsetLookup,
    build_evidence_offset_index,
)
from echoes.final_discovery.features import (
    candidate_pair_id,
    canonical_json,
    empirical_percentile,
)
from echoes.final_discovery.formulaic import apply_formulaic_control
from echoes.final_discovery.inputs import (
    InputExpectation,
    LocalObjectStore,
    MaterializationReceipt,
    ObjectStore,
    ObjectStoreIdentity,
    RcloneB2ObjectStore,
    TransferVerificationReceipt,
    inventory_directory,
    materialize_authenticated_input,
    resume_or_upload_and_verify_tree,
)
from echoes.final_discovery.knownness import KnownnessIndex, KnownRelationship
from echoes.final_discovery.knownness_projection import (
    KnownnessProjectionReceipt,
    authenticate_knownness_jsonl,
    iter_authenticated_knownness_jsonl,
    project_openbible_knownness,
)
from echoes.final_discovery.m7_adapter import (
    M7HydratedEvidenceLookup,
    authenticate_m7_input,
    build_m7_hydration_index,
    build_m7_lexical_projection,
    iter_m7_raw_evidence,
)
from echoes.final_discovery.models import (
    EvidenceFamily,
    EvidenceRow,
    FinalCandidate,
    PassageRecord,
    RawEvidence,
)
from echoes.final_discovery.nulls import (
    EnsembleNullCalibrationRow,
    EnsembleNullThresholdReport,
    build_ensemble_null_threshold_report,
    detector_reference_and_null_scores,
    stratified_ensemble_null_calibration_with_reporting,
)
from echoes.final_discovery.passages import (
    PassageParquetSources,
    PassageProjectionScope,
    authenticate_prepared_passage_projection,
    load_book_genres,
)
from echoes.final_discovery.retrieval import (
    blockwise_top_k_sparse,
    build_tfidf_representation,
    canonical_neighbor_pairs,
)
from echoes.final_discovery.review import (
    iter_bounded_dossier_candidates,
    write_review_bundle,
    write_review_bundle_streaming,
)
from echoes.final_discovery.scale import (
    CANONICAL_M7_CANDIDATE_COUNT,
    CampaignScaleContract,
    campaign_scale_contract,
)
from echoes.final_discovery.semantic import (
    OfflineSentenceTransformerEncoder,
    SentenceEncoder,
    blockwise_top_k_cosine,
    encode_passages,
    semantic_pair_evidence,
    verify_model_artifacts,
    verify_model_runtime_dependencies,
)
from echoes.final_discovery.stages import (
    StageCompletionManifest,
    StageRegistrationLike,
    StageRunResult,
    StageStore,
    assert_stage_registrations,
)
from echoes.final_discovery.storage import (
    inspect_jsonl_file,
    iter_jsonl,
    merge_sorted_jsonl,
    read_jsonl,
    sha256_file,
    write_jsonl_atomic,
    write_jsonl_stream_atomic,
)
from echoes.final_discovery.structure import structural_signature, structure_pair_evidence
from echoes.final_discovery.syntax import (
    feature_document_frequencies,
    grammar_pair_evidence,
    grammatical_features,
)
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    validate_final_discovery,
)

ExecutionMode = Literal["fixture", "production"]

_M7_PROJECTION_MEMORY_LIMIT_BYTES = 1024**3
# The complete 608,533-row M6 projection exceeded 1 GiB on the target
# production host. Keep this operational bound below both the 40 GiB DuckDB
# campaign ceiling and the 56 GiB systemd process ceiling. The projection
# query, ordering, mapping policy, and authenticated output remain unchanged.
_KNOWNNESS_PROJECTION_MEMORY_LIMIT_BYTES = 4 * 1024**3
_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES = 4 * 1024**3
_FINAL_DISCOVERY_DUCKDB_THREADS = 1
_DISK_ENSEMBLE_CHUNK_SIZE = 10_000
_MINIMUM_PRODUCTION_DISK_FLOOR_BYTES = 80 * 1024**3
_EXPECTED_PRODUCTION_PASSAGE_STREAM_COUNTS = {
    ("hebrew", "edition_complete", "qere"): 23_213,
    ("greek", "edition_complete", "source"): 7_943,
    ("hebrew", "edition_complete", "ketiv"): 23_213,
    ("greek", "critical_core", "source"): 7_918,
}
_MANAGED_PRODUCTION_UNIT = "echoes-final-discovery.service"
_MANAGED_LAUNCH_ROOT = Path("/var/lib/project-echoes/final-discovery/launches")
_MANAGED_LAUNCH_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")


class FinalDiscoveryCampaignError(RuntimeError):
    """Raised when a campaign request cannot honor the frozen boundary."""


@dataclass(frozen=True, slots=True)
class InputFileAnchor:
    """One preregistered local manifest/file identity authenticated at stage 1."""

    relative_path: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class CampaignRequest:
    """All local identities needed by the exact one-command campaign.

    ``fixture_m7_evidence`` is accepted only for a bounded fixture.  Production
    always authenticates the canonical M7 tree and projects it through
    :mod:`echoes.final_discovery.m7_adapter` without rerunning M7.
    """

    config: FinalDiscoveryConfig
    stage_store: StageStore
    prepared_passages_path: Path
    m7_store: ObjectStore
    m7_expectation: InputExpectation
    destination_store: ObjectStore
    code_sha256: str
    code_commit: str
    execution_mode: ExecutionMode
    known_relationships: tuple[KnownRelationship, ...] = ()
    offline_model_root: Path | None = None
    encoder: SentenceEncoder | None = None
    fixture_m7_evidence: tuple[RawEvidence, ...] = ()
    minimum_free_disk_bytes: int | None = None
    input_file_anchors: tuple[InputFileAnchor, ...] = ()
    prepared_passages_expected_sha256: str | None = None
    knownness_source_path: Path | None = None
    knownness_source_sha256: str | None = None
    knownness_projection_receipt_path: Path | None = None
    knownness_benchmark_root: Path | None = None
    positive_control_config_path: Path = Path("data/benchmarks/positive_controls.yaml")
    positive_control_data_path: Path = Path("data/benchmarks/positive_controls.csv")
    passage_sources: PassageParquetSources | None = None
    passage_projection_scope: PassageProjectionScope = field(
        default_factory=lambda: PassageProjectionScope(
            include_greek_critical_core=True,
            include_hebrew_ketiv=True,
        )
    )
    checkpoint_stores: Mapping[str, ObjectStore] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckpointInventoryEntry:
    stage_number: int
    stage_id: str
    completion_manifest_sha256: str
    output_inventory_sha256: str
    artifact_count: int
    skipped: bool


@dataclass(frozen=True, slots=True)
class CampaignRunResult:
    """Authenticated local boundary returned after stage 11 verifies upload."""

    experiment_id: Literal["final-discovery-v1"]
    execution_mode: ExecutionMode
    stage_store_root: Path
    stage_results: tuple[StageRunResult, ...]
    checkpoints: tuple[CheckpointInventoryEntry, ...]
    durable_checkpoint_receipts: tuple[StageCheckpointReceipt, ...]
    evidence_path: Path
    candidates_path: Path
    review_directory: Path
    validation_report_path: Path
    package_path: Path
    package_sha256: str
    transfer_verification_path: Path
    campaign_seal_path: Path
    finalization_receipt_path: Path
    evidence_count: int
    candidate_count: int
    tier_a_count: int
    tier_b_count: int


def assert_production_authorized(config: FinalDiscoveryConfig) -> None:
    """Enforce the local pre-production boundary without provisioning anything."""

    if platform.system().casefold() != config.cloud.production_operating_system:
        raise FinalDiscoveryCampaignError("production final discovery is supported on Linux only")
    variable = config.cloud.authorization_environment_variable
    observed = os.environ.get(variable)
    if observed != config.cloud.authorization_value:
        raise FinalDiscoveryCampaignError(
            f"production requires exact {variable}={config.cloud.authorization_value}"
        )
    if not config.cloud.no_automatic_provisioning:
        raise FinalDiscoveryCampaignError("the frozen configuration must prohibit provisioning")
    _assert_managed_production_launch()


def _read_process_cgroup() -> str:
    try:
        return Path("/proc/self/cgroup").read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise FinalDiscoveryCampaignError(
            "production cannot authenticate its systemd cgroup"
        ) from exc


def _assert_managed_production_launch() -> None:
    """Reject a production CLI invoked outside the reviewed systemd launcher."""

    invocation_id = os.environ.get("INVOCATION_ID", "")
    if len(invocation_id) != 32 or any(value not in "0123456789abcdef" for value in invocation_id):
        raise FinalDiscoveryCampaignError("production requires a systemd invocation identity")
    cgroup_paths = {
        line.split(":", 2)[-1].rstrip("/")
        for line in _read_process_cgroup().splitlines()
        if line.count(":") >= 2
    }
    if not any(path.rsplit("/", 1)[-1] == _MANAGED_PRODUCTION_UNIT for path in cgroup_paths):
        raise FinalDiscoveryCampaignError(f"production must run inside {_MANAGED_PRODUCTION_UNIT}")

    launch_id = os.environ.get("ECHOES_MANAGED_LAUNCH_ID", "")
    intent_sha256 = os.environ.get("ECHOES_MANAGED_LAUNCH_INTENT_SHA256", "")
    raw_intent_path = os.environ.get("ECHOES_MANAGED_LAUNCH_INTENT_PATH", "")
    if not _MANAGED_LAUNCH_ID.fullmatch(launch_id):
        raise FinalDiscoveryCampaignError("managed production launch ID is absent or invalid")
    if len(intent_sha256) != 64 or any(value not in "0123456789abcdef" for value in intent_sha256):
        raise FinalDiscoveryCampaignError("managed production intent SHA-256 is absent or invalid")
    intent_path = Path(raw_intent_path)
    if not intent_path.is_absolute() or intent_path.is_symlink():
        raise FinalDiscoveryCampaignError("managed production intent path is absent or unsafe")
    try:
        resolved_intent = intent_path.resolve(strict=True)
        resolved_intent.relative_to(_MANAGED_LAUNCH_ROOT.resolve(strict=True))
        intent_stat = resolved_intent.stat()
    except (OSError, ValueError) as exc:
        raise FinalDiscoveryCampaignError(
            "managed production intent escapes its launch root"
        ) from exc
    if (
        not resolved_intent.is_file()
        or resolved_intent.name != f"{launch_id}.intent.json"
        or intent_stat.st_uid != 0
        or stat.S_IMODE(intent_stat.st_mode) & 0o022
        or intent_stat.st_size < 1
        or intent_stat.st_size > 2 * 1024**2
    ):
        raise FinalDiscoveryCampaignError("managed production intent ownership or mode is unsafe")
    if sha256_file(resolved_intent) != intent_sha256:
        raise FinalDiscoveryCampaignError("managed production intent SHA-256 differs")
    try:
        intent = json.loads(resolved_intent.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalDiscoveryCampaignError("managed production intent is invalid JSON") from exc
    if (
        not isinstance(intent, dict)
        or intent.get("experiment_id") != FINAL_DISCOVERY_EXPERIMENT
        or intent.get("launch_id") != launch_id
        or intent.get("service_unit") != _MANAGED_PRODUCTION_UNIT
        or not isinstance(intent.get("command"), list)
        or "--production" not in intent["command"]
        or intent.get("polling_or_automatic_restart") is not False
    ):
        raise FinalDiscoveryCampaignError("managed production intent contract differs")


def build_bounded_fixture_campaign_request(
    work_directory: Path,
    *,
    config: FinalDiscoveryConfig,
    code_sha256: str,
    code_commit: str,
) -> CampaignRequest:
    """Create or authenticate a tiny local preflight request with no network access."""

    work_root = work_directory.resolve()
    inputs_root = work_root / "inputs"
    inputs_root.mkdir(parents=True, exist_ok=True)
    passages = tuple(
        _fixture_passage(
            passage_id,
            corpus=cast(Literal["hebrew", "greek"], corpus),
            ordinal=ordinal,
        )
        for passage_id, corpus, ordinal in (
            ("fixture-greek-001", "greek", 1),
            ("fixture-greek-002", "greek", 2),
            ("fixture-hebrew-001", "hebrew", 3),
            ("fixture-hebrew-002", "hebrew", 4),
        )
    )
    passages_path = inputs_root / "prepared-passages.jsonl"
    if passages_path.exists():
        if read_jsonl(passages_path, PassageRecord) != passages:
            raise FinalDiscoveryCampaignError("existing fixture passages differ")
    else:
        write_jsonl_atomic(passages_path, passages, sort_key="passage_id")

    m7_root = inputs_root / "m7-object-store"
    m7_root.mkdir(parents=True, exist_ok=True)
    fixture_leaf = m7_root / "fixture.bin"
    fixture_bytes = b"bounded final-discovery M7 fixture\n"
    _write_or_authenticate_bytes(fixture_leaf, fixture_bytes)
    manifest_bytes = (
        json.dumps(
            {
                "schema_version": 1,
                "file_sha256": {"fixture.bin": hashlib.sha256(fixture_bytes).hexdigest()},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )
    manifest_path = m7_root / "table-hashes.json"
    _write_or_authenticate_bytes(manifest_path, manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    m7_identity = ObjectStoreIdentity(
        provider="local", bucket="fixture-m7", prefix="canonical-schema-v1"
    )
    destination_identity = ObjectStoreIdentity(
        provider="local", bucket="fixture-output", prefix="final-discovery-v1"
    )
    lexical = tuple(
        RawEvidence(
            candidate_pair_id=candidate_pair_id(first, second),
            passage_a_id=first,
            passage_b_id=second,
            detector_id="m7_lexical_rrf",
            family="lexical",
            independence_group="lexical_m7",
            raw_score=score,
            contains_english_derived_evidence=False,
            original_language_evidence_remains=True,
            counts_for_independence=True,
            trace_json=canonical_json(
                {
                    "bounded_fixture": True,
                    "fixture": True,
                    "representation": "canonical_m7_reciprocal_rank_fusion",
                    "rrf_score": score,
                    "m7_both_null_families_present": True,
                    "m7_openbible_relationship_ids": [],
                    "m7_known_link_status": "not_represented_in_openbible_snapshot",
                    "m7_quality": None,
                }
            ),
            source_artifact_id="m7-canonical-schema-v1",
            source_artifact_sha256=manifest_sha256,
        )
        for first, second, score in (
            ("fixture-greek-001", "fixture-hebrew-001", 0.95),
            ("fixture-greek-002", "fixture-hebrew-002", 0.85),
        )
    )
    return CampaignRequest(
        config=config,
        stage_store=StageStore(work_root / "stages"),
        prepared_passages_path=passages_path,
        m7_store=LocalObjectStore(m7_root, identity=m7_identity),
        m7_expectation=InputExpectation(
            identity=m7_identity,
            table_hashes_sha256=manifest_sha256,
        ),
        destination_store=LocalObjectStore(
            work_root / "destination-object-store", identity=destination_identity
        ),
        code_sha256=code_sha256,
        code_commit=code_commit,
        execution_mode="fixture",
        known_relationships=(
            KnownRelationship(
                relationship_id="fixture-known-reverse",
                source_passage_id="fixture-hebrew-002",
                target_passage_id="fixture-greek-001",
                source_name="bounded-fixture",
                mapping_quality="exact",
            ),
        ),
        fixture_m7_evidence=lexical,
        checkpoint_stores={
            stage.stage_id: LocalObjectStore(
                work_root / "checkpoint-object-stores" / f"{stage.number:02d}-{stage.stage_id}",
                identity=ObjectStoreIdentity(
                    provider="local",
                    bucket="fixture-checkpoints",
                    prefix=f"final-discovery-v1/{stage.number:02d}-{stage.stage_id}",
                ),
            )
            for stage in config.stages
            if stage.upload_after_completion
        },
    )


def run_final_discovery_campaign(request: CampaignRequest) -> CampaignRunResult:
    """Run or authenticate all eleven stages, then verify the final destination."""

    _validate_request(request)
    if request.execution_mode == "production":
        assert_production_authorized(request.config)
    positive_controls = validate_positive_controls(
        request.positive_control_config_path,
        data_path=request.positive_control_data_path,
    )
    config_hash = final_discovery_config_sha256(request.config)
    registrations = {item.detector_id: item for item in request.config.detectors}
    passage_source_hash = sha256_file(request.prepared_passages_path)
    knownness_hash = (
        sha256_file(request.knownness_source_path)
        if request.execution_mode == "production" and request.knownness_source_path is not None
        else _models_sha256(request.known_relationships)
    )
    stage_results: list[StageRunResult] = []
    durable_checkpoint_receipts: list[StageCheckpointReceipt] = []

    _assert_checkpoint_disk_floor(request)
    stage_one = request.stage_store.run_stage(
        "authenticate_materialize_inputs",
        input_hashes={
            "m7-table-hashes.json": request.m7_expectation.table_hashes_sha256,
            "prepared-passages.jsonl": passage_source_hash,
            "knownness-relationships": knownness_hash,
            **(
                {
                    "knownness-projection-receipt": sha256_file(
                        request.knownness_projection_receipt_path
                    )
                }
                if request.knownness_projection_receipt_path is not None
                else {}
            ),
            "positive-control-config": positive_controls.validation.config_sha256,
            "positive-control-data": positive_controls.validation.data_sha256,
            **{
                f"input-anchor:{anchor.relative_path}": anchor.sha256
                for anchor in request.input_file_anchors
            },
        },
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_one(root, request, positive_controls),
    )
    stage_results.append(stage_one)
    stage_one_root = _artifact_root(request.stage_store, stage_one.manifest)
    passages_path = stage_one_root / "passages.jsonl"
    relationships_path = stage_one_root / "known-relationships.jsonl"
    materialized_passages = read_jsonl(passages_path, PassageRecord)
    passages = _primary_discovery_passages(materialized_passages)
    passage_by_id = _passage_index(passages)

    model_state_hash = _model_state_sha256(request)
    _assert_checkpoint_disk_floor(request)
    stage_two = request.stage_store.run_stage(
        "semantic_representations_indexes",
        input_hashes={"offline-embedding-model-state": model_state_hash},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_two(root, request, passages),
    )
    stage_results.append(stage_two)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_two))
    stage_two_root = _artifact_root(request.stage_store, stage_two.manifest)

    stage_three_inputs: dict[str, str] = {}
    if request.execution_mode == "fixture":
        stage_three_inputs["fixture-m7-evidence"] = _models_sha256(request.fixture_m7_evidence)
    _assert_checkpoint_disk_floor(request)
    stage_three = request.stage_store.run_stage(
        "semantic_candidate_evidence",
        input_hashes=stage_three_inputs,
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_three(
            root,
            request,
            passages,
            passage_by_id,
            registrations,
            stage_one_root,
            stage_two_root,
        ),
    )
    stage_results.append(stage_three)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_three))
    stage_three_root = _artifact_root(request.stage_store, stage_three.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_four = request.stage_store.run_stage(
        "grammatical_syntactic_evidence",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_four(
            root,
            request,
            passages,
            passage_by_id,
            registrations,
            sha256_file(passages_path),
        ),
    )
    stage_results.append(stage_four)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_four))
    stage_four_root = _artifact_root(request.stage_store, stage_four.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_five = request.stage_store.run_stage(
        "structural_narrative_evidence",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_five(
            root,
            request,
            passages,
            passage_by_id,
            registrations,
            sha256_file(passages_path),
        ),
    )
    stage_results.append(stage_five)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_five))
    stage_five_root = _artifact_root(request.stage_store, stage_five.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_six = request.stage_store.run_stage(
        "anomaly_evidence",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_six(
            root,
            request,
            passage_by_id,
            registrations,
            stage_three_root,
            stage_four_root,
            stage_five_root,
        ),
    )
    stage_results.append(stage_six)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_six))
    stage_six_root = _artifact_root(request.stage_store, stage_six.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_seven = request.stage_store.run_stage(
        "empirical_null_controls",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_seven(
            root,
            request,
            positive_controls,
            passage_by_id,
            stage_three_root,
            stage_four_root,
            stage_five_root,
            stage_six_root,
        ),
    )
    stage_results.append(stage_seven)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_seven))
    stage_seven_root = _artifact_root(request.stage_store, stage_seven.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_eight = request.stage_store.run_stage(
        "transparent_final_ensemble",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_eight(
            root,
            request,
            passage_by_id,
            relationships_path,
            stage_seven_root,
        ),
    )
    stage_results.append(stage_eight)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_eight))
    stage_eight_root = _artifact_root(request.stage_store, stage_eight.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_nine = request.stage_store.run_stage(
        "tier_a_tier_b_outputs",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_nine(
            root,
            request,
            passage_by_id,
            stage_one_root,
            stage_seven_root,
            stage_eight_root,
        ),
    )
    stage_results.append(stage_nine)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_nine))
    stage_nine_root = _artifact_root(request.stage_store, stage_nine.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_ten = request.stage_store.run_stage(
        "strict_validation",
        input_hashes={},
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_ten(
            root,
            request,
            passage_by_id,
            relationships_path,
            stage_one_root,
            stage_two_root,
            stage_three_root,
            stage_four_root,
            stage_five_root,
            stage_seven_root,
            stage_eight_root,
        ),
    )
    stage_results.append(stage_ten)
    durable_checkpoint_receipts.append(_upload_stage_checkpoint(request, stage_ten))
    stage_ten_root = _artifact_root(request.stage_store, stage_ten.manifest)

    _assert_checkpoint_disk_floor(request)
    stage_eleven = request.stage_store.run_stage(
        "package_upload_verify",
        input_hashes={
            "destination-object-store": _text_sha256(
                request.destination_store.identity.canonical_uri
            )
        },
        config_sha256=config_hash,
        code_sha256=request.code_sha256,
        code_commit=request.code_commit,
        producer=lambda root: _produce_stage_eleven(
            root,
            request,
            tuple(stage_results),
            stage_one_root,
            stage_two_root,
            stage_three_root,
            stage_four_root,
            stage_five_root,
            stage_six_root,
            stage_seven_root,
            stage_eight_root,
            stage_nine_root,
            stage_ten_root,
        ),
    )
    stage_results.append(stage_eleven)
    stage_eleven_root = _artifact_root(request.stage_store, stage_eleven.manifest)
    upload_root = stage_eleven_root / "upload"
    transfer = request.destination_store.check_tree(upload_root)
    _assert_transfer_receipt_matches(stage_eleven_root / "transfer-verification.json", transfer)

    evidence_path = stage_seven_root / "evidence.jsonl"
    candidates_path = stage_eight_root / "candidates.jsonl"
    package_path = upload_root / "package-receipt.json"
    package_payload = _read_json_object(upload_root / "package-receipt.json")
    package_sha256 = sha256_file(package_path)
    package_inventory = inventory_directory(
        upload_root / "package",
        _final_package_local_identity(),
    )
    if (
        package_payload.get("package_format") != "authenticated_directory_v1"
        or package_payload.get("source_inventory_sha256") != package_inventory.sha256
        or package_payload.get("source_file_count") != package_inventory.object_count
        or package_payload.get("source_total_size") != package_inventory.total_size
    ):
        raise FinalDiscoveryCampaignError(
            "the completed package tree no longer matches its receipt"
        )

    all_stage_validation_receipt: DiskFinalDiscoveryValidationReceipt | None = None
    all_stage_validation_files: dict[str, Path] = {}
    if request.execution_mode == "production":
        ensemble_receipt = DiskEnsembleReceipt.model_validate(
            _read_json_object(stage_eight_root / "disk-ensemble-receipt.json")
        )
        review_summary = _read_json_object(stage_nine_root / "review-summary.json")
        all_stage_result = _run_or_authenticate_all_stage_disk_validation(
            request,
            output_directory=(
                request.stage_store.root.parent
                / "campaign-validations"
                / stage_eleven.completion_manifest_sha256
            ),
            evidence_path=evidence_path,
            candidates_path=candidates_path,
            full_null_path=stage_seven_root / "ensemble-null-full.jsonl",
            ablated_null_path=(stage_seven_root / "ensemble-null-remove-all-english.jsonl"),
            passage_by_id=passage_by_id,
            relationships_path=relationships_path,
            expected_source_artifact_sha256=_expected_evidence_source_hashes(
                request,
                stage_one_root,
                stage_two_root,
                stage_three_root,
                stage_four_root,
                stage_five_root,
            ),
        )
        all_stage_validation = all_stage_result.report
        all_stage_validation_receipt = all_stage_result.receipt
        all_stage_validation_files = {
            "all-stage-validation-report.json": all_stage_result.report_path,
            "all-stage-validation-receipt.json": all_stage_result.receipt_path,
        }
        evidence_count = ensemble_receipt.evidence_row_count
        candidate_count = ensemble_receipt.candidate_pair_count
        tier_a_count = ensemble_receipt.tier_a_count
        tier_b_count = ensemble_receipt.tier_b_count
        expected_review_counts = {
            "candidate_count": candidate_count,
            "evidence_count": evidence_count,
            "tier_a_count": tier_a_count,
            "tier_b_count": tier_b_count,
        }
        if any(review_summary.get(key) != value for key, value in expected_review_counts.items()):
            raise FinalDiscoveryCampaignError(
                "Stage 9 review summary disagrees with the authenticated ensemble population"
            )
    else:
        evidence = read_jsonl(evidence_path, EvidenceRow)
        candidates = read_jsonl(candidates_path, FinalCandidate)
        full_null_rows = read_jsonl(
            stage_seven_root / "ensemble-null-full.jsonl",
            EnsembleNullCalibrationRow,
        )
        ablated_null_rows = read_jsonl(
            stage_seven_root / "ensemble-null-remove-all-english.jsonl",
            EnsembleNullCalibrationRow,
        )
        all_stage_validation = validate_final_discovery(
            evidence,
            candidates,
            config=request.config,
            stage_store=request.stage_store,
            require_all_stages=True,
            passages=passage_by_id,
            knownness=KnownnessIndex(iter_jsonl(relationships_path, KnownRelationship)),
            null_calibration_by_pair=full_null_rows,
            english_ablation_null_calibration_by_pair=ablated_null_rows,
        )
        evidence_count = len(evidence)
        candidate_count = len(candidates)
        tier_a_count = sum(item.tier_a_eligible for item in candidates)
        tier_b_count = sum(item.tier_b_rank is not None for item in candidates)
    if not all_stage_validation.passed or all_stage_validation.authenticated_stage_count != 11:
        messages = "; ".join(
            f"{item.code}: {item.message}" for item in all_stage_validation.findings
        )
        raise FinalDiscoveryCampaignError(
            "post-package all-stage validation failed" + (f": {messages}" if messages else "")
        )
    campaign_seal_path = (
        request.stage_store.root.parent
        / "campaign-seals"
        / stage_eleven.completion_manifest_sha256
        / "campaign-seal.json"
    )
    finalization_supplemental_files = {
        "campaign-seal.json": campaign_seal_path,
        **all_stage_validation_files,
    }
    finalization_checkpoint_store = request.checkpoint_stores[stage_eleven.manifest.stage_id]
    campaign_seal_payload = {
        "schema_version": 1,
        "experiment_id": request.config.experiment_id,
        "execution_mode": request.execution_mode,
        "config_sha256": config_hash,
        "code_sha256": request.code_sha256,
        "code_commit": request.code_commit,
        "stage_completion_sha256": {
            result.manifest.stage_id: result.completion_manifest_sha256 for result in stage_results
        },
        "stage_output_inventory_sha256": {
            result.manifest.stage_id: result.manifest.output_inventory_sha256
            for result in stage_results
        },
        "pre_stage_11_durable_checkpoints": [
            receipt.model_dump(mode="json", exclude={"transfer_action"})
            for receipt in durable_checkpoint_receipts
        ],
        "final_package": {
            "format": "authenticated_directory_v1",
            "manifest_name": package_path.name,
            "manifest_sha256": package_sha256,
            "source_inventory_sha256": package_inventory.sha256,
            "source_file_count": package_inventory.object_count,
            "source_total_size": package_inventory.total_size,
        },
        "final_destination": request.destination_store.identity.canonical_uri,
        "transfer_verification": _transfer_payload(transfer),
        "transfer_action": _read_json_object(stage_eleven_root / "transfer-action.json"),
        "all_stage_validation": all_stage_validation.model_dump(mode="json"),
        "finalization_checkpoint": {
            "destination": finalization_checkpoint_store.identity.canonical_uri,
            "layout": "authenticated_stage_checkpoint_payload_v1",
            "required_supplemental_paths": sorted(finalization_supplemental_files),
            "remote_reverification_required_before_server_cleanup": True,
        },
        **(
            {"all_stage_validation_receipt": (all_stage_validation_receipt.model_dump(mode="json"))}
            if all_stage_validation_receipt is not None
            else {}
        ),
    }
    campaign_seal_bytes = (
        json.dumps(
            campaign_seal_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )
    _write_or_authenticate_bytes(campaign_seal_path, campaign_seal_bytes)
    stage_eleven_checkpoint_receipt = _upload_stage_checkpoint(
        request,
        stage_eleven,
        supplemental_files=finalization_supplemental_files,
    )
    durable_checkpoint_receipts.append(stage_eleven_checkpoint_receipt)
    finalization_receipt_path = campaign_seal_path.with_name("finalization-receipt.json")
    finalization_receipt_payload = {
        "schema_version": 1,
        "experiment_id": request.config.experiment_id,
        "receipt_kind": "post_stage_11_finalization_checkpoint_v1",
        "stage_11_completion_manifest_sha256": stage_eleven.completion_manifest_sha256,
        "campaign_seal_sha256": sha256_file(campaign_seal_path),
        "all_stage_validation_report_sha256": (
            sha256_file(all_stage_validation_files["all-stage-validation-report.json"])
            if "all-stage-validation-report.json" in all_stage_validation_files
            else None
        ),
        "all_stage_validation_receipt_sha256": (
            sha256_file(all_stage_validation_files["all-stage-validation-receipt.json"])
            if "all-stage-validation-receipt.json" in all_stage_validation_files
            else None
        ),
        # The transfer action is deliberately excluded: an authenticated rerun
        # changes only from uploaded/resumed to verified-existing.  The exact
        # per-attempt receipt remains preserved in its UUID-named checkpoint
        # workspace, while this deterministic binding is stable across restarts.
        "stage_11_checkpoint": stage_eleven_checkpoint_receipt.model_dump(
            mode="json", exclude={"transfer_action"}
        ),
        "per_attempt_receipts_preserved_under": str(
            request.stage_store.root.parent
            / "checkpoint-packages"
            / f"{stage_eleven.manifest.stage_number:02d}-{stage_eleven.manifest.stage_id}"
        ),
    }
    finalization_receipt_bytes = (
        json.dumps(
            finalization_receipt_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )
    _write_or_authenticate_bytes(finalization_receipt_path, finalization_receipt_bytes)

    checkpoints = tuple(
        CheckpointInventoryEntry(
            stage_number=result.manifest.stage_number,
            stage_id=result.manifest.stage_id,
            completion_manifest_sha256=result.completion_manifest_sha256,
            output_inventory_sha256=result.manifest.output_inventory_sha256,
            artifact_count=len(result.manifest.artifacts),
            skipped=result.skipped,
        )
        for result in stage_results
    )
    return CampaignRunResult(
        experiment_id="final-discovery-v1",
        execution_mode=request.execution_mode,
        stage_store_root=request.stage_store.root,
        stage_results=tuple(stage_results),
        checkpoints=checkpoints,
        durable_checkpoint_receipts=tuple(durable_checkpoint_receipts),
        evidence_path=evidence_path,
        candidates_path=candidates_path,
        review_directory=stage_nine_root / "review",
        validation_report_path=stage_ten_root / "validation-report.json",
        package_path=package_path,
        package_sha256=package_sha256,
        transfer_verification_path=stage_eleven_root / "transfer-verification.json",
        campaign_seal_path=campaign_seal_path,
        finalization_receipt_path=finalization_receipt_path,
        evidence_count=evidence_count,
        candidate_count=candidate_count,
        tier_a_count=tier_a_count,
        tier_b_count=tier_b_count,
    )


def _validate_request(request: CampaignRequest) -> None:
    if request.config.experiment_id != FINAL_DISCOVERY_EXPERIMENT:
        raise FinalDiscoveryCampaignError("campaign requires final-discovery-v1")
    try:
        assert_stage_registrations(cast(Sequence[StageRegistrationLike], request.config.stages))
        validate_checkpoint_store_mapping(request.config.stages, request.checkpoint_stores)
    except ValueError as exc:
        raise FinalDiscoveryCampaignError(str(exc)) from exc
    if len(request.code_sha256) != 64 or any(
        value not in "0123456789abcdef" for value in request.code_sha256
    ):
        raise FinalDiscoveryCampaignError("code_sha256 must be a lowercase SHA-256")
    if not request.code_commit or any(value in request.code_commit for value in "\r\n\x00"):
        raise FinalDiscoveryCampaignError("code_commit must be one nonempty line")
    if (request.offline_model_root is None) != (request.encoder is None):
        raise FinalDiscoveryCampaignError(
            "offline_model_root and encoder must be supplied together or both omitted"
        )
    if request.minimum_free_disk_bytes is not None and request.minimum_free_disk_bytes < 1:
        raise FinalDiscoveryCampaignError("minimum_free_disk_bytes must be positive")
    if request.execution_mode == "production":
        if request.fixture_m7_evidence:
            raise FinalDiscoveryCampaignError("production cannot accept fixture M7 evidence")
        if request.offline_model_root is None or request.encoder is None:
            raise FinalDiscoveryCampaignError(
                "production requires the authenticated pinned offline embedding model"
            )
        if not isinstance(request.encoder, OfflineSentenceTransformerEncoder):
            raise FinalDiscoveryCampaignError(
                "production encoder must come from the governed offline loader"
            )
        if (
            request.knownness_source_path is None
            or request.knownness_source_sha256 is None
            or request.knownness_projection_receipt_path is None
            or request.knownness_benchmark_root is None
        ):
            raise FinalDiscoveryCampaignError(
                "production requires the authenticated M6-derived knownness projection inputs"
            )
        if request.passage_sources is None:
            raise FinalDiscoveryCampaignError(
                "production requires governed M5/token sources for exact passage re-projection"
            )
        if request.passage_projection_scope != PassageProjectionScope(
            include_greek_critical_core=True,
            include_hebrew_ketiv=True,
        ):
            raise FinalDiscoveryCampaignError(
                "production requires the frozen primary-plus-sensitivities passage scope"
            )
        if (
            request.minimum_free_disk_bytes is None
            or request.minimum_free_disk_bytes < _MINIMUM_PRODUCTION_DISK_FLOOR_BYTES
        ):
            raise FinalDiscoveryCampaignError(
                "production requires a checkpoint disk floor of at least 80 GiB"
            )
        if not isinstance(request.m7_store, RcloneB2ObjectStore) or not isinstance(
            request.destination_store, RcloneB2ObjectStore
        ):
            raise FinalDiscoveryCampaignError(
                "production requires the environment-only rclone Backblaze B2 adapters"
            )
        if any(
            not isinstance(store, RcloneB2ObjectStore)
            for store in request.checkpoint_stores.values()
        ):
            raise FinalDiscoveryCampaignError(
                "production checkpoint stores must use the rclone Backblaze B2 adapter"
            )
        m7_input = next(item for item in request.config.inputs if item.role == "canonical_m7")
        expected_m7_uri = m7_input.source.removeprefix("b2:")
        observed_m7_uri = f"{request.m7_store.identity.bucket}/{request.m7_store.identity.prefix}"
        if (
            not m7_input.source.startswith("b2:")
            or request.m7_store.identity.provider != "b2"
            or observed_m7_uri != expected_m7_uri
        ):
            raise FinalDiscoveryCampaignError(
                "production M7 B2 bucket/prefix differs from the preregistration"
            )
        if request.destination_store.identity.provider != "b2":
            raise FinalDiscoveryCampaignError("production destination must be Backblaze B2")
        if request.destination_store.identity == request.m7_store.identity:
            raise FinalDiscoveryCampaignError("M7 input and final output prefixes must differ")
        output_identities = {
            request.destination_store.identity.canonical_uri,
            *(store.identity.canonical_uri for store in request.checkpoint_stores.values()),
        }
        if len(output_identities) != 1 + len(request.checkpoint_stores):
            raise FinalDiscoveryCampaignError(
                "final and per-stage outputs require distinct immutable B2 prefixes"
            )
        if request.m7_store.identity.canonical_uri in output_identities:
            raise FinalDiscoveryCampaignError("M7 input cannot be reused as an output prefix")
        _authenticate_production_file_inputs(request)
        _validate_production_passages(request.prepared_passages_path)
        expected_hash = next(
            item.expected_manifest_sha256
            for item in request.config.inputs
            if item.role == "canonical_m7"
        )
        if request.m7_expectation.table_hashes_sha256 != expected_hash:
            raise FinalDiscoveryCampaignError(
                "production M7 expectation differs from the preregistered manifest"
            )
    elif request.execution_mode == "fixture":
        if not isinstance(request.m7_store, LocalObjectStore) or not isinstance(
            request.destination_store, LocalObjectStore
        ):
            raise FinalDiscoveryCampaignError("fixture campaigns require local object stores")
        if any(
            not isinstance(store, LocalObjectStore) for store in request.checkpoint_stores.values()
        ):
            raise FinalDiscoveryCampaignError("fixture checkpoints require local object stores")
        if not request.fixture_m7_evidence:
            raise FinalDiscoveryCampaignError("fixture campaign requires explicit M7 evidence")
    else:
        raise FinalDiscoveryCampaignError(f"unsupported execution mode: {request.execution_mode}")


def _authenticate_production_file_inputs(request: CampaignRequest) -> None:
    expected = {
        name: digest
        for artifact in request.config.inputs
        if artifact.role != "canonical_m7"
        for name, digest in artifact.expected_hashes.items()
    }
    observed = {anchor.relative_path: anchor for anchor in request.input_file_anchors}
    if len(observed) != len(request.input_file_anchors) or set(observed) != set(expected):
        raise FinalDiscoveryCampaignError(
            "production input-file anchors do not exactly cover the preregistered inventory"
        )
    for relative_path, expected_sha256 in expected.items():
        anchor = observed[relative_path]
        if anchor.sha256 != expected_sha256 or sha256_file(anchor.path) != expected_sha256:
            raise FinalDiscoveryCampaignError(
                f"production input-file anchor differs: {relative_path}"
            )
    assert request.passage_sources is not None
    if request.passage_sources.hebrew_ketiv_tokens_path is None:
        raise FinalDiscoveryCampaignError("production Ketiv token source is absent")
    governed_manifest_paths = {
        "data/processed/passages/schema-v1/table-hashes.json": (
            request.passage_sources.resolved_passage_hash_manifest_path
        ),
        "data/processed/macula-hebrew/25.08.11/table-hashes.json": (
            request.passage_sources.resolved_hebrew_hash_manifest_path
        ),
        "data/processed/macula-greek/24.06.17/table-hashes.json": (
            request.passage_sources.resolved_greek_hash_manifest_path
        ),
        "data/processed/oshb-morphhb/master-3d15126/table-hashes.json": (
            request.passage_sources.resolved_hebrew_ketiv_hash_manifest_path
        ),
    }
    for relative_path, source_path in governed_manifest_paths.items():
        if source_path.resolve() != observed[relative_path].path.resolve():
            raise FinalDiscoveryCampaignError(
                f"passage extraction is not bound to governed input: {relative_path}"
            )
    prepared_sha256 = sha256_file(request.prepared_passages_path)
    if request.prepared_passages_expected_sha256 != prepared_sha256:
        raise FinalDiscoveryCampaignError(
            "prepared passage projection differs from its operator-authorized SHA-256"
        )
    if request.knownness_source_path is None or request.knownness_source_sha256 is None:
        raise FinalDiscoveryCampaignError("production requires a hash-pinned knownness JSONL")
    if sha256_file(request.knownness_source_path) != request.knownness_source_sha256:
        raise FinalDiscoveryCampaignError("knownness JSONL differs from its authorized SHA-256")
    if request.knownness_projection_receipt_path is None:
        raise FinalDiscoveryCampaignError("production knownness receipt is absent")
    knownness_input = next(item for item in request.config.inputs if item.role == "knownness")
    expected_knownness_manifest = next(iter(knownness_input.expected_hashes.values()))
    authenticate_knownness_jsonl(
        request.knownness_source_path,
        request.knownness_projection_receipt_path,
        expected_manifest_sha256=expected_knownness_manifest,
    )
    if (
        request.knownness_benchmark_root is None
        or (request.knownness_benchmark_root / "table-hashes.json").resolve()
        != observed["data/processed/benchmarks/schema-v1/table-hashes.json"].path.resolve()
    ):
        raise FinalDiscoveryCampaignError(
            "knownness extraction is not bound to the governed M6 benchmark root"
        )


def _validate_production_passages(path: Path) -> None:
    passages = read_jsonl(path, PassageRecord)
    genres = load_book_genres()
    primary = _primary_discovery_passages(passages)
    primary_books = {passage.book for passage in primary}
    if primary_books != set(genres):
        raise FinalDiscoveryCampaignError(
            "production prepared passages do not cover the 66-book primary verse canon"
        )
    stream_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    stream_references: set[tuple[str, str, str, str]] = set()
    for passage in passages:
        stream = (passage.corpus, passage.analysis_profile, passage.analysis_reading)
        stream_counts[stream] += 1
        reference_key = (*stream, passage.reference)
        if reference_key in stream_references:
            raise FinalDiscoveryCampaignError(
                "prepared passages repeat a reference inside one governed stream"
            )
        stream_references.add(reference_key)
    if dict(stream_counts) != _EXPECTED_PRODUCTION_PASSAGE_STREAM_COUNTS:
        raise FinalDiscoveryCampaignError(
            "production passage streams differ from the exact accepted M5 verse counts"
        )
    if any(passage.genre != genres[passage.book] for passage in passages):
        raise FinalDiscoveryCampaignError("prepared passage genre labels differ from governance")


def _assert_knownness_projection_is_canonical(
    receipt: KnownnessProjectionReceipt,
) -> None:
    observed = {
        "eligible_source_relationship_count": receipt.eligible_source_relationship_count,
        "mapped_endpoint_target_count": receipt.mapped_endpoint_target_count,
        "expanded_edge_count": receipt.expanded_edge_count,
        "excluded_self_edge_count": receipt.excluded_self_edge_count,
        "row_count": receipt.row_count,
        "represented_source_relationship_count": (receipt.represented_source_relationship_count),
        "unique_unordered_pair_count": receipt.unique_unordered_pair_count,
        "multi_pair_relationship_count": receipt.multi_pair_relationship_count,
        "maximum_pairs_per_relationship": receipt.maximum_pairs_per_relationship,
    }
    expected = {
        "eligible_source_relationship_count": 344_799,
        "mapped_endpoint_target_count": 954_614,
        "expanded_edge_count": 608_600,
        "excluded_self_edge_count": 67,
        "row_count": 608_533,
        "represented_source_relationship_count": 341_926,
        "unique_unordered_pair_count": 550_333,
        "multi_pair_relationship_count": 87_436,
        "maximum_pairs_per_relationship": 182,
    }
    if observed != expected:
        raise FinalDiscoveryCampaignError(
            f"M6 knownness projection differs from the accepted complete graph: {observed}"
        )


def _assert_checkpoint_disk_floor(request: CampaignRequest) -> None:
    """Fail safely at stage boundaries; this is deliberately not a monitor."""

    floor = request.minimum_free_disk_bytes
    if floor is None:
        return
    free = shutil.disk_usage(request.stage_store.root).free
    if free < floor:
        raise FinalDiscoveryCampaignError(
            "checkpoint disk floor reached before the next stage: "
            f"free_bytes={free}, required_bytes={floor}"
        )


def _upload_stage_checkpoint(
    request: CampaignRequest,
    result: StageRunResult,
    *,
    supplemental_files: Mapping[str, Path] | None = None,
) -> StageCheckpointReceipt:
    try:
        store = request.checkpoint_stores[result.manifest.stage_id]
    except KeyError as exc:
        raise FinalDiscoveryCampaignError(
            f"durable checkpoint store is absent for stage {result.manifest.stage_id}"
        ) from exc
    checkpoint_root = (
        request.stage_store.root.parent
        / "checkpoint-packages"
        / f"{result.manifest.stage_number:02d}-{result.manifest.stage_id}"
        / f"{result.completion_manifest_sha256}-{uuid4().hex}"
    )
    receipt = package_and_upload_stage_checkpoint(
        request.stage_store,
        result,
        store,
        checkpoint_root=checkpoint_root,
        expected_store_identity=store.identity,
        supplemental_files=supplemental_files,
    )
    _write_json_new(
        checkpoint_root / "stage-checkpoint-receipt.json",
        receipt.model_dump(mode="json"),
    )
    return receipt


def _produce_stage_one(
    root: Path,
    request: CampaignRequest,
    positive_controls: PositiveControlDataset,
) -> None:
    passages = read_jsonl(request.prepared_passages_path, PassageRecord)
    _passage_index(passages)
    projection_receipt = None
    if request.execution_mode == "production":
        assert request.passage_sources is not None
        expected_hashes = {
            name: digest
            for artifact in request.config.inputs
            for name, digest in artifact.expected_hashes.items()
        }
        projection_receipt = authenticate_prepared_passage_projection(
            request.prepared_passages_path,
            request.passage_sources,
            scope=request.passage_projection_scope,
            extraction_code_sha256=request.code_sha256,
            expected_passage_manifest_sha256=expected_hashes[
                "data/processed/passages/schema-v1/table-hashes.json"
            ],
            expected_hebrew_manifest_sha256=expected_hashes[
                "data/processed/macula-hebrew/25.08.11/table-hashes.json"
            ],
            expected_greek_manifest_sha256=expected_hashes[
                "data/processed/macula-greek/24.06.17/table-hashes.json"
            ],
            expected_hebrew_ketiv_manifest_sha256=expected_hashes[
                "data/processed/oshb-morphhb/master-3d15126/table-hashes.json"
            ],
        )
        assert request.knownness_source_path is not None
        assert request.knownness_projection_receipt_path is not None
        assert request.knownness_benchmark_root is not None
        expected_knownness_manifest = expected_hashes[
            "data/processed/benchmarks/schema-v1/table-hashes.json"
        ]
        supplied_knownness_receipt = authenticate_knownness_jsonl(
            request.knownness_source_path,
            request.knownness_projection_receipt_path,
            expected_manifest_sha256=expected_knownness_manifest,
        )
        generated_knownness_receipt = project_openbible_knownness(
            request.knownness_benchmark_root,
            root / "known-relationships.jsonl",
            root / "knownness-projection-receipt.json",
            expected_manifest_sha256=expected_knownness_manifest,
            memory_limit_bytes=_KNOWNNESS_PROJECTION_MEMORY_LIMIT_BYTES,
            temp_directory=root / "knownness-duckdb-temp",
        )
        _assert_knownness_projection_is_canonical(generated_knownness_receipt)
        primary_ids = {passage.passage_id for passage in _primary_discovery_passages(passages)}
        for relationship in iter_authenticated_knownness_jsonl(
            root / "known-relationships.jsonl",
            root / "knownness-projection-receipt.json",
            expected_manifest_sha256=expected_knownness_manifest,
        ):
            if (
                relationship.source_passage_id not in primary_ids
                or relationship.target_passage_id not in primary_ids
            ):
                raise FinalDiscoveryCampaignError(
                    "M6 knownness projection references a non-primary passage"
                )
        if (
            supplied_knownness_receipt.logical_sha256 != generated_knownness_receipt.logical_sha256
            or supplied_knownness_receipt.jsonl_sha256 != generated_knownness_receipt.jsonl_sha256
            or supplied_knownness_receipt.row_count != generated_knownness_receipt.row_count
        ):
            raise FinalDiscoveryCampaignError(
                "supplied knownness cache differs from fresh authenticated M6 projection"
            )
        known_relationship_count = generated_knownness_receipt.row_count
    else:
        write_jsonl_atomic(
            root / "known-relationships.jsonl",
            request.known_relationships,
            sort_key="relationship_id",
        )
        _write_json_new(
            root / "knownness-projection-receipt.json",
            {
                "fixture_only": True,
                "row_count": len(request.known_relationships),
                "logical_sha256": _models_sha256(request.known_relationships),
            },
        )
        known_relationship_count = len(request.known_relationships)
    primary_ids_for_formulaic_control = {
        passage.passage_id for passage in _primary_discovery_passages(passages)
    }
    (
        passages,
        formulaic_features,
        formulaic_passage_rows,
        formulaic_report,
    ) = apply_formulaic_control(
        passages,
        primary_passage_ids=primary_ids_for_formulaic_control,
        policy=request.config.formulaic_control,
    )
    receipt = materialize_authenticated_input(request.m7_store, root / "m7", request.m7_expectation)
    if request.execution_mode == "production":
        report = authenticate_m7_input(
            root / "m7",
            expected_manifest_sha256=request.m7_expectation.table_hashes_sha256,
            verify_individual_files=True,
        )
        _write_json_new(root / "m7-authentication-report.json", report.model_dump(mode="json"))
    else:
        _write_json_new(
            root / "m7-authentication-report.json",
            {
                "fixture_only": True,
                "manifest_sha256": request.m7_expectation.table_hashes_sha256,
                "object_count": receipt.object_count,
            },
        )
    write_jsonl_atomic(root / "passages.jsonl", passages, sort_key="passage_id")
    write_jsonl_atomic(
        root / "formulaic-features.jsonl",
        formulaic_features,
        sort_key="feature_id",
    )
    write_jsonl_atomic(
        root / "passage-formulaic-controls.jsonl",
        formulaic_passage_rows,
        sort_key="passage_id",
    )
    _write_json_new(
        root / "formulaic-control-report.json",
        formulaic_report.model_dump(mode="json"),
    )
    write_jsonl_atomic(
        root / "positive-controls.jsonl",
        positive_controls.rows,
        sort_key="control_id",
    )
    _write_json_new(
        root / "positive-control-validation.json",
        positive_controls.validation.model_dump(mode="json"),
    )
    _write_json_new(
        root / "passage-projection-authentication.json",
        (
            projection_receipt.model_dump(mode="json")
            if projection_receipt is not None
            else {
                "fixture_only": True,
                "prepared_jsonl_sha256": sha256_file(request.prepared_passages_path),
                "row_count": len(passages),
            }
        ),
    )
    _write_json_new(
        root / "input-file-anchors.json",
        {
            "anchors": [
                {
                    "relative_path": anchor.relative_path,
                    "sha256": anchor.sha256,
                }
                for anchor in sorted(
                    request.input_file_anchors,
                    key=lambda item: item.relative_path,
                )
            ]
        },
    )
    _write_json_new(root / "materialization-receipt.json", _materialization_payload(receipt))
    _write_json_new(
        root / "input-summary.json",
        {
            "execution_mode": request.execution_mode,
            "m7_policy": "authenticate_and_reuse_canonical_m7_never_recompute",
            "passage_count": len(passages),
            "primary_discovery_passage_count": len(_primary_discovery_passages(passages)),
            "sensitivity_passage_count": len(passages) - len(_primary_discovery_passages(passages)),
            "sensitivity_records_enter_candidate_universe": False,
            "passages_source_sha256": sha256_file(request.prepared_passages_path),
            "known_relationship_count": known_relationship_count,
            "positive_control_count": len(positive_controls.rows),
            "formulaic_passage_count": formulaic_report.formulaic_passage_count,
        },
    )
    primary = _primary_discovery_passages(passages)
    scale_contract = _campaign_scale_for_request(request, len(primary))
    _write_json_new(
        root / "campaign-scale-contract.json",
        scale_contract.model_dump(mode="json"),
    )
    primary_ids = {passage.passage_id for passage in primary}
    sensitivity = tuple(passage for passage in passages if passage.passage_id not in primary_ids)
    _write_json_new(
        root / "passage-scope-receipt.json",
        {
            "primary_scope": "edition_complete_hebrew_qere_and_greek_source_verse",
            "primary_count": len(primary),
            "primary_passage_ids_sha256": _hash_sequence(
                sorted(passage.passage_id for passage in primary)
            ),
            "sensitivity_scope": "critical_core_and_hebrew_ketiv_distinct_records",
            "sensitivity_count": len(sensitivity),
            "sensitivity_passage_ids_sha256": _hash_sequence(
                sorted(passage.passage_id for passage in sensitivity)
            ),
            "sensitivity_records_enter_candidate_universe": False,
        },
    )


def _produce_stage_two(
    root: Path, request: CampaignRequest, passages: Sequence[PassageRecord]
) -> None:
    representation = build_tfidf_representation(passages, _semantic_retrieval_features)
    neighbors = blockwise_top_k_sparse(
        representation,
        k=request.config.retrieval.sparse_top_k,
        block_size=request.config.retrieval.block_size,
    )
    pairs = set(canonical_neighbor_pairs(neighbors))
    model_payload: dict[str, object] = {
        "enabled": False,
        "model_id": request.config.embedding_model.model_id,
        "revision": request.config.embedding_model.revision,
        "optional": True,
    }
    if request.offline_model_root is not None and request.encoder is not None:
        report = verify_model_artifacts(request.offline_model_root, request.config.embedding_model)
        runtime_report = verify_model_runtime_dependencies(request.config.embedding_model)
        if isinstance(request.encoder, OfflineSentenceTransformerEncoder) and (
            request.encoder.model_artifact_report.model_dump(mode="json")
            != report.model_dump(mode="json")
            or request.encoder.runtime_dependency_report.model_dump(mode="json")
            != runtime_report.model_dump(mode="json")
        ):
            raise FinalDiscoveryCampaignError(
                "the production encoder is not bound to its model and runtime inventory"
            )
        original = encode_passages(
            passages,
            encoder=request.encoder,
            pin=request.config.embedding_model,
            english_gloss=False,
        )
        english = encode_passages(
            passages,
            encoder=request.encoder,
            pin=request.config.embedding_model,
            english_gloss=True,
        )
        _write_embedding_artifact(root, "original", original)
        _write_embedding_artifact(root, "english", english)
        pairs.update(
            _embedding_neighbor_pairs(
                original,
                k=request.config.retrieval.embedding_top_k,
                block_size=request.config.retrieval.block_size,
            )
        )
        pairs.update(
            _embedding_neighbor_pairs(
                english,
                k=request.config.retrieval.embedding_top_k,
                block_size=request.config.retrieval.block_size,
            )
        )
        model_payload = {
            "enabled": True,
            **report.model_dump(mode="json"),
            "runtime": runtime_report.model_dump(mode="json"),
        }
    scale = _campaign_scale_for_request(request, len(passages))
    if len(pairs) > scale.maximum_stage_two_semantic_pairs:
        raise FinalDiscoveryCampaignError(
            "Stage 2 semantic candidate population exceeds the governed scale contract"
        )
    _write_json_new(root / "model-report.json", model_payload)
    _write_json_new(
        root / "semantic-index.json",
        {
            "representation": "annotation_tfidf_plus_optional_pinned_offline_e5",
            "passage_count": len(passages),
            "feature_count": len(representation.feature_ids),
            "sparse_retrieval_top_k": request.config.retrieval.sparse_top_k,
            "embedding_retrieval_top_k": request.config.retrieval.embedding_top_k,
            "retrieval_block_size": request.config.retrieval.block_size,
            "candidate_pairs": [list(pair) for pair in sorted(pairs)],
        },
    )


def _produce_stage_three(
    root: Path,
    request: CampaignRequest,
    passages: Sequence[PassageRecord],
    passage_by_id: Mapping[str, PassageRecord],
    registrations: Mapping[str, DetectorRegistration],
    stage_one_root: Path,
    stage_two_root: Path,
) -> None:
    semantic_pairs = set(_read_pair_index(stage_two_root / "semantic-index.json"))
    if request.execution_mode == "production":
        projection_path = build_m7_lexical_projection(
            stage_one_root / "m7",
            root / "m7-lexical-projection.parquet",
            memory_limit_bytes=_M7_PROJECTION_MEMORY_LIMIT_BYTES,
            temp_directory=root / "duckdb-temp",
        )
        selected_m7_pairs = _select_m7_evidence_pairs(
            iter_m7_raw_evidence(
                projection_path,
                registration=registrations["m7_lexical_rrf"],
                source_artifact_sha256=request.m7_expectation.table_hashes_sha256,
            ),
            passage_by_id,
            required_pairs=semantic_pairs,
            maximum_seed_pairs=request.config.retrieval.maximum_m7_seed_pairs,
        )
        lexical: Iterable[RawEvidence] = (
            row
            for row in iter_m7_raw_evidence(
                projection_path,
                registration=registrations["m7_lexical_rrf"],
                source_artifact_sha256=request.m7_expectation.table_hashes_sha256,
            )
            if row.candidate_pair_id in selected_m7_pairs
        )
    else:
        lexical = tuple(request.fixture_m7_evidence)
        selected_m7_pairs = {
            row.candidate_pair_id: (row.passage_a_id, row.passage_b_id) for row in lexical
        }
        _validate_fixture_m7_evidence(lexical, passage_by_id, registrations)
        _write_json_new(
            root / "fixture-m7-projection.json",
            {"fixture_only": True, "evidence_count": len(lexical)},
        )
    candidate_pairs_by_id = {
        candidate_pair_id(first, second): (first, second) for first, second in semantic_pairs
    }
    if len(candidate_pairs_by_id) != len(semantic_pairs):
        raise FinalDiscoveryCampaignError("semantic candidate identities collide")
    for pair_id, pair in selected_m7_pairs.items():
        prior = candidate_pairs_by_id.setdefault(pair_id, pair)
        if prior != pair:
            raise FinalDiscoveryCampaignError("M7 and semantic candidate identities collide")
    scale = _campaign_scale_for_request(request, len(passages))
    if len(candidate_pairs_by_id) > scale.maximum_stage_three_pairs:
        raise FinalDiscoveryCampaignError(
            "Stage 3 candidate population exceeds the governed scale contract"
        )
    original = _read_embedding_artifact(stage_two_root, "original")
    english = _read_embedding_artifact(stage_two_root, "english")
    passages_hash = sha256_file(stage_one_root / "passages.jsonl")
    model_report = _read_json_object(stage_two_root / "model-report.json")
    model_inventory_sha256 = (
        str(model_report["inventory_sha256"])
        if original is not None or english is not None
        else None
    )
    embedding_source_sha256 = (
        _json_sha256(
            {
                "model_inventory_sha256": model_inventory_sha256,
                "passage_projection_sha256": passages_hash,
            }
        )
        if model_inventory_sha256 is not None
        else None
    )
    lexical_count = 0

    def raw_rows() -> Iterator[RawEvidence]:
        nonlocal lexical_count
        lexical_iterator = iter(lexical)
        lexical_row = next(lexical_iterator, None)
        prior_lexical_id: str | None = None
        for pair_id in sorted(candidate_pairs_by_id):
            first, second = candidate_pairs_by_id[pair_id]
            rows = list(
                semantic_pair_evidence(
                    passage_by_id[first],
                    passage_by_id[second],
                    registrations=registrations,
                    source_artifact_id="prepared-passage-projection-v1",
                    source_artifact_sha256=passages_hash,
                    original_embeddings=original,
                    english_embeddings=english,
                    embedding_model=(
                        request.config.embedding_model
                        if original is not None or english is not None
                        else None
                    ),
                    embedding_source_artifact_sha256=(
                        embedding_source_sha256
                        if original is not None or english is not None
                        else None
                    ),
                    embedding_model_inventory_sha256=model_inventory_sha256,
                    embedding_passage_projection_sha256=(
                        passages_hash if original is not None or english is not None else None
                    ),
                )
            )
            if lexical_row is not None and lexical_row.candidate_pair_id < pair_id:
                raise FinalDiscoveryCampaignError("selected M7 evidence is not pair ordered")
            if lexical_row is not None and lexical_row.candidate_pair_id == pair_id:
                if (
                    prior_lexical_id is not None
                    and lexical_row.candidate_pair_id <= prior_lexical_id
                ):
                    raise FinalDiscoveryCampaignError("selected M7 evidence repeats a pair")
                rows.append(lexical_row)
                lexical_count += 1
                prior_lexical_id = lexical_row.candidate_pair_id
                lexical_row = next(lexical_iterator, None)
            yield from sorted(rows, key=lambda item: item.detector_id)
        if lexical_row is not None or lexical_count != len(selected_m7_pairs):
            raise FinalDiscoveryCampaignError(
                "authenticated M7 selection did not emit every selected identity"
            )

    raw_receipt = write_jsonl_stream_atomic(
        root / "raw-evidence.jsonl",
        raw_rows(),
        order_key=_raw_evidence_order_key,
        require_strict_order=True,
    )
    if raw_receipt.row_count > scale.maximum_stage_three_raw_evidence_rows:
        raise FinalDiscoveryCampaignError(
            "Stage 3 evidence population exceeds the governed scale contract"
        )
    _write_json_new(
        root / "semantic-evidence-summary.json",
        {
            "passage_count": len(passages),
            "candidate_pair_count": len(candidate_pairs_by_id),
            "m7_lexical_evidence_count": lexical_count,
            "raw_evidence_count": raw_receipt.row_count,
            "raw_evidence_streamed": True,
            "m7_was_rerun": False,
            "m7_adapter_projection_used": request.execution_mode == "production",
        },
    )


def _produce_stage_four(
    root: Path,
    request: CampaignRequest,
    passages: Sequence[PassageRecord],
    passage_by_id: Mapping[str, PassageRecord],
    registrations: Mapping[str, DetectorRegistration],
    passages_hash: str,
) -> None:
    representation = build_tfidf_representation(passages, grammatical_features)
    pairs = canonical_neighbor_pairs(
        blockwise_top_k_sparse(
            representation,
            k=request.config.retrieval.sparse_top_k,
            block_size=request.config.retrieval.block_size,
        )
    )
    document_frequencies = feature_document_frequencies(passages)
    pairs_by_id = {candidate_pair_id(first, second): (first, second) for first, second in pairs}
    if len(pairs_by_id) != len(pairs):
        raise FinalDiscoveryCampaignError("grammar candidate identities collide")
    scale = _campaign_scale_for_request(request, len(passages))
    if len(pairs) > scale.maximum_stage_four_pairs:
        raise FinalDiscoveryCampaignError(
            "Stage 4 candidate population exceeds the governed scale contract"
        )
    raw_receipt = write_jsonl_stream_atomic(
        root / "raw-evidence.jsonl",
        (
            row
            for pair_id in sorted(pairs_by_id)
            for first, second in (pairs_by_id[pair_id],)
            for row in sorted(
                grammar_pair_evidence(
                    passage_by_id[first],
                    passage_by_id[second],
                    registrations=registrations,
                    document_frequencies=document_frequencies,
                    passage_count=len(passages),
                    source_artifact_id="prepared-passage-projection-v1",
                    source_artifact_sha256=passages_hash,
                ),
                key=lambda item: item.detector_id,
            )
        ),
        order_key=_raw_evidence_order_key,
        require_strict_order=True,
    )
    if raw_receipt.row_count > scale.maximum_stage_four_raw_evidence_rows:
        raise FinalDiscoveryCampaignError(
            "Stage 4 evidence population exceeds the governed scale contract"
        )
    _write_json_new(
        root / "grammar-index-summary.json",
        {
            "feature_count": len(representation.feature_ids),
            "candidate_pair_count": len(pairs),
            "raw_evidence_count": raw_receipt.row_count,
            "raw_evidence_streamed": True,
        },
    )


def _produce_stage_five(
    root: Path,
    request: CampaignRequest,
    passages: Sequence[PassageRecord],
    passage_by_id: Mapping[str, PassageRecord],
    registrations: Mapping[str, DetectorRegistration],
    passages_hash: str,
) -> None:
    representation = build_tfidf_representation(passages, _structural_retrieval_features)
    pairs = canonical_neighbor_pairs(
        blockwise_top_k_sparse(
            representation,
            k=request.config.retrieval.sparse_top_k,
            block_size=request.config.retrieval.block_size,
        )
    )
    pairs_by_id = {candidate_pair_id(first, second): (first, second) for first, second in pairs}
    if len(pairs_by_id) != len(pairs):
        raise FinalDiscoveryCampaignError("structure candidate identities collide")
    scale = _campaign_scale_for_request(request, len(passages))
    if len(pairs) > scale.maximum_stage_five_pairs:
        raise FinalDiscoveryCampaignError(
            "Stage 5 candidate population exceeds the governed scale contract"
        )
    raw_receipt = write_jsonl_stream_atomic(
        root / "raw-evidence.jsonl",
        (
            structure_pair_evidence(
                passage_by_id[first],
                passage_by_id[second],
                registrations=registrations,
                source_artifact_id="prepared-passage-projection-v1",
                source_artifact_sha256=passages_hash,
            )
            for pair_id in sorted(pairs_by_id)
            for first, second in (pairs_by_id[pair_id],)
        ),
        order_key=_raw_evidence_order_key,
        require_strict_order=True,
    )
    if raw_receipt.row_count > scale.maximum_stage_five_raw_evidence_rows:
        raise FinalDiscoveryCampaignError(
            "Stage 5 evidence population exceeds the governed scale contract"
        )
    _write_json_new(
        root / "structure-index-summary.json",
        {
            "feature_count": len(representation.feature_ids),
            "candidate_pair_count": len(pairs),
            "raw_evidence_count": raw_receipt.row_count,
            "raw_evidence_streamed": True,
        },
    )


def _produce_stage_six(
    root: Path,
    request: CampaignRequest,
    passage_by_id: Mapping[str, PassageRecord],
    registrations: Mapping[str, DetectorRegistration],
    stage_three_root: Path,
    stage_four_root: Path,
    stage_five_root: Path,
) -> None:
    scale = _campaign_scale_for_request(request, len(passage_by_id))
    sources = (
        stage_three_root / "raw-evidence.jsonl",
        stage_four_root / "raw-evidence.jsonl",
        stage_five_root / "raw-evidence.jsonl",
    )
    source_hash = _hash_sequence(sha256_file(path) for path in sources)
    if request.execution_mode == "production":
        projection = project_anomaly_pair_scores_disk_backed(
            sources,
            root / "anomaly-pair-projection",
            config=request.config,
            memory_limit_bytes=_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES,
            temp_directory=root / "anomaly-pair-projection-duckdb-temp",
            threads=_FINAL_DISCOVERY_DUCKDB_THREADS,
        )
        calibrated = calibrate_anomaly_evidence_disk_backed(
            projection.pair_family_scores_path,
            passage_by_id,
            root / "anomaly-calibration-bundle",
            config=request.config,
            source_artifact_id="stage-3-5-family-evidence",
            source_artifact_sha256=source_hash,
            memory_limit_bytes=_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES,
            temp_directory=root / "anomaly-calibration-duckdb-temp",
            threads=_FINAL_DISCOVERY_DUCKDB_THREADS,
        )
        if (
            projection.receipt.eligible_pair_count > scale.maximum_retained_candidate_pairs
            or calibrated.receipt.candidate_pair_count > scale.maximum_stage_six_raw_evidence_rows
        ):
            raise FinalDiscoveryCampaignError(
                "Stage 6 anomaly population exceeds the governed scale contract"
            )
        raw_evidence_path = root / "raw-evidence.jsonl"
        calibrated.anomaly_evidence_path.rename(raw_evidence_path)
        _promote_bundle_files(calibrated.output_directory, root)
        _write_json_new(
            root / "anomaly-summary.json",
            {
                "eligible_multi_family_pair_count": projection.receipt.eligible_pair_count,
                "anomaly_evidence_count": calibrated.receipt.candidate_pair_count,
                "anomaly_stratum_count": calibrated.receipt.anomaly_stratum_count,
                "diagnostic_not_independent": True,
                "disk_backed": True,
                "pair_projection_receipt": projection.receipt.model_dump(mode="json"),
                "anomaly_calibration_receipt": calibrated.receipt.model_dump(mode="json"),
            },
        )
        return
    raw = tuple(row for path in sources for row in read_jsonl(path, RawEvidence))
    detector_references: dict[str, list[float]] = defaultdict(list)
    for row in raw:
        detector_references[row.detector_id].append(row.raw_score)
    grouped: dict[str, list[RawEvidence]] = defaultdict(list)
    for row in raw:
        grouped[row.candidate_pair_id].append(row)
    observations: list[PairFamilyScores] = []
    for pair_id, rows in sorted(grouped.items()):
        family_scores: dict[EvidenceFamily, float] = {}
        for row in rows:
            normalized = empirical_percentile(
                row.raw_score,
                detector_references[row.detector_id],
            )
            family_scores[row.family] = max(family_scores.get(row.family, 0.0), normalized)
        if len(family_scores) < 2:
            continue
        first = rows[0]
        observations.append(
            PairFamilyScores(
                candidate_pair_id=pair_id,
                passage_a_id=first.passage_a_id,
                passage_b_id=first.passage_b_id,
                family_scores=family_scores,
                formulaic_control=any(
                    row.source_quality is not None and row.source_quality.formulaic_language
                    for row in rows
                ),
            )
        )
    anomaly = anomaly_evidence(
        observations,
        passage_by_id,
        registrations=registrations,
        source_artifact_id="stage-3-5-family-evidence",
        source_artifact_sha256=source_hash,
    )
    if len(anomaly) > scale.maximum_stage_six_raw_evidence_rows:
        raise FinalDiscoveryCampaignError(
            "Stage 6 anomaly population exceeds the governed scale contract"
        )
    write_jsonl_atomic(root / "raw-evidence.jsonl", anomaly, sort_key="candidate_pair_id")
    _write_json_new(
        root / "anomaly-summary.json",
        {
            "eligible_multi_family_pair_count": len(observations),
            "anomaly_evidence_count": len(anomaly),
            "diagnostic_not_independent": True,
        },
    )


def _produce_stage_seven(
    root: Path,
    request: CampaignRequest,
    positive_controls: PositiveControlDataset,
    passage_by_id: Mapping[str, PassageRecord],
    stage_three_root: Path,
    stage_four_root: Path,
    stage_five_root: Path,
    stage_six_root: Path,
) -> None:
    scale = _campaign_scale_for_request(request, len(passage_by_id))
    source_paths = tuple(
        stage / "raw-evidence.jsonl"
        for stage in (stage_three_root, stage_four_root, stage_five_root, stage_six_root)
    )
    positive_control_report = evaluate_positive_controls(
        positive_controls,
        tuple(passage_by_id[key] for key in sorted(passage_by_id)),
        merge_sorted_jsonl(
            source_paths,
            RawEvidence,
            key=lambda row: (row.candidate_pair_id, row.detector_id),
        ),
        seed=request.config.random_seed,
        detector_families={
            registration.detector_id: registration.family
            for registration in request.config.detectors
        },
    )
    write_jsonl_atomic(
        root / "positive-control-evaluation-rows.jsonl",
        positive_control_report.rows,
        sort_key="control_id",
    )
    _write_json_new(
        root / "positive-control-evaluation.json",
        positive_control_report.model_dump(mode="json"),
    )
    iterations = (
        request.config.calibration.production_iterations
        if request.execution_mode == "production"
        else request.config.calibration.fixture_iterations
    )
    seed = request.config.calibration.seeds["stratified_permutation"]
    if request.execution_mode == "production":
        calibration = calibrate_detector_evidence_disk_backed(
            source_paths,
            _iter_pair_strata(source_paths, passage_by_id),
            root / "detector-calibration-bundle",
            config=request.config,
            iterations=iterations,
            memory_limit_bytes=_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES,
            temp_directory=root / "detector-calibration-duckdb-temp",
            threads=_FINAL_DISCOVERY_DUCKDB_THREADS,
        )
        if (
            calibration.receipt.raw_evidence_row_count > scale.maximum_total_raw_evidence_rows
            or calibration.receipt.candidate_pair_count > scale.maximum_retained_candidate_pairs
        ):
            raise FinalDiscoveryCampaignError(
                "Stage 7 calibrated population exceeds the governed scale contract"
            )
        _promote_bundle_files(calibration.output_directory, root)
        group_ids = tuple(request.config.ensemble.group_weights)
        compact_scores = write_compact_group_scores(
            _iter_compact_group_score_rows(
                root / "evidence.jsonl",
                passage_by_id,
                request.config,
            ),
            root / "compact-group-scores",
            group_ids=group_ids,
            missing_group_score=request.config.ensemble.missing_group_score,
        )
        compact_nulls = calibrate_compact_ensemble_nulls(
            compact_scores,
            root / "compact-ensemble-null",
            config=request.config,
            iterations=iterations,
            seed=seed,
        )
        full_receipt = write_jsonl_stream_atomic(
            root / "ensemble-null-full.jsonl",
            compact_nulls.iter_rows("full"),
            order_key=_ensemble_null_order_key,
            require_strict_order=True,
        )
        ablated_receipt = write_jsonl_stream_atomic(
            root / "ensemble-null-remove-all-english.jsonl",
            compact_nulls.iter_rows("remove_all_english"),
            order_key=_ensemble_null_order_key,
            require_strict_order=True,
        )
        threshold_report = compact_nulls.threshold_report()
        threshold_report_path = root / "ensemble-null-threshold-report.json"
        _write_json_new(
            threshold_report_path,
            threshold_report.model_dump(mode="json"),
        )
        detector_payload = {
            "execution_mode": "production",
            "iterations": iterations,
            "disk_backed": True,
            "receipt_file": "detector-calibration-receipt.json",
            "raw_evidence_row_count": calibration.receipt.raw_evidence_row_count,
            "candidate_pair_count": calibration.receipt.candidate_pair_count,
            "detector_stratum_count": calibration.receipt.detector_stratum_count,
        }
        _write_json_new(root / "detector-calibration.json", detector_payload)
        _write_json_new(
            root / "final-ensemble-null-provenance.json",
            {
                "execution_mode": "production",
                "iterations": iterations,
                "seed": seed,
                "null_method": request.config.ensemble.final_null_method,
                "full_row_count": full_receipt.row_count,
                "remove_all_english_row_count": ablated_receipt.row_count,
                "pair_population_sha256": compact_scores.receipt.logical_sha256,
                "compact_group_score_receipt": compact_scores.receipt.model_dump(mode="json"),
                "compact_null_receipt": compact_nulls.receipt.model_dump(mode="json"),
                "threshold_report_file": threshold_report_path.name,
                "threshold_report_sha256": sha256_file(threshold_report_path),
                "pair_by_iteration_matrices_persisted": False,
                "threshold_count_vectors_persisted": True,
                "output_rows_retained_in_memory": False,
            },
        )
        return
    else:
        raw = tuple(
            merge_sorted_jsonl(
                source_paths,
                RawEvidence,
                key=lambda row: (row.candidate_pair_id, row.detector_id),
            )
        )
        if len(raw) > scale.maximum_total_raw_evidence_rows:
            raise FinalDiscoveryCampaignError(
                "Stage 7 raw population exceeds the governed scale contract"
            )
        pair_passages: dict[str, tuple[str, str]] = {}
        for row in raw:
            observed = (row.passage_a_id, row.passage_b_id)
            prior = pair_passages.setdefault(row.candidate_pair_id, observed)
            if prior != observed:
                raise FinalDiscoveryCampaignError(
                    f"raw evidence pair identity disagrees: {row.candidate_pair_id}"
                )
        strata = {
            pair_id: _pair_stratum(passage_by_id[first], passage_by_id[second])
            for pair_id, (first, second) in pair_passages.items()
        }
        raw_scores: dict[str, list[float]] = defaultdict(list)
        for row in raw:
            raw_scores[row.detector_id].append(row.raw_score)
        references, detector_nulls = detector_reference_and_null_scores(
            raw_scores,
            iterations=iterations,
            seed=seed,
            execution_mode="fixture",
        )
        evidence = calibrate_detector_evidence(
            raw,
            config=request.config,
            reference_scores=references,
            null_scores=detector_nulls,
        )
        detector_payload = {
            "execution_mode": "fixture",
            "iterations": iterations,
            "seed": seed,
            "reference_scores": references,
            "null_scores": detector_nulls,
        }
    group_scores = ensemble_group_scores_by_pair(evidence)
    ablated_group_scores = ensemble_group_scores_by_pair(
        evidence,
        remove_all_english=True,
    )
    full_null_rows, full_threshold_summaries = stratified_ensemble_null_calibration_with_reporting(
        group_scores,
        strata,
        config=request.config,
        iterations=iterations,
        seed=seed,
        calibration_scope="full",
    )
    ablated_null_rows, ablated_threshold_summaries = (
        stratified_ensemble_null_calibration_with_reporting(
            ablated_group_scores,
            strata,
            config=request.config,
            iterations=iterations,
            seed=seed,
            calibration_scope="remove_all_english",
        )
    )
    threshold_report = build_ensemble_null_threshold_report(
        (*full_threshold_summaries, *ablated_threshold_summaries),
        config=request.config,
        hypothesis_count=len(strata),
        iterations=iterations,
        seed=seed,
    )
    write_jsonl_atomic(root / "evidence.jsonl", evidence, sort_key="evidence_id")
    write_jsonl_atomic(
        root / "ensemble-null-full.jsonl",
        full_null_rows,
        sort_key="candidate_pair_id",
    )
    write_jsonl_atomic(
        root / "ensemble-null-remove-all-english.jsonl",
        ablated_null_rows,
        sort_key="candidate_pair_id",
    )
    _write_json_new(root / "detector-calibration.json", detector_payload)
    threshold_report_path = root / "ensemble-null-threshold-report.json"
    _write_json_new(threshold_report_path, threshold_report.model_dump(mode="json"))
    _write_json_new(
        root / "final-ensemble-null-provenance.json",
        {
            "iterations": iterations,
            "seed": seed,
            "null_method": request.config.ensemble.final_null_method,
            "full_row_count": len(full_null_rows),
            "remove_all_english_row_count": len(ablated_null_rows),
            "pair_population_sha256": _hash_sequence(sorted(strata)),
            "threshold_report_file": threshold_report_path.name,
            "threshold_report_sha256": sha256_file(threshold_report_path),
            "pair_by_iteration_matrices_persisted": False,
            "threshold_count_vectors_persisted": True,
        },
    )


def _produce_stage_eight(
    root: Path,
    request: CampaignRequest,
    passage_by_id: Mapping[str, PassageRecord],
    relationships_path: Path,
    stage_seven_root: Path,
) -> None:
    if request.execution_mode == "production":
        scale = campaign_scale_contract(
            request.config,
            primary_passage_count=len(passage_by_id),
        )
        receipt = build_final_candidates_disk_backed(
            stage_seven_root / "evidence.jsonl",
            stage_seven_root / "ensemble-null-full.jsonl",
            stage_seven_root / "ensemble-null-remove-all-english.jsonl",
            root / "candidates.jsonl",
            work_directory=root / "disk-ensemble-work",
            passages=passage_by_id,
            knownness=KnownnessIndex(iter_jsonl(relationships_path, KnownRelationship)),
            config=request.config,
            maximum_candidate_pairs=scale.maximum_retained_candidate_pairs,
            chunk_size=_DISK_ENSEMBLE_CHUNK_SIZE,
        )
        if (
            receipt.evidence_row_count > scale.maximum_total_raw_evidence_rows
            or receipt.maximum_evidence_rows_per_pair > scale.maximum_evidence_rows_per_pair
        ):
            raise FinalDiscoveryCampaignError(
                "Stage 8 ensemble population exceeds the governed scale contract"
            )
        _write_json_new(root / "disk-ensemble-receipt.json", receipt.model_dump(mode="json"))
        _write_json_new(
            root / "ensemble-summary.json",
            {
                "candidate_count": receipt.candidate_pair_count,
                "tier_a_count": receipt.tier_a_count,
                "tier_b_count": receipt.tier_b_count,
                "method": request.config.ensemble.method,
                "learned_ensemble": False,
                "disk_backed": True,
                "maximum_candidate_pair_count": receipt.maximum_candidate_pair_count,
            },
        )
        return
    evidence = read_jsonl(stage_seven_root / "evidence.jsonl", EvidenceRow)
    full_null_rows = read_jsonl(
        stage_seven_root / "ensemble-null-full.jsonl",
        EnsembleNullCalibrationRow,
    )
    ablated_null_rows = read_jsonl(
        stage_seven_root / "ensemble-null-remove-all-english.jsonl",
        EnsembleNullCalibrationRow,
    )
    full_nulls = {row.candidate_pair_id: row for row in full_null_rows}
    ablated_nulls = {row.candidate_pair_id: row for row in ablated_null_rows}
    if len(full_nulls) != len(full_null_rows) or len(ablated_nulls) != len(ablated_null_rows):
        raise FinalDiscoveryCampaignError("ensemble null calibration repeats a candidate pair")
    candidates = build_final_candidates(
        evidence,
        passage_by_id,
        knownness=KnownnessIndex(iter_jsonl(relationships_path, KnownRelationship)),
        config=request.config,
        null_calibration_by_pair=full_nulls,
        english_ablation_null_calibration_by_pair=ablated_nulls,
    )
    scale = _campaign_scale_for_request(request, len(passage_by_id))
    if len(candidates) > scale.maximum_retained_candidate_pairs:
        raise FinalDiscoveryCampaignError(
            "Stage 8 candidate population exceeds the governed scale contract"
        )
    write_jsonl_atomic(root / "candidates.jsonl", candidates, sort_key=None)
    _write_json_new(
        root / "ensemble-summary.json",
        {
            "candidate_count": len(candidates),
            "tier_a_count": sum(item.tier_a_eligible for item in candidates),
            "tier_b_count": sum(item.tier_b_rank is not None for item in candidates),
            "method": request.config.ensemble.method,
            "learned_ensemble": False,
        },
    )


def _produce_stage_nine(
    root: Path,
    request: CampaignRequest,
    passage_by_id: Mapping[str, PassageRecord],
    stage_one_root: Path,
    stage_seven_root: Path,
    stage_eight_root: Path,
) -> None:
    threshold_report_path = stage_seven_root / "ensemble-null-threshold-report.json"
    threshold_report = EnsembleNullThresholdReport.model_validate(
        _read_json_object(threshold_report_path)
    )
    if (
        threshold_report.config_sha256 != final_discovery_config_sha256(request.config)
        or threshold_report.reporting_thresholds
        != (request.config.ensemble.minimum_tier_a_ensemble_score,)
        or threshold_report.seed != request.config.calibration.seeds["stratified_permutation"]
        or threshold_report.null_method != request.config.ensemble.final_null_method
    ):
        raise FinalDiscoveryCampaignError(
            "Stage 7 threshold report differs from the frozen campaign configuration"
        )
    threshold_summary_payload = [
        summary.model_dump(mode="json", exclude={"null_discovery_counts"})
        for summary in threshold_report.summaries
    ]
    if request.execution_mode == "production":
        evidence_path = stage_seven_root / "evidence.jsonl"
        candidates_path = stage_eight_root / "candidates.jsonl"
        calibration_receipt = DiskDetectorCalibrationReceipt.model_validate(
            _read_json_object(stage_seven_root / "detector-calibration-receipt.json")
        )
        ensemble_receipt = DiskEnsembleReceipt.model_validate(
            _read_json_object(stage_eight_root / "disk-ensemble-receipt.json")
        )
        if threshold_report.hypothesis_count != ensemble_receipt.candidate_pair_count:
            raise FinalDiscoveryCampaignError(
                "Stage 7 threshold report and Stage 8 candidate populations differ"
            )
        calibrated_evidence = calibration_receipt.output_files["evidence.jsonl"]
        if (
            calibrated_evidence.row_count != ensemble_receipt.evidence_row_count
            or calibrated_evidence.sha256 != sha256_file(evidence_path)
            or ensemble_receipt.output_sha256 != sha256_file(candidates_path)
        ):
            raise FinalDiscoveryCampaignError(
                "Stage 7 and Stage 8 production receipts do not authenticate their ledgers"
            )

        index_path = root / "evidence-offset-index.sqlite3"
        index_receipt = build_evidence_offset_index(
            evidence_path,
            index_path,
            expected_source_sha256=calibrated_evidence.sha256,
            expected_evidence_row_count=ensemble_receipt.evidence_row_count,
            expected_maximum_rows_per_pair=(ensemble_receipt.maximum_evidence_rows_per_pair),
        )
        if index_receipt.candidate_pair_count != ensemble_receipt.candidate_pair_count:
            raise FinalDiscoveryCampaignError(
                "evidence offset index and ensemble candidate populations differ"
            )
        _write_json_new(
            root / "evidence-offset-index-receipt.json",
            index_receipt.model_dump(mode="json"),
        )

        with EvidenceOffsetLookup(index_path, evidence_path) as evidence_lookup:
            selected_m7 = (
                row
                for candidate in iter_bounded_dossier_candidates(
                    iter_jsonl(candidates_path, FinalCandidate),
                    tier_a_dossier_limit=request.config.review.tier_a_dossier_limit,
                )
                for row in evidence_lookup(candidate)
                if row.detector_id == "m7_lexical_rrf"
            )
            hydration_index_path = root / "m7-hydrated-evidence.sqlite3"
            hydration_receipt = build_m7_hydration_index(
                selected_m7,
                stage_one_root / "m7",
                hydration_index_path,
                memory_limit_bytes=_M7_PROJECTION_MEMORY_LIMIT_BYTES,
                temp_directory=root / "m7-shared-evidence-hydration",
            )
            with M7HydratedEvidenceLookup(
                hydration_index_path,
                hydration_receipt,
            ) as hydrated_m7_lookup:

                def prepare_selected_evidence(
                    _candidate: FinalCandidate,
                    rows: tuple[EvidenceRow, ...],
                ) -> tuple[EvidenceRow, ...]:
                    return tuple(
                        hydrated_m7_lookup(row) if row.detector_id == "m7_lexical_rrf" else row
                        for row in rows
                    )

                review_artifacts = write_review_bundle_streaming(
                    root / "review",
                    iter_jsonl(candidates_path, FinalCandidate),
                    evidence_for_candidate=evidence_lookup,
                    passages=passage_by_id,
                    expected_candidate_count=ensemble_receipt.candidate_pair_count,
                    expected_evidence_count=ensemble_receipt.evidence_row_count,
                    tier_b_size=request.config.tiers.tier_b_size,
                    maximum_evidence_rows_per_candidate=(
                        ensemble_receipt.maximum_evidence_rows_per_pair
                    ),
                    expected_candidate_ledger_sha256=ensemble_receipt.output_sha256,
                    prepare_selected_evidence=prepare_selected_evidence,
                    threshold_report=threshold_report,
                    tier_a_dossier_limit=request.config.review.tier_a_dossier_limit,
                )
                if hydrated_m7_lookup.lookup_count != hydration_receipt.row_count:
                    raise FinalDiscoveryCampaignError(
                        "review did not consume every selected hydrated M7 evidence row "
                        "exactly once"
                    )
            hydration_index_path.unlink()
        summary = review_artifacts.summary
        if (
            summary.tier_a_count != ensemble_receipt.tier_a_count
            or summary.tier_b_count != ensemble_receipt.tier_b_count
            or summary.tier_a_dossier_count
            != min(
                request.config.review.tier_a_dossier_limit,
                ensemble_receipt.tier_a_count,
            )
            or summary.tier_b_dossier_count != ensemble_receipt.tier_b_count
        ):
            raise FinalDiscoveryCampaignError(
                "streaming review tiers or bounded dossier selection disagree with the "
                "authenticated ensemble receipt"
            )

        tier_a_receipt = write_jsonl_stream_atomic(
            root / "tier-a.jsonl",
            (
                candidate
                for candidate in iter_jsonl(candidates_path, FinalCandidate)
                if candidate.tier_a_eligible
            ),
            order_key=None,
            require_strict_order=False,
        )
        tier_b_receipt = write_jsonl_stream_atomic(
            root / "tier-b.jsonl",
            (
                candidate
                for candidate in iter_jsonl(candidates_path, FinalCandidate)
                if candidate.tier_b_rank is not None
            ),
            order_key=None,
            require_strict_order=False,
        )
        retained_receipt = write_jsonl_stream_atomic(
            root / "retained-excluded.jsonl",
            (
                candidate
                for candidate in iter_jsonl(candidates_path, FinalCandidate)
                if not candidate.tier_a_eligible and candidate.tier_b_rank is None
            ),
            order_key=None,
            require_strict_order=False,
        )
        if (
            tier_a_receipt.row_count != summary.tier_a_count
            or tier_b_receipt.row_count != summary.tier_b_count
            or retained_receipt.row_count != summary.retained_excluded_count
        ):
            raise FinalDiscoveryCampaignError(
                "streamed tier ledgers disagree with the complete review population"
            )
        _write_json_new(
            root / "review-summary.json",
            {
                "candidate_count": summary.candidate_count,
                "evidence_count": summary.evidence_count,
                "tier_a_count": summary.tier_a_count,
                "tier_b_count": summary.tier_b_count,
                "tier_a_dossier_count": summary.tier_a_dossier_count,
                "tier_b_dossier_count": summary.tier_b_dossier_count,
                "actual_reviewed_count": summary.actual_reviewed_count,
                "retained_excluded_count": summary.retained_excluded_count,
                "candidate_stream_sha256": summary.candidate_stream_sha256,
                "evidence_review_stream_sha256": summary.evidence_stream_sha256,
                "review_stream_sha256": summary.review_stream_sha256,
                "tier_a_sha256": tier_a_receipt.sha256,
                "tier_b_sha256": tier_b_receipt.sha256,
                "retained_excluded_sha256": retained_receipt.sha256,
                "disk_backed": True,
                "full_ledgers_retained_in_python": False,
                "m7_hydration_scope": "first_100_score_ranked_tier_a_and_all_tier_b",
                "m7_hydrated_evidence_count": hydration_receipt.row_count,
                "m7_hydration_source_scans": hydration_receipt.source_scan_count,
                "m7_hydration_disk_backed_lookup": True,
                "m7_hydration_selection_batch_size": (hydration_receipt.selection_batch_size),
                "m7_hydration_maximum_selection_batch_rows_observed": (
                    hydration_receipt.maximum_selection_batch_rows_observed
                ),
                "m7_hydration_arrow_batch_size": hydration_receipt.arrow_batch_size,
                "ensemble_null_threshold_report_sha256": sha256_file(threshold_report_path),
                "ensemble_null_threshold_summaries": threshold_summary_payload,
            },
        )
        return

    evidence = read_jsonl(stage_seven_root / "evidence.jsonl", EvidenceRow)
    candidates = read_jsonl(stage_eight_root / "candidates.jsonl", FinalCandidate)
    if threshold_report.hypothesis_count != len(candidates):
        raise FinalDiscoveryCampaignError(
            "Stage 7 threshold report and Stage 8 candidate populations differ"
        )
    tier_a = tuple(item for item in candidates if item.tier_a_eligible)
    tier_b = tuple(item for item in candidates if item.tier_b_rank is not None)
    retained = tuple(
        item for item in candidates if not item.tier_a_eligible and item.tier_b_rank is None
    )
    write_jsonl_atomic(root / "tier-a.jsonl", tier_a, sort_key="candidate_pair_id")
    write_jsonl_atomic(root / "tier-b.jsonl", tier_b, sort_key="tier_b_rank")
    write_jsonl_atomic(root / "retained-excluded.jsonl", retained, sort_key="candidate_pair_id")
    fixture_review_artifacts = write_review_bundle(
        root / "review",
        candidates,
        evidence,
        passages=passage_by_id,
        threshold_report=threshold_report,
        tier_a_dossier_limit=request.config.review.tier_a_dossier_limit,
    )
    _write_json_new(
        root / "review-summary.json",
        {
            "candidate_count": fixture_review_artifacts.candidate_count,
            "evidence_count": fixture_review_artifacts.evidence_count,
            "tier_a_count": fixture_review_artifacts.tier_a_count,
            "tier_b_count": fixture_review_artifacts.tier_b_count,
            "tier_a_dossier_count": fixture_review_artifacts.tier_a_dossier_count,
            "tier_b_dossier_count": fixture_review_artifacts.tier_b_dossier_count,
            "actual_reviewed_count": fixture_review_artifacts.actual_reviewed_count,
            "retained_excluded_count": fixture_review_artifacts.retained_excluded_count,
            "disk_backed": False,
            "ensemble_null_threshold_report_sha256": sha256_file(threshold_report_path),
            "ensemble_null_threshold_summaries": threshold_summary_payload,
        },
    )


def _produce_stage_ten(
    root: Path,
    request: CampaignRequest,
    passage_by_id: Mapping[str, PassageRecord],
    relationships_path: Path,
    stage_one_root: Path,
    stage_two_root: Path,
    stage_three_root: Path,
    stage_four_root: Path,
    stage_five_root: Path,
    stage_seven_root: Path,
    stage_eight_root: Path,
) -> None:
    if request.execution_mode == "production":
        result = validate_final_discovery_disk_backed(
            stage_seven_root / "evidence.jsonl",
            stage_eight_root / "candidates.jsonl",
            stage_seven_root / "ensemble-null-full.jsonl",
            stage_seven_root / "ensemble-null-remove-all-english.jsonl",
            root / "disk-validation",
            passages=passage_by_id,
            knownness=iter_jsonl(relationships_path, KnownRelationship),
            config=request.config,
            memory_limit_bytes=_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES,
            temp_directory=root / "disk-validation-duckdb-temp",
            expected_source_artifact_sha256=_expected_evidence_source_hashes(
                request,
                stage_one_root,
                stage_two_root,
                stage_three_root,
                stage_four_root,
                stage_five_root,
            ),
            stage_store=request.stage_store,
            expected_authenticated_stage_count=9,
            threads=_FINAL_DISCOVERY_DUCKDB_THREADS,
        )
        if (
            not result.receipt.validation_passed
            or not result.report.passed
            or result.receipt.authenticated_stage_count != 9
        ):
            messages = "; ".join(f"{item.code}: {item.message}" for item in result.report.findings)
            raise FinalDiscoveryCampaignError(
                "disk-backed strict final-discovery validation failed"
                + (f": {messages}" if messages else "")
            )
        _link_new(result.report_path, root / "validation-report.json")
        _link_new(result.receipt_path, root / "validation-receipt.json")
        return

    evidence = read_jsonl(stage_seven_root / "evidence.jsonl", EvidenceRow)
    candidates = read_jsonl(stage_eight_root / "candidates.jsonl", FinalCandidate)
    full_null_rows = read_jsonl(
        stage_seven_root / "ensemble-null-full.jsonl",
        EnsembleNullCalibrationRow,
    )
    ablated_null_rows = read_jsonl(
        stage_seven_root / "ensemble-null-remove-all-english.jsonl",
        EnsembleNullCalibrationRow,
    )
    report = validate_final_discovery(
        evidence,
        candidates,
        config=request.config,
        stage_store=request.stage_store,
        require_all_stages=False,
        passages=passage_by_id,
        knownness=KnownnessIndex(iter_jsonl(relationships_path, KnownRelationship)),
        null_calibration_by_pair=full_null_rows,
        english_ablation_null_calibration_by_pair=ablated_null_rows,
    )
    if report.authenticated_stage_count != 9:
        raise FinalDiscoveryCampaignError(
            "strict validation expected exactly nine authenticated upstream stages"
        )
    if not report.passed:
        messages = "; ".join(f"{item.code}: {item.message}" for item in report.findings)
        raise FinalDiscoveryCampaignError(f"strict final-discovery validation failed: {messages}")
    _write_json_new(root / "validation-report.json", report.model_dump(mode="json"))


def _expected_evidence_source_hashes(
    request: CampaignRequest,
    stage_one_root: Path,
    stage_two_root: Path,
    stage_three_root: Path,
    stage_four_root: Path,
    stage_five_root: Path,
) -> dict[str, str]:
    """Bind every governed evidence source to its authenticated upstream state."""

    passages_sha256 = sha256_file(stage_one_root / "passages.jsonl")
    expected = {
        "m7-canonical-schema-v1": request.m7_expectation.table_hashes_sha256,
        "prepared-passage-projection-v1": passages_sha256,
        "stage-3-5-family-evidence": _hash_sequence(
            sha256_file(stage / "raw-evidence.jsonl")
            for stage in (stage_three_root, stage_four_root, stage_five_root)
        ),
    }
    model_report = _read_json_object(stage_two_root / "model-report.json")
    enabled = model_report.get("enabled")
    if not isinstance(enabled, bool):
        raise FinalDiscoveryCampaignError("Stage 2 model report has no Boolean enabled state")
    if enabled:
        inventory_sha256 = model_report.get("inventory_sha256")
        if (
            not isinstance(inventory_sha256, str)
            or len(inventory_sha256) != 64
            or any(character not in "0123456789abcdef" for character in inventory_sha256)
        ):
            raise FinalDiscoveryCampaignError(
                "enabled Stage 2 model report has no valid inventory SHA-256"
            )
        expected[
            f"{request.config.embedding_model.model_id}@{request.config.embedding_model.revision}"
        ] = _json_sha256(
            {
                "model_inventory_sha256": inventory_sha256,
                "passage_projection_sha256": passages_sha256,
            }
        )
    return expected


def _run_or_authenticate_all_stage_disk_validation(
    request: CampaignRequest,
    *,
    output_directory: Path,
    evidence_path: Path,
    candidates_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
    passage_by_id: Mapping[str, PassageRecord],
    relationships_path: Path,
    expected_source_artifact_sha256: Mapping[str, str],
) -> DiskFinalDiscoveryValidationResult:
    input_paths = (evidence_path, candidates_path, full_null_path, ablated_null_path)
    if not output_directory.exists():
        validate_final_discovery_disk_backed(
            evidence_path,
            candidates_path,
            full_null_path,
            ablated_null_path,
            output_directory,
            passages=passage_by_id,
            knownness=iter_jsonl(relationships_path, KnownRelationship),
            config=request.config,
            memory_limit_bytes=_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES,
            temp_directory=(
                output_directory.parent / "campaign-validation-work" / output_directory.name
            ),
            expected_source_artifact_sha256=expected_source_artifact_sha256,
            stage_store=request.stage_store,
            expected_authenticated_stage_count=11,
            threads=_FINAL_DISCOVERY_DUCKDB_THREADS,
        )
    if not output_directory.is_dir() or output_directory.is_symlink():
        raise FinalDiscoveryCampaignError(
            f"all-stage validation output is missing or unsafe: {output_directory}"
        )
    report_path = output_directory / "validation-report.json"
    receipt_path = output_directory / "validation-receipt.json"
    report_payload = _read_json_object(report_path)
    serialized_error_count = report_payload.pop("error_count", None)
    serialized_passed = report_payload.pop("passed", None)
    report = FinalDiscoveryValidationReport.model_validate(report_payload)
    if serialized_error_count != report.error_count or serialized_passed is not report.passed:
        raise FinalDiscoveryCampaignError(
            "all-stage validation computed fields do not match its findings"
        )
    receipt = DiskFinalDiscoveryValidationReceipt.model_validate(_read_json_object(receipt_path))
    if (
        receipt.config_sha256 != final_discovery_config_sha256(request.config)
        or receipt.expected_authenticated_stage_count != 11
        or receipt.authenticated_stage_count != 11
        or not receipt.validation_passed
        or not report.passed
        or report.authenticated_stage_count != 11
        or receipt.report_sha256 != sha256_file(report_path)
        or receipt.report_size_bytes != report_path.stat().st_size
        or receipt.retained_finding_count != len(report.findings)
    ):
        raise FinalDiscoveryCampaignError(
            "all-stage disk-validation report or receipt is not an authenticated pass"
        )
    for path, input_receipt in zip(input_paths, receipt.inputs, strict=True):
        observed = inspect_jsonl_file(path)
        if (
            observed.row_count != input_receipt.row_count
            or observed.size_bytes != input_receipt.size_bytes
            or observed.sha256 != input_receipt.sha256
        ):
            raise FinalDiscoveryCampaignError(
                f"all-stage validation input changed after validation: {input_receipt.role}"
            )
    authenticated = request.stage_store.authenticate_all_completions()
    if len(authenticated) != 11:
        raise FinalDiscoveryCampaignError(
            "all-stage validation restart authentication did not find eleven stages"
        )
    return DiskFinalDiscoveryValidationResult(
        output_directory=output_directory,
        report_path=report_path,
        receipt_path=receipt_path,
        report=report,
        receipt=receipt,
    )


def _produce_stage_eleven(
    root: Path,
    request: CampaignRequest,
    upstream_results: Sequence[StageRunResult],
    stage_one_root: Path,
    stage_two_root: Path,
    stage_three_root: Path,
    stage_four_root: Path,
    stage_five_root: Path,
    stage_six_root: Path,
    stage_seven_root: Path,
    stage_eight_root: Path,
    stage_nine_root: Path,
    stage_ten_root: Path,
) -> None:
    upload_root = root / "upload"
    upload_root.mkdir()
    package_source = upload_root / "package"
    package_source.mkdir(parents=True)
    checkpoints: list[dict[str, object]] = []
    for result in upstream_results:
        manifest_path = request.stage_store.completion_path(result.manifest.stage_id)
        destination = (
            package_source
            / "checkpoints"
            / (f"{result.manifest.stage_number:02d}-{result.manifest.stage_id}.completion.json")
        )
        _copy_new(manifest_path, destination)
        checkpoints.append(
            {
                "stage_number": result.manifest.stage_number,
                "stage_id": result.manifest.stage_id,
                "completion_manifest_sha256": result.completion_manifest_sha256,
                "output_inventory_sha256": result.manifest.output_inventory_sha256,
                "artifacts": [item.model_dump(mode="json") for item in result.manifest.artifacts],
            }
        )
    _write_json_new(
        package_source / "run-inventory.json",
        {
            "experiment_id": request.config.experiment_id,
            "execution_mode": request.execution_mode,
            "config_sha256": final_discovery_config_sha256(request.config),
            "code_sha256": request.code_sha256,
            "code_commit": request.code_commit,
            "checkpoints": checkpoints,
        },
    )
    selected_roots = {
        "inputs": (
            stage_one_root,
            (
                "input-summary.json",
                "materialization-receipt.json",
                "m7-authentication-report.json",
                "passages.jsonl",
                "known-relationships.jsonl",
                "knownness-projection-receipt.json",
                "positive-controls.jsonl",
                "positive-control-validation.json",
                "passage-projection-authentication.json",
                "passage-scope-receipt.json",
                "formulaic-features.jsonl",
                "passage-formulaic-controls.jsonl",
                "formulaic-control-report.json",
                "campaign-scale-contract.json",
                "input-file-anchors.json",
            ),
        ),
        "representations": (stage_two_root, None),
        "semantic_evidence": (stage_three_root, None),
        "grammar_syntax_evidence": (stage_four_root, None),
        "structure_narrative_evidence": (stage_five_root, None),
        "anomaly_evidence": (stage_six_root, None),
        "calibration": (stage_seven_root, None),
        "ensemble": (stage_eight_root, None),
        "review": (stage_nine_root, None),
        "validation": (stage_ten_root, None),
    }
    for label, (source_root, selected_names) in selected_roots.items():
        _copy_selected_tree(source_root, package_source / "artifacts" / label, selected_names)
    _write_json_new(
        package_source / "preregistration.json",
        request.config.model_dump(mode="json"),
    )

    package_inventory = inventory_directory(
        package_source,
        _final_package_local_identity(),
    )
    _write_json_new(
        upload_root / "package-receipt.json",
        {
            "schema_version": 1,
            "experiment_id": request.config.experiment_id,
            "package_format": "authenticated_directory_v1",
            "package_relative_path": "package",
            "source_inventory_sha256": package_inventory.sha256,
            "source_file_count": package_inventory.object_count,
            "source_total_size": package_inventory.total_size,
            "same_filesystem_hardlink_staging": True,
            "archive_materialized": False,
        },
    )
    transfer, transfer_action = resume_or_upload_and_verify_tree(
        request.destination_store,
        upload_root,
    )
    _write_json_new(root / "transfer-verification.json", _transfer_payload(transfer))
    _write_json_new(
        root / "transfer-action.json",
        {
            "action": transfer_action,
            "immutable_no_overwrite": True,
            "full_tree_verified_after_transfer": True,
        },
    )


def _semantic_retrieval_features(passage: PassageRecord) -> tuple[str, ...]:
    values: list[str] = []
    values.extend(f"domain:{value}" for value in passage.semantic_domains if value)
    values.extend(f"lemma:{value}" for value in passage.lemma_sequence if value)
    values.extend(f"root:{value}" for value in passage.root_sequence if value)
    return tuple(values)


def _fixture_passage(
    passage_id: str, *, corpus: Literal["hebrew", "greek"], ordinal: int
) -> PassageRecord:
    return PassageRecord(
        passage_id=passage_id,
        reference=f"Fixture {ordinal}:1",
        corpus=corpus,
        book=f"FixtureBook{ordinal % 2}",
        genre="narrative",
        analysis_profile="edition_complete",
        analysis_reading="source" if corpus == "greek" else "qere",
        granularity="verse",
        token_count=4,
        original_text=f"fixture original text {ordinal}",
        normalized_text=f"fixture normalized text {ordinal}",
        lemma_sequence=("say", "mercy", "king", f"token-{ordinal}"),
        root_sequence=("say", "kind", "rule", f"root-{ordinal}"),
        pos_sequence=("verb", "noun", "noun", "verb"),
        morphology_sequence=("perfect", "singular", "singular", "perfect"),
        semantic_domains=("speech", "mercy", "royalty", "action"),
        entities=("speaker", "king", "people", "speaker"),
        participants=("agent", "recipient", "agent", "recipient"),
        frames=("event:say", "event:give", "event:rule", "event:answer"),
        english_gloss=f"the king speaks mercy {ordinal}",
        source_digest=hashlib.sha256(passage_id.encode("utf-8")).hexdigest(),
    )


def _structural_retrieval_features(passage: PassageRecord) -> tuple[str, ...]:
    signature = structural_signature(passage)
    return tuple(
        f"{category}:{value}" for category in sorted(signature) for value in signature[category]
    )


def _embedding_neighbor_pairs(
    values: Mapping[str, np.ndarray],
    *,
    k: int,
    block_size: int,
) -> set[tuple[str, str]]:
    ids = tuple(sorted(values))
    if len(ids) < 2:
        return set()
    matrix = np.vstack([values[value] for value in ids])
    neighbors = blockwise_top_k_cosine(
        ids,
        matrix,
        ids,
        matrix,
        k=k,
        block_size=block_size,
    )
    return {
        cast(tuple[str, str], tuple(sorted((item.query_id, item.target_id)))) for item in neighbors
    }


def _write_embedding_artifact(root: Path, label: str, values: Mapping[str, np.ndarray]) -> None:
    ids = tuple(sorted(values))
    matrix = (
        np.vstack([values[value] for value in ids]) if ids else np.empty((0, 0), dtype=np.float64)
    )
    np.save(root / f"{label}-embeddings.npy", matrix, allow_pickle=False)
    _write_json_new(root / f"{label}-embedding-ids.json", {"passage_ids": ids})


def _read_embedding_artifact(root: Path, label: str) -> dict[str, np.ndarray] | None:
    matrix_path = root / f"{label}-embeddings.npy"
    ids_path = root / f"{label}-embedding-ids.json"
    if not matrix_path.exists() and not ids_path.exists():
        return None
    if not matrix_path.is_file() or not ids_path.is_file():
        raise FinalDiscoveryCampaignError(f"incomplete {label} embedding checkpoint")
    payload = _read_json_object(ids_path)
    ids = tuple(str(value) for value in cast(list[object], payload["passage_ids"]))
    matrix = np.load(matrix_path, allow_pickle=False)
    if matrix.ndim != 2 or matrix.shape[0] != len(ids) or not np.isfinite(matrix).all():
        raise FinalDiscoveryCampaignError(f"invalid {label} embedding checkpoint")
    return {value: matrix[index].copy() for index, value in enumerate(ids)}


def _select_m7_evidence_pairs(
    rows: Iterable[RawEvidence],
    passages: Mapping[str, PassageRecord],
    *,
    required_pairs: set[tuple[str, str]],
    maximum_seed_pairs: int,
) -> dict[str, tuple[str, str]]:
    if maximum_seed_pairs < 1:
        raise FinalDiscoveryCampaignError("maximum M7 seed-pair count must be positive")
    required: dict[str, tuple[str, str]] = {}
    retained: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    heap: list[tuple[float, str]] = []
    for row in rows:
        if row.passage_a_id not in passages or row.passage_b_id not in passages:
            continue
        if row.candidate_pair_id in seen:
            raise FinalDiscoveryCampaignError("M7 projection repeats a candidate pair")
        seen.add(row.candidate_pair_id)
        pair = (row.passage_a_id, row.passage_b_id)
        if pair in required_pairs:
            required[row.candidate_pair_id] = pair
        if row.candidate_pair_id in retained:
            continue
        key = (row.raw_score, row.candidate_pair_id)
        if len(heap) < maximum_seed_pairs:
            heapq.heappush(heap, key)
            retained[row.candidate_pair_id] = pair
            continue
        if key > heap[0]:
            _, evicted = heapq.heapreplace(heap, key)
            retained.pop(evicted)
            retained[row.candidate_pair_id] = pair
    retained.update(required)
    return retained


def _validate_fixture_m7_evidence(
    rows: Sequence[RawEvidence],
    passages: Mapping[str, PassageRecord],
    registrations: Mapping[str, DetectorRegistration],
) -> None:
    registration = registrations["m7_lexical_rrf"]
    identities: set[str] = set()
    for row in rows:
        if (
            row.detector_id != registration.detector_id
            or row.family != "lexical"
            or row.independence_group != registration.independence_group
        ):
            raise FinalDiscoveryCampaignError("fixture M7 evidence violates its registration")
        if row.passage_a_id not in passages or row.passage_b_id not in passages:
            raise FinalDiscoveryCampaignError("fixture M7 evidence references an absent passage")
        if row.candidate_pair_id in identities:
            raise FinalDiscoveryCampaignError("fixture M7 evidence repeats a candidate pair")
        identities.add(row.candidate_pair_id)


def _passage_index(passages: Sequence[PassageRecord]) -> dict[str, PassageRecord]:
    if len(passages) < 2:
        raise FinalDiscoveryCampaignError("final discovery requires at least two passages")
    result = {item.passage_id: item for item in passages}
    if len(result) != len(passages):
        raise FinalDiscoveryCampaignError("prepared passage IDs must be unique")
    return result


def _primary_discovery_passages(
    passages: Sequence[PassageRecord],
) -> tuple[PassageRecord, ...]:
    """Keep registered sensitivity editions outside the discovery/FDR universe."""

    return tuple(
        passage
        for passage in passages
        if passage.analysis_profile == "edition_complete"
        and (
            (passage.corpus == "hebrew" and passage.analysis_reading == "qere")
            or (passage.corpus == "greek" and passage.analysis_reading == "source")
        )
    )


def _campaign_scale_for_request(
    request: CampaignRequest,
    primary_passage_count: int,
) -> CampaignScaleContract:
    return campaign_scale_contract(
        request.config,
        primary_passage_count=primary_passage_count,
        canonical_m7_candidate_count=(
            CANONICAL_M7_CANDIDATE_COUNT
            if request.execution_mode == "production"
            else max(1, len(request.fixture_m7_evidence))
        ),
    )


def _pair_stratum(left: PassageRecord, right: PassageRecord) -> str:
    corpus = "_".join(sorted((left.corpus, right.corpus)))
    books = "_".join(sorted((left.book, right.book)))
    genres = "_".join(sorted((left.genre, right.genre)))
    ratio = max(left.token_count, right.token_count) / min(left.token_count, right.token_count)
    length = "matched" if ratio <= 1.25 else "moderate" if ratio <= 2.0 else "large"
    return f"{corpus}|{books}|{genres}|{length}"


def _read_pair_index(path: Path) -> tuple[tuple[str, str], ...]:
    payload = _read_json_object(path)
    raw_pairs = cast(list[list[object]], payload["candidate_pairs"])
    pairs: list[tuple[str, str]] = []
    for value in raw_pairs:
        if len(value) != 2:
            raise FinalDiscoveryCampaignError("semantic candidate index contains an invalid pair")
        first, second = str(value[0]), str(value[1])
        if first >= second:
            raise FinalDiscoveryCampaignError("semantic candidate index is not canonical")
        pairs.append((first, second))
    return tuple(pairs)


def _artifact_root(store: StageStore, manifest: StageCompletionManifest) -> Path:
    return (
        store.root
        / f"{manifest.stage_number:02d}-{manifest.stage_id}"
        / Path(manifest.artifacts_root)
    )


def _model_state_sha256(request: CampaignRequest) -> str:
    if request.offline_model_root is None:
        return _text_sha256("optional-offline-model-disabled")
    return _text_sha256(
        json.dumps(
            {
                "model_id": request.config.embedding_model.model_id,
                "revision": request.config.embedding_model.revision,
                "allowed_files": request.config.embedding_model.allowed_files,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _models_sha256(rows: Sequence[BaseModel]) -> str:
    payload = [row.model_dump(mode="json") for row in rows]
    return _json_sha256(payload)


def _raw_evidence_order_key(row: BaseModel) -> tuple[str, ...]:
    if not isinstance(row, RawEvidence):
        raise FinalDiscoveryCampaignError("raw-evidence stream contains the wrong row type")
    return row.candidate_pair_id, row.detector_id


def _ensemble_null_order_key(row: BaseModel) -> tuple[str, ...]:
    if not isinstance(row, EnsembleNullCalibrationRow):
        raise FinalDiscoveryCampaignError("ensemble-null stream contains the wrong row type")
    return (row.candidate_pair_id,)


def _iter_pair_strata(
    paths: Sequence[Path],
    passages: Mapping[str, PassageRecord],
) -> Iterator[PairStratum]:
    rows = merge_sorted_jsonl(
        paths,
        RawEvidence,
        key=lambda row: (row.candidate_pair_id, row.detector_id),
    )
    for pair_id, grouped_rows in groupby(rows, key=lambda row: row.candidate_pair_id):
        group = tuple(grouped_rows)
        first = group[0]
        observed = (first.passage_a_id, first.passage_b_id)
        if candidate_pair_id(*observed) != pair_id or any(
            (row.passage_a_id, row.passage_b_id) != observed for row in group
        ):
            raise FinalDiscoveryCampaignError(f"raw evidence pair identity disagrees: {pair_id}")
        try:
            left, right = (passages[observed[0]], passages[observed[1]])
        except KeyError as exc:
            raise FinalDiscoveryCampaignError(
                f"raw evidence references an absent primary passage: {exc}"
            ) from exc
        yield PairStratum(candidate_pair_id=pair_id, stratum=_pair_stratum(left, right))


def _iter_compact_group_score_rows(
    evidence_path: Path,
    passages: Mapping[str, PassageRecord],
    config: FinalDiscoveryConfig,
) -> Iterator[CompactGroupScoreRow]:
    groups = tuple(config.ensemble.group_weights)
    permitted_groups = set(groups)
    rows = iter_jsonl(evidence_path, EvidenceRow)
    for pair_id, grouped_rows in groupby(rows, key=lambda row: row.candidate_pair_id):
        pair_rows = tuple(grouped_rows)
        first = pair_rows[0]
        observed = (first.passage_a_id, first.passage_b_id)
        if candidate_pair_id(*observed) != pair_id or any(
            (row.passage_a_id, row.passage_b_id) != observed for row in pair_rows
        ):
            raise FinalDiscoveryCampaignError(
                f"calibrated evidence pair identity disagrees: {pair_id}"
            )
        detector_ids = [row.detector_id for row in pair_rows]
        if len(detector_ids) != len(set(detector_ids)):
            raise FinalDiscoveryCampaignError(
                f"calibrated evidence repeats a detector for pair {pair_id}"
            )
        full: dict[str, float] = {}
        ablated: dict[str, float] = {}
        for row in pair_rows:
            if row.independence_group not in permitted_groups:
                raise FinalDiscoveryCampaignError(
                    f"calibrated evidence has an unregistered group: {row.independence_group}"
                )
            full[row.independence_group] = max(
                full.get(row.independence_group, 0.0), row.normalized_score
            )
            if row.contains_english_derived_evidence:
                if row.english_ablation_normalized_score is None:
                    continue
                ablated_score = row.english_ablation_normalized_score
            else:
                ablated_score = row.normalized_score
            ablated[row.independence_group] = max(
                ablated.get(row.independence_group, 0.0), ablated_score
            )
        try:
            left, right = (passages[observed[0]], passages[observed[1]])
        except KeyError as exc:
            raise FinalDiscoveryCampaignError(
                f"calibrated evidence references an absent passage: {exc}"
            ) from exc
        yield CompactGroupScoreRow(
            candidate_pair_id=pair_id,
            stratum=_pair_stratum(left, right),
            full_scores=tuple(
                full.get(group, config.ensemble.missing_group_score) for group in groups
            ),
            remove_all_english_scores=tuple(
                ablated.get(group, config.ensemble.missing_group_score) for group in groups
            ),
        )


def _promote_bundle_files(source: Path, destination: Path) -> None:
    for path in sorted(source.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            raise FinalDiscoveryCampaignError(
                f"calibration bundle contains a non-file artifact: {path.name}"
            )
        target = destination / path.name
        if target.exists():
            raise FinalDiscoveryCampaignError(
                f"calibration bundle promotion would replace {target.name}"
            )
        path.rename(target)


def _hash_sequence(values: Iterable[str]) -> str:
    return _json_sha256(tuple(values))


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _write_json_new(path: Path, value: object) -> None:
    if path.exists():
        raise FinalDiscoveryCampaignError(f"refusing to replace campaign artifact: {path}")
    payload = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_or_authenticate_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise FinalDiscoveryCampaignError(f"existing fixture artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise FinalDiscoveryCampaignError(
            f"could not create fixture artifact {path}: {exc}"
        ) from exc


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalDiscoveryCampaignError(f"invalid campaign JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalDiscoveryCampaignError(f"campaign JSON artifact is not an object: {path}")
    return cast(dict[str, object], value)


def _copy_new(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FinalDiscoveryCampaignError(f"refusing to replace package member: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def _copy_selected_tree(
    source_root: Path,
    destination_root: Path,
    selected_names: Sequence[str] | None,
) -> None:
    selected = set(selected_names) if selected_names is not None else None
    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if selected is not None and relative.as_posix() not in selected:
            continue
        _link_new(source, destination_root / relative)


def _link_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FinalDiscoveryCampaignError(f"refusing to replace hardlink target: {destination}")
    try:
        os.link(source, destination)
    except OSError as exc:
        raise FinalDiscoveryCampaignError(
            "final package source requires same-filesystem hardlinks; refusing an "
            f"unbounded physical copy for {destination}"
        ) from exc
    if not os.path.samefile(source, destination):
        raise FinalDiscoveryCampaignError(f"final package hardlink identity differs: {destination}")


def _materialization_payload(receipt: MaterializationReceipt) -> dict[str, object]:
    return {
        "identity": receipt.identity.canonical_uri,
        "remote_inventory_sha256": receipt.remote_inventory_sha256,
        "materialized_inventory_sha256": receipt.materialized_inventory_sha256,
        "table_hashes_sha256": receipt.table_hashes_sha256,
        "object_count": receipt.object_count,
        "total_size": receipt.total_size,
        "listed_file_sha256": dict(receipt.listed_file_sha256),
        "receipt_sha256": receipt.sha256,
    }


def _final_package_local_identity() -> ObjectStoreIdentity:
    return ObjectStoreIdentity(
        provider="local",
        bucket="final-discovery-package",
        prefix="authenticated-directory-v1",
    )


def _transfer_payload(receipt: TransferVerificationReceipt) -> dict[str, object]:
    return {
        "identity": receipt.identity.canonical_uri,
        "local_inventory_sha256": receipt.local_inventory_sha256,
        "remote_inventory_sha256": receipt.remote_inventory_sha256,
        "object_count": receipt.object_count,
        "total_size": receipt.total_size,
    }


def _assert_transfer_receipt_matches(path: Path, receipt: TransferVerificationReceipt) -> None:
    if _read_json_object(path) != _transfer_payload(receipt):
        raise FinalDiscoveryCampaignError("destination verification differs from stage 11 receipt")


__all__ = [
    "CampaignRequest",
    "CampaignRunResult",
    "CheckpointInventoryEntry",
    "ExecutionMode",
    "FinalDiscoveryCampaignError",
    "assert_production_authorized",
    "build_bounded_fixture_campaign_request",
    "run_final_discovery_campaign",
]
