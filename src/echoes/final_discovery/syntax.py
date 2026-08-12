"""Transparent grammatical and syntactic feature detectors."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence

from echoes.final_discovery.config import DetectorRegistration
from echoes.final_discovery.features import (
    aligned_sequence_similarity,
    candidate_pair_id,
    canonical_json,
    matched_aligned_value_trace,
    present,
    weighted_jaccard,
)
from echoes.final_discovery.models import PassageRecord, RawEvidence


class SyntaxError(ValueError):
    """Raised when grammar evidence violates its registered contract."""


_REGISTERED_MARKERS = {
    "negation": ("neg", "negative", "לא", "οὐ", "μη"),
    "imperative": ("imperative", "impv", "imp"),
    "conditional": ("conditional", "cond", "if", "כי", "ἐάν", "εἰ"),
    "perfective": ("perfect", "aorist", "qatal"),
    "imperfective": ("imperfect", "present", "yiqtol"),
    "speech_frame": ("speech", "say", "אמר", "λέγω"),
    "passive": ("passive", "pass"),
}


def _source_occurrence(
    passage: PassageRecord,
    *,
    sequence: str,
    positions: tuple[int, ...],
) -> dict[str, object]:
    return {
        "source_sequence": sequence,
        "positions": positions,
        "token_ids": (
            tuple(passage.token_ids[position - 1] for position in positions)
            if passage.token_ids
            else None
        ),
    }


def _grammatical_feature_occurrences(
    passage: PassageRecord,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Derive every scored feature together with exact source-token positions."""

    pos_items = tuple(
        (position, value)
        for position, value in enumerate(passage.pos_sequence, start=1)
        if value is not None and value != ""
    )
    morphology_items = tuple(
        (position, value)
        for position, value in enumerate(passage.morphology_sequence, start=1)
        if value is not None and value != ""
    )
    rows: list[tuple[str, dict[str, object]]] = []
    for prefix, items, sizes in (
        ("pos", pos_items, (1, 2, 3)),
        ("morph", morphology_items, (1, 2)),
    ):
        for size in sizes:
            feature_prefix = prefix if size == 1 else f"{prefix}{size}"
            for start in range(len(items) - size + 1):
                window = items[start : start + size]
                value = "\u241f".join(item[1] for item in window)
                positions = tuple(item[0] for item in window)
                rows.append(
                    (
                        f"{feature_prefix}:{value}",
                        _source_occurrence(
                            passage,
                            sequence=prefix,
                            positions=positions,
                        ),
                    )
                )
    lowered = tuple(
        (sequence, position, value.casefold())
        for sequence, items in (("pos", pos_items), ("morph", morphology_items))
        for position, value in items
    )
    for label, needles in _REGISTERED_MARKERS.items():
        matches = tuple(
            _source_occurrence(passage, sequence=sequence, positions=(position,))
            for sequence, position, value in lowered
            if any(needle in value for needle in needles)
        )
        if matches:
            rows.append((f"marker:{label}", {"marker_matches": matches}))
    return tuple(rows)


def grammatical_features(passage: PassageRecord) -> tuple[str, ...]:
    """Derive bounded annotation-only fingerprints without an inferred ontology."""

    # Source frames, participants, entities, and event progression are reserved
    # for the independently registered structural family. Grammar is confined
    # to POS/morphology and markers derived from those annotations.
    return tuple(feature for feature, _ in _grammatical_feature_occurrences(passage))


def feature_document_frequencies(
    passages: Sequence[PassageRecord],
) -> dict[str, int]:
    """Count each deterministic grammatical feature once per passage."""

    counts: Counter[str] = Counter()
    for passage in passages:
        counts.update(set(grammatical_features(passage)))
    return dict(counts)


def _registration(
    registrations: Mapping[str, DetectorRegistration], detector_id: str
) -> DetectorRegistration:
    try:
        registration = registrations[detector_id]
    except KeyError as exc:
        raise SyntaxError(f"unregistered grammar detector: {detector_id}") from exc
    if registration.family != "grammar_syntax":
        raise SyntaxError(f"detector {detector_id} is not registered as grammar_syntax")
    return registration


