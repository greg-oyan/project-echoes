"""Oracle-equivalence tests for bounded strict final-discovery validation."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path

import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.disk_validation import (
    DiskFinalDiscoveryValidationError,
    DiskFinalDiscoveryValidationResult,
    validate_final_discovery_disk_backed,
)
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json, evidence_id
from echoes.final_discovery.knownness import KnownnessIndex, KnownRelationship
from echoes.final_discovery.models import EvidenceRow, FinalCandidate, PassageRecord
from echoes.final_discovery.nulls import (
    EnsembleNullCalibrationRow,
    stratified_ensemble_null_calibration,
)
from echoes.final_discovery.storage import write_jsonl_stream_atomic
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    validate_final_discovery,
)

CONFIG = load_final_discovery_config()
SOURCE_ID = "prepared-passage-projection-v1"
SOURCE_HASH = "a" * 64
MEMORY_LIMIT = 256 * 1024**2
REGISTRATIONS = {registration.detector_id: registration for registration in CONFIG.detectors}


@dataclass(frozen=True, slots=True)
class _Fixture:
    evidence: tuple[EvidenceRow, ...]
    candidates: tuple[FinalCandidate, ...]
    passages: dict[str, PassageRecord]
    full_null: tuple[EnsembleNullCalibrationRow, ...]
    ablated_null: tuple[EnsembleNullCalibrationRow, ...]
    source_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class _Paths:
    evidence: Path
    candidates: Path
    full_null: Path
    ablated_null: Path


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
        token_ids=(f"token-{passage_id}",),
        original_text="aleph",
        normalized_text="aleph",
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


def _evidence(left: PassageRecord, right: PassageRecord, score: float) -> EvidenceRow:
    detector_id = "semantic_domain_overlap"
    registration = REGISTRATIONS[detector_id]
    pair_id = candidate_pair_id(left.passage_id, right.passage_id)
    return EvidenceRow(
        evidence_id=evidence_id(pair_id, detector_id, SOURCE_HASH),
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
        contains_english_derived_evidence=False,
        english_ablation_normalized_score=score,
        original_language_evidence_remains=True,
        counts_for_independence=registration.counts_for_independence,
        trace_json=canonical_json({"representation": "semantic_domains", "score": score}),
        source_artifact_id=SOURCE_ID,
        source_artifact_sha256=SOURCE_HASH,
    )


def _registered_evidence(
    left: PassageRecord,
    right: PassageRecord,
    detector_id: str,
    score: float,
    *,
    trace: dict[str, object],
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
        counts_for_independence=registration.counts_for_independence and (not english or original),
        trace_json=canonical_json(trace),
        source_artifact_id=source_id,
        source_artifact_sha256=source_hash,
    )


def _null_rows(
    evidence: tuple[EvidenceRow, ...],
    *,
    remove_all_english: bool,
    strata: dict[str, str],
) -> tuple[EnsembleNullCalibrationRow, ...]:
    scores = ensemble_group_scores_by_pair(
        evidence,
        remove_all_english=remove_all_english,
    )
    return stratified_ensemble_null_calibration(
        scores,
        strata,
        config=CONFIG,
        iterations=CONFIG.calibration.fixture_iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope=("remove_all_english" if remove_all_english else "full"),
    )


def _make_fixture() -> _Fixture:
    source = random.Random(47_103)
    passages: dict[str, PassageRecord] = {}
    evidence: list[EvidenceRow] = []
    strata: dict[str, str] = {}
    tied_scores = (0.2, 0.35, 0.5, 0.5, 0.65, 0.8, 0.95)
    for index in range(101):
        left = _passage(f"A{index:03d}", f"GEN {index + 1}:1")
        right = _passage(f"B{index:03d}", f"GEN {index + 1}:2")
        passages[left.passage_id] = left
        passages[right.passage_id] = right
        row = _evidence(left, right, source.choice(tied_scores))
        evidence.append(row)
        strata[row.candidate_pair_id] = ("alpha", "middle", "zeta")[index % 3]
    retained = tuple(sorted(evidence, key=lambda row: (row.candidate_pair_id, row.detector_id)))
    full_null = _null_rows(retained, remove_all_english=False, strata=strata)
    ablated_null = _null_rows(retained, remove_all_english=True, strata=strata)
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
    return _Fixture(
        evidence=retained,
        candidates=candidates,
        passages=passages,
        full_null=full_null,
        ablated_null=ablated_null,
        source_hashes={SOURCE_ID: SOURCE_HASH},
    )


@pytest.fixture(scope="module")
def fixture() -> _Fixture:
    return _make_fixture()


def _write_paths(
    root: Path,
    fixture: _Fixture,
    *,
    evidence: tuple[EvidenceRow, ...] | None = None,
    candidates: tuple[FinalCandidate, ...] | None = None,
    full_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
    ablated_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
    preserve_supplied_order: bool = False,
) -> _Paths:
    root.mkdir()
    evidence_rows = evidence if evidence is not None else fixture.evidence
    candidate_rows = candidates if candidates is not None else fixture.candidates
    full_rows = full_null if full_null is not None else fixture.full_null
    ablated_rows = ablated_null if ablated_null is not None else fixture.ablated_null
    if not preserve_supplied_order:
        evidence_rows = tuple(
            sorted(evidence_rows, key=lambda row: (row.candidate_pair_id, row.detector_id))
        )
        candidate_rows = tuple(
            sorted(candidate_rows, key=lambda row: (-row.ensemble_score, row.candidate_pair_id))
        )
        full_rows = tuple(sorted(full_rows, key=lambda row: row.candidate_pair_id))
        ablated_rows = tuple(sorted(ablated_rows, key=lambda row: row.candidate_pair_id))
    paths = _Paths(
        evidence=root / "evidence.jsonl",
        candidates=root / "candidates.jsonl",
        full_null=root / "full-null.jsonl",
        ablated_null=root / "ablated-null.jsonl",
    )
    write_jsonl_stream_atomic(paths.evidence, evidence_rows, order_key=None)
    write_jsonl_stream_atomic(paths.candidates, candidate_rows, order_key=None)
    write_jsonl_stream_atomic(paths.full_null, full_rows, order_key=None)
    write_jsonl_stream_atomic(paths.ablated_null, ablated_rows, order_key=None)
    return paths


def _oracle(
    fixture: _Fixture,
    *,
    evidence: tuple[EvidenceRow, ...] | None = None,
    candidates: tuple[FinalCandidate, ...] | None = None,
    full_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
    ablated_null: tuple[EnsembleNullCalibrationRow, ...] | None = None,
    knownness: KnownnessIndex | None = None,
) -> FinalDiscoveryValidationReport:
    return validate_final_discovery(
        evidence if evidence is not None else fixture.evidence,
        candidates if candidates is not None else fixture.candidates,
        config=CONFIG,
        passages=fixture.passages,
        knownness=knownness or KnownnessIndex(()),
        null_calibration_by_pair=(full_null if full_null is not None else fixture.full_null),
        english_ablation_null_calibration_by_pair=(
            ablated_null if ablated_null is not None else fixture.ablated_null
        ),
        expected_source_artifact_sha256=fixture.source_hashes,
    )


def _disk_validate(
    tmp_path: Path,
    fixture: _Fixture,
    paths: _Paths,
    *,
    output_name: str = "validation",
    expected_stage_count: int | None = None,
    knownness: KnownnessIndex | tuple[KnownRelationship, ...] | None = None,
) -> DiskFinalDiscoveryValidationResult:
    return validate_final_discovery_disk_backed(
        paths.evidence,
        paths.candidates,
        paths.full_null,
        paths.ablated_null,
        tmp_path / output_name,
        passages=fixture.passages,
        knownness=knownness or KnownnessIndex(()),
        config=CONFIG,
        memory_limit_bytes=MEMORY_LIMIT,
        temp_directory=tmp_path / "spill",
        expected_source_artifact_sha256=fixture.source_hashes,
        expected_authenticated_stage_count=expected_stage_count,
        minimum_temp_free_bytes=256 * 1024**2,
        batch_size=17,
    )


def _codes(report: FinalDiscoveryValidationReport) -> set[str]:
    return {finding.code for finding in report.findings}


def test_disk_validator_exactly_matches_valid_oracle_and_receipts(
    tmp_path: Path,
    fixture: _Fixture,
) -> None:
    oracle = _oracle(fixture)
    paths = _write_paths(tmp_path / "inputs", fixture)
    result = _disk_validate(tmp_path, fixture, paths)

    assert oracle.passed, oracle.findings
    assert result.report.model_dump() == oracle.model_dump()
    assert result.receipt.validation_passed
    assert result.receipt.evidence_pair_count == 101
    assert result.receipt.known_relationship_count == 0
    assert result.receipt.resource_bounds.maximum_evidence_rows_retained_per_pair == 1
    assert result.receipt.resource_bounds.full_ledgers_retained_in_python is False
    assert result.receipt.resource_bounds.duckdb_state_persisted is False
    assert (
        result.receipt.report_sha256 == hashlib.sha256(result.report_path.read_bytes()).hexdigest()
    )
    assert [item.role for item in result.receipt.inputs] == [
        "evidence",
        "candidates",
        "full_null",
        "remove_all_english_null",
    ]
    assert not list((tmp_path / "spill").glob("*.duckdb*"))


@pytest.mark.parametrize(
    "corruption",
    ["candidate_score", "candidate_q", "evidence_registration", "null_score", "tier_rank"],
)
def test_disk_validator_rejects_oracle_corruptions_with_same_contract_code(
    tmp_path: Path,
    fixture: _Fixture,
    corruption: str,
) -> None:
    evidence = fixture.evidence
    candidates = fixture.candidates
    full_null = fixture.full_null
    expected_code = ""
    if corruption == "candidate_score":
        mutated = list(candidates)
        mutated[-1] = mutated[-1].model_copy(update={"ensemble_score": 0.01})
        candidates = tuple(mutated)
        expected_code = "ensemble-score"
    elif corruption == "candidate_q":
        mutated = list(candidates)
        mutated[0] = mutated[0].model_copy(update={"bh_q_value": 0.99})
        candidates = tuple(mutated)
        expected_code = "bh-reconciliation"
    elif corruption == "evidence_registration":
        mutated_evidence = list(evidence)
        mutated_evidence[0] = mutated_evidence[0].model_copy(
            update={"independence_group": "grammar_annotations"}
        )
        evidence = tuple(mutated_evidence)
        expected_code = "detector-registration-lineage"
    elif corruption == "null_score":
        mutated_null = list(full_null)
        replacement = 0.0 if mutated_null[0].observed_score != 0.0 else 0.1
        mutated_null[0] = mutated_null[0].model_copy(update={"observed_score": replacement})
        full_null = tuple(mutated_null)
        expected_code = "full-null-observed-score"
    else:
        mutated = list(candidates)
        first = next(index for index, row in enumerate(mutated) if row.tier_b_rank == 1)
        second = next(index for index, row in enumerate(mutated) if row.tier_b_rank == 2)
        mutated[first] = mutated[first].model_copy(update={"tier_b_rank": 2})
        mutated[second] = mutated[second].model_copy(update={"tier_b_rank": 1})
        candidates = tuple(mutated)
        expected_code = "tier-b-exact-membership"
    oracle = _oracle(
        fixture,
        evidence=evidence,
        candidates=candidates,
        full_null=full_null,
    )
    paths = _write_paths(
        tmp_path / "inputs",
        fixture,
        evidence=evidence,
        candidates=candidates,
        full_null=full_null,
    )
    result = _disk_validate(tmp_path, fixture, paths)

    assert expected_code in _codes(oracle)
    assert expected_code in _codes(result.report)
    assert not result.receipt.validation_passed


def test_disk_validator_stage_expectation_fails_closed_in_receipt(
    tmp_path: Path,
    fixture: _Fixture,
) -> None:
    paths = _write_paths(tmp_path / "inputs", fixture)
    result = _disk_validate(
        tmp_path,
        fixture,
        paths,
        expected_stage_count=11,
    )

    assert "stage-store-missing" in _codes(result.report)
    assert result.receipt.expected_authenticated_stage_count == 11
    assert result.receipt.authenticated_stage_count == 0
    assert not result.receipt.validation_passed


def test_disk_validator_streams_knownness_iterable_with_index_oracle(
    tmp_path: Path,
    fixture: _Fixture,
) -> None:
    first = fixture.evidence[0]
    relationship = KnownRelationship(
        relationship_id="known-1",
        source_passage_id=first.passage_a_id,
        target_passage_id=first.passage_b_id,
        source_name="fixture",
        mapping_quality="exact",
    )
    index = KnownnessIndex((relationship,))
    candidates = build_final_candidates(
        fixture.evidence,
        fixture.passages,
        knownness=index,
        config=CONFIG,
        null_calibration_by_pair={row.candidate_pair_id: row for row in fixture.full_null},
        english_ablation_null_calibration_by_pair={
            row.candidate_pair_id: row for row in fixture.ablated_null
        },
    )
    known_fixture = _Fixture(
        evidence=fixture.evidence,
        candidates=candidates,
        passages=fixture.passages,
        full_null=fixture.full_null,
        ablated_null=fixture.ablated_null,
        source_hashes=fixture.source_hashes,
    )
    oracle = _oracle(known_fixture, knownness=index)
    paths = _write_paths(tmp_path / "inputs", known_fixture)
    result = _disk_validate(
        tmp_path,
        known_fixture,
        paths,
        knownness=(relationship,),
    )

    assert oracle.passed, oracle.findings
    assert result.report.model_dump() == oracle.model_dump()
    assert result.receipt.known_relationship_count == 1
    assert result.receipt.validation_passed


def test_disk_validator_recomputes_explicit_english_ablation_scope(
    tmp_path: Path,
) -> None:
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
                _registered_evidence(
                    left,
                    right,
                    "semantic_domain_overlap",
                    0.95 - index * 0.05,
                    trace={"representation": "semantic_domains"},
                ),
                _registered_evidence(
                    left,
                    right,
                    "grammar_sequence_alignment",
                    0.94 - index * 0.05,
                    trace={"representation": "grammar_sequence"},
                ),
                _registered_evidence(
                    left,
                    right,
                    "multilingual_e5_english_gloss",
                    0.90 - index * 0.05,
                    trace={
                        "representation": "pinned_multilingual_e5_literal_english_gloss",
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
    retained = tuple(sorted(evidence, key=lambda row: (row.candidate_pair_id, row.detector_id)))
    strata = {row.candidate_pair_id: "all" for row in retained}
    full_null = _null_rows(retained, remove_all_english=False, strata=strata)
    ablated_null = _null_rows(retained, remove_all_english=True, strata=strata)
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
    fixture = _Fixture(
        evidence=retained,
        candidates=candidates,
        passages=passages,
        full_null=full_null,
        ablated_null=ablated_null,
        source_hashes={
            SOURCE_ID: SOURCE_HASH,
            f"{pin.model_id}@{pin.revision}": composite_hash,
        },
    )
    oracle = _oracle(fixture)
    paths = _write_paths(tmp_path / "inputs", fixture)
    result = _disk_validate(tmp_path, fixture, paths)

    assert oracle.passed, oracle.findings
    assert result.report.model_dump() == oracle.model_dump()
    assert all(row.contains_english_derived_evidence for row in fixture.candidates)
    assert result.receipt.validation_passed


def test_disk_validator_rejects_unordered_evidence_without_publishing(
    tmp_path: Path,
    fixture: _Fixture,
) -> None:
    paths = _write_paths(
        tmp_path / "inputs",
        fixture,
        evidence=tuple(reversed(fixture.evidence)),
        preserve_supplied_order=True,
    )
    output = tmp_path / "validation"

    with pytest.raises(DiskFinalDiscoveryValidationError, match="strictly ordered"):
        validate_final_discovery_disk_backed(
            paths.evidence,
            paths.candidates,
            paths.full_null,
            paths.ablated_null,
            output,
            passages=fixture.passages,
            knownness=KnownnessIndex(()),
            config=CONFIG,
            memory_limit_bytes=MEMORY_LIMIT,
            temp_directory=tmp_path / "spill",
            minimum_temp_free_bytes=256 * 1024**2,
        )
    assert not output.exists()


def test_disk_validator_rejects_underbounded_resources_before_work(
    tmp_path: Path,
    fixture: _Fixture,
) -> None:
    paths = _write_paths(tmp_path / "inputs", fixture)

    with pytest.raises(DiskFinalDiscoveryValidationError, match="at least 256 MiB"):
        validate_final_discovery_disk_backed(
            paths.evidence,
            paths.candidates,
            paths.full_null,
            paths.ablated_null,
            tmp_path / "validation",
            passages=fixture.passages,
            knownness=KnownnessIndex(()),
            config=CONFIG,
            memory_limit_bytes=128 * 1024**2,
            temp_directory=tmp_path / "spill",
        )
