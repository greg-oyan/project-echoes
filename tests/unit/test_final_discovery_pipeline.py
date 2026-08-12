from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import echoes.final_discovery.pipeline as campaign_pipeline
from echoes.final_discovery.checkpoints import StageCheckpointMetadata, StageCheckpointReceipt
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.inputs import (
    InputExpectation,
    LocalObjectStore,
    ObjectStoreIdentity,
)
from echoes.final_discovery.knownness import KnownRelationship
from echoes.final_discovery.m7_adapter import M7AuthenticationReport, M7HydrationIndexReceipt
from echoes.final_discovery.models import PassageRecord, RawEvidence
from echoes.final_discovery.pipeline import (
    CampaignRequest,
    FinalDiscoveryCampaignError,
    assert_production_authorized,
    build_bounded_fixture_campaign_request,
    run_final_discovery_campaign,
)
from echoes.final_discovery.stages import StageStore
from echoes.final_discovery.storage import read_jsonl, write_jsonl_atomic


class CountingLocalObjectStore(LocalObjectStore):
    def __init__(self, root: Path, *, identity: ObjectStoreIdentity) -> None:
        super().__init__(root, identity=identity)
        self.upload_calls = 0
        self.check_calls = 0

    def upload_tree(self, source: Path):  # type: ignore[no-untyped-def]
        self.upload_calls += 1
        return super().upload_tree(source)

    def check_tree(self, source: Path):  # type: ignore[no-untyped-def]
        self.check_calls += 1
        return super().check_tree(source)


def _passage(passage_id: str, *, corpus: str, ordinal: int) -> PassageRecord:
    greek = corpus == "greek"
    return PassageRecord(
        passage_id=passage_id,
        reference=f"Fixture {ordinal}:1",
        corpus=corpus,
        book=f"Book{ordinal % 2}",
        genre="narrative",
        analysis_profile="edition_complete",
        analysis_reading="source" if greek else "qere",
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
        source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
    )


def _fixture_inputs(tmp_path: Path):  # type: ignore[no-untyped-def]
    passages = (
        _passage("g-001", corpus="greek", ordinal=1),
        _passage("g-002", corpus="greek", ordinal=2),
        _passage("h-001", corpus="hebrew", ordinal=3),
        _passage("h-002", corpus="hebrew", ordinal=4),
    )
    passages_path = tmp_path / "prepared-passages.jsonl"
    write_jsonl_atomic(passages_path, passages, sort_key="passage_id")

    m7_root = tmp_path / "m7-objects"
    m7_root.mkdir()
    payload = b"bounded M7 fixture\n"
    (m7_root / "fixture.bin").write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "file_sha256": {"fixture.bin": hashlib.sha256(payload).hexdigest()},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (m7_root / "table-hashes.json").write_bytes(manifest_bytes)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    m7_identity = ObjectStoreIdentity(provider="local", bucket="m7-fixture", prefix="canonical")
    m7_store = LocalObjectStore(m7_root, identity=m7_identity)
    expectation = InputExpectation(
        identity=m7_identity,
        table_hashes_sha256=manifest_hash,
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
            source_artifact_sha256=manifest_hash,
        )
        for first, second, score in (
            ("g-001", "h-001", 0.95),
            ("g-002", "h-002", 0.85),
        )
    )
    return passages_path, m7_store, expectation, lexical


def _request(
    tmp_path: Path,
    *,
    execution_mode: str = "fixture",
    config=None,  # type: ignore[no-untyped-def]
    destination=None,  # type: ignore[no-untyped-def]
) -> CampaignRequest:
    passages_path, m7_store, expectation, lexical = _fixture_inputs(tmp_path)
    resolved_config = config or load_final_discovery_config()
    destination_identity = ObjectStoreIdentity(
        provider="local", bucket="final-fixture", prefix="campaign-output"
    )
    destination = destination or CountingLocalObjectStore(
        tmp_path / "destination", identity=destination_identity
    )
    return CampaignRequest(
        config=resolved_config,
        stage_store=StageStore(tmp_path / "stages"),
        prepared_passages_path=passages_path,
        m7_store=m7_store,
        m7_expectation=expectation,
        destination_store=destination,
        code_sha256="a" * 64,
        code_commit="fixture-commit",
        execution_mode=execution_mode,  # type: ignore[arg-type]
        known_relationships=(
            KnownRelationship(
                relationship_id="known-reverse",
                source_passage_id="h-002",
                target_passage_id="g-001",
                source_name="fixture",
                mapping_quality="exact",
            ),
        ),
        fixture_m7_evidence=lexical if execution_mode == "fixture" else (),
        checkpoint_stores={
            stage.stage_id: LocalObjectStore(
                tmp_path / "checkpoint-stores" / stage.stage_id,
                identity=ObjectStoreIdentity(
                    provider="local",
                    bucket="fixture-checkpoints",
                    prefix=f"final-discovery-v1/{stage.number:02d}-{stage.stage_id}",
                ),
            )
            for stage in resolved_config.stages
            if stage.upload_after_completion
        },
    )


