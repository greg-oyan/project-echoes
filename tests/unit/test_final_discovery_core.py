"""Focused scientific-contract tests for final-discovery-v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pytest

from echoes.final_discovery.anomaly import PairFamilyScores, anomaly_evidence
from echoes.final_discovery.config import (
    ModelPin,
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.ensemble import (
    build_final_candidates,
    calibrate_detector_evidence,
    ensemble_group_scores_by_pair,
)
from echoes.final_discovery.features import (
    aligned_sequence_similarity,
    candidate_pair_id,
    empirical_upper_tail,
)
from echoes.final_discovery.knownness import KnownnessIndex, KnownRelationship
from echoes.final_discovery.models import EvidenceRow, PassageRecord, QualityFlags, RawEvidence
from echoes.final_discovery.nulls import EnsembleNullCalibrationRow
from echoes.final_discovery.semantic import (
    SemanticError,
    blockwise_top_k_cosine,
    semantic_pair_evidence,
    verify_model_artifacts,
    verify_model_runtime_dependencies,
)
from echoes.final_discovery.structure import structure_pair_evidence
from echoes.final_discovery.syntax import (
    feature_document_frequencies,
    grammar_pair_evidence,
    grammatical_features,
)
from echoes.final_discovery.validation import validate_final_discovery

CONFIG = load_final_discovery_config()
REGISTRATIONS = {item.detector_id: item for item in CONFIG.detectors}
SOURCE_HASH = "a" * 64


def _passage(
    passage_id: str,
    reference: str,
    *,
    book: str,
    corpus: str = "hebrew",
    genre: str = "narrative",
    disputed: bool = False,
) -> PassageRecord:
    reading = "source" if corpus == "greek" else "qere"
    return PassageRecord(
        passage_id=passage_id,
        reference=reference,
        corpus=corpus,
        book=book,
        genre=genre,
        analysis_profile="edition_complete",
        analysis_reading=reading,
        granularity="verse",
        token_count=4,
        token_ids=tuple(f"{passage_id}-token-{position}" for position in range(1, 5)),
        original_text="אמר מלך הלך עיר" if corpus == "hebrew" else "λεγει βασιλευς πολις",
        normalized_text="אמר מלך הלך עיר",
        lemma_sequence=("say", "king", "walk", "city"),
        root_sequence=("say", "king", "walk", "city"),
        pos_sequence=("VERB", "NOUN", "VERB", "NOUN"),
        morphology_sequence=("qatal", "noun", "imperfect", "noun"),
        semantic_domains=("speech", "person", "motion", "place"),
        entities=(None, "king", None, "city"),
        participants=("speaker", "king", "king", "city"),
        frames=("speech:predicate", "participant", "motion:event", "goal"),
        english_gloss="the king said and went to the city",
        disputed_passage=disputed,
        source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
    )


def _raw(
    pair: tuple[PassageRecord, PassageRecord],
    detector_id: str,
    score: float,
    *,
    english: bool = False,
) -> RawEvidence:
    registration = REGISTRATIONS[detector_id]
    left, right = sorted(pair, key=lambda passage: passage.passage_id)
    return RawEvidence(
        candidate_pair_id=candidate_pair_id(left.passage_id, right.passage_id),
        passage_a_id=left.passage_id,
        passage_b_id=right.passage_id,
        detector_id=detector_id,
        family=registration.family,
        independence_group=registration.independence_group,
        raw_score=score,
        contains_english_derived_evidence=english,
        original_language_evidence_remains=not english,
        counts_for_independence=registration.counts_for_independence and not english,
        trace_json=json.dumps({"fixture": detector_id}),
        source_artifact_id="fixture",
        source_artifact_sha256=SOURCE_HASH,
    )


def _calibrated_pair(
    pair: tuple[PassageRecord, PassageRecord],
    detector_ids: list[str],
    *,
    score: float = 1.0,
) -> tuple[EvidenceRow, ...]:
    raw = tuple(_raw(pair, detector_id, score) for detector_id in detector_ids)
    references = {detector_id: [index / 20 for index in range(20)] for detector_id in detector_ids}
    nulls = {detector_id: [0.1] * 20 for detector_id in detector_ids}
    return calibrate_detector_evidence(
        raw,
        config=CONFIG,
        reference_scores=references,
        null_scores=nulls,
    )


def _null_calibration(
    evidence: tuple[EvidenceRow, ...],
    *,
    scope: Literal["full", "remove_all_english"] = "full",
    remove_all_english: bool = False,
) -> dict[str, EnsembleNullCalibrationRow]:
    group_scores = ensemble_group_scores_by_pair(evidence, remove_all_english=remove_all_english)
    observed = {
        pair_id: sum(
            CONFIG.ensemble.group_weights[group] * scores.get(group, 0.0)
            for group in CONFIG.ensemble.group_weights
        )
        for pair_id, scores in group_scores.items()
    }
    pair_count = len(observed)
    iterations = CONFIG.calibration.fixture_iterations
    effective_cells = pair_count * iterations
    mean_null = 1 / (iterations + 1)
    raw_fdr = {
        score: min(
            mean_null / sum(other >= score for other in observed.values()),
            1.0,
        )
        for score in observed.values()
    }
    monotone_fdr: dict[float, float] = {}
    running = 0.0
    for score in sorted(set(observed.values()), reverse=True):
        running = max(running, raw_fdr[score])
        monotone_fdr[score] = running
    return {
        pair_id: EnsembleNullCalibrationRow(
            candidate_pair_id=pair_id,
            calibration_scope=scope,
            stratum="fixture",
            stratum_size=pair_count,
            observed_score=score,
            null_exceedance_count=0,
            effective_null_cell_count=effective_cells,
            empirical_p_value=1 / (effective_cells + 1),
            null_discovery_count_sum=0,
            mean_null_discovery_count=mean_null,
            observed_discovery_count=sum(other >= score for other in observed.values()),
            raw_empirical_fdr=raw_fdr[score],
            empirical_fdr=monotone_fdr[score],
            minimum_attainable_p_value=1 / (effective_cells + 1),
            minimum_effective_null_draws=iterations,
            stratum_sufficient_for_bh=True,
            hypothesis_count=pair_count,
            iterations=iterations,
            seed=CONFIG.calibration.seeds["stratified_permutation"],
            null_method=CONFIG.ensemble.final_null_method,
        )
        for pair_id, score in observed.items()
    }


def test_preregistration_pins_model_and_all_independence_groups() -> None:
    digest = final_discovery_config_sha256(CONFIG)

    assert len(digest) == 64
    assert CONFIG.embedding_model.revision == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert CONFIG.embedding_model.license == "MIT"
    assert set(CONFIG.embedding_model.allowed_files) == {
        "1_Pooling/config.json",
        "config.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    assert set(CONFIG.ensemble.group_weights) == {
        registration.independence_group for registration in CONFIG.detectors
    }
    assert [stage.number for stage in CONFIG.stages] == list(range(1, 12))


def test_sequence_and_empirical_primitives_are_bounded() -> None:
    assert aligned_sequence_similarity(("a", "b"), ("a", "b")) == 1.0
    assert 0.0 <= aligned_sequence_similarity(("a",), ("b", "c")) <= 1.0
    assert empirical_upper_tail(1.0, [0.0] * 20) == pytest.approx(1 / 21)


def test_model_verifier_requires_exact_hash_and_inventory(tmp_path: Path) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    payload = b"bounded fake model"
    (model_root / "model.safetensors").write_bytes(payload)
    pin = ModelPin(
        model_id="fixture/model",
        revision="1" * 40,
        license="MIT",
        tokenizer="fixture",
        dimensions=2,
        maximum_tokens=8,
        pooling="mean_l2",
        symmetric_prefix="query: ",
        allowed_files={"model.safetensors": hashlib.sha256(payload).hexdigest()},
        possible_training_or_benchmark_exposure="none; synthetic fixture",
        dependency_versions={"fixture": "1.0.0"},
    )

    report = verify_model_artifacts(model_root, pin)
    assert report.total_bytes == len(payload)
    (model_root / "unexpected.bin").write_bytes(b"not allowed")
    with pytest.raises(SemanticError, match="unexpected"):
        verify_model_artifacts(model_root, pin)


def test_model_runtime_requires_python_and_every_exact_registered_distribution() -> None:
    expected = CONFIG.embedding_model.dependency_versions
    observed = {
        package: f"{version}+cpu" if package == "torch" else version
        for package, version in expected.items()
    }

    report = verify_model_runtime_dependencies(
        CONFIG.embedding_model,
        version_getter=observed.__getitem__,
        python_version_info=(3, 12, 13),
    )

    assert report.dependency_versions == observed
    drifted = {**observed, "transformers": "5.14.0"}
    with pytest.raises(SemanticError, match=r"transformers=5\.14\.0"):
        verify_model_runtime_dependencies(
            CONFIG.embedding_model,
            version_getter=drifted.__getitem__,
            python_version_info=(3, 12, 13),
        )
    with pytest.raises(SemanticError, match=r"Python 3\.12"):
        verify_model_runtime_dependencies(
            CONFIG.embedding_model,
            version_getter=observed.__getitem__,
            python_version_info=(3, 13, 0),
        )


def test_blockwise_cosine_is_deterministic_and_excludes_self() -> None:
    matrix = np.asarray([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])
    neighbors = blockwise_top_k_cosine(
        ["A", "B", "C"], matrix, ["A", "B", "C"], matrix, k=1, block_size=1
    )

    assert [(row.query_id, row.target_id) for row in neighbors] == [
        ("A", "B"),
        ("B", "A"),
        ("C", "B"),
    ]


def test_all_annotation_engines_retain_transparent_traces() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "EXO 1:1", book="EXO")
    semantic = semantic_pair_evidence(
        left,
        right,
        registrations=REGISTRATIONS,
        source_artifact_id="passages",
        source_artifact_sha256=SOURCE_HASH,
    )
    frequencies = feature_document_frequencies([left, right])
    grammar = grammar_pair_evidence(
        left,
        right,
        registrations=REGISTRATIONS,
        document_frequencies=frequencies,
        passage_count=2,
        source_artifact_id="tokens",
        source_artifact_sha256=SOURCE_HASH,
    )
    structure = structure_pair_evidence(
        left,
        right,
        registrations=REGISTRATIONS,
        source_artifact_id="passages",
        source_artifact_sha256=SOURCE_HASH,
    )

    assert {row.detector_id for row in semantic} == {
        "semantic_domain_overlap",
        "lemma_root_sequence_semantic",
    }
    assert all(row.family == "grammar_syntax" for row in grammar)
    assert not any(feature.startswith("frame:") for feature in grammatical_features(left))
    assert "structural_frames_explicitly_excluded" in grammar[0].trace_json
    assert structure.family == "structure_narrative"
    assert "no_generated_ontology" in structure.trace_json
    semantic_trace = json.loads(semantic[0].trace_json)
    speech = next(
        item for item in semantic_trace["matched_domain_evidence"] if item["value"] == "speech"
    )
    assert speech["occurrences"]["A"] == {
        "positions": [1],
        "token_ids": ["A-token-1"],
    }
    grammar_trace = json.loads(grammar[0].trace_json)
    shared_pos = next(
        item for item in grammar_trace["shared_feature_evidence"] if item["feature"] == "pos:VERB"
    )
    assert shared_pos["passage_occurrences"]["A"][0] == {
        "positions": [1],
        "source_sequence": "pos",
        "token_ids": ["A-token-1"],
    }
    structure_trace = json.loads(structure.trace_json)
    assert structure_trace["matched_signature_evidence"]["frames"][0]["passage_occurrences"]["A"][
        0
    ]["token_ids"]


def test_anomaly_is_stratified_and_never_independent() -> None:
    passages = {
        "A": _passage("A", "GEN 1:1", book="GEN"),
        "B": _passage("B", "EXO 1:1", book="EXO"),
        "C": _passage("C", "LEV 1:1", book="LEV"),
    }
    observations = [
        PairFamilyScores(
            candidate_pair_id=candidate_pair_id("A", "B"),
            passage_a_id="A",
            passage_b_id="B",
            family_scores={"lexical": 0.9, "semantic": 0.1, "grammar_syntax": 0.5},
        ),
        PairFamilyScores(
            candidate_pair_id=candidate_pair_id("A", "C"),
            passage_a_id="A",
            passage_b_id="C",
            family_scores={"lexical": 0.5, "semantic": 0.5, "grammar_syntax": 0.5},
        ),
    ]

    rows = anomaly_evidence(
        observations,
        passages,
        registrations=REGISTRATIONS,
        source_artifact_id="fixture",
        source_artifact_sha256=SOURCE_HASH,
    )

    assert all(not row.counts_for_independence for row in rows)
    assert all("stratum" in row.trace_json for row in rows)


def test_knownness_checks_reverse_direction_and_rejects_duplicate_id_collision() -> None:
    reverse = KnownRelationship(
        relationship_id="known-1",
        source_passage_id="B",
        target_passage_id="A",
        source_name="fixture",
        mapping_quality="verified",
    )
    index = KnownnessIndex([reverse])

    assert index.classify("A", "B") == ("known_reverse", ("known-1",))
    with pytest.raises(ValueError, match="multiple pairs"):
        KnownnessIndex(
            [
                reverse,
                KnownRelationship(
                    relationship_id="known-1",
                    source_passage_id="C",
                    target_passage_id="A",
                    source_name="fixture",
                    mapping_quality="verified",
                ),
            ]
        )


def test_tier_a_requires_independent_families_and_tier_b_is_distinct() -> None:
    passages = {
        "A": _passage("A", "GEN 1:1", book="GEN"),
        "B": _passage("B", "EXO 1:1", book="EXO"),
        "C": _passage("C", "LEV 1:1", book="LEV"),
    }
    accepted_pair = (passages["A"], passages["B"])
    exploratory_pair = (passages["A"], passages["C"])
    accepted = _calibrated_pair(
        accepted_pair,
        [
            "m7_lexical_rrf",
            "semantic_domain_overlap",
            "grammar_sequence_alignment",
            "participant_frame_progression",
        ],
    )
    exploratory = _calibrated_pair(exploratory_pair, ["m7_lexical_rrf"])
    all_evidence = (*accepted, *exploratory)

    candidates = build_final_candidates(
        all_evidence,
        passages,
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(all_evidence),
    )
    by_id = {candidate.candidate_pair_id: candidate for candidate in candidates}

    tier_a = by_id[candidate_pair_id("A", "B")]
    tier_b = by_id[candidate_pair_id("A", "C")]
    assert tier_a.tier_a_eligible
    assert tier_a.tier_b_rank is None
    assert set(tier_a.families) >= {"lexical", "semantic", "grammar_syntax"}
    assert not tier_b.tier_a_eligible
    assert tier_b.tier_b_rank == 1
    assert tier_b.output_label == "exploratory_not_statistically_accepted"
    assert "fewer_than_two_independent_original_language_families" in (
        tier_b.tier_a_exclusion_reasons
    )


def test_known_pair_is_retained_but_never_tier_a() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "EXO 1:1", book="EXO")
    evidence = _calibrated_pair(
        (left, right),
        [
            "m7_lexical_rrf",
            "semantic_domain_overlap",
            "grammar_sequence_alignment",
            "participant_frame_progression",
        ],
    )
    knownness = KnownnessIndex(
        [
            KnownRelationship(
                relationship_id="known",
                source_passage_id="B",
                target_passage_id="A",
                source_name="fixture",
                mapping_quality="verified",
            )
        ]
    )

    candidate = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=knownness,
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(evidence),
    )[0]

    assert not candidate.tier_a_eligible
    assert candidate.knownness_status == "known_reverse"
    assert candidate.output_label == "retained_excluded"
    assert "known_relationship_either_direction" in candidate.tier_a_exclusion_reasons


def test_english_ablation_cannot_supply_missing_independence() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "EXO 1:1", book="EXO")
    raw = (
        _raw((left, right), "semantic_domain_overlap", 1.0),
        _raw((left, right), "multilingual_e5_english_gloss", 1.0, english=True),
    )
    detector_ids = [item.detector_id for item in raw]
    evidence = calibrate_detector_evidence(
        raw,
        config=CONFIG,
        reference_scores={item: [index / 20 for index in range(20)] for item in detector_ids},
        null_scores={item: [0.1] * 20 for item in detector_ids},
    )

    candidate = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(evidence),
    )[0]

    assert candidate.contains_english_derived_evidence
    assert not candidate.tier_a_eligible
    assert "semantic" in candidate.families
    assert len(candidate.original_language_independence_groups) == 1
    assert "fewer_than_two_independent_original_language_families" in (
        candidate.tier_a_exclusion_reasons
    )


def test_english_ablation_recomputes_p_q_and_fdr_without_changing_full_results() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "EXO 1:1", book="EXO")
    detector_ids = [
        "m7_lexical_rrf",
        "semantic_domain_overlap",
        "multilingual_e5_original_language",
        "grammar_sequence_alignment",
        "participant_frame_progression",
        "multilingual_e5_english_gloss",
    ]
    raw = tuple(
        _raw(
            (left, right),
            detector_id,
            1.0,
            english=detector_id == "multilingual_e5_english_gloss",
        ).model_copy(
            update={
                "english_ablation_raw_score": (
                    0.0 if detector_id == "multilingual_e5_english_gloss" else None
                )
            }
        )
        for detector_id in detector_ids
    )
    evidence = calibrate_detector_evidence(
        raw,
        config=CONFIG,
        reference_scores={item: [index / 20 for index in range(20)] for item in detector_ids},
        null_scores={item: [0.1] * 20 for item in detector_ids},
    )
    full_null = _null_calibration(evidence)
    good_ablation = _null_calibration(evidence, scope="remove_all_english", remove_all_english=True)
    good = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=full_null,
        english_ablation_null_calibration_by_pair=good_ablation,
    )[0]

    assert good.tier_a_eligible
    assert good.english_ablation_survives
    assert good.score_without_english < good.ensemble_score
    assert good.english_ablation_empirical_p_value < 0.05

    pair_id = candidate_pair_id("A", "B")
    good_row = good_ablation[pair_id]
    bad_row = EnsembleNullCalibrationRow(
        candidate_pair_id=pair_id,
        calibration_scope="remove_all_english",
        stratum=good_row.stratum,
        stratum_size=1,
        observed_score=good_row.observed_score,
        null_exceedance_count=20,
        effective_null_cell_count=20,
        empirical_p_value=1.0,
        null_discovery_count_sum=20,
        mean_null_discovery_count=1.0,
        observed_discovery_count=1,
        raw_empirical_fdr=1.0,
        empirical_fdr=1.0,
        minimum_attainable_p_value=1 / 21,
        minimum_effective_null_draws=20,
        stratum_sufficient_for_bh=True,
        hypothesis_count=1,
        iterations=20,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        null_method=CONFIG.ensemble.final_null_method,
    )
    failed = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=full_null,
        english_ablation_null_calibration_by_pair={pair_id: bad_row},
    )[0]

    assert failed.ensemble_score == good.ensemble_score
    assert failed.empirical_p_value == good.empirical_p_value
    assert failed.bh_q_value == good.bh_q_value
    assert failed.empirical_fdr == good.empirical_fdr
    assert failed.score_without_english >= CONFIG.ensemble.minimum_tier_a_ensemble_score
    assert failed.english_ablation_empirical_p_value == 1.0
    assert failed.english_ablation_bh_q_value == 1.0
    assert failed.english_ablation_empirical_fdr == 1.0
    assert not failed.english_ablation_survives
    assert not failed.tier_a_eligible
    assert "remove_all_english_ablation_failed" in failed.tier_a_exclusion_reasons


def test_source_quality_and_m7_knownness_are_conservatively_retained() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "GEN 1:1", book="GEN")
    evidence = tuple(
        row.model_copy(
            update={
                "source_quality": QualityFlags(
                    disputed_passage=False,
                    reference_gap=False,
                    ketiv_uncertainty=False,
                    formulaic_language=False,
                    overlapping_passages=False,
                    unresolved_data_error=False,
                    invalid_trace=False,
                    local_context=True,
                ),
                "source_knownness_status": "known_m7_snapshot",
            }
        )
        for row in _calibrated_pair(
            (left, right),
            [
                "m7_lexical_rrf",
                "semantic_domain_overlap",
                "grammar_sequence_alignment",
                "participant_frame_progression",
            ],
        )
    )
    candidate = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(evidence),
    )[0]

    assert candidate.knownness_status == "known_m7_snapshot"
    assert candidate.quality.local_context
    assert candidate.quality.same_reference_sensitivity
    assert not candidate.tier_a_eligible
    assert candidate.tier_b_rank is None
    assert "known_relationship_either_direction" in candidate.tier_a_exclusion_reasons
    assert "basic_data_quality_exclusion" in candidate.tier_a_exclusion_reasons


def test_quality_flags_exclude_tier_a_without_removing_exploratory_record() -> None:
    left = _passage("A", "GEN 1:1", book="GEN", disputed=True)
    right = _passage("B", "EXO 1:1", book="EXO")
    evidence = _calibrated_pair(
        (left, right),
        [
            "m7_lexical_rrf",
            "semantic_domain_overlap",
            "grammar_sequence_alignment",
            "participant_frame_progression",
        ],
    )

    candidate = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(evidence),
    )[0]

    assert not candidate.tier_a_eligible
    assert candidate.tier_b_rank == 1
    assert "quality_disputed_passage" in candidate.tier_a_exclusion_reasons


def test_final_validation_reconciles_candidate_evidence_and_bh_values() -> None:
    left = _passage("A", "GEN 1:1", book="GEN")
    right = _passage("B", "EXO 1:1", book="EXO")
    evidence = _calibrated_pair(
        (left, right),
        [
            "m7_lexical_rrf",
            "semantic_domain_overlap",
            "grammar_sequence_alignment",
            "participant_frame_progression",
        ],
    )
    candidate = build_final_candidates(
        evidence,
        {"A": left, "B": right},
        knownness=KnownnessIndex([]),
        config=CONFIG,
        null_calibration_by_pair=_null_calibration(evidence),
    )[0]

    report = validate_final_discovery(evidence, [candidate], config=CONFIG)
    assert report.passed
    corrupted = candidate.model_copy(update={"bh_q_value": 0.9})
    failed = validate_final_discovery(evidence, [corrupted], config=CONFIG)
    assert not failed.passed
    assert {finding.code for finding in failed.findings} >= {"bh-reconciliation"}
