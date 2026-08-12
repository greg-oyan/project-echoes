"""Focused tests for reference-only final-discovery positive controls."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

import pytest

from echoes.benchmarks.positive_controls import (
    PositiveControlDataset,
    validate_positive_controls,
)
from echoes.corpus.greek_books import GREEK_BOOKS
from echoes.final_discovery.evaluation import evaluate_positive_controls
from echoes.final_discovery.features import candidate_pair_id
from echoes.final_discovery.models import PassageRecord, RawEvidence

SOURCE_HASH = "a" * 64
REFERENCE_RE = re.compile(
    r"^(?P<book>[1-3]?[A-Z]{2,3}) (?P<chapter>[1-9][0-9]*):"
    r"(?P<verse>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$"
)
GREEK_CODES = {book.code for book in GREEK_BOOKS}


def _expand(reference: str) -> tuple[str, ...]:
    match = REFERENCE_RE.fullmatch(reference)
    assert match is not None
    start = int(match.group("verse"))
    end = int(match.group("end") or start)
    return tuple(
        f"{match.group('book')} {match.group('chapter')}:{verse}" for verse in range(start, end + 1)
    )


def _passage(reference: str) -> PassageRecord:
    book = reference.split()[0]
    corpus: Literal["hebrew", "greek"] = "greek" if book in GREEK_CODES else "hebrew"
    passage_id = f"primary-{hashlib.sha256(reference.encode()).hexdigest()}"
    distinctive = reference.replace(" ", "_").replace(":", "_")
    return PassageRecord(
        passage_id=passage_id,
        reference=reference,
        corpus=corpus,
        book=book,
        genre="narrative",
        analysis_profile="edition_complete",
        analysis_reading="source" if corpus == "greek" else "qere",
        granularity="verse",
        token_count=3,
        original_text=f"RESTRICTED_SOURCE_TEXT {reference}",
        normalized_text=f"normalized {reference}",
        lemma_sequence=("shared", "lemma", distinctive),
        root_sequence=("shared", "root", distinctive),
        pos_sequence=("noun", "verb", "noun"),
        morphology_sequence=("m1", "m2", "m3"),
        semantic_domains=("event", "person", distinctive),
        entities=(None, "person", None),
        participants=("agent", "patient", "agent"),
        frames=("event", "participant", distinctive),
        english_gloss="supplemental gloss",
        source_digest=hashlib.sha256(f"source:{reference}".encode()).hexdigest(),
    )


@pytest.fixture(scope="module")
def dataset() -> PositiveControlDataset:
    return validate_positive_controls(Path("data/benchmarks/positive_controls.yaml"))


@pytest.fixture(scope="module")
def passages(dataset: PositiveControlDataset) -> tuple[PassageRecord, ...]:
    references = {
        value
        for row in dataset.rows
        for reference in (row.reference_a, row.reference_b)
        for value in _expand(reference)
    }
    references.update({"EXO 1:1", "LEV 1:1", "JHN 1:1", "ACT 1:1"})
    return tuple(_passage(reference) for reference in sorted(references))


def test_ranges_map_to_primary_verse_ids_and_all_rows_remain_outside_discovery(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    report = evaluate_positive_controls(dataset, passages, (), seed=9101)

    assert report.row_count == 24
    assert report.mapped_control_count == 24
    ranged = next(row for row in report.rows if row.reference_b == "MRK 10:7-8")
    assert ranged.expanded_references_b == ("MRK 10:7", "MRK 10:8")
    by_reference = {passage.reference: passage.passage_id for passage in passages}
    assert ranged.mapped_passage_ids_b == (
        by_reference["MRK 10:7"],
        by_reference["MRK 10:8"],
    )
    assert len(ranged.positive_pairs) == 2
    assert all(row.benchmark_only for row in report.rows)
    assert not any(row.eligible_for_candidate_generation for row in report.rows)
    serialized = report.model_dump_json()
    assert "RESTRICTED_SOURCE_TEXT" not in serialized
    assert '"tier_a"' not in serialized
    assert '"tier_b"' not in serialized
    assert '"output_label"' not in serialized


def test_leakage_splits_are_preserved_in_rows_and_summaries(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    report = evaluate_positive_controls(dataset, passages, (), seed=9101)
    expected_by_control = {row.control_id: row.split for row in dataset.rows}
    observed_group_splits: dict[str, set[str]] = defaultdict(set)
    for row in report.rows:
        assert row.split == expected_by_control[row.control_id]
        observed_group_splits[row.leakage_group_id].add(row.split)
    assert all(len(splits) == 1 for splits in observed_group_splits.values())

    counts = Counter(row.split for row in report.rows)
    random_summaries = {
        summary.split: summary
        for summary in report.summaries
        if summary.method_kind == "baseline" and summary.method_id == "deterministic_random"
    }
    assert random_summaries["train"].control_count == counts["train"] == 15
    assert random_summaries["development"].control_count == counts["development"] == 3
    assert random_summaries["test"].control_count == counts["test"] == 6
    assert random_summaries["all"].control_count == 24


def test_random_baseline_and_negative_selection_are_seed_deterministic(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    first = evaluate_positive_controls(dataset, passages, (), seed=9101)
    repeated = evaluate_positive_controls(dataset, passages, (), seed=9101)
    changed = evaluate_positive_controls(dataset, passages, (), seed=9102)

    assert first.model_dump(mode="json") == repeated.model_dump(mode="json")
    first_random = tuple(
        next(item for item in row.baseline_results if item.method_id == "deterministic_random")
        for row in first.rows
    )
    changed_random = tuple(
        next(item for item in row.baseline_results if item.method_id == "deterministic_random")
        for row in changed.rows
    )
    assert first_random != changed_random
    assert first.rows[0].matched_negative_pair is not None
    assert changed.rows[0].matched_negative_pair is not None
    assert (
        first.rows[0].matched_negative_pair.selection_sha256
        != changed.rows[0].matched_negative_pair.selection_sha256
    )


def test_wholly_absent_m7_is_explicit_and_counts_as_no_recovery(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    report = evaluate_positive_controls(
        dataset,
        passages,
        (),
        seed=9101,
        detector_families={"m7_lexical_rrf": "lexical"},
    )

    assert report.detector_inventory[0].detector_id == "m7_lexical_rrf"
    assert report.detector_inventory[0].retained_anywhere is False
    for row in report.rows:
        baseline = next(item for item in row.baseline_results if item.method_id == "m7_lexical_rrf")
        assert baseline.available is False
        assert baseline.recovered is False
        assert baseline.unavailable_reason == ("m7_lexical_rrf_not_present_in_retained_evidence")
    all_summary = next(
        item
        for item in report.summaries
        if item.method_kind == "baseline"
        and item.method_id == "m7_lexical_rrf"
        and item.split == "all"
    )
    assert all_summary.mapped_control_count == 24
    assert all_summary.available_control_count == 0
    assert all_summary.recovered_control_count == 0


def test_retained_detector_and_family_recovery_are_summarized(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    initial = evaluate_positive_controls(dataset, passages, (), seed=9101)
    benchmark_row = initial.rows[0]
    pair = benchmark_row.positive_pairs[0]
    raw = RawEvidence(
        candidate_pair_id=candidate_pair_id(pair.passage_a_id, pair.passage_b_id),
        passage_a_id=pair.passage_a_id,
        passage_b_id=pair.passage_b_id,
        detector_id="semantic_domain_overlap",
        family="semantic",
        independence_group="semantic_annotations",
        raw_score=0.9,
        contains_english_derived_evidence=False,
        original_language_evidence_remains=True,
        counts_for_independence=True,
        trace_json='{"benchmark_fixture":true}',
        source_artifact_id="retained-evidence-fixture",
        source_artifact_sha256=SOURCE_HASH,
    )
    report = evaluate_positive_controls(
        dataset,
        passages,
        (raw,),
        seed=9101,
        detector_families={"semantic_domain_overlap": "semantic"},
    )

    evaluated_row = report.rows[0]
    detector = evaluated_row.detector_results[0]
    assert detector.method_id == "semantic_domain_overlap"
    assert detector.positive_score == 0.9
    assert detector.negative_score == 0.0
    assert detector.recovered is True
    assert next(
        item for item in evaluated_row.family_results if item.family == "semantic"
    ).recovered
    detector_summary = next(
        item
        for item in report.summaries
        if item.method_kind == "detector"
        and item.method_id == "semantic_domain_overlap"
        and item.split == "all"
    )
    family_summary = next(
        item
        for item in report.summaries
        if item.method_kind == "family" and item.method_id == "semantic" and item.split == "all"
    )
    assert detector_summary.recovered_control_count == 1
    assert family_summary.recovered_control_count == 1


def test_unmapped_control_is_retained_with_missing_reference(
    dataset: PositiveControlDataset,
    passages: tuple[PassageRecord, ...],
) -> None:
    incomplete = tuple(passage for passage in passages if passage.reference != "MRK 10:8")
    report = evaluate_positive_controls(dataset, incomplete, (), seed=9101)
    row = next(item for item in report.rows if item.reference_b == "MRK 10:7-8")

    assert row.mapping_status == "unmapped"
    assert row.mapping_reason == "missing_primary_verse"
    assert row.missing_references == ("MRK 10:8",)
    assert row.positive_pairs == ()
    assert row.matched_negative_pair is None
    assert all(not item.available for item in row.baseline_results)
