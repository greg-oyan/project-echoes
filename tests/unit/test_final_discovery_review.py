from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

import echoes.final_discovery.review as review_module
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.models import (
    EvidenceRow,
    FinalCandidate,
    PassageRecord,
    QualityFlags,
    ReviewClassification,
)
from echoes.final_discovery.nulls import (
    EnsembleNullThresholdReport,
    build_ensemble_null_threshold_report,
    build_ensemble_null_threshold_summary,
)
from echoes.final_discovery.review import (
    ENGLISH_SUPPLEMENTAL_LABEL,
    OUTPUT_J_PLACEHOLDER,
    REVIEW_COLUMNS,
    STREAMING_REVIEW_SCHEMA_VERSION,
    ReviewTraceabilityError,
    build_review_records,
    render_candidate_dossier,
    validate_review_traceability,
    write_review_bundle,
    write_review_bundle_streaming,
)
from echoes.final_discovery.storage import write_jsonl_atomic

CONFIG = load_final_discovery_config()


def _threshold_report() -> EnsembleNullThresholdReport:
    full = build_ensemble_null_threshold_summary(
        scope="full",
        threshold=CONFIG.ensemble.minimum_tier_a_ensemble_score,
        observed_count=2,
        null_counts=(0, 2, 0),
        hypothesis_count=3,
    )
    ablated = build_ensemble_null_threshold_summary(
        scope="remove_all_english",
        threshold=CONFIG.ensemble.minimum_tier_a_ensemble_score,
        observed_count=1,
        null_counts=(0, 1, 0),
        hypothesis_count=3,
    )
    return build_ensemble_null_threshold_report(
        (full, ablated),
        config=CONFIG,
        hypothesis_count=3,
        iterations=3,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
    )


def _evidence(
    evidence_id: str,
    candidate_pair_id: str,
    passage_a_id: str,
    passage_b_id: str,
    detector_id: str,
    family: str,
    independence_group: str,
    *,
    english: bool = False,
    counts_for_independence: bool = True,
) -> EvidenceRow:
    return EvidenceRow.model_validate(
        {
            "evidence_id": evidence_id,
            "candidate_pair_id": candidate_pair_id,
            "passage_a_id": passage_a_id,
            "passage_b_id": passage_b_id,
            "detector_id": detector_id,
            "family": family,
            "independence_group": independence_group,
            "raw_score": 2.5,
            "normalized_score": 0.8,
            "normalization_method": "frozen-empirical-cdf-v1",
            "empirical_p_value": 0.01,
            "null_method": "within-book-plus-frequency-preserving-v1",
            "contains_english_derived_evidence": english,
            "original_language_evidence_remains": True,
            "counts_for_independence": counts_for_independence,
            "trace_json": json.dumps(
                {"candidate": candidate_pair_id, "matched_tokens": ["alpha", "beta"]},
                sort_keys=True,
            ),
            "source_artifact_id": "fixture-source-v1",
            "source_artifact_sha256": "a" * 64,
        }
    )


def _quality(*, formulaic: bool = False) -> QualityFlags:
    return QualityFlags(
        disputed_passage=False,
        reference_gap=False,
        ketiv_uncertainty=False,
        formulaic_language=formulaic,
        overlapping_passages=False,
        unresolved_data_error=False,
        invalid_trace=False,
    )