def test_bounded_fixture_runs_all_eleven_stages_and_restarts(tmp_path: Path) -> None:
    destination = CountingLocalObjectStore(
        tmp_path / "destination",
        identity=ObjectStoreIdentity(
            provider="local", bucket="final-fixture", prefix="campaign-output"
        ),
    )
    request = _request(tmp_path, destination=destination)

    first = run_final_discovery_campaign(request)

    assert len(first.stage_results) == 11
    assert not any(result.skipped for result in first.stage_results)
    assert [item.stage_number for item in first.checkpoints] == list(range(1, 12))
    assert first.evidence_count > 0
    assert first.candidate_count > 0
    assert first.tier_b_count > 0
    assert first.package_path.is_file()
    assert first.validation_report_path.is_file()
    assert (first.review_directory / "review.csv").is_file()
    assert (first.review_directory / "review.parquet").is_file()
    assert (first.review_directory / "output-j-template.md").is_file()
    stage_seven_root = campaign_pipeline._artifact_root(
        request.stage_store, first.stage_results[6].manifest
    )
    threshold_report = json.loads(
        (stage_seven_root / "ensemble-null-threshold-report.json").read_text(encoding="ascii")
    )
    assert threshold_report["reporting_thresholds"] == [
        request.config.ensemble.minimum_tier_a_ensemble_score
    ]
    assert [row["calibration_scope"] for row in threshold_report["summaries"]] == [
        "full",
        "remove_all_english",
    ]
    assert all(
        len(row["null_discovery_counts"]) == request.config.calibration.fixture_iterations
        for row in threshold_report["summaries"]
    )
    stage_nine_root = campaign_pipeline._artifact_root(
        request.stage_store, first.stage_results[8].manifest
    )
    review_summary = json.loads(
        (stage_nine_root / "review-summary.json").read_text(encoding="ascii")
    )
    assert len(review_summary["ensemble_null_threshold_summaries"]) == 2
    assert all(
        "null_discovery_counts" not in row
        for row in review_summary["ensemble_null_threshold_summaries"]
    )
    output_j = (first.review_directory / "output-j-template.md").read_text(encoding="utf-8")
    assert "| `full` |" in output_j
    assert "| `remove_all_english` |" in output_j
    assert destination.upload_calls == 1
    destination_paths = {item.path for item in destination.inventory().objects}
    assert "package-receipt.json" in destination_paths
    assert "package/preregistration.json" in destination_paths
    assert "package/run-inventory.json" in destination_paths
    assert not any(path.endswith(".tar") for path in destination_paths)
    assert first.campaign_seal_path.is_file()
    assert first.finalization_receipt_path.is_file()
    finalization_remote = tmp_path / "checkpoint-stores" / "package_upload_verify"
    finalization_metadata = StageCheckpointMetadata.model_validate_json(
        (finalization_remote / "checkpoint.json").read_bytes()
    )
    assert [item.path for item in finalization_metadata.supplemental_artifacts] == [
        "campaign-seal.json"
    ]
    remote_seal = json.loads(
        (finalization_remote / "supplemental" / "campaign-seal.json").read_text(encoding="ascii")
    )
    assert remote_seal["all_stage_validation"]["passed"] is True
    assert remote_seal["all_stage_validation"]["authenticated_stage_count"] == 11
    assert remote_seal["finalization_checkpoint"] == {
        "destination": ("local://fixture-checkpoints/final-discovery-v1/11-package_upload_verify"),
        "layout": "authenticated_stage_checkpoint_payload_v1",
        "remote_reverification_required_before_server_cleanup": True,
        "required_supplemental_paths": ["campaign-seal.json"],
    }
    finalization_binding = json.loads(first.finalization_receipt_path.read_text(encoding="ascii"))
    assert (
        finalization_binding["campaign_seal_sha256"]
        == hashlib.sha256(first.campaign_seal_path.read_bytes()).hexdigest()
    )
    assert (
        finalization_binding["stage_11_checkpoint"]["transfer_verification"][
            "local_inventory_sha256"
        ]
        == finalization_binding["stage_11_checkpoint"]["transfer_verification"][
            "remote_inventory_sha256"
        ]
    )
    first_stage_eleven_receipts = tuple(
        (tmp_path / "checkpoint-packages" / "11-package_upload_verify").glob(
            "*/stage-checkpoint-receipt.json"
        )
    )
    assert len(first_stage_eleven_receipts) == 1
    first_stage_eleven_receipt = StageCheckpointReceipt.model_validate_json(
        first_stage_eleven_receipts[0].read_bytes()
    )
    assert first_stage_eleven_receipt.transfer_action == "uploaded_new"
    assert (
        first_stage_eleven_receipt.model_dump(mode="json", exclude={"transfer_action"})
        == finalization_binding["stage_11_checkpoint"]
    )
    evidence = read_jsonl(first.evidence_path, campaign_pipeline.EvidenceRow)
    assert {row.family for row in evidence} >= {
        "lexical",
        "semantic",
        "grammar_syntax",
        "structure_narrative",
        "anomaly",
    }

    second = run_final_discovery_campaign(request)

    assert all(result.skipped for result in second.stage_results)
    assert second.package_sha256 == first.package_sha256
    assert (
        second.finalization_receipt_path.read_bytes()
        == first.finalization_receipt_path.read_bytes()
    )
    assert destination.upload_calls == 1
    assert destination.check_calls > first.stage_results[-1].skipped
    second_stage_eleven_receipts = tuple(
        (tmp_path / "checkpoint-packages" / "11-package_upload_verify").glob(
            "*/stage-checkpoint-receipt.json"
        )
    )
    assert len(second_stage_eleven_receipts) == 2
    assert sorted(
        StageCheckpointReceipt.model_validate_json(path.read_bytes()).transfer_action
        for path in second_stage_eleven_receipts
    ) == ["uploaded_new", "verified_existing"]


