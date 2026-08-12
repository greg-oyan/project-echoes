"""Adversarial tests for independent final-discovery validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from echoes.final_discovery.config import FinalDiscoveryConfig, load_final_discovery_config
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json, evidence_id
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import EvidenceRow, FinalCandidate, PassageRecord
from echoes.final_discovery.nulls import (
    EnsembleNullCalibrationRow,
    stratified_ensemble_null_calibration,
)
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    validate_final_discovery,
)

CONFIG = load_final_discovery_config()
SOURCE_ID = "prepared-passage-projection-v1"
SOURCE_HASH = "a" * 64
REGISTRATIONS = {registration.detector_id: registration for registration in CONFIG.detectors}


@dataclass(frozen=True, slots=True)
class _ValidationFixture:
    evidence: tuple[EvidenceRow, ...]
    candidates: tuple[FinalCandidate, ...]
    passages: dict[str, PassageRecord]
    full_null: tuple[EnsembleNullCalibrationRow, ...]
    ablated_null: tuple[EnsembleNullCalibrationRow, ...] | None
    source_hashes: dict[str, str]


def _passage(passage_id: str, reference: str) -> PassageRecord:
    return PassageRecord(
        passage_id=passage_id,
        reference=reference,
        corpus="hebrew",
        book="GEN",
        genre="narrative",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        token_count=1,
        original_text="א",
        normalized_text="א",
        lemma_sequence=("lemma",),
        root_sequence=("root",),
        pos_sequence=("NOUN",),
        morphology_sequence=("noun",),
        semantic_domains=("domain",),
        entities=(None,),
        participants=(None,),
        frames=(None,),
        source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
    )


def _evidence(
    left: PassageRecord,
    right: PassageRecord,
    detector_id: str,
    score: float,
    *,
    trace: dict[str, object] | None = None,
    source_id: str = SOURCE_ID,
    source_hash: str = SOURCE_HASH,
) -> EvidenceRow:
    registration = REGISTRATIONS[detector_id]
    pair_id = candidate_pair_id(left.passage_id, right.passage_id)
    english = registration.contains_english_derived_evidence
    original = registration.original_language_capable
    return EvidenceRow(
        evidence_id=evidence_id(pair_id, detector_id, source_hash),
        candidate_pair_id=pair_id,
        passage_a_id=left.passage_id,
        passage_b_id=right.passage_id,
        detector_id=detector_id,
        family=registration.family,
        independence_group=registration.independence_group,
        raw_score=score,
        normalized_score=score,
        normalization_method=registration.normalization,
        empirical_p_value=0.5,
        null_method=registration.null_family,
        contains_english_derived_evidence=english,
        english_ablation_normalized_score=0.0 if english else score,
        original_language_evidence_remains=original,
        counts_for_independence=registration.counts_for_independence,
        trace_json=canonical_json(trace or {"fixture": detector_id}),
        source_artifact_id=source_id,
        source_artifact_sha256=source_hash,
    )


def _null_rows(
    evidence: tuple[EvidenceRow, ...],
    *,
    config: FinalDiscoveryConfig,
    remove_all_english: bool,
) -> tuple[EnsembleNullCalibrationRow, ...]:
    scores = ensemble_group_scores_by_pair(
        evidence,
        remove_all_english=remove_all_english,
    )
    return stratified_ensemble_null_calibration(
        scores,
        {pair_id: "all" for pair_id in scores},
        config=config,
        iterations=config.calibration.fixture_iterations,
        seed=config.calibration.seeds["stratified_permutation"],
        calibration_scope=("remove_all_english" if remove_all_english else "full"),
    )


def _large_fixture() -> _ValidationFixture:
    passages: dict[str, PassageRecord] = {}
    evidence: list[EvidenceRow] = []
    for index in range(101):
        left = _passage(f"A{index:03d}", f"GEN {index + 1}:1")
        right = _passage(f"B{index:03d}", f"GEN {index + 1}:2")
        passages[left.passage_id] = left
        passages[right.passage_id] = right
        evidence.append(
            _evidence(
                left,
                right,
                "semantic_domain_overlap",
                1.0 - index / 202,
                trace={"fixture_index": index, "representation": "semantic_domains"},
            )
        )
    retained = tuple(evidence)
    full_null = _null_rows(retained, config=CONFIG, remove_all_english=False)
    full_by_pair = {row.candidate_pair_id: row for row in full_null}
    candidates = build_final_candidates(
        retained,
        passages,
        knownness=KnownnessIndex(()),
        config=CONFIG,
        null_calibration_by_pair=full_by_pair,
    )
    return _ValidationFixture(
        evidence=retained,
        candidates=candidates,
        passages=passages,
        full_null=full_null,
        ablated_null=None,
        source_hashes={SOURCE_ID: SOURCE_HASH},
    )


@pytest.fixture(scope="module")
def large_fixture() -> _ValidationFixture:
    return _large_fixture()


def _validate(
    fixture: _ValidationFixture,
    *,
    evidence: tuple[EvidenceRow, ...] | None = None,
    candidates: tuple[FinalCandidate, ...] | None = None,
    full_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
    ablated_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
) -> FinalDiscoveryValidationReport:
    return validate_final_discovery(
        evidence if evidence is not None else fixture.evidence,
        candidates if candidates is not None else fixture.candidates,
        config=CONFIG,
        passages=fixture.passages,
        knownness=KnownnessIndex(()),
        null_calibration_by_pair=(full_null if full_null is not None else fixture.full_null),
        english_ablation_null_calibration_by_pair=(
            ablated_null if ablated_null is not None else fixture.ablated_null
        ),
        expected_source_artifact_sha256=fixture.source_hashes,
    )


def _codes(report: FinalDiscoveryValidationReport) -> set[str]:
    return {finding.code for finding in report.findings}


def test_strict_validation_recomputes_contract_and_exact_top_100(
    large_fixture: _ValidationFixture,
) -> None:
    report = _validate(large_fixture)

    assert report.passed, report.findings
    assert report.tier_b_count == 100
    report_input = large_fixture.candidates
    assert sum(candidate.output_label == "retained_excluded" for candidate in report_input) == 1
    assert sorted(
        candidate.tier_b_rank for candidate in report_input if candidate.tier_b_rank is not None
    ) == list(range(1, 101))


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"ensemble_score": 0.5}, "ensemble-score"),
        ({"bh_q_value": 0.9}, "bh-reconciliation"),
        ({"knownness_status": "known_forward"}, "knownness-reconciliation"),
        ({"tier_a_exclusion_reasons": ("forged",)}, "tier-a-exclusion-reasons"),
        ({"output_label": "statistically_eligible"}, "output-label-reconciliation"),
    ],
)
def test_strict_validation_rejects_mutated_candidate_fields(
    large_fixture: _ValidationFixture,
    updates: dict[str, object],
    expected_code: str,
) -> None:
    corrupted = list(large_fixture.candidates)
    corrupted[0] = corrupted[0].model_copy(update=updates)

    report = _validate(large_fixture, candidates=tuple(corrupted))

    assert expected_code in _codes(report)


def test_strict_validation_rejects_noncanonical_candidate_id(
    large_fixture: _ValidationFixture,
) -> None:
    corrupted = list(large_fixture.candidates)
    corrupted[0] = corrupted[0].model_copy(update={"candidate_pair_id": f"FDPAIR~{'0' * 64}"})

    report = _validate(large_fixture, candidates=tuple(corrupted))

    assert {"candidate-id", "candidate-population"} <= _codes(report)


def test_strict_validation_rejects_missing_exact_tier_b_member(
    large_fixture: _ValidationFixture,
) -> None:
    corrupted = list(large_fixture.candidates)
    index = next(
        index
        for index, candidate in enumerate(corrupted)
        if candidate.tier_b_rank == CONFIG.tiers.tier_b_size
    )
    corrupted[index] = corrupted[index].model_copy(
        update={"tier_b_rank": None, "output_label": "retained_excluded"}
    )

    report = _validate(large_fixture, candidates=tuple(corrupted))

    assert {"tier-b-exact-size", "tier-b-exact-membership"} <= _codes(report)


def test_strict_validation_rejects_tier_b_rank_swap(
    large_fixture: _ValidationFixture,
) -> None:
    corrupted = list(large_fixture.candidates)
    first_index = next(
        index for index, candidate in enumerate(corrupted) if candidate.tier_b_rank == 1
    )
    second_index = next(
        index for index, candidate in enumerate(corrupted) if candidate.tier_b_rank == 2
    )
    corrupted[first_index] = corrupted[first_index].model_copy(update={"tier_b_rank": 2})
    corrupted[second_index] = corrupted[second_index].model_copy(update={"tier_b_rank": 1})

    report = _validate(large_fixture, candidates=tuple(corrupted))

    assert "tier-b-exact-membership" in _codes(report)


def test_strict_validation_rejects_quality_and_output_order_mutations(
    large_fixture: _ValidationFixture,
) -> None:
    corrupted = list(large_fixture.candidates)
    corrupted[0] = corrupted[0].model_copy(
        update={"quality": corrupted[0].quality.model_copy(update={"disputed_passage": True})}
    )
    corrupted[0], corrupted[-1] = corrupted[-1], corrupted[0]

    report = _validate(large_fixture, candidates=tuple(corrupted))

    assert {"quality-reconciliation", "candidate-output-order"} <= _codes(report)


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"evidence_id": f"FDEVID~{'0' * 64}"}, "evidence-id"),
        ({"independence_group": "grammar_annotations"}, "detector-registration-lineage"),
        ({"trace_json": '{"z": 1}'}, "noncanonical-evidence-trace"),
        ({"source_artifact_sha256": "b" * 64}, "source-artifact-hash"),
    ],
)
def test_strict_validation_rejects_mutated_evidence_lineage(
    large_fixture: _ValidationFixture,
    updates: dict[str, object],
    expected_code: str,
) -> None:
    corrupted = list(large_fixture.evidence)
    corrupted[0] = corrupted[0].model_copy(update=updates)

    report = _validate(large_fixture, evidence=tuple(corrupted))

    assert expected_code in _codes(report)


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"observed_score": 0.0}, "full-null-observed-score"),
        ({"empirical_p_value": 0.5}, "full-null-p-value-invariant"),
        ({"raw_empirical_fdr": 0.9}, "full-null-fdr-invariant"),
        ({"observed_discovery_count": 1}, "full-null-observed-discoveries"),
    ],
)
def test_strict_validation_rejects_mutated_null_rows(
    large_fixture: _ValidationFixture,
    updates: dict[str, object],
    expected_code: str,
) -> None:
    corrupted = list(large_fixture.full_null)
    corrupted[0] = corrupted[0].model_copy(update=updates)

    report = _validate(large_fixture, full_null=tuple(corrupted))

    assert expected_code in _codes(report)


def test_strict_validation_requires_exact_null_population(
    large_fixture: _ValidationFixture,
) -> None:
    report = _validate(large_fixture, full_null=large_fixture.full_null[:-1])

    assert "full-null-coverage" in _codes(report)


def _english_fixture() -> _ValidationFixture:
    pin = CONFIG.embedding_model
    inventory_hash = "c" * 64
    projection_hash = "d" * 64
    composite_hash = hashlib.sha256(
        canonical_json(
            {
                "model_inventory_sha256": inventory_hash,
                "passage_projection_sha256": projection_hash,
            }
        ).encode("ascii")
    ).hexdigest()
    passages: dict[str, PassageRecord] = {}
    evidence: list[EvidenceRow] = []
    for index in range(2):
        left = _passage(f"EA{index}", f"GEN {index + 1}:1")
        right = _passage(f"EB{index}", f"GEN {index + 1}:2")
        passages[left.passage_id] = left
        passages[right.passage_id] = right
        evidence.extend(
            (
                _evidence(left, right, "semantic_domain_overlap", 0.95 - index * 0.05),
                _evidence(left, right, "grammar_sequence_alignment", 0.94 - index * 0.05),
                _evidence(
                    left,
                    right,
                    "multilingual_e5_english_gloss",
                    0.90 - index * 0.05,
                    trace={
                        "representation": "pinned_multilingual_e5_literal_english_gloss",
                        "cosine_similarity": 0.8 - index * 0.1,
                        "supplemental_english_derived": True,
                        "model_id": pin.model_id,
                        "model_revision": pin.revision,
                        "tokenizer": pin.tokenizer,
                        "pooling": pin.pooling,
                        "maximum_tokens": pin.maximum_tokens,
                        "symmetric_prefix": pin.symmetric_prefix,
                        "model_inventory_sha256": inventory_hash,
                        "passage_projection_sha256": projection_hash,
                        "composite_source_sha256": composite_hash,
                    },
                    source_id=f"{pin.model_id}@{pin.revision}",
                    source_hash=composite_hash,
                ),
            )
        )
    retained = tuple(evidence)
    full_null = _null_rows(retained, config=CONFIG, remove_all_english=False)
    ablated_null = _null_rows(retained, config=CONFIG, remove_all_english=True)
    candidates = build_final_candidates(
        retained,
        passages,
        knownness=KnownnessIndex(()),
        config=CONFIG,
        null_calibration_by_pair={row.candidate_pair_id: row for row in full_null},
        english_ablation_null_calibration_by_pair={
            row.candidate_pair_id: row for row in ablated_null
        },
    )
    return _ValidationFixture(
        evidence=retained,
        candidates=candidates,
        passages=passages,
        full_null=full_null,
        ablated_null=ablated_null,
        source_hashes={SOURCE_ID: SOURCE_HASH, f"{pin.model_id}@{pin.revision}": composite_hash},
    )


def test_strict_validation_reconciles_explicit_english_ablation_scope() -> None:
    fixture = _english_fixture()
    report = _validate(fixture, ablated_null=fixture.ablated_null)

    assert report.passed, report.findings

    corrupted = list(fixture.ablated_null or ())
    corrupted[0] = corrupted[0].model_copy(update={"empirical_p_value": 0.5})
    failed = _validate(fixture, ablated_null=tuple(corrupted))
    assert "english-ablation-null-p-value-invariant" in _codes(failed)

    corrupted_candidates = list(fixture.candidates)
    corrupted_candidates[0] = corrupted_candidates[0].model_copy(
        update={"english_ablation_bh_q_value": 0.99}
    )
    failed_candidate = _validate(
        fixture,
        candidates=tuple(corrupted_candidates),
        ablated_null=fixture.ablated_null,
    )
    assert "english-ablation-bh-reconciliation" in _codes(failed_candidate)

    missing_ablated = validate_final_discovery(
        fixture.evidence,
        fixture.candidates,
        config=CONFIG,
        passages=fixture.passages,
        knownness=KnownnessIndex(()),
        null_calibration_by_pair=fixture.full_null,
        expected_source_artifact_sha256=fixture.source_hashes,
    )
    assert "english-ablation-null-missing" in _codes(missing_ablated)