def _fixture_rows() -> tuple[tuple[FinalCandidate, ...], tuple[EvidenceRow, ...]]:
    evidence = (
        _evidence(
            "e-a-semantic",
            "candidate-a",
            "a-1",
            "b-1",
            "semantic-embedding",
            "semantic",
            "semantic-original",
            english=True,
        ),
        _evidence(
            "e-a-syntax",
            "candidate-a",
            "a-1",
            "b-1",
            "predicate-argument",
            "grammar_syntax",
            "grammar-syntax",
        ),
        _evidence(
            "e-b-anomaly",
            "candidate-b",
            "a-2",
            "b-2",
            "neighbor-anomaly",
            "anomaly",
            "anomaly-diagnostic",
            counts_for_independence=False,
        ),
        _evidence(
            "e-c-structure",
            "candidate-c",
            "a-3",
            "b-3",
            "event-sequence",
            "structure_narrative",
            "structure-narrative",
        ),
    )
    candidates = (
        FinalCandidate(
            candidate_pair_id="candidate-a",
            passage_a_id="a-1",
            passage_b_id="b-1",
            passage_a_reference="Genesis 1:1",
            passage_b_reference="John 1:1",
            ensemble_score=0.91,
            empirical_p_value=0.002,
            bh_q_value=0.01,
            empirical_fdr=0.03,
            knownness_status="unknown",
            known_relationship_ids=(),
            quality=_quality(),
            evidence_ids=("e-a-semantic", "e-a-syntax"),
            detector_ids=("predicate-argument", "semantic-embedding"),
            families=("grammar_syntax", "semantic"),
            qualifying_independence_groups=("grammar-syntax", "semantic-original"),
            original_language_independence_groups=("grammar-syntax", "semantic-original"),
            contains_english_derived_evidence=True,
            score_without_english=0.86,
            english_ablation_empirical_p_value=0.003,
            english_ablation_bh_q_value=0.02,
            english_ablation_empirical_fdr=0.04,
            english_ablation_survives=True,
            tier_a_eligible=True,
            tier_a_exclusion_reasons=(),
            tier_b_rank=None,
            output_label="statistically_eligible",
        ),
        FinalCandidate(
            candidate_pair_id="candidate-b",
            passage_a_id="a-2",
            passage_b_id="b-2",
            passage_a_reference="Exodus 2:1",
            passage_b_reference="Luke 2:1",
            ensemble_score=0.72,
            empirical_p_value=0.08,
            bh_q_value=0.12,
            empirical_fdr=0.2,
            knownness_status="unknown",
            known_relationship_ids=(),
            quality=_quality(),
            evidence_ids=("e-b-anomaly",),
            detector_ids=("neighbor-anomaly",),
            families=("anomaly",),
            qualifying_independence_groups=(),
            original_language_independence_groups=(),
            contains_english_derived_evidence=False,
            score_without_english=0.72,
            english_ablation_empirical_p_value=0.08,
            english_ablation_bh_q_value=0.12,
            english_ablation_empirical_fdr=0.2,
            english_ablation_survives=True,
            tier_a_eligible=False,
            tier_a_exclusion_reasons=("fewer_than_two_independent_original_language_families",),
            tier_b_rank=1,
            output_label="exploratory_not_statistically_accepted",
        ),
        FinalCandidate(
            candidate_pair_id="candidate-c",
            passage_a_id="a-3",
            passage_b_id="b-3",
            passage_a_reference="Isaiah 1:1",
            passage_b_reference="Romans 1:1",
            ensemble_score=0.4,
            empirical_p_value=0.4,
            bh_q_value=0.5,
            empirical_fdr=0.6,
            knownness_status="known_forward",
            known_relationship_ids=("known-relationship-1",),
            quality=_quality(formulaic=True),
            evidence_ids=("e-c-structure",),
            detector_ids=("event-sequence",),
            families=("structure_narrative",),
            qualifying_independence_groups=("structure-narrative",),
            original_language_independence_groups=("structure-narrative",),
            contains_english_derived_evidence=False,
            score_without_english=0.4,
            english_ablation_empirical_p_value=0.4,
            english_ablation_bh_q_value=0.5,
            english_ablation_empirical_fdr=0.6,
            english_ablation_survives=True,
            tier_a_eligible=False,
            tier_a_exclusion_reasons=("known_relationship_either_direction",),
            tier_b_rank=None,
            output_label="retained_excluded",
        ),
    )
    return candidates, evidence