def _raw(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
    *,
    registration: DetectorRegistration,
    score: float,
    trace: object,
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> RawEvidence:
    first, second = sorted((passage_a, passage_b), key=lambda passage: passage.passage_id)
    return RawEvidence(
        candidate_pair_id=candidate_pair_id(first.passage_id, second.passage_id),
        passage_a_id=first.passage_id,
        passage_b_id=second.passage_id,
        detector_id=registration.detector_id,
        family="grammar_syntax",
        independence_group=registration.independence_group,
        raw_score=min(max(score, 0.0), 1.0),
        contains_english_derived_evidence=False,
        original_language_evidence_remains=True,
        counts_for_independence=registration.counts_for_independence,
        trace_json=canonical_json(trace),
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_artifact_sha256,
    )


def grammar_pair_evidence(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
    *,
    registrations: Mapping[str, DetectorRegistration],
    document_frequencies: Mapping[str, int],
    passage_count: int,
    rare_maximum_document_frequency: int = 3,
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> tuple[RawEvidence, RawEvidence]:
    """Compare source POS/morphology annotations for a bounded pair."""

    if passage_count < 1 or rare_maximum_document_frequency < 1:
        raise SyntaxError("grammar corpus counts must be positive")
    pos_a = present(passage_a.pos_sequence)
    pos_b = present(passage_b.pos_sequence)
    morphology_a = present(passage_a.morphology_sequence)
    morphology_b = present(passage_b.morphology_sequence)
    feature_occurrences_a = _grammatical_feature_occurrences(passage_a)
    feature_occurrences_b = _grammatical_feature_occurrences(passage_b)
    features_a = tuple(feature for feature, _ in feature_occurrences_a)
    features_b = tuple(feature for feature, _ in feature_occurrences_b)
    weights = {
        feature: math.log((1 + passage_count) / (1 + frequency)) + 1.0
        for feature, frequency in document_frequencies.items()
    }
    component_scores = {
        "weighted_feature_overlap": weighted_jaccard(features_a, features_b, weights=weights),
        "pos_sequence_alignment": aligned_sequence_similarity(pos_a, pos_b),
        "morphology_sequence_alignment": aligned_sequence_similarity(morphology_a, morphology_b),
    }
    sequence_score = math.fsum(component_scores.values()) / len(component_scores)
    shared_features = set(features_a) & set(features_b)
    rare_shared = sorted(
        feature
        for feature in shared_features
        if document_frequencies.get(feature, passage_count) <= rare_maximum_document_frequency
    )
    rare_union = {
        feature
        for feature in set(features_a) | set(features_b)
        if document_frequencies.get(feature, passage_count) <= rare_maximum_document_frequency
    }
    rare_score = len(rare_shared) / len(rare_union) if rare_union else 0.0
    occurrences_a: dict[str, list[dict[str, object]]] = {}
    occurrences_b: dict[str, list[dict[str, object]]] = {}
    for feature, occurrence in feature_occurrences_a:
        occurrences_a.setdefault(feature, []).append(occurrence)
    for feature, occurrence in feature_occurrences_b:
        occurrences_b.setdefault(feature, []).append(occurrence)
    shared_feature_evidence = tuple(
        {
            "feature": feature,
            "document_frequency": document_frequencies.get(feature),
            "passage_occurrences": {
                passage_a.passage_id: tuple(occurrences_a[feature]),
                passage_b.passage_id: tuple(occurrences_b[feature]),
            },
        }
        for feature in sorted(shared_features, key=lambda value: value.encode("utf-8"))
    )
    rare_shared_set = set(rare_shared)
    sequence = _raw(
        passage_a,
        passage_b,
        registration=_registration(registrations, "grammar_sequence_alignment"),
        score=sequence_score,
        trace={
            "representation": "pos_morphology_weighted_overlap_and_alignment",
            "component_scores": component_scores,
            "shared_feature_count": len(shared_features),
            "shared_feature_evidence": shared_feature_evidence,
            "matched_pos_evidence": matched_aligned_value_trace(
                passage_a.passage_id,
                passage_a.pos_sequence,
                passage_a.token_ids,
                passage_b.passage_id,
                passage_b.pos_sequence,
                passage_b.token_ids,
            ),
            "matched_morphology_evidence": matched_aligned_value_trace(
                passage_a.passage_id,
                passage_a.morphology_sequence,
                passage_a.token_ids,
                passage_b.passage_id,
                passage_b.morphology_sequence,
                passage_b.token_ids,
            ),
            "structural_frames_explicitly_excluded": True,
            "syntax_alone_is_not_dependence": True,
        },
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_artifact_sha256,
    )
    rare = _raw(
        passage_a,
        passage_b,
        registration=_registration(registrations, "grammar_rare_pattern"),
        score=rare_score,
        trace={
            "representation": "rare_grammar_feature_intersection",
            "maximum_document_frequency": rare_maximum_document_frequency,
            "shared_rare_features": rare_shared,
            "shared_rare_feature_evidence": tuple(
                row for row in shared_feature_evidence if row["feature"] in rare_shared_set
            ),
            "rare_union_count": len(rare_union),
            "same_independence_group_as_sequence": True,
        },
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_artifact_sha256,
    )
    return sequence, rare