def test_production_guard_requires_linux_and_exact_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_final_discovery_config()
    monkeypatch.setenv("ECHOES_AUTHORIZE_PRODUCTION", "final-discovery-v1")
    monkeypatch.setattr(campaign_pipeline.platform, "system", lambda: "Windows")
    with pytest.raises(FinalDiscoveryCampaignError, match="Linux only"):
        assert_production_authorized(config)

    monkeypatch.setattr(campaign_pipeline.platform, "system", lambda: "Linux")
    monkeypatch.delenv("ECHOES_AUTHORIZE_PRODUCTION")
    with pytest.raises(FinalDiscoveryCampaignError, match="requires exact"):
        assert_production_authorized(config)

    monkeypatch.setenv("ECHOES_AUTHORIZE_PRODUCTION", "final-discovery-v1")
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    with pytest.raises(FinalDiscoveryCampaignError, match="systemd invocation"):
        assert_production_authorized(config)

    launch_root = tmp_path / "launches"
    launch_root.mkdir()
    launch_id = "20260808T120000Z-abcdef123456"
    intent_path = launch_root / f"{launch_id}.intent.json"
    intent_path.write_text(
        json.dumps(
            {
                "experiment_id": "final-discovery-v1",
                "launch_id": launch_id,
                "service_unit": "echoes-final-discovery.service",
                "command": ["echoes", "run-final-discovery", "--production"],
                "polling_or_automatic_restart": False,
            }
        ),
        encoding="utf-8",
    )
    intent_path.chmod(0o440)
    monkeypatch.setattr(campaign_pipeline, "_MANAGED_LAUNCH_ROOT", launch_root)
    monkeypatch.setattr(
        campaign_pipeline,
        "_read_process_cgroup",
        lambda: "0::/system.slice/echoes-final-discovery.service\n",
    )
    monkeypatch.setenv("INVOCATION_ID", "1" * 32)
    monkeypatch.setenv("ECHOES_MANAGED_LAUNCH_ID", launch_id)
    monkeypatch.setenv("ECHOES_MANAGED_LAUNCH_INTENT_PATH", str(intent_path))
    monkeypatch.setenv(
        "ECHOES_MANAGED_LAUNCH_INTENT_SHA256",
        hashlib.sha256(intent_path.read_bytes()).hexdigest(),
    )
    assert_production_authorized(config)
    monkeypatch.setattr(
        campaign_pipeline,
        "_read_process_cgroup",
        lambda: "0::/user.slice/user-1000.slice/session.scope\n",
    )
    with pytest.raises(FinalDiscoveryCampaignError, match="must run inside"):
        assert_production_authorized(config)


