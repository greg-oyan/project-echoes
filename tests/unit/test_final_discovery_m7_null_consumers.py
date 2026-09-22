"""Canonical negative M7 outcomes remain negative through authenticated consumers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_final_discovery_disk_validation import _passage
from test_final_discovery_m7_null_provenance import _fixture

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.disk_calibration import (
    DiskCalibrationError,
    calibrate_detector_evidence_disk_backed,
    project_anomaly_pair_scores_disk_backed,
)
from echoes.final_discovery.disk_validation import validate_final_discovery_disk_backed
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    calibrate_detector_evidence,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.m7_null_provenance import (
    M7NullProvenance,
    authenticate_m7_null_provenance,
)
from echoes.final_discovery.models import EvidenceRow, RawEvidence
from echoes.final_discovery.nulls import (
    NullControlError,
    production_detector_calibration,
    stratified_ensemble_null_calibration,
)
from echoes.final_discovery.storage import read_jsonl, write_jsonl_stream_atomic
from echoes.final_discovery.validation import validate_final_discovery

CONFIG = load_final_discovery_config()
MEMORY = 256 * 1024**2
M7_INPUT = next(item for item in CONFIG.inputs if item.role == "canonical_m7")
REGISTRATION = next(item for item in CONFIG.detectors if item.detector_id == "m7_lexical_rrf")


@pytest.fixture(scope="module")
def authenticated_negative(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[RawEvidence, M7NullProvenance]:
    temporary = tmp_path_factory.mktemp("canonical-negative-m7")
    root, digest, trace = _fixture(temporary)
    proof = authenticate_m7_null_provenance(
        root, expected_manifest_sha256=digest, temp_directory=temporary / "spill"
    )
    trace.update(
        m7_openbible_relationship_ids=[],
        m7_known_link_status="not_represented_in_openbible_snapshot",
        m7_quality=None,
    )
    raw = RawEvidence(
        candidate_pair_id=candidate_pair_id("A", "B"),
        passage_a_id="A",
        passage_b_id="B",
        detector_id=REGISTRATION.detector_id,
        family=REGISTRATION.family,
        independence_group=REGISTRATION.independence_group,
        raw_score=0.03,
        contains_english_derived_evidence=False,
        original_language_evidence_remains=True,
        counts_for_independence=REGISTRATION.counts_for_independence,
        trace_json=canonical_json(trace),
        source_artifact_id=M7_INPUT.artifact_id,
        source_artifact_sha256=digest,
    )
    return raw, proof


def _alter(raw: RawEvidence, corruption: str) -> RawEvidence:
    trace = json.loads(raw.trace_json)
    if corruption == "manifest":
        return raw.model_copy(update={"source_artifact_sha256": "0" * 64})
    if corruption == "outcome":
        trace["m7_empirical_fdr"] = 0.0
        return raw.model_copy(update={"trace_json": canonical_json(trace)})
    if corruption == "pair":
        return raw.model_copy(
            update={
                "passage_b_id": "C",
                "candidate_pair_id": candidate_pair_id("A", "C"),
            }
        )
    if corruption == "score":
        return raw.model_copy(update={"raw_score": 0.99})
    return raw


@pytest.mark.parametrize("consumer", ["memory", "disk", "anomaly_projection"])
@pytest.mark.parametrize("corruption", ["none", "no_proof", "manifest", "outcome", "pair", "score"])
def test_calibration_requires_exact_authenticated_negative_outcome(
    tmp_path: Path,
    authenticated_negative: tuple[RawEvidence, M7NullProvenance],
    consumer: str,
    corruption: str,
) -> None:
    canonical, proof = authenticated_negative
    raw = _alter(canonical, corruption)
    context = None if corruption == "no_proof" else proof
    raw_path = tmp_path / "raw.jsonl"
    raw_rows = [raw]
    if consumer == "anomaly_projection":
        companion = next(
            item for item in CONFIG.detectors if item.detector_id == "semantic_domain_overlap"
        )
        raw_rows.append(
            raw.model_copy(
                update={
                    "detector_id": companion.detector_id,
                    "family": companion.family,
                    "independence_group": companion.independence_group,
                    "counts_for_independence": companion.counts_for_independence,
                    "trace_json": canonical_json({"representation": "semantic_domains"}),
                }
            )
        )
    write_jsonl_stream_atomic(raw_path, raw_rows, order_key=None)

    def run() -> object:
        if consumer == "memory":
            result = production_detector_calibration(
                [raw],
                {raw.candidate_pair_id: "all"},
                config=CONFIG,
                iterations=CONFIG.calibration.production_iterations,
                m7_null_provenance=context,
            )
            provenance = result.provenance_by_detector["m7_lexical_rrf"]
        elif consumer == "disk":
            disk_result = calibrate_detector_evidence_disk_backed(
                [raw_path],
                {raw.candidate_pair_id: "all"},
                tmp_path / "calibrated",
                config=CONFIG,
                iterations=CONFIG.calibration.production_iterations,
                memory_limit_bytes=MEMORY,
                temp_directory=tmp_path / "spill",
                m7_null_provenance=context,
            )
            provenance = json.loads(disk_result.provenance_path.read_text())[
                "provenance_by_detector"
            ]["m7_lexical_rrf"]
            evidence = read_jsonl(disk_result.evidence_path, EvidenceRow)
            assert json.loads(evidence[0].trace_json)["m7_both_null_families_present"] is False
        else:
            return project_anomaly_pair_scores_disk_backed(
                [raw_path],
                tmp_path / "anomaly",
                config=CONFIG,
                memory_limit_bytes=MEMORY,
                temp_directory=tmp_path / "spill",
                m7_null_provenance=context,
            )
        assert provenance["source_null_validation"] == "authenticated_m7_source_null_provenance"
        assert provenance["source_null_provenance_sha256"] == proof.provenance_sha256
        return provenance

    if corruption == "none":
        run()
        assert json.loads(raw.trace_json)["m7_both_null_families_present"] is False
        assert json.loads(raw.trace_json)["m7_empirical_fdr"] == (
            "positive_infinity_no_qualified_threshold"
        )
    else:
        with pytest.raises((NullControlError, DiskCalibrationError), match="M7"):
            run()


@pytest.mark.parametrize("backend", ["memory", "disk"])
@pytest.mark.parametrize("corruption", ["none", "no_proof", "manifest", "outcome", "pair", "score"])
def test_strict_validation_authenticates_negative_source_outcome(
    tmp_path: Path,
    authenticated_negative: tuple[RawEvidence, M7NullProvenance],
    backend: str,
    corruption: str,
) -> None:
    raw, proof = authenticated_negative
    evidence = calibrate_detector_evidence(
        [raw],
        config=CONFIG,
        reference_scores={raw.detector_id: (0.01, 0.03)},
        null_scores={raw.detector_id: (0.01, 0.03)},
    )
    passages = {
        key: _passage(key, reference) for key, reference in (("A", "GEN 1:1"), ("B", "EXO 1:1"))
    }
    knownness = KnownnessIndex(())
    full_null = stratified_ensemble_null_calibration(
        ensemble_group_scores_by_pair(evidence),
        {raw.candidate_pair_id: "all"},
        config=CONFIG,
        iterations=CONFIG.calibration.fixture_iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope="full",
    )
    ablated_null = stratified_ensemble_null_calibration(
        ensemble_group_scores_by_pair(evidence, remove_all_english=True),
        {raw.candidate_pair_id: "all"},
        config=CONFIG,
        iterations=CONFIG.calibration.fixture_iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope="remove_all_english",
    )
    candidates = build_final_candidates(
        evidence,
        passages,
        config=CONFIG,
        knownness=knownness,
        null_calibration_by_pair={item.candidate_pair_id: item for item in full_null},
        english_ablation_null_calibration_by_pair={
            item.candidate_pair_id: item for item in ablated_null
        },
    )
    changed = _alter(raw, corruption)
    changed_evidence = (
        evidence[0].model_copy(
            update={
                "trace_json": changed.trace_json,
                "source_artifact_sha256": changed.source_artifact_sha256,
                "passage_b_id": changed.passage_b_id,
                "raw_score": changed.raw_score,
            }
        ),
    )
    context = None if corruption == "no_proof" else proof
    if backend == "memory":
        report = validate_final_discovery(
            changed_evidence,
            candidates,
            config=CONFIG,
            passages=passages,
            knownness=knownness,
            null_calibration_by_pair=full_null,
            english_ablation_null_calibration_by_pair=ablated_null,
            expected_source_artifact_sha256={raw.source_artifact_id: raw.source_artifact_sha256},
            m7_null_provenance=context,
        )
    else:
        paths = [
            tmp_path / name
            for name in ("evidence.jsonl", "candidates.jsonl", "full.jsonl", "ablated.jsonl")
        ]
        for path, rows in zip(
            paths, (changed_evidence, candidates, full_null, ablated_null), strict=True
        ):
            write_jsonl_stream_atomic(path, rows, order_key=None)
        result = validate_final_discovery_disk_backed(
            *paths,
            tmp_path / "validated",
            config=CONFIG,
            passages=passages,
            knownness=knownness,
            memory_limit_bytes=MEMORY,
            temp_directory=tmp_path / "spill",
            expected_source_artifact_sha256={raw.source_artifact_id: raw.source_artifact_sha256},
            m7_null_provenance=context,
        )
        report = result.report
    findings = {item.code for item in report.findings}
    if corruption == "none":
        assert report.passed, report.findings
        assert not candidates[0].tier_a_eligible
    else:
        assert not report.passed
        assert "m7-null-family-authentication" in findings