def _passages() -> dict[str, PassageRecord]:
    references = {
        "a-1": ("Genesis 1:1", "GEN", "hebrew"),
        "b-1": ("John 1:1", "JHN", "greek"),
        "a-2": ("Exodus 2:1", "EXO", "hebrew"),
        "b-2": ("Luke 2:1", "LUK", "greek"),
        "a-3": ("Isaiah 1:1", "ISA", "hebrew"),
        "b-3": ("Romans 1:1", "ROM", "greek"),
    }
    return {
        passage_id: PassageRecord(
            passage_id=passage_id,
            reference=reference,
            corpus=corpus,  # type: ignore[arg-type]
            book=book,
            genre="fixture",
            analysis_profile="edition_complete",
            analysis_reading="qere" if corpus == "hebrew" else "source",
            granularity="verse",
            token_count=1,
            token_ids=(f"{passage_id}-token-1",),
            original_text=f"original {passage_id}",
            normalized_text=f"normalized {passage_id}",
            lemma_sequence=("lemma",),
            root_sequence=("root",),
            pos_sequence=("noun",),
            morphology_sequence=("singular",),
            semantic_domains=("fixture",),
            entities=("entity",),
            participants=("participant",),
            frames=("event",),
            english_gloss=f"gloss {passage_id}",
            source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
        )
        for passage_id, (reference, book, corpus) in references.items()
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_review_bundle_is_deterministic_traceable_and_retains_rejections(
    tmp_path: Path,
) -> None:
    candidates, evidence = _fixture_rows()
    initial = build_review_records(candidates, evidence, passages=_passages())
    rejected = next(row for row in initial if row.candidate_pair_id == "candidate-c").model_copy(
        update={
            "reviewer_classification": ReviewClassification.FORMAL_COINCIDENCE,
            "rejection_category": "formulaic_language_effect",
            "reviewer_notes": "Retained for the false-positive taxonomy.",
        }
    )

    first = write_review_bundle(
        tmp_path / "review-one",
        candidates,
        evidence,
        passages=_passages(),
        prior_reviews=(rejected,),
    )
    second = write_review_bundle(
        tmp_path / "review-two",
        candidates,
        evidence,
        passages=_passages(),
        prior_reviews=(rejected,),
    )

    assert _tree_bytes(first.output_directory) == _tree_bytes(second.output_directory)
    assert first.tier_a_count == 1
    assert first.tier_b_count == 1
    assert first.retained_excluded_count == 1

    with first.csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert tuple(csv_rows[0]) == REVIEW_COLUMNS
    assert [row["candidate_pair_id"] for row in csv_rows] == [
        "candidate-a",
        "candidate-b",
        "candidate-c",
    ]
    assert csv_rows[0]["output_label"] == "statistically_eligible"
    assert csv_rows[0]["tier_b_rank"] == ""
    assert csv_rows[1]["output_label"] == "exploratory_not_statistically_accepted"
    assert csv_rows[1]["tier_b_rank"] == "1"
    assert csv_rows[2]["rejection_category"] == "formulaic_language_effect"
    assert csv_rows[2]["reviewer_notes"] == "Retained for the false-positive taxonomy."
    supplemental = json.loads(csv_rows[0]["supplemental_gloss_evidence_json"])
    assert supplemental["label"] == ENGLISH_SUPPLEMENTAL_LABEL
    assert not supplemental["counts_as_an_independent_original_language_family"]
    assert supplemental["evidence"][0]["source_artifact_sha256"] == "a" * 64
    parquet = pl.read_parquet(first.parquet_path)
    assert tuple(parquet.columns) == REVIEW_COLUMNS
    assert parquet.height == 3
    assert (
        parquet.filter(pl.col("candidate_pair_id") == "candidate-c").item(
            0, "reviewer_classification"
        )
        == ReviewClassification.FORMAL_COINCIDENCE.value
    )

    tier_a_dossier = first.dossier_paths[0].read_text(encoding="utf-8")
    assert ENGLISH_SUPPLEMENTAL_LABEL in tier_a_dossier
    assert "Tier A — statistically eligible" in tier_a_dossier
    assert len(first.dossier_paths) == 2
    assert "original a-1" in tier_a_dossier
    assert "`a-1-token-1`" in tier_a_dossier
    assert "`b-1-token-1`" in tier_a_dossier
    assert ENGLISH_SUPPLEMENTAL_LABEL in tier_a_dossier

    output_j = first.output_j_path.read_text(encoding="utf-8")
    assert "Tier B — exploratory top 100, not statistically accepted" in output_j
    assert "formulaic_language_effect" not in output_j
    assert "Human-review dispositions — bounded selection only" in output_j
    assert OUTPUT_J_PLACEHOLDER in output_j
    assert "## Common-vocabulary effects" in output_j

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["candidate_count"] == 3
    assert manifest["tier_a_count"] == 1
    assert manifest["tier_b_count"] == 1
    assert manifest["candidate_payload_sha256"]
    for artifact in manifest["artifacts"]:
        path = first.output_directory / artifact["relative_path"]
        assert path.stat().st_size == artifact["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_output_j_populates_both_frozen_null_scopes_without_rerunning_nulls(
    tmp_path: Path,
) -> None:
    candidates, evidence = _fixture_rows()
    artifacts = write_review_bundle(
        tmp_path / "review-with-thresholds",
        candidates,
        evidence,
        passages=_passages(),
        threshold_report=_threshold_report(),
    )

    output_j = artifacts.output_j_path.read_text(encoding="utf-8")
    assert "| 0.65 | `full` | 2 | 0.75 | [0, 1.9] |" in output_j
    assert "| 0.65 | `remove_all_english` | 1 | 0.5 | [0, 0.95] |" in output_j
    assert "the table below is populated without rerunning either null scope" in output_j
    threshold_section = output_j.split("## Frozen thresholds and expected noise", maxsplit=1)[1]
    threshold_section = threshold_section.split("## Tier A", maxsplit=1)[0]
    assert OUTPUT_J_PLACEHOLDER not in threshold_section


def test_single_dossier_preserves_global_tier_b_rank_without_requiring_full_set() -> None:
    candidates, evidence = _fixture_rows()
    candidate = candidates[1].model_copy(update={"tier_b_rank": 7})
    original_record = build_review_records(candidates, evidence, passages=_passages())[1]
    record = original_record.model_copy(update={"tier_b_rank": 7})
    rows = tuple(row for row in evidence if row.candidate_pair_id == candidate.candidate_pair_id)

    dossier = render_candidate_dossier(candidate, rows, record, passages=_passages())

    assert "Tier B rank 7" in dossier


def test_m7_dossier_requires_bounded_exact_shared_evidence_hydration() -> None:
    candidates, evidence = _fixture_rows()
    candidate = candidates[1].model_copy(
        update={"detector_ids": ("m7_lexical_rrf",), "families": ("lexical",)}
    )
    compact_trace = {
        "m7_candidate_pair_id": "M7PAIR",
        "m7_shared_evidence_count": 1,
        "m7_shared_evidence_ids": ["M7DETAIL"],
        "m7_shared_evidence_hydrated": False,
    }
    compact = evidence[2].model_copy(
        update={
            "detector_id": "m7_lexical_rrf",
            "family": "lexical",
            "trace_json": json.dumps(compact_trace, sort_keys=True),
        }
    )
    record = build_review_records((candidate,), (compact,), passages=_passages())[0]

    with pytest.raises(ReviewTraceabilityError, match="hydrated before dossier export"):
        render_candidate_dossier(candidate, (compact,), record, passages=_passages())

    hydrated_trace = {
        **compact_trace,
        "m7_shared_evidence_hydrated": True,
        "m7_shared_evidence": [{"candidate_pair_id": "M7PAIR", "evidence_id": "M7DETAIL"}],
    }
    hydrated = compact.model_copy(update={"trace_json": json.dumps(hydrated_trace, sort_keys=True)})
    hydrated_record = build_review_records((candidate,), (hydrated,), passages=_passages())[0]

    dossier = render_candidate_dossier(
        candidate, (hydrated,), hydrated_record, passages=_passages()
    )
    assert '"m7_shared_evidence_hydrated":true' in dossier


def test_traceability_rejects_missing_orphan_invalid_and_stale_evidence() -> None:
    candidates, evidence = _fixture_rows()

    with pytest.raises(ReviewTraceabilityError, match="missing evidence"):
        validate_review_traceability(candidates, evidence[:-1], passages=_passages())

    orphan = evidence[0].model_copy(update={"evidence_id": "orphan-evidence"})
    with pytest.raises(ReviewTraceabilityError, match="orphan evidence IDs"):
        validate_review_traceability(candidates, (*evidence, orphan), passages=_passages())

    invalid_trace = evidence[0].model_copy(update={"trace_json": "[]"})
    with pytest.raises(ReviewTraceabilityError, match="must be a JSON object"):
        validate_review_traceability(
            candidates, (invalid_trace, *evidence[1:]), passages=_passages()
        )

    stale_candidate = candidates[0].model_copy(update={"detector_ids": ("stale-detector",)})
    with pytest.raises(ReviewTraceabilityError, match="detector IDs"):
        validate_review_traceability(
            (stale_candidate, *candidates[1:]), evidence, passages=_passages()
        )

    records = build_review_records(candidates, evidence, passages=_passages())
    stale_record = records[0].model_copy(update={"detector_contributions_json": "{}"})
    with pytest.raises(ReviewTraceabilityError, match="stale traceability field"):
        validate_review_traceability(
            candidates,
            evidence,
            (stale_record, *records[1:]),
            passages=_passages(),
        )


def test_review_bundle_refuses_implicit_overwrite_and_preserves_target_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates, evidence = _fixture_rows()
    target = tmp_path / "review"
    write_review_bundle(target, candidates, evidence, passages=_passages())
    original = _tree_bytes(target)

    with pytest.raises(FileExistsError):
        write_review_bundle(target, candidates, evidence, passages=_passages())
    assert _tree_bytes(target) == original

    def fail_parquet(path: Path, records: object) -> None:
        del path, records
        raise OSError("simulated parquet failure")

    monkeypatch.setattr(review_module, "_write_parquet_atomically", fail_parquet)
    with pytest.raises(OSError, match="simulated parquet failure"):
        write_review_bundle(target, candidates, evidence, passages=_passages(), overwrite=True)
    assert _tree_bytes(target) == original
    assert not tuple(tmp_path.glob(".review.writing-*"))


def test_prior_review_cannot_silently_move_to_changed_candidate_identity() -> None:
    candidates, evidence = _fixture_rows()
    prior = build_review_records(candidates, evidence, passages=_passages())[0]
    changed = candidates[0].model_copy(update={"ensemble_score": 0.905})

    with pytest.raises(ReviewTraceabilityError, match="stale identity fields"):
        build_review_records(
            (changed, *candidates[1:]),
            evidence,
            passages=_passages(),
            prior_reviews=(prior,),
        )


def test_streaming_review_is_deterministic_and_semantically_matches_legacy_bundle(
    tmp_path: Path,
) -> None:
    candidates, evidence = _fixture_rows()
    initial = build_review_records(candidates, evidence, passages=_passages())
    rejected = next(row for row in initial if row.candidate_pair_id == "candidate-c").model_copy(
        update={
            "reviewer_classification": ReviewClassification.FORMAL_COINCIDENCE,
            "rejection_category": "formulaic_language_effect",
            "reviewer_notes": "Retained for the false-positive taxonomy.",
        }
    )
    evidence_by_pair = {
        candidate.candidate_pair_id: tuple(
            row for row in evidence if row.candidate_pair_id == candidate.candidate_pair_id
        )
        for candidate in candidates
    }
    prepared: list[str] = []

    def lookup(candidate: FinalCandidate) -> tuple[EvidenceRow, ...]:
        return evidence_by_pair[candidate.candidate_pair_id]

    def prepare(
        candidate: FinalCandidate, rows: tuple[EvidenceRow, ...]
    ) -> tuple[EvidenceRow, ...]:
        prepared.append(candidate.candidate_pair_id)
        return rows

    _, candidate_ledger_sha256 = write_jsonl_atomic(
        tmp_path / "candidates.jsonl",
        candidates,
        sort_key=None,
    )

    legacy = write_review_bundle(
        tmp_path / "legacy",
        candidates,
        evidence,
        passages=_passages(),
        prior_reviews=(rejected,),
    )
    first = write_review_bundle_streaming(
        tmp_path / "stream-one",
        iter(candidates),
        evidence_for_candidate=lookup,
        passages=_passages(),
        expected_candidate_count=3,
        expected_evidence_count=4,
        tier_b_size=100,
        maximum_evidence_rows_per_candidate=2,
        expected_candidate_ledger_sha256=candidate_ledger_sha256,
        prepare_selected_evidence=prepare,
        prior_review_for_candidate=lambda candidate: (
            rejected if candidate.candidate_pair_id == "candidate-c" else None
        ),
        parquet_row_group_size=2,
    )
    prepared_after_first = tuple(prepared)
    prepared.clear()
    second = write_review_bundle_streaming(
        tmp_path / "stream-two",
        candidates,
        evidence_for_candidate=lookup,
        passages=_passages(),
        expected_candidate_count=3,
        expected_evidence_count=4,
        tier_b_size=100,
        maximum_evidence_rows_per_candidate=2,
        expected_candidate_ledger_sha256=first.summary.candidate_stream_sha256,
        prepare_selected_evidence=prepare,
        prior_review_for_candidate=lambda candidate: (
            rejected if candidate.candidate_pair_id == "candidate-c" else None
        ),
        parquet_row_group_size=2,
    )

    assert prepared_after_first == ("candidate-a", "candidate-b")
    assert tuple(prepared) == prepared_after_first
    assert _tree_bytes(first.output_directory) == _tree_bytes(second.output_directory)
    assert first.csv_path.read_bytes() == legacy.csv_path.read_bytes()
    assert first.output_j_path.read_bytes() == legacy.output_j_path.read_bytes()
    assert _tree_bytes(first.dossier_directory) == _tree_bytes(legacy.output_directory / "dossiers")
    assert pl.read_parquet(first.parquet_path).equals(pl.read_parquet(legacy.parquet_path))
    assert first.summary.candidate_count == 3
    assert first.summary.evidence_count == 4
    assert first.summary.tier_a_count == 1
    assert first.summary.tier_b_count == 1
    assert first.summary.tier_a_dossier_count == 1
    assert first.summary.tier_b_dossier_count == 1
    assert first.summary.actual_reviewed_count == 0
    assert first.summary.retained_excluded_count == 1

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == STREAMING_REVIEW_SCHEMA_VERSION
    assert manifest["full_identity_lists_omitted"] is True
    assert manifest["identity_uniqueness_method"] == "sqlite_primary_key_exact"
    assert manifest["candidate_stream_sha256"] == first.summary.candidate_stream_sha256
    assert manifest["evidence_stream_sha256"] == first.summary.evidence_stream_sha256
    assert manifest["review_stream_sha256"] == first.summary.review_stream_sha256
    for artifact in manifest["artifacts"]:
        path = first.output_directory / artifact["relative_path"]
        assert path.stat().st_size == artifact["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_streaming_review_fails_closed_on_order_rank_and_population_errors(
    tmp_path: Path,
) -> None:
    candidates, evidence = _fixture_rows()
    evidence_by_pair = {
        candidate.candidate_pair_id: tuple(
            row for row in evidence if row.candidate_pair_id == candidate.candidate_pair_id
        )
        for candidate in candidates
    }

    def lookup(candidate: FinalCandidate) -> tuple[EvidenceRow, ...]:
        return evidence_by_pair[candidate.candidate_pair_id]

    _, candidate_ledger_sha256 = write_jsonl_atomic(
        tmp_path / "candidates.jsonl",
        candidates,
        sort_key=None,
    )

    target = tmp_path / "review"
    write_review_bundle_streaming(
        target,
        candidates,
        evidence_for_candidate=lookup,
        passages=_passages(),
        expected_candidate_count=3,
        expected_evidence_count=4,
        tier_b_size=100,
        maximum_evidence_rows_per_candidate=2,
        expected_candidate_ledger_sha256=candidate_ledger_sha256,
    )
    original = _tree_bytes(target)

    with pytest.raises(ReviewTraceabilityError, match="strictly ordered"):
        write_review_bundle_streaming(
            target,
            (candidates[1], candidates[0], candidates[2]),
            evidence_for_candidate=lookup,
            passages=_passages(),
            expected_candidate_count=3,
            expected_evidence_count=4,
            tier_b_size=100,
            maximum_evidence_rows_per_candidate=2,
            expected_candidate_ledger_sha256=candidate_ledger_sha256,
            overwrite=True,
        )
    assert _tree_bytes(target) == original
    assert not tuple(tmp_path.glob(".review.writing-*"))

    stale_rank = candidates[1].model_copy(update={"tier_b_rank": 2})
    with pytest.raises(ReviewTraceabilityError, match="expected 1"):
        write_review_bundle_streaming(
            tmp_path / "stale-rank",
            (candidates[0], stale_rank, candidates[2]),
            evidence_for_candidate=lookup,
            passages=_passages(),
            expected_candidate_count=3,
            expected_evidence_count=4,
            tier_b_size=100,
            maximum_evidence_rows_per_candidate=2,
            expected_candidate_ledger_sha256=candidate_ledger_sha256,
        )

    with pytest.raises(ReviewTraceabilityError, match="evidence stream has 4 rows; expected 5"):
        write_review_bundle_streaming(
            tmp_path / "wrong-population",
            candidates,
            evidence_for_candidate=lookup,
            passages=_passages(),
            expected_candidate_count=3,
            expected_evidence_count=5,
            tier_b_size=100,
            maximum_evidence_rows_per_candidate=2,
            expected_candidate_ledger_sha256=candidate_ledger_sha256,
        )

    with pytest.raises(ReviewTraceabilityError, match="Stage-8 receipt"):
        write_review_bundle_streaming(
            tmp_path / "wrong-ledger-hash",
            candidates,
            evidence_for_candidate=lookup,
            passages=_passages(),
            expected_candidate_count=3,
            expected_evidence_count=4,
            tier_b_size=100,
            maximum_evidence_rows_per_candidate=2,
            expected_candidate_ledger_sha256="0" * 64,
        )


def test_streaming_review_caps_tier_a_outputs_and_hydration_but_retains_full_ledger(
    tmp_path: Path,
) -> None:
    fixture_candidates, fixture_evidence = _fixture_rows()
    tier_a_template = fixture_candidates[0]
    tier_a_evidence_templates = fixture_evidence[:2]
    candidates: list[FinalCandidate] = []
    evidence: list[EvidenceRow] = []
    passages = _passages()
    for index in range(101):
        candidate_id = f"tier-a-{index:03d}"
        passage_a_id = f"tier-a-{index:03d}-a"
        passage_b_id = f"tier-a-{index:03d}-b"
        passage_a_reference = f"Genesis 1:{index + 1}"
        passage_b_reference = f"John 1:{index + 1}"
        evidence_ids = (f"e-{candidate_id}-semantic", f"e-{candidate_id}-syntax")
        candidates.append(
            tier_a_template.model_copy(
                update={
                    "candidate_pair_id": candidate_id,
                    "passage_a_id": passage_a_id,
                    "passage_b_id": passage_b_id,
                    "passage_a_reference": passage_a_reference,
                    "passage_b_reference": passage_b_reference,
                    "ensemble_score": 0.99 - index / 1_000,
                    "evidence_ids": evidence_ids,
                }
            )
        )
        for template, evidence_id in zip(tier_a_evidence_templates, evidence_ids, strict=True):
            evidence.append(
                template.model_copy(
                    update={
                        "evidence_id": evidence_id,
                        "candidate_pair_id": candidate_id,
                        "passage_a_id": passage_a_id,
                        "passage_b_id": passage_b_id,
                    }
                )
            )
        passages[passage_a_id] = passages["a-1"].model_copy(
            update={
                "passage_id": passage_a_id,
                "reference": passage_a_reference,
                "token_ids": (f"{passage_a_id}-token-1",),
            }
        )
        passages[passage_b_id] = passages["b-1"].model_copy(
            update={
                "passage_id": passage_b_id,
                "reference": passage_b_reference,
                "token_ids": (f"{passage_b_id}-token-1",),
            }
        )

    tier_b = fixture_candidates[1].model_copy(update={"ensemble_score": 0.5})
    candidates.append(tier_b)
    evidence.append(fixture_evidence[2])
    evidence_by_pair = {
        candidate.candidate_pair_id: tuple(
            row for row in evidence if row.candidate_pair_id == candidate.candidate_pair_id
        )
        for candidate in candidates
    }
    prepared: list[str] = []

    _, candidate_ledger_sha256 = write_jsonl_atomic(
        tmp_path / "bounded-candidates.jsonl",
        candidates,
        sort_key=None,
    )
    artifacts = write_review_bundle_streaming(
        tmp_path / "bounded-review",
        iter(candidates),
        evidence_for_candidate=lambda candidate: evidence_by_pair[candidate.candidate_pair_id],
        passages=passages,
        expected_candidate_count=102,
        expected_evidence_count=203,
        tier_b_size=100,
        maximum_evidence_rows_per_candidate=2,
        expected_candidate_ledger_sha256=candidate_ledger_sha256,
        prepare_selected_evidence=lambda candidate, rows: (
            prepared.append(candidate.candidate_pair_id) or rows
        ),
        parquet_row_group_size=25,
    )

    assert artifacts.summary.candidate_count == 102
    assert artifacts.summary.tier_a_count == 101
    assert artifacts.summary.tier_a_dossier_count == 100
    assert artifacts.summary.tier_b_count == 1
    assert artifacts.summary.tier_b_dossier_count == 1
    assert artifacts.summary.actual_reviewed_count == 0
    assert len(tuple(artifacts.dossier_directory.glob("*.md"))) == 101
    assert prepared == [
        *(f"tier-a-{index:03d}" for index in range(100)),
        tier_b.candidate_pair_id,
    ]
    assert pl.scan_parquet(artifacts.parquet_path).select(pl.len()).collect().item() == 102

    output_j = artifacts.output_j_path.read_text(encoding="utf-8")
    assert "Tier A statistically eligible candidates in the complete ledger: **101**" in output_j
    assert "Tier A dossier/review-selection rows (first score-ranked, cap 100): **100**" in output_j
    assert "`tier-a-099`" in output_j
    assert "`tier-a-100`" not in output_j
    assert f"`{tier_b.candidate_pair_id}`" in output_j

    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert manifest["review_ledger_count"] == 102
    assert manifest["review_selection_count"] == 101
    assert manifest["tier_a_count"] == 101
    assert manifest["tier_a_dossier_count"] == 100
    assert manifest["tier_b_dossier_count"] == 1
    assert len(manifest["dossiers"]) == 101
    assert not any(
        path.name.startswith(".review-") for path in artifacts.output_directory.iterdir()
    )
