"""Equivalence and fail-closed tests for the production disk ensemble."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.disk_ensemble import (
    DiskEnsembleError,
    build_final_candidates_disk_backed,
)
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    calibrate_detector_evidence,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import FinalCandidate, PassageRecord, RawEvidence
from echoes.final_discovery.nulls import stratified_ensemble_null_calibration
from echoes.final_discovery.storage import read_jsonl, write_jsonl_atomic

CONFIG = load_final_discovery_config()
SOURCE_SHA = "a" * 64


def _passage(passage_id: str, reference: str, ordinal: int) -> PassageRecord:
    return PassageRecord(
        passage_id=passage_id,
        reference=reference,
        corpus="greek" if passage_id.startswith("g") else "hebrew",
        book=f"Book{ordinal % 2}",
        genre="narrative" if ordinal % 2 else "poetry",
        analysis_profile="edition_complete",
        analysis_reading="source" if passage_id.startswith("g") else "qere",
        granularity="verse",
        token_count=3,
        original_text=f"original {ordinal}",
        normalized_text=f"normalized {ordinal}",
        lemma_sequence=("say", "king", f"lemma-{ordinal}"),
        root_sequence=("speak", "rule", f"root-{ordinal}"),
        pos_sequence=("verb", "noun", "verb"),
        morphology_sequence=("a", "b", "c"),
        semantic_domains=("speech", "royalty", f"domain-{ordinal}"),
        entities=("speaker", "king", "people"),
        participants=("agent", "recipient", "agent"),
        frames=("say", "rule", "answer"),
        english_gloss=f"fixture gloss {ordinal}",
        source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
    )


def _raw(
    first: PassageRecord,
    second: PassageRecord,
    detector_id: str,
    score: float,
) -> RawEvidence:
    registration = next(item for item in CONFIG.detectors if item.detector_id == detector_id)
    left, right = sorted((first.passage_id, second.passage_id))
    return RawEvidence(
        candidate_pair_id=candidate_pair_id(left, right),
        passage_a_id=left,
        passage_b_id=right,
        detector_id=detector_id,
        family=registration.family,
        independence_group=registration.independence_group,
        raw_score=score,
        contains_english_derived_evidence=registration.contains_english_derived_evidence,
        english_ablation_raw_score=(
            0.0 if registration.contains_english_derived_evidence else None
        ),
        original_language_evidence_remains=registration.original_language_capable,
        counts_for_independence=registration.counts_for_independence,
        trace_json=canonical_json({"detector": detector_id, "score": score}),
        source_artifact_id=f"fixture-{detector_id}",
        source_artifact_sha256=SOURCE_SHA,
    )


def _fixture():  # type: ignore[no-untyped-def]
    rows = (
        _passage("g-a", "A 1:1", 1),
        _passage("h-b", "B 1:1", 2),
        _passage("g-c", "C 1:1", 3),
        _passage("h-d", "D 1:1", 4),
    )
    by_id = {row.passage_id: row for row in rows}
    pairs = ((rows[0], rows[1]), (rows[0], rows[3]), (rows[2], rows[1]))
    detector_sets = (
        (
            "semantic_domain_overlap",
            "grammar_sequence_alignment",
            "participant_frame_progression",
            "multilingual_e5_english_gloss",
        ),
        ("semantic_domain_overlap", "grammar_sequence_alignment"),
        ("participant_frame_progression",),
    )
    raw = tuple(
        _raw(left, right, detector_id, 0.95 - pair_index * 0.15 - detector_index * 0.03)
        for pair_index, ((left, right), detectors) in enumerate(
            zip(pairs, detector_sets, strict=True)
        )
        for detector_index, detector_id in enumerate(detectors)
    )
    detector_ids = {row.detector_id for row in raw}
    evidence = calibrate_detector_evidence(
        raw,
        config=CONFIG,
        reference_scores={
            detector: tuple(index / 20 for index in range(21)) for detector in detector_ids
        },
        null_scores={detector: (0.1,) * 20 for detector in detector_ids},
    )
    passages_by_pair = {
        row.candidate_pair_id: (row.passage_a_id, row.passage_b_id) for row in evidence
    }
    strata = {pair_id: "cross-book|narrative-poetry" for pair_id in passages_by_pair}
    full = stratified_ensemble_null_calibration(
        ensemble_group_scores_by_pair(evidence),
        strata,
        config=CONFIG,
        iterations=CONFIG.calibration.fixture_iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope="full",
    )
    ablated = stratified_ensemble_null_calibration(
        ensemble_group_scores_by_pair(evidence, remove_all_english=True),
        strata,
        config=CONFIG,
        iterations=CONFIG.calibration.fixture_iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope="remove_all_english",
    )
    return by_id, evidence, full, ablated


def _write_inputs(tmp_path: Path):  # type: ignore[no-untyped-def]
    passages, evidence, full, ablated = _fixture()
    evidence_path = tmp_path / "evidence.jsonl"
    full_path = tmp_path / "full.jsonl"
    ablated_path = tmp_path / "ablated.jsonl"
    write_jsonl_atomic(evidence_path, evidence, sort_key="candidate_pair_id")
    write_jsonl_atomic(full_path, full, sort_key="candidate_pair_id")
    write_jsonl_atomic(ablated_path, ablated, sort_key="candidate_pair_id")
    return passages, evidence, full, ablated, evidence_path, full_path, ablated_path


def test_disk_ensemble_matches_in_memory_oracle_exactly(tmp_path: Path) -> None:
    passages, evidence, full, ablated, evidence_path, full_path, ablated_path = _write_inputs(
        tmp_path
    )
    full_by_pair = {row.candidate_pair_id: row for row in full}
    ablated_by_pair = {row.candidate_pair_id: row for row in ablated}
    expected = build_final_candidates(
        evidence,
        passages,
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=full_by_pair,
        english_ablation_null_calibration_by_pair=ablated_by_pair,
    )

    output = tmp_path / "candidates.jsonl"
    receipt = build_final_candidates_disk_backed(
        evidence_path,
        full_path,
        ablated_path,
        output,
        work_directory=tmp_path / "disk-work",
        passages=passages,
        knownness=KnownnessIndex([]),
        config=CONFIG,
        maximum_candidate_pairs=10,
        chunk_size=2,
    )
    observed = read_jsonl(output, FinalCandidate)

    assert [row.model_dump(mode="json") for row in observed] == [
        row.model_dump(mode="json") for row in expected
    ]
    assert receipt.candidate_pair_count == len(expected) == 3
    assert receipt.evidence_row_count == len(evidence)
    assert receipt.chunk_count == 2
    assert receipt.tier_a_count == sum(row.tier_a_eligible for row in expected)
    assert receipt.tier_b_count == sum(row.tier_b_rank is not None for row in expected)
    assert list((tmp_path / "disk-work" / "candidate-sort-chunks").glob("*.jsonl"))


def test_disk_ensemble_rejects_bound_or_incomplete_null_population(tmp_path: Path) -> None:
    passages, _, _, ablated, evidence_path, full_path, _ = _write_inputs(tmp_path)
    with pytest.raises(DiskEnsembleError, match="resource bound"):
        build_final_candidates_disk_backed(
            evidence_path,
            full_path,
            tmp_path / "ablated.jsonl",
            tmp_path / "too-many.jsonl",
            work_directory=tmp_path / "too-many-work",
            passages=passages,
            knownness=KnownnessIndex([]),
            config=CONFIG,
            maximum_candidate_pairs=1,
        )

    incomplete_path = tmp_path / "incomplete-ablated.jsonl"
    write_jsonl_atomic(incomplete_path, ablated[:-1], sort_key="candidate_pair_id")
    with pytest.raises(DiskEnsembleError, match="different populations"):
        build_final_candidates_disk_backed(
            evidence_path,
            full_path,
            incomplete_path,
            tmp_path / "incomplete.jsonl",
            work_directory=tmp_path / "incomplete-work",
            passages=passages,
            knownness=KnownnessIndex([]),
            config=CONFIG,
            maximum_candidate_pairs=10,
        )