def test_public_bounded_fixture_builder_is_idempotent(tmp_path: Path) -> None:
    config = load_final_discovery_config()
    first = build_bounded_fixture_campaign_request(
        tmp_path / "public-fixture",
        config=config,
        code_sha256="b" * 64,
        code_commit="fixture-builder",
    )
    second = build_bounded_fixture_campaign_request(
        tmp_path / "public-fixture",
        config=config,
        code_sha256="b" * 64,
        code_commit="fixture-builder",
    )

    assert first.execution_mode == "fixture"
    assert second.prepared_passages_path == first.prepared_passages_path
    assert second.m7_expectation == first.m7_expectation
    assert len(read_jsonl(first.prepared_passages_path, PassageRecord)) == 4


def test_public_bounded_fixture_path_exports_selected_m7_dossiers(tmp_path: Path) -> None:
    request = build_bounded_fixture_campaign_request(
        tmp_path / "public-fixture-campaign",
        config=load_final_discovery_config(),
        code_sha256="c" * 64,
        code_commit="fixture-stage-nine-regression",
    )
    assert all(json.loads(row.trace_json)["fixture"] is True for row in request.fixture_m7_evidence)

    result = run_final_discovery_campaign(request)

    assert result.tier_b_count > 0
    dossiers = tuple((result.review_directory / "dossiers").glob("*.md"))
    assert dossiers
    dossier_text = "\n".join(path.read_text(encoding="utf-8") for path in dossiers)
    assert '"bounded_fixture":true' in dossier_text
    assert '"fixture":true' in dossier_text


