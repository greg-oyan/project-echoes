"""Bounded source-annotation structural and narrative fingerprints."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from echoes.final_discovery.config import DetectorRegistration
from echoes.final_discovery.features import (
    aligned_sequence_similarity,
    candidate_pair_id,
    canonical_json,
    weighted_jaccard,
)
from echoes.final_discovery.models import PassageRecord, RawEvidence


class StructureError(ValueError):
    """Raised when structural evidence violates its registration."""


def _aligned_items(values: Sequence[str | None]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    return tuple(
        (value, (position,))
        for position, value in enumerate(values, start=1)
        if value is not None and value != ""
    )


def _transitions(
    items: Sequence[tuple[str, tuple[int, ...]]],
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    return tuple(
        (
            f"{items[index][0]}\u241f{items[index + 1][0]}",
            (*items[index][1], *items[index + 1][1]),
        )
        for index in range(len(items) - 1)
    )


def _structural_signature_items(
    passage: PassageRecord,
) -> dict[str, tuple[tuple[str, tuple[int, ...]], ...]]:
    frames = _aligned_items(passage.frames)
    participants = _aligned_items(passage.participants)
    entities = _aligned_items(passage.entities)
    actions = tuple(
        item
        for item in frames
        if any(marker in item[0].casefold() for marker in ("verb", "event", "action", "predicate"))
    )
    return {
        "frames": frames,
        "frame_transitions": _transitions(frames),
        "participants": participants,
        "participant_transitions": _transitions(participants),
        "entities": entities,
        "actions": actions,
        "action_progression": _transitions(actions),
    }


def structural_signature(passage: PassageRecord) -> dict[str, tuple[str, ...]]:
    """Project only source-provided frames, participants, and entities."""

    return {
        name: tuple(value for value, _ in items)
        for name, items in _structural_signature_items(passage).items()
    }


def _occurrence_payload(
    passage: PassageRecord,
    positions: tuple[int, ...],
) -> dict[str, object]:
    return {
        "positions": positions,
        "token_ids": (
            tuple(passage.token_ids[position - 1] for position in positions)
            if passage.token_ids
            else None
        ),
    }


def _matched_signature_evidence(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
) -> dict[str, tuple[dict[str, object], ...]]:
    items_a = _structural_signature_items(passage_a)
    items_b = _structural_signature_items(passage_b)
    result: dict[str, tuple[dict[str, object], ...]] = {}
    for name in items_a:
        shared = sorted(
            {value for value, _ in items_a[name]} & {value for value, _ in items_b[name]},
            key=lambda value: value.encode("utf-8"),
        )
        result[name] = tuple(
            {
                "value": value,
                "passage_occurrences": {
                    passage_a.passage_id: tuple(
                        _occurrence_payload(passage_a, positions)
                        for item, positions in items_a[name]
                        if item == value
                    ),
                    passage_b.passage_id: tuple(
                        _occurrence_payload(passage_b, positions)
                        for item, positions in items_b[name]
                        if item == value
                    ),
                },
            }
            for value in shared
        )
    return result


def _registration(
    registrations: Mapping[str, DetectorRegistration],
) -> DetectorRegistration:
    detector_id = "participant_frame_progression"
    try:
        registration = registrations[detector_id]
    except KeyError as exc:
        raise StructureError(f"unregistered structural detector: {detector_id}") from exc
    if registration.family != "structure_narrative":
        raise StructureError(f"detector {detector_id} is not structural")
    return registration


def structure_pair_evidence(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
    *,
    registrations: Mapping[str, DetectorRegistration],
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> RawEvidence:
    """Score event progression and role configuration without generated semantics."""

    signature_a = structural_signature(passage_a)
    signature_b = structural_signature(passage_b)
    components = {
        "frame_alignment": aligned_sequence_similarity(
            signature_a["frames"], signature_b["frames"]
        ),
        "frame_transition_overlap": weighted_jaccard(
            signature_a["frame_transitions"], signature_b["frame_transitions"]
        ),
        "participant_configuration": weighted_jaccard(
            signature_a["participants"], signature_b["participants"]
        ),
        "participant_progression": weighted_jaccard(
            signature_a["participant_transitions"], signature_b["participant_transitions"]
        ),
        "entity_configuration": weighted_jaccard(signature_a["entities"], signature_b["entities"]),
        "action_progression": weighted_jaccard(
            signature_a["action_progression"], signature_b["action_progression"]
        ),
    }
    component_sources = {
        "frame_alignment": "frames",
        "frame_transition_overlap": "frame_transitions",
        "participant_configuration": "participants",
        "participant_progression": "participant_transitions",
        "entity_configuration": "entities",
        "action_progression": "action_progression",
    }
    informative = [
        value
        for name, value in components.items()
        if signature_a[component_sources[name]] and signature_b[component_sources[name]]
    ]
    score = math.fsum(informative) / len(informative) if informative else 0.0
    forward_participant_alignment = aligned_sequence_similarity(
        signature_a["participants"], signature_b["participants"]
    )
    reversed_participant_alignment = aligned_sequence_similarity(
        signature_a["participants"], tuple(reversed(signature_b["participants"]))
    )
    role_reversal_signal = (
        bool(signature_a["participants"] and signature_b["participants"])
        and reversed_participant_alignment > forward_participant_alignment
    )
    first, second = sorted((passage_a, passage_b), key=lambda passage: passage.passage_id)
    registration = _registration(registrations)
    return RawEvidence(
        candidate_pair_id=candidate_pair_id(first.passage_id, second.passage_id),
        passage_a_id=first.passage_id,
        passage_b_id=second.passage_id,
        detector_id=registration.detector_id,
        family="structure_narrative",
        independence_group=registration.independence_group,
        raw_score=min(max(score, 0.0), 1.0),
        contains_english_derived_evidence=False,
        original_language_evidence_remains=True,
        counts_for_independence=registration.counts_for_independence,
        trace_json=canonical_json(
            {
                "representation": "source_frame_participant_entity_progression",
                "component_scores": components,
                "informative_component_count": len(informative),
                "matched_signature_evidence": _matched_signature_evidence(passage_a, passage_b),
                "possible_role_reversal": role_reversal_signal,
                "forward_participant_alignment": forward_participant_alignment,
                "reversed_participant_alignment": reversed_participant_alignment,
                "no_generated_ontology": True,
            }
        ),
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_artifact_sha256,
    )
