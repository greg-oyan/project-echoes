"""Independent final-discovery command-path validation tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from echoes.final_discovery import command
from echoes.final_discovery.config import (
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.disk_validation import (
    DiskFinalDiscoveryValidationReceipt,
    DiskFinalDiscoveryValidationResult,
    DiskValidationInputReceipt,
    DiskValidationResourceReceipt,
)
from echoes.final_discovery.inputs import LocalObjectStore, ObjectStoreIdentity
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.stages import FINAL_DISCOVERY_STAGE_IDS
from echoes.final_discovery.storage import (
    inspect_jsonl_file,
    read_jsonl,
    write_json_atomic_new,
    write_jsonl_stream_atomic,
)
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    ValidationFinding,
)

CONFIG_PATH = Path("config/experiments/final-discovery-v1.yaml")


@dataclass(frozen=True, slots=True)
class _Artifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _Manifest:
    stage_id: str
    code_sha256: str
    code_commit: str
    artifacts_root: str
    artifacts: tuple[_Artifact, ...]


class _FakeStageStore:
    def __init__(self, root: Path, execution_mode: str) -> None:
        self.root = root
        summary_path = self.artifact_root("authenticate_materialize_inputs") / (
            "input-summary.json"
        )
        summary_path.parent.mkdir(parents=True)
        summary_payload = (
            json.dumps(
                {"execution_mode": execution_mode},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
        summary_path.write_bytes(summary_payload)
        summary_artifact = _Artifact(
            path="input-summary.json",
            size=len(summary_payload),
            sha256=hashlib.sha256(summary_payload).hexdigest(),
        )
        self.manifests = tuple(
            _Manifest(
                stage_id=stage_id,
                code_sha256="a" * 64,
                code_commit="b" * 40,
                artifacts_root="artifacts",
                artifacts=(summary_artifact,) if index == 0 else (),
            )
            for index, stage_id in enumerate(FINAL_DISCOVERY_STAGE_IDS)
        )
        self.authenticate_all_count = 0

    def artifact_root(self, stage_id: str) -> Path:
        return self.root / stage_id / "artifacts"

    def completion_path(self, stage_id: str) -> Path:
        return self.root / stage_id / "completion.json"

    def authenticate_all_completions(self) -> tuple[_Manifest, ...]:
        self.authenticate_all_count += 1
        return self.manifests

    def authenticate_completion(self, stage_id: str, **_: object) -> _Manifest:
        return next(item for item in self.manifests if item.stage_id == stage_id)


def _empty_jsonl(path: Path) -> None:
    write_jsonl_stream_atomic(path, (), order_key=None)


def test_output_namespace_preflight_accepts_empty_or_exact_local_subset_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_root = tmp_path / "remote"
    store = LocalObjectStore(
        remote_root,
        identity=ObjectStoreIdentity(
            provider="b2",
            bucket="project-echoes-archive",
            prefix="final-discovery-v1/run-fixture",
        ),
    )
    monkeypatch.setattr(command, "RcloneB2ObjectStore", lambda **_kwargs: store)
    work = tmp_path / "work"

    empty = command.inspect_production_output_namespace(
        work_directory=work,
        output_bucket="project-echoes-archive",
        output_prefix="final-discovery-v1/run-fixture",
    )

    assert empty["state"] == "empty_new_campaign"
    local_payload = (
        work / "checkpoint-packages" / "02-semantic_representations_indexes" / "attempt" / "payload"
    )
    (local_payload / "artifacts").mkdir(parents=True)
    (local_payload / "checkpoint.json").write_bytes(b"checkpoint\n")
    (local_payload / "completion.json").write_bytes(b"completion\n")
    (local_payload / "artifacts/model.json").write_bytes(b"model\n")
    remote_checkpoint = remote_root / "checkpoints" / "02-semantic_representations_indexes"
    remote_checkpoint.mkdir(parents=True)
    (remote_checkpoint / "checkpoint.json").write_bytes(b"checkpoint\n")

    partial = command.inspect_production_output_namespace(
        work_directory=work,
        output_bucket="project-echoes-archive",
        output_prefix="final-discovery-v1/run-fixture",
    )

    assert partial["state"] == "registered_restart_state"
    assert (
        partial["active_prefix_state"]["checkpoints/02-semantic_representations_indexes"]["state"]
        == "resumable_exact_path_size_subset"
    )
    (remote_checkpoint / "unexpected.json").write_bytes(b"not-local\n")
    with pytest.raises(command.FinalDiscoveryCommandError, match="not an exact resumable"):
        command.inspect_production_output_namespace(
            work_directory=work,
            output_bucket="project-echoes-archive",
            output_prefix="final-discovery-v1/run-fixture",
        )


def _campaign_files(store: _FakeStageStore) -> tuple[Path, Path, Path, Path]:
    stage_one = store.artifact_root("authenticate_materialize_inputs")
    stage_seven = store.artifact_root("empirical_null_controls")
    stage_eight = store.artifact_root("transparent_final_ensemble")
    _empty_jsonl(stage_one / "passages.jsonl")
    _empty_jsonl(stage_one / "known-relationships.jsonl")
    paths = (
        stage_seven / "evidence.jsonl",
        stage_eight / "candidates.jsonl",
        stage_seven / "ensemble-null-full.jsonl",
        stage_seven / "ensemble-null-remove-all-english.jsonl",
    )
    for path in paths:
        _empty_jsonl(path)
    return paths


def _input_receipts(
    paths: tuple[Path, Path, Path, Path],
) -> tuple[DiskValidationInputReceipt, ...]:
    roles = ("evidence", "candidates", "full_null", "remove_all_english_null")
    orderings = (
        "candidate_pair_id,detector_id",
        "ensemble_score_desc,candidate_pair_id",
        "candidate_pair_id",
        "candidate_pair_id",
    )
    receipts: list[DiskValidationInputReceipt] = []
    for path, role, ordering in zip(paths, roles, orderings, strict=True):
        observed = inspect_jsonl_file(path)
        receipts.append(
            DiskValidationInputReceipt(
                role=role,  # type: ignore[arg-type]
                file_name=path.name,
                row_count=observed.row_count,
                size_bytes=observed.size_bytes,
                sha256=observed.sha256,
                ordering=ordering,
                canonical_jsonl_required=True,
            )
        )
    return tuple(receipts)


def _publish_validation(
    output_directory: Path,
    paths: tuple[Path, Path, Path, Path],
    *,
    passed: bool = True,
) -> DiskFinalDiscoveryValidationResult:
    output_directory.mkdir(parents=True)
    findings = (
        ()
        if passed
        else (
            ValidationFinding(
                code="test-finding",
                message="deliberate scientific failure",
            ),
        )
    )
    report = FinalDiscoveryValidationReport(
        experiment_id="final-discovery-v1",
        evidence_count=0,
        candidate_count=0,
        tier_a_count=0,
        tier_b_count=0,
        authenticated_stage_count=11,
        findings=findings,
    )
    report_path = output_directory / "validation-report.json"
    report_file = write_json_atomic_new(report_path, report)
    config = load_final_discovery_config(CONFIG_PATH)
    receipt = DiskFinalDiscoveryValidationReceipt(
        experiment_id="final-discovery-v1",
        config_sha256=final_discovery_config_sha256(config),
        inputs=_input_receipts(paths),
        passage_count=0,
        passage_logical_sha256="c" * 64,
        known_relationship_count=0,
        knownness_logical_sha256="d" * 64,
        evidence_pair_count=0,
        authenticated_stage_count=11,
        expected_authenticated_stage_count=11,
        validation_passed=passed,
        retained_finding_count=len(findings),
        total_finding_count=len(findings),
        findings_truncated=False,
        report_size_bytes=report_file.size_bytes,
        report_sha256=report_file.sha256,
        resource_bounds=DiskValidationResourceReceipt(
            duckdb_memory_limit_bytes=4 * 1024**3,
            duckdb_threads=1,
            ingestion_batch_size=65_536,
            maximum_decoded_rows_per_fetch=4_096,
            finding_limit=1_000,
            minimum_temp_free_bytes=1024**3,
            initial_temp_free_bytes=1024**3,
            duckdb_database_peak_bytes=0,
            maximum_evidence_rows_retained_per_pair=0,
            full_ledgers_retained_in_python=False,
            duckdb_state_persisted=False,
        ),
    )
    receipt_path = output_directory / "validation-receipt.json"
    write_json_atomic_new(receipt_path, receipt)
    return DiskFinalDiscoveryValidationResult(
        output_directory=output_directory,
        report_path=report_path,
        receipt_path=receipt_path,
        report=report,
        receipt=receipt,
    )


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    work_directory: Path,
    execution_mode: str,
) -> tuple[_FakeStageStore, tuple[Path, Path, Path, Path]]:
    store = _FakeStageStore(work_directory.resolve() / "stages", execution_mode)
    paths = _campaign_files(store)
    monkeypatch.setattr(command, "StageStore", lambda _: store)
    return store, paths


def test_fixture_validation_keeps_the_readable_in_memory_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_directory = tmp_path / "fixture-campaign"
    store, _ = _install_store(monkeypatch, work_directory, "fixture")
    captured: dict[str, Any] = {}

    def oracle(*args: object, **kwargs: object) -> FinalDiscoveryValidationReport:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FinalDiscoveryValidationReport(
            experiment_id="final-discovery-v1",
            evidence_count=0,
            candidate_count=0,
            tier_a_count=0,
            tier_b_count=0,
            authenticated_stage_count=11,
            findings=(),
        )

    monkeypatch.setattr(command, "validate_final_discovery", oracle)
    monkeypatch.setattr(
        command,
        "validate_final_discovery_disk_backed",
        lambda *args, **kwargs: pytest.fail("fixture validation called the disk path"),
    )

    report = command.validate_completed_campaign(
        work_directory=work_directory,
        config_path=CONFIG_PATH,
    )

    assert report.passed
    assert captured["args"] == ((), ())
    kwargs = captured["kwargs"]
    assert kwargs["require_all_stages"] is True
    assert kwargs["stage_store"] is store
    assert isinstance(kwargs["knownness"], KnownnessIndex)
    assert not (work_directory / "independent-validation").exists()


def test_production_validation_streams_ledgers_and_authenticates_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_directory = tmp_path / "production-campaign"
    store, paths = _install_store(monkeypatch, work_directory, "production")
    original_read_jsonl = read_jsonl
    materialized_names: list[str] = []
    large_names = {path.name for path in paths}

    def guarded_read_jsonl(path: Path, model: type[Any]) -> tuple[Any, ...]:
        materialized_names.append(path.name)
        if path.name in large_names:
            pytest.fail(f"production materialized governed ledger {path.name}")
        return original_read_jsonl(path, model)

    captured: dict[str, Any] = {}

    def disk_validator(
        evidence_path: Path,
        candidates_path: Path,
        full_null_path: Path,
        ablated_null_path: Path,
        output_directory: Path,
        **kwargs: Any,
    ) -> DiskFinalDiscoveryValidationResult:
        observed_paths = (
            evidence_path,
            candidates_path,
            full_null_path,
            ablated_null_path,
        )
        captured.update(kwargs)
        captured["output_directory"] = output_directory
        captured["knownness_rows"] = tuple(kwargs["knownness"])
        return _publish_validation(output_directory, observed_paths)

    monkeypatch.setattr(command, "read_jsonl", guarded_read_jsonl)
    monkeypatch.setattr(command, "validate_final_discovery_disk_backed", disk_validator)

    first = command.validate_completed_campaign(
        work_directory=work_directory,
        config_path=CONFIG_PATH,
    )

    expected_output = work_directory.resolve() / "independent-validation"
    assert first.passed
    assert first.authenticated_stage_count == 11
    assert materialized_names == ["passages.jsonl"]
    assert captured["output_directory"] == expected_output
    assert captured["knownness_rows"] == ()
    assert captured["memory_limit_bytes"] == 4 * 1024**3
    assert captured["threads"] == 1
    assert captured["expected_authenticated_stage_count"] == 11
    assert captured["stage_store"] is store
    assert captured["temp_directory"] == (work_directory.resolve() / "independent-validation-work")

    monkeypatch.setattr(
        command,
        "validate_final_discovery_disk_backed",
        lambda *args, **kwargs: pytest.fail("restart replaced independent validation"),
    )
    restarted = command.validate_completed_campaign(
        work_directory=work_directory,
        config_path=CONFIG_PATH,
    )
    assert restarted == first
    assert store.authenticate_all_count == 4

    paths[2].write_bytes(b"{}\n")
    with pytest.raises(command.FinalDiscoveryCommandError, match="full_null"):
        command.validate_completed_campaign(
            work_directory=work_directory,
            config_path=CONFIG_PATH,
        )
    assert (expected_output / "validation-receipt.json").is_file()


def test_production_validation_rejects_a_published_scientific_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_directory = tmp_path / "failed-production-campaign"
    _, paths = _install_store(monkeypatch, work_directory, "production")

    def failed_validator(
        evidence_path: Path,
        candidates_path: Path,
        full_null_path: Path,
        ablated_null_path: Path,
        output_directory: Path,
        **_: object,
    ) -> DiskFinalDiscoveryValidationResult:
        assert (evidence_path, candidates_path, full_null_path, ablated_null_path) == paths
        return _publish_validation(output_directory, paths, passed=False)

    monkeypatch.setattr(command, "validate_final_discovery_disk_backed", failed_validator)

    with pytest.raises(command.FinalDiscoveryCommandError, match="authenticated pass"):
        command.validate_completed_campaign(
            work_directory=work_directory,
            config_path=CONFIG_PATH,
        )
    assert (work_directory / "independent-validation" / "validation-receipt.json").is_file()


def test_execution_mode_is_read_from_authenticated_stage_one_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_directory = tmp_path / "tampered-mode-campaign"
    store, _ = _install_store(monkeypatch, work_directory, "production")
    summary_path = store.artifact_root("authenticate_materialize_inputs") / "input-summary.json"
    summary_path.write_text('{"execution_mode":"fixture"}\n', encoding="ascii", newline="")

    with pytest.raises(command.FinalDiscoveryCommandError, match="changed after"):
        command.validate_completed_campaign(
            work_directory=work_directory,
            config_path=CONFIG_PATH,
        )