def test_production_uses_authenticated_m7_adapter_without_cloud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_request = _request(tmp_path)
    expected_hash = base_request.m7_expectation.table_hashes_sha256
    config = base_request.config.model_copy(
        update={
            "inputs": [
                item.model_copy(update={"expected_manifest_sha256": expected_hash})
                if item.role == "canonical_m7"
                else item
                for item in base_request.config.inputs
            ]
        }
    )
    calls = {"authenticate": 0, "project": 0, "iterate": 0}
    bounded_selection_limits: list[int] = []
    exporter_limits: list[int] = []
    fixture_stage_one = campaign_pipeline._produce_stage_one
    real_bounded_selection = campaign_pipeline.iter_bounded_dossier_candidates
    real_streaming_exporter = campaign_pipeline.write_review_bundle_streaming

    def spy_bounded_selection(candidates, *, tier_a_dossier_limit):  # type: ignore[no-untyped-def]
        bounded_selection_limits.append(tier_a_dossier_limit)
        yield from real_bounded_selection(
            candidates,
            tier_a_dossier_limit=tier_a_dossier_limit,
        )

    def spy_streaming_exporter(*args, **kwargs):  # type: ignore[no-untyped-def]
        exporter_limits.append(kwargs["tier_a_dossier_limit"])
        return real_streaming_exporter(*args, **kwargs)

    def fake_authenticate(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["authenticate"] += 1
        return M7AuthenticationReport(
            root=str(args[0]),
            manifest_sha256=expected_hash,
            table_counts={},
            table_logical_sha256={},
            file_count=1,
            verified_file_count=1,
            total_bytes=1,
        )

    def fake_projection(input_root, output_path, **kwargs):  # type: ignore[no-untyped-def]
        del input_root, kwargs
        calls["project"] += 1
        output_path.write_bytes(b"fixture projection\n")
        return output_path

    def fake_iter(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        calls["iterate"] += 1
        yield RawEvidence(
            candidate_pair_id=candidate_pair_id("g-001", "h-001"),
            passage_a_id="g-001",
            passage_b_id="h-001",
            detector_id="m7_lexical_rrf",
            family="lexical",
            independence_group="lexical_m7",
            raw_score=0.95,
            contains_english_derived_evidence=False,
            original_language_evidence_remains=True,
            counts_for_independence=True,
            trace_json=canonical_json(
                {
                    "adapter": True,
                    "representation": "canonical_m7_reciprocal_rank_fusion",
                    "m7_both_null_families_present": True,
                    "m7_openbible_relationship_ids": [],
                    "m7_known_link_status": "not_represented_in_openbible_snapshot",
                    "m7_quality": None,
                }
            ),
            source_artifact_id="m7-canonical-schema-v1",
            source_artifact_sha256=expected_hash,
        )

    hydrated_by_id = {}

    def fake_build_hydration_index(  # type: ignore[no-untyped-def]
        rows,
        _input_root,
        output_path,
        **_kwargs,
    ):
        assert not isinstance(rows, tuple)
        for row in rows:
            hydrated_by_id[row.evidence_id] = row.model_copy(
                update={
                    "trace_json": canonical_json({**json.loads(row.trace_json), "fixture": True})
                }
            )
        output_path.write_bytes(b"transient fixture hydration index\n")
        return M7HydrationIndexReceipt(
            row_count=len(hydrated_by_id),
            source_scan_count=1 if hydrated_by_id else 0,
            selection_batch_size=1_024,
            maximum_selection_batch_rows_observed=len(hydrated_by_id),
            arrow_batch_size=65_536,
            source_manifest_sha256=expected_hash,
        )

    class FakeHydratedLookup:
        def __init__(self, _path, _receipt):  # type: ignore[no-untyped-def]
            self.lookup_count = 0

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

        def __call__(self, row):  # type: ignore[no-untyped-def]
            self.lookup_count += 1
            return hydrated_by_id[row.evidence_id]

    def fixture_stage_one_with_m7_authentication(
        root: Path,
        request: CampaignRequest,
        positive_controls,  # type: ignore[no-untyped-def]
    ) -> None:
        fixture_stage_one(
            root,
            replace(request, execution_mode="fixture"),
            positive_controls,
        )
        fake_authenticate(
            root / "m7",
            expected_manifest_sha256=expected_hash,
            verify_individual_files=True,
        )

    monkeypatch.setattr(campaign_pipeline, "authenticate_m7_input", fake_authenticate)
    monkeypatch.setattr(campaign_pipeline, "build_m7_lexical_projection", fake_projection)
    monkeypatch.setattr(campaign_pipeline, "iter_m7_raw_evidence", fake_iter)
    monkeypatch.setattr(
        campaign_pipeline,
        "build_m7_hydration_index",
        fake_build_hydration_index,
    )
    monkeypatch.setattr(campaign_pipeline, "M7HydratedEvidenceLookup", FakeHydratedLookup)
    monkeypatch.setattr(
        campaign_pipeline,
        "iter_bounded_dossier_candidates",
        spy_bounded_selection,
    )
    monkeypatch.setattr(
        campaign_pipeline,
        "write_review_bundle_streaming",
        spy_streaming_exporter,
    )
    monkeypatch.setattr(campaign_pipeline, "_validate_request", lambda _request: None)
    monkeypatch.setattr(campaign_pipeline, "_assert_managed_production_launch", lambda: None)
    monkeypatch.setattr(
        campaign_pipeline,
        "_produce_stage_one",
        fixture_stage_one_with_m7_authentication,
    )
    monkeypatch.setattr(campaign_pipeline.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        campaign_pipeline.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=100 * 1024**3),
    )
    monkeypatch.setenv("ECHOES_AUTHORIZE_PRODUCTION", "final-discovery-v1")
    request = replace(
        base_request,
        config=config,
        execution_mode="production",
        fixture_m7_evidence=(),
        minimum_free_disk_bytes=80 * 1024**3,
    )

    result = run_final_discovery_campaign(request)

    assert len(result.stage_results) == 11
    assert calls == {"authenticate": 1, "project": 1, "iterate": 2}
    summary = json.loads(
        (
            campaign_pipeline._artifact_root(request.stage_store, result.stage_results[2].manifest)
            / "semantic-evidence-summary.json"
        ).read_text()
    )
    assert summary["m7_was_rerun"] is False
    assert summary["m7_adapter_projection_used"] is True
    review_summary = json.loads(
        (
            campaign_pipeline._artifact_root(request.stage_store, result.stage_results[8].manifest)
            / "review-summary.json"
        ).read_text()
    )
    assert review_summary["m7_hydration_disk_backed_lookup"] is True
    assert review_summary["m7_hydration_selection_batch_size"] == 1_024
    assert review_summary["m7_hydration_maximum_selection_batch_rows_observed"] <= 1_024
    assert bounded_selection_limits == [config.review.tier_a_dossier_limit]
    assert exporter_limits == [config.review.tier_a_dossier_limit]
    assert review_summary["m7_hydration_scope"] == ("first_100_score_ranked_tier_a_and_all_tier_b")
