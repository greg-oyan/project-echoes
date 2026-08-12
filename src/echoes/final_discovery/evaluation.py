"""Reference-only positive-control evaluation for ``final-discovery-v1``.

The evaluator is intentionally downstream of candidate generation.  It maps
the separately governed positive controls onto primary verse identities, but
it never appends those pairs to a retrieval universe or emits discovery-tier
records.  Missing mappings and missing retained detector output remain visible
as benchmark failures instead of being silently dropped.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echoes.benchmarks.positive_controls import (
    PositiveControlDataset,
    PositiveControlRow,
    SplitPartition,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json, canonical_pair
from echoes.final_discovery.models import EvidenceFamily, PassageRecord, RawEvidence
from echoes.lexical.detectors import bm25_score, tfidf_cosine_similarity

EvaluationPartition = SplitPartition | Literal["all"]
MethodKind = Literal["detector", "baseline"]
RecoveryRule = Literal["positive_score_strictly_greater_than_matched_negative"]
NegativeSelectionMethod = Literal[
    "replace_endpoint_b_with_nonbenchmark_primary_verse_matched_by_corpus_genre_"
    "and_token_count_then_seeded_sha256_tie_break"
]

_REFERENCE_RE = re.compile(
    r"^(?P<book>[1-3]?[A-Z]{2,3}) (?P<chapter>[1-9][0-9]*):"
    r"(?P<verse>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$"
)
_BASELINE_IDS = (
    "annotation_tfidf",
    "bm25",
    "m7_lexical_rrf",
    "deterministic_random",
)
_FAMILIES: tuple[EvidenceFamily, ...] = (
    "lexical",
    "semantic",
    "grammar_syntax",
    "structure_narrative",
    "anomaly",
)
_RECOVERY_RULE: RecoveryRule = "positive_score_strictly_greater_than_matched_negative"
_NEGATIVE_METHOD: NegativeSelectionMethod = (
    "replace_endpoint_b_with_nonbenchmark_primary_verse_matched_by_corpus_genre_"
    "and_token_count_then_seeded_sha256_tie_break"
)


class PositiveControlEvaluationError(ValueError):
    """Raised when benchmark evaluation would violate its frozen boundary."""


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def finite_floats_only(cls, value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("positive-control evaluation numbers must be finite")
        return value


class PositiveControlProvenance(_EvaluationModel):
    """Reference-only source identity copied from one validated control."""

    source_id: str = Field(min_length=1)
    source_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_file: str = Field(min_length=1)
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_record_locator: str = Field(min_length=1)
    source_license: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)
    verified_by: str = Field(min_length=1)
    verified_at: str = Field(min_length=1)


class BenchmarkPassagePair(_EvaluationModel):
    """One expanded verse pair used only for benchmark scoring."""

    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    passage_a_reference: str = Field(min_length=1)
    passage_b_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def pair_is_canonical(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("benchmark passage IDs must use canonical lexical ordering")
        return self


class MatchedNegativePair(BenchmarkPassagePair):
    """One deterministic, nonbenchmark comparison for a mapped control."""

    preserved_endpoint: Literal["a"] = "a"
    target_corpus_matched: Literal[True] = True
    target_genre_matched: bool
    target_token_count_delta: int = Field(ge=0)
    selection_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class MethodEvaluation(_EvaluationModel):
    """Positive-versus-negative result for one detector or explicit baseline."""

    method_id: str = Field(min_length=1)
    method_kind: MethodKind
    family: EvidenceFamily | None = None
    available: bool
    positive_score: float | None = None
    negative_score: float | None = None
    positive_evidence_observed: bool
    negative_evidence_observed: bool
    recovered: bool
    recovery_rule: RecoveryRule = _RECOVERY_RULE
    unavailable_reason: str | None = None
    retained_evidence_count: int = Field(ge=0)
    source_artifact_ids: tuple[str, ...] = ()
    source_artifact_sha256s: tuple[str, ...] = ()

    @model_validator(mode="after")
    def availability_is_explicit(self) -> Self:
        if self.available:
            if self.positive_score is None or self.negative_score is None:
                raise ValueError("available method results require both scores")
            if self.unavailable_reason is not None:
                raise ValueError("available method results cannot carry an unavailable reason")
            if self.recovered != (self.positive_score > self.negative_score):
                raise ValueError("method recovery must follow the frozen strict comparison")
        else:
            if self.positive_score is not None or self.negative_score is not None:
                raise ValueError("unavailable method results cannot carry scores")
            if self.recovered:
                raise ValueError("an unavailable method cannot recover a control")
            if not self.unavailable_reason:
                raise ValueError("unavailable method results require a reason")
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("source artifact IDs must be unique")
        if len(self.source_artifact_sha256s) != len(set(self.source_artifact_sha256s)):
            raise ValueError("source artifact hashes must be unique")
        return self


class FamilyEvaluation(_EvaluationModel):
    """Recovery by any retained detector in one registered family."""

    family: EvidenceFamily
    member_detector_ids: tuple[str, ...]
    available: bool
    recovered: bool
    aggregation_rule: Literal["any_member_detector_recovers"] = "any_member_detector_recovers"
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def family_result_is_consistent(self) -> Self:
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available family results cannot carry an unavailable reason")
        if not self.available:
            if self.recovered:
                raise ValueError("an unavailable family cannot recover a control")
            if not self.unavailable_reason:
                raise ValueError("unavailable family results require a reason")
        return self


class PositiveControlEvaluationRow(_EvaluationModel):
    """Complete mapping and evaluation trace for one validated control row."""

    control_id: str = Field(pattern=r"^PC_[a-f0-9]{64}$")
    reference_a: str = Field(min_length=1)
    reference_b: str = Field(min_length=1)
    expanded_references_a: tuple[str, ...] = Field(min_length=1)
    expanded_references_b: tuple[str, ...] = Field(min_length=1)
    mapped_passage_ids_a: tuple[str, ...]
    mapped_passage_ids_b: tuple[str, ...]
    missing_references: tuple[str, ...]
    mapping_status: Literal["mapped", "unmapped"]
    mapping_reason: Literal[
        "complete_primary_verse_expansion",
        "missing_primary_verse",
        "no_nonbenchmark_matched_negative",
    ]
    corpus_pair: str = Field(min_length=1)
    relationship_class: str = Field(min_length=1)
    relationship_family_id: str = Field(min_length=1)
    leakage_group_id: str = Field(min_length=1)
    split: SplitPartition
    provenance: PositiveControlProvenance
    positive_pairs: tuple[BenchmarkPassagePair, ...]
    matched_negative_pair: MatchedNegativePair | None
    detector_results: tuple[MethodEvaluation, ...]
    family_results: tuple[FamilyEvaluation, ...]
    baseline_results: tuple[MethodEvaluation, ...] = Field(min_length=4, max_length=4)
    benchmark_only: Literal[True] = True
    eligible_for_candidate_generation: Literal[False] = False

    @model_validator(mode="after")
    def mapping_and_methods_are_consistent(self) -> Self:
        mapped = self.mapping_status == "mapped"
        if mapped != bool(self.positive_pairs):
            raise ValueError("mapped controls require positive pairs and unmapped controls cannot")
        if mapped and self.missing_references:
            raise ValueError("mapped controls cannot carry missing references")
        if not mapped and not self.missing_references:
            raise ValueError("unmapped controls require missing references")
        if self.mapping_reason == "no_nonbenchmark_matched_negative":
            if not mapped or self.matched_negative_pair is not None:
                raise ValueError(
                    "negative-pair failure requires a mapped control without a negative"
                )
        elif mapped and self.matched_negative_pair is None:
            raise ValueError("mapped controls require a matched negative or an explicit failure")
        if tuple(item.method_id for item in self.baseline_results) != _BASELINE_IDS:
            raise ValueError("all four baselines must appear in frozen order")
        if len({item.method_id for item in self.detector_results}) != len(self.detector_results):
            raise ValueError("detector results must be unique")
        if tuple(item.family for item in self.family_results) != _FAMILIES:
            raise ValueError("all registered evidence families must be reported")
        return self


class RecoverySummary(_EvaluationModel):
    """Transparent recovery counts for one split and method/family."""

    method_id: str = Field(min_length=1)
    method_kind: Literal["detector", "family", "baseline"]
    family: EvidenceFamily | None = None
    split: EvaluationPartition
    control_count: int = Field(ge=0)
    mapped_control_count: int = Field(ge=0)
    matched_negative_count: int = Field(ge=0)
    available_control_count: int = Field(ge=0)
    recovered_control_count: int = Field(ge=0)
    recovery_rate_over_mapped: float = Field(ge=0.0, le=1.0)
    recovery_rate_over_available: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def counts_are_nested(self) -> Self:
        if not (
            self.recovered_control_count
            <= self.available_control_count
            <= self.matched_negative_count
            <= self.mapped_control_count
            <= self.control_count
        ):
            raise ValueError("summary counts must be monotonically nested")
        mapped_rate = (
            self.recovered_control_count / self.mapped_control_count
            if self.mapped_control_count
            else 0.0
        )
        available_rate = (
            self.recovered_control_count / self.available_control_count
            if self.available_control_count
            else 0.0
        )
        if self.recovery_rate_over_mapped != mapped_rate:
            raise ValueError("mapped recovery rate differs from exact counts")
        if self.recovery_rate_over_available != available_rate:
            raise ValueError("available recovery rate differs from exact counts")
        return self


class DetectorInventoryEntry(_EvaluationModel):
    detector_id: str = Field(min_length=1)
    family: EvidenceFamily
    retained_anywhere: bool


class BaselineDefinition(_EvaluationModel):
    baseline_id: Literal[
        "annotation_tfidf",
        "bm25",
        "m7_lexical_rrf",
        "deterministic_random",
    ]
    definition: str = Field(min_length=1)
    original_language_only: bool


class PositiveControlEvaluationReport(_EvaluationModel):
    """Persistable, reference-only positive-control evaluation artifact."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = "final-discovery-v1"
    benchmark_id: str = Field(min_length=1)
    benchmark_config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    benchmark_data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen_seed: int = Field(ge=0)
    row_count: int = Field(ge=1, le=100)
    mapped_control_count: int = Field(ge=0)
    unmapped_control_count: int = Field(ge=0)
    benchmark_payload_policy: Literal["reference_only_no_source_text"] = (
        "reference_only_no_source_text"
    )
    benchmark_only: Literal[True] = True
    candidate_generation_allowed: Literal[False] = False
    recovery_rule: RecoveryRule = _RECOVERY_RULE
    negative_selection_method: NegativeSelectionMethod = _NEGATIVE_METHOD
    detector_inventory: tuple[DetectorInventoryEntry, ...]
    baseline_definitions: tuple[BaselineDefinition, ...] = Field(min_length=4, max_length=4)
    rows: tuple[PositiveControlEvaluationRow, ...] = Field(min_length=1, max_length=100)
    summaries: tuple[RecoverySummary, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_and_split_safe(self) -> Self:
        if self.row_count != len(self.rows):
            raise ValueError("report row count differs from serialized rows")
        mapped = sum(row.mapping_status == "mapped" for row in self.rows)
        if mapped != self.mapped_control_count:
            raise ValueError("mapped control count differs from serialized rows")
        if self.unmapped_control_count != self.row_count - mapped:
            raise ValueError("unmapped control count differs from serialized rows")
        if len({row.control_id for row in self.rows}) != len(self.rows):
            raise ValueError("report control IDs must be unique")
        leakage_splits: dict[str, set[SplitPartition]] = defaultdict(set)
        for row in self.rows:
            leakage_splits[row.leakage_group_id].add(row.split)
        crossing = sorted(group for group, splits in leakage_splits.items() if len(splits) != 1)
        if crossing:
            raise ValueError(f"leakage groups cross evaluation splits: {crossing}")
        if tuple(item.baseline_id for item in self.baseline_definitions) != _BASELINE_IDS:
            raise ValueError("baseline definitions must use the frozen inventory")
        return self


@dataclass(slots=True)
class _MappedControl:
    row: PositiveControlRow
    expanded_a: tuple[str, ...]
    expanded_b: tuple[str, ...]
    passages_a: tuple[PassageRecord, ...]
    passages_b: tuple[PassageRecord, ...]
    missing: tuple[str, ...]
    pairs: tuple[tuple[str, str], ...]
    negative: MatchedNegativePair | None = None


@dataclass(slots=True)
class _EvidenceAggregate:
    score: float
    count: int
    artifact_ids: set[str]
    artifact_sha256s: set[str]


def _expanded_references(reference: str) -> tuple[str, ...]:
    match = _REFERENCE_RE.fullmatch(reference)
    if match is None:
        raise PositiveControlEvaluationError(f"invalid positive-control reference: {reference!r}")
    book = match.group("book")
    chapter = int(match.group("chapter"))
    start = int(match.group("verse"))
    end = int(match.group("end") or start)
    if end < start:
        raise PositiveControlEvaluationError(
            f"positive-control reference range ends before it starts: {reference!r}"
        )
    return tuple(f"{book} {chapter}:{verse}" for verse in range(start, end + 1))


def _primary_passage_index(
    passages: Sequence[PassageRecord],
) -> tuple[dict[str, PassageRecord], dict[str, PassageRecord]]:
    by_reference: dict[str, PassageRecord] = {}
    by_id: dict[str, PassageRecord] = {}
    for passage in passages:
        is_primary = passage.analysis_profile == "edition_complete" and (
            (passage.corpus == "hebrew" and passage.analysis_reading == "qere")
            or (passage.corpus == "greek" and passage.analysis_reading == "source")
        )
        if not is_primary:
            raise PositiveControlEvaluationError(
                "positive controls require primary edition-complete Qere/source verse records: "
                f"{passage.passage_id}"
            )
        if passage.reference in by_reference:
            raise PositiveControlEvaluationError(
                f"duplicate primary verse reference: {passage.reference}"
            )
        if passage.passage_id in by_id:
            raise PositiveControlEvaluationError(
                f"duplicate primary passage ID: {passage.passage_id}"
            )
        by_reference[passage.reference] = passage
        by_id[passage.passage_id] = passage
    if not by_id:
        raise PositiveControlEvaluationError("positive-control evaluation requires passages")
    return by_reference, by_id


def _map_controls(
    rows: Sequence[PositiveControlRow],
    by_reference: Mapping[str, PassageRecord],
) -> list[_MappedControl]:
    mapped: list[_MappedControl] = []
    for row in rows:
        expanded_a = _expanded_references(row.reference_a)
        expanded_b = _expanded_references(row.reference_b)
        missing = tuple(
            reference for reference in (*expanded_a, *expanded_b) if reference not in by_reference
        )
        passages_a = tuple(by_reference[value] for value in expanded_a if value in by_reference)
        passages_b = tuple(by_reference[value] for value in expanded_b if value in by_reference)
        pairs: tuple[tuple[str, str], ...] = ()
        if not missing:
            try:
                pairs = tuple(
                    sorted(
                        {
                            canonical_pair(left.passage_id, right.passage_id)
                            for left in passages_a
                            for right in passages_b
                        }
                    )
                )
            except ValueError as exc:
                raise PositiveControlEvaluationError(
                    f"positive control expands to a self-pair: {row.control_id}"
                ) from exc
        mapped.append(
            _MappedControl(
                row=row,
                expanded_a=expanded_a,
                expanded_b=expanded_b,
                passages_a=passages_a,
                passages_b=passages_b,
                missing=missing,
                pairs=pairs,
            )
        )
    return mapped


def _seeded_digest(*values: object) -> str:
    return hashlib.sha256(canonical_json(list(values)).encode("ascii")).hexdigest()


def _choose_seeded_passage(
    passages: Sequence[PassageRecord], *, seed: int, control_id: str, role: str
) -> PassageRecord:
    return min(
        passages,
        key=lambda passage: (
            _seeded_digest(seed, control_id, role, passage.passage_id),
            passage.passage_id,
        ),
    )


def _attach_negatives(
    controls: Sequence[_MappedControl],
    passages: Sequence[PassageRecord],
    *,
    seed: int,
) -> None:
    positive_pairs = {pair for control in controls for pair in control.pairs}
    benchmark_passage_ids = {
        passage.passage_id
        for control in controls
        for passage in (*control.passages_a, *control.passages_b)
    }
    for control in controls:
        if not control.pairs:
            continue
        anchor = _choose_seeded_passage(
            control.passages_a,
            seed=seed,
            control_id=control.row.control_id,
            role="anchor_a",
        )
        replaced = _choose_seeded_passage(
            control.passages_b,
            seed=seed,
            control_id=control.row.control_id,
            role="replaced_b",
        )
        candidates: list[PassageRecord] = []
        for candidate in passages:
            if candidate.corpus != replaced.corpus:
                continue
            if candidate.passage_id in benchmark_passage_ids:
                continue
            if candidate.passage_id == anchor.passage_id:
                continue
            pair = canonical_pair(anchor.passage_id, candidate.passage_id)
            if pair in positive_pairs:
                continue
            candidates.append(candidate)
        if not candidates:
            continue
        negative_target = min(
            candidates,
            key=lambda candidate: (
                candidate.genre != replaced.genre,
                abs(candidate.token_count - replaced.token_count),
                candidate.book in {anchor.book, replaced.book},
                _seeded_digest(
                    seed,
                    control.row.control_id,
                    "negative_b",
                    candidate.passage_id,
                ),
                candidate.passage_id,
            ),
        )
        first, second = canonical_pair(anchor.passage_id, negative_target.passage_id)
        first_passage = anchor if anchor.passage_id == first else negative_target
        second_passage = negative_target if negative_target.passage_id == second else anchor
        selection_sha256 = _seeded_digest(
            seed,
            control.row.control_id,
            anchor.passage_id,
            replaced.passage_id,
            negative_target.passage_id,
            _NEGATIVE_METHOD,
        )
        control.negative = MatchedNegativePair(
            passage_a_id=first,
            passage_b_id=second,
            passage_a_reference=first_passage.reference,
            passage_b_reference=second_passage.reference,
            target_genre_matched=negative_target.genre == replaced.genre,
            target_token_count_delta=abs(negative_target.token_count - replaced.token_count),
            selection_sha256=selection_sha256,
        )


def _annotation_features(passage: PassageRecord) -> tuple[str, ...]:
    """Return the frozen original-language annotation baseline features."""

    layers: tuple[tuple[str, Sequence[str | None]], ...] = (
        ("lemma", passage.lemma_sequence),
        ("root", passage.root_sequence),
        ("pos", passage.pos_sequence),
        ("morphology", passage.morphology_sequence),
        ("semantic_domain", passage.semantic_domains),
        ("entity", passage.entities),
        ("participant", passage.participants),
        ("frame", passage.frames),
    )
    return tuple(
        f"{layer}:{value}"
        for layer, values in layers
        for value in values
        if value is not None and value != ""
    )


def _build_baseline_scores(
    passages: Sequence[PassageRecord],
    relevant_pairs: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Score only the bounded positive/negative pair inventory."""

    document_frequency: Counter[str] = Counter()
    relevant_ids = {value for pair in relevant_pairs for value in pair}
    relevant_counts: dict[str, Counter[str]] = {}
    total_feature_count = 0
    for passage in passages:
        counts = Counter(_annotation_features(passage))
        document_frequency.update(counts.keys())
        total_feature_count += sum(counts.values())
        if passage.passage_id in relevant_ids:
            relevant_counts[passage.passage_id] = counts
    missing = sorted(relevant_ids - set(relevant_counts))
    if missing:
        raise PositiveControlEvaluationError(
            f"relevant benchmark passage IDs are absent from the primary corpus: {missing}"
        )
    document_count = len(passages)
    average_length = total_feature_count / document_count
    tfidf_scores: dict[tuple[str, str], float] = {}
    bm25_scores: dict[tuple[str, str], float] = {}
    for pair in sorted(relevant_pairs):
        counts_a = relevant_counts[pair[0]]
        counts_b = relevant_counts[pair[1]]
        tfidf_scores[pair] = tfidf_cosine_similarity(
            counts_a,
            counts_b,
            document_frequency,
            document_count,
            sublinear_tf=True,
            smooth_idf=True,
        ).score
        if average_length == 0.0:
            bm25_scores[pair] = 0.0
            continue
        score_ab = bm25_score(
            counts_a,
            counts_b,
            document_frequency,
            document_count,
            document_length=sum(counts_b.values()),
            average_document_length=average_length,
            k1=1.2,
            b=0.75,
            query_term_frequency_mode="binary",
        ).score
        score_ba = bm25_score(
            counts_b,
            counts_a,
            document_frequency,
            document_count,
            document_length=sum(counts_a.values()),
            average_document_length=average_length,
            k1=1.2,
            b=0.75,
            query_term_frequency_mode="binary",
        ).score
        bm25_scores[pair] = max(score_ab, score_ba)
    return tfidf_scores, bm25_scores


def _random_score(seed: int, control_id: str, label: str, pair: tuple[str, str]) -> float:
    digest = hashlib.sha256(
        canonical_json([seed, control_id, label, pair[0], pair[1]]).encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) / 2**64


def _aggregate_evidence(
    evidence: Iterable[RawEvidence],
    relevant_pairs: set[tuple[str, str]],
    supplied_inventory: Mapping[str, EvidenceFamily] | None,
) -> tuple[
    dict[str, EvidenceFamily],
    set[str],
    dict[tuple[str, tuple[str, str]], _EvidenceAggregate],
]:
    inventory = dict(supplied_inventory or {})
    for detector_id, family in inventory.items():
        if not detector_id:
            raise PositiveControlEvaluationError("detector inventory IDs must be nonempty")
        if family not in _FAMILIES:
            raise PositiveControlEvaluationError(
                f"detector inventory has unsupported family: {detector_id}={family}"
            )
    observed: set[str] = set()
    aggregates: dict[tuple[str, tuple[str, str]], _EvidenceAggregate] = {}
    for item in evidence:
        expected_pair_id = candidate_pair_id(item.passage_a_id, item.passage_b_id)
        if item.candidate_pair_id != expected_pair_id:
            raise PositiveControlEvaluationError(
                f"retained evidence has inconsistent candidate pair ID: {item.detector_id}"
            )
        prior_family = inventory.get(item.detector_id)
        if prior_family is not None and prior_family != item.family:
            raise PositiveControlEvaluationError(
                f"detector changes family in retained evidence: {item.detector_id}"
            )
        inventory[item.detector_id] = item.family
        observed.add(item.detector_id)
        pair = (item.passage_a_id, item.passage_b_id)
        if pair not in relevant_pairs:
            continue
        key = (item.detector_id, pair)
        aggregate = aggregates.get(key)
        if aggregate is None:
            aggregates[key] = _EvidenceAggregate(
                score=item.raw_score,
                count=1,
                artifact_ids={item.source_artifact_id},
                artifact_sha256s={item.source_artifact_sha256},
            )
        else:
            aggregate.score = max(aggregate.score, item.raw_score)
            aggregate.count += 1
            aggregate.artifact_ids.add(item.source_artifact_id)
            aggregate.artifact_sha256s.add(item.source_artifact_sha256)
    return inventory, observed, aggregates


def _unavailable_method(
    method_id: str,
    method_kind: MethodKind,
    *,
    family: EvidenceFamily | None,
    reason: str,
) -> MethodEvaluation:
    return MethodEvaluation(
        method_id=method_id,
        method_kind=method_kind,
        family=family,
        available=False,
        positive_evidence_observed=False,
        negative_evidence_observed=False,
        recovered=False,
        unavailable_reason=reason,
        retained_evidence_count=0,
    )


def _score_from_mapping(
    method_id: str,
    method_kind: MethodKind,
    positive_pairs: Sequence[tuple[str, str]],
    negative_pair: tuple[str, str],
    score_by_pair: Mapping[tuple[str, str], float],
    *,
    family: EvidenceFamily | None = None,
    evidence_by_pair: Mapping[tuple[str, str], _EvidenceAggregate] | None = None,
) -> MethodEvaluation:
    observed_positive = [pair for pair in positive_pairs if pair in score_by_pair]
    positive_score = max((score_by_pair.get(pair, 0.0) for pair in positive_pairs), default=0.0)
    negative_observed = negative_pair in score_by_pair
    negative_score = score_by_pair.get(negative_pair, 0.0)
    aggregates = evidence_by_pair or {}
    used_aggregates = [aggregates[pair] for pair in observed_positive if pair in aggregates]
    if negative_pair in aggregates:
        used_aggregates.append(aggregates[negative_pair])
    return MethodEvaluation(
        method_id=method_id,
        method_kind=method_kind,
        family=family,
        available=True,
        positive_score=positive_score,
        negative_score=negative_score,
        positive_evidence_observed=bool(observed_positive),
        negative_evidence_observed=negative_observed,
        recovered=positive_score > negative_score,
        retained_evidence_count=sum(item.count for item in used_aggregates),
        source_artifact_ids=tuple(
            sorted({value for item in used_aggregates for value in item.artifact_ids})
        ),
        source_artifact_sha256s=tuple(
            sorted({value for item in used_aggregates for value in item.artifact_sha256s})
        ),
    )


def _benchmark_pair_model(
    pair: tuple[str, str], by_id: Mapping[str, PassageRecord]
) -> BenchmarkPassagePair:
    return BenchmarkPassagePair(
        passage_a_id=pair[0],
        passage_b_id=pair[1],
        passage_a_reference=by_id[pair[0]].reference,
        passage_b_reference=by_id[pair[1]].reference,
    )


def _method_summaries(
    rows: Sequence[PositiveControlEvaluationRow],
) -> tuple[RecoverySummary, ...]:
    summaries: list[RecoverySummary] = []
    detector_ids = tuple(
        sorted({result.method_id for row in rows for result in row.detector_results})
    )
    partitions: tuple[EvaluationPartition, ...] = (
        "train",
        "development",
        "test",
        "all",
    )

    def selected(partition: EvaluationPartition) -> list[PositiveControlEvaluationRow]:
        return [row for row in rows if partition == "all" or row.split == partition]

    def add_summary(
        method_id: str,
        method_kind: Literal["detector", "family", "baseline"],
        family: EvidenceFamily | None,
        partition: EvaluationPartition,
        values: Sequence[MethodEvaluation | FamilyEvaluation],
        selected_rows: Sequence[PositiveControlEvaluationRow],
    ) -> None:
        control_count = len(selected_rows)
        mapped_count = sum(row.mapping_status == "mapped" for row in selected_rows)
        negative_count = sum(row.matched_negative_pair is not None for row in selected_rows)
        available_count = sum(value.available for value in values)
        recovered_count = sum(value.recovered for value in values)
        summaries.append(
            RecoverySummary(
                method_id=method_id,
                method_kind=method_kind,
                family=family,
                split=partition,
                control_count=control_count,
                mapped_control_count=mapped_count,
                matched_negative_count=negative_count,
                available_control_count=available_count,
                recovered_control_count=recovered_count,
                recovery_rate_over_mapped=(recovered_count / mapped_count if mapped_count else 0.0),
                recovery_rate_over_available=(
                    recovered_count / available_count if available_count else 0.0
                ),
            )
        )

    for detector_id in detector_ids:
        family = next(
            result.family
            for row in rows
            for result in row.detector_results
            if result.method_id == detector_id
        )
        for partition in partitions:
            partition_rows = selected(partition)
            detector_values = [
                next(item for item in row.detector_results if item.method_id == detector_id)
                for row in partition_rows
            ]
            add_summary(
                detector_id,
                "detector",
                family,
                partition,
                detector_values,
                partition_rows,
            )
    for family in _FAMILIES:
        for partition in partitions:
            partition_rows = selected(partition)
            family_values = [
                next(item for item in row.family_results if item.family == family)
                for row in partition_rows
            ]
            add_summary(
                family,
                "family",
                family,
                partition,
                family_values,
                partition_rows,
            )
    for baseline_id in _BASELINE_IDS:
        for partition in partitions:
            partition_rows = selected(partition)
            baseline_values = [
                next(item for item in row.baseline_results if item.method_id == baseline_id)
                for row in partition_rows
            ]
            add_summary(
                baseline_id,
                "baseline",
                "lexical" if baseline_id == "m7_lexical_rrf" else None,
                partition,
                baseline_values,
                partition_rows,
            )
    return tuple(summaries)


def _validate_dataset_receipt(dataset: PositiveControlDataset) -> None:
    if len(dataset.rows) != dataset.validation.row_count:
        raise PositiveControlEvaluationError(
            "positive-control rows differ from their validation receipt"
        )
    if len(dataset.rows) != dataset.config.dataset.expected_row_count:
        raise PositiveControlEvaluationError(
            "positive-control rows differ from the governed expected row count"
        )
    if dataset.validation.benchmark_id != dataset.config.benchmark_id:
        raise PositiveControlEvaluationError(
            "positive-control validation receipt has a different benchmark ID"
        )
    group_splits: dict[str, set[SplitPartition]] = defaultdict(set)
    for row in dataset.rows:
        group_splits[row.leakage_group_id].add(row.split)
    crossing = sorted(group for group, splits in group_splits.items() if len(splits) != 1)
    if crossing:
        raise PositiveControlEvaluationError(
            f"positive-control leakage groups cross splits: {crossing}"
        )


def evaluate_positive_controls(
    dataset: PositiveControlDataset,
    passages: Sequence[PassageRecord],
    retained_evidence: Iterable[RawEvidence],
    *,
    seed: int,
    detector_families: Mapping[str, EvidenceFamily] | None = None,
) -> PositiveControlEvaluationReport:
    """Evaluate every validated control without mutating the discovery universe.

    Ranges are expanded to individual primary verse identities.  Each mapped
    control is represented by the Cartesian product of its two endpoint ranges;
    a method's positive score is the maximum across that bounded set.  Recovery
    requires the positive score to be strictly greater than one deterministic
    matched-negative score.  Missing retained detector evidence is zero only
    when that detector is present elsewhere in the supplied artifact; a wholly
    absent detector (including M7) is reported as unavailable.
    """

    if isinstance(seed, bool) or seed < 0:
        raise PositiveControlEvaluationError("positive-control seed must be nonnegative")
    _validate_dataset_receipt(dataset)
    by_reference, by_id = _primary_passage_index(passages)
    controls = _map_controls(dataset.rows, by_reference)
    _attach_negatives(controls, passages, seed=seed)
    relevant_pairs = {pair for control in controls for pair in control.pairs}
    for control in controls:
        if control.negative is not None:
            relevant_pairs.add((control.negative.passage_a_id, control.negative.passage_b_id))
    tfidf_scores, bm25_scores = _build_baseline_scores(passages, relevant_pairs)
    inventory, observed_detectors, aggregates = _aggregate_evidence(
        retained_evidence,
        relevant_pairs,
        detector_families,
    )
    detector_ids = tuple(sorted(inventory))
    output_rows: list[PositiveControlEvaluationRow] = []

    for control in controls:
        mapped = bool(control.pairs)
        has_negative = control.negative is not None
        if not mapped:
            unavailable_reason = "control_not_mapped_to_complete_primary_verse_ranges"
        elif not has_negative:
            unavailable_reason = "no_nonbenchmark_matched_negative_available"
        else:
            unavailable_reason = ""
        negative_pair = (
            (control.negative.passage_a_id, control.negative.passage_b_id)
            if control.negative is not None
            else None
        )

        detector_results: list[MethodEvaluation] = []
        for detector_id in detector_ids:
            family = inventory[detector_id]
            if unavailable_reason:
                result = _unavailable_method(
                    detector_id,
                    "detector",
                    family=family,
                    reason=unavailable_reason,
                )
            elif detector_id not in observed_detectors:
                result = _unavailable_method(
                    detector_id,
                    "detector",
                    family=family,
                    reason="detector_not_present_in_retained_evidence",
                )
            else:
                assert negative_pair is not None
                detector_aggregates = {
                    pair: aggregate
                    for (observed_id, pair), aggregate in aggregates.items()
                    if observed_id == detector_id
                }
                result = _score_from_mapping(
                    detector_id,
                    "detector",
                    control.pairs,
                    negative_pair,
                    {pair: value.score for pair, value in detector_aggregates.items()},
                    family=family,
                    evidence_by_pair=detector_aggregates,
                )
            detector_results.append(result)

        family_results: list[FamilyEvaluation] = []
        for family in _FAMILIES:
            members = tuple(
                result.method_id for result in detector_results if result.family == family
            )
            available_members = tuple(
                result
                for result in detector_results
                if result.family == family and result.available
            )
            family_results.append(
                FamilyEvaluation(
                    family=family,
                    member_detector_ids=members,
                    available=bool(available_members),
                    recovered=any(result.recovered for result in available_members),
                    unavailable_reason=(
                        None
                        if available_members
                        else (unavailable_reason or "no_retained_detector_available_for_family")
                    ),
                )
            )

        baseline_results: list[MethodEvaluation] = []
        if unavailable_reason:
            baseline_results.extend(
                _unavailable_method(
                    baseline_id,
                    "baseline",
                    family="lexical" if baseline_id == "m7_lexical_rrf" else None,
                    reason=unavailable_reason,
                )
                for baseline_id in _BASELINE_IDS
            )
        else:
            assert negative_pair is not None
            baseline_results.append(
                _score_from_mapping(
                    "annotation_tfidf",
                    "baseline",
                    control.pairs,
                    negative_pair,
                    tfidf_scores,
                )
            )
            baseline_results.append(
                _score_from_mapping(
                    "bm25",
                    "baseline",
                    control.pairs,
                    negative_pair,
                    bm25_scores,
                )
            )
            if "m7_lexical_rrf" not in observed_detectors:
                baseline_results.append(
                    _unavailable_method(
                        "m7_lexical_rrf",
                        "baseline",
                        family="lexical",
                        reason="m7_lexical_rrf_not_present_in_retained_evidence",
                    )
                )
            else:
                m7_aggregates = {
                    pair: aggregate
                    for (detector_id, pair), aggregate in aggregates.items()
                    if detector_id == "m7_lexical_rrf"
                }
                baseline_results.append(
                    _score_from_mapping(
                        "m7_lexical_rrf",
                        "baseline",
                        control.pairs,
                        negative_pair,
                        {pair: value.score for pair, value in m7_aggregates.items()},
                        family="lexical",
                        evidence_by_pair=m7_aggregates,
                    )
                )
            random_positive_scores = {
                pair: _random_score(seed, control.row.control_id, "positive", pair)
                for pair in control.pairs
            }
            random_scores = {
                **random_positive_scores,
                negative_pair: _random_score(
                    seed,
                    control.row.control_id,
                    "matched_negative",
                    negative_pair,
                ),
            }
            baseline_results.append(
                _score_from_mapping(
                    "deterministic_random",
                    "baseline",
                    control.pairs,
                    negative_pair,
                    random_scores,
                )
            )

        mapping_reason: Literal[
            "complete_primary_verse_expansion",
            "missing_primary_verse",
            "no_nonbenchmark_matched_negative",
        ]
        if not mapped:
            mapping_reason = "missing_primary_verse"
        elif not has_negative:
            mapping_reason = "no_nonbenchmark_matched_negative"
        else:
            mapping_reason = "complete_primary_verse_expansion"
        output_rows.append(
            PositiveControlEvaluationRow(
                control_id=control.row.control_id,
                reference_a=control.row.reference_a,
                reference_b=control.row.reference_b,
                expanded_references_a=control.expanded_a,
                expanded_references_b=control.expanded_b,
                mapped_passage_ids_a=tuple(item.passage_id for item in control.passages_a),
                mapped_passage_ids_b=tuple(item.passage_id for item in control.passages_b),
                missing_references=control.missing,
                mapping_status="mapped" if mapped else "unmapped",
                mapping_reason=mapping_reason,
                corpus_pair=control.row.corpus_pair,
                relationship_class=control.row.relationship_class,
                relationship_family_id=control.row.relationship_family_id,
                leakage_group_id=control.row.leakage_group_id,
                split=control.row.split,
                provenance=PositiveControlProvenance(
                    source_id=control.row.source_id,
                    source_version=control.row.source_version,
                    source_file=control.row.source_file,
                    source_file_sha256=control.row.source_file_sha256,
                    source_record_locator=control.row.source_record_locator,
                    source_license=control.row.source_license,
                    verification_status=control.row.verification_status,
                    verification_method=control.row.verification_method,
                    verified_by=control.row.verified_by,
                    verified_at=control.row.verified_at.isoformat(),
                ),
                positive_pairs=tuple(_benchmark_pair_model(pair, by_id) for pair in control.pairs),
                matched_negative_pair=control.negative,
                detector_results=tuple(detector_results),
                family_results=tuple(family_results),
                baseline_results=tuple(baseline_results),
            )
        )

    rows_tuple = tuple(output_rows)
    return PositiveControlEvaluationReport(
        benchmark_id=dataset.config.benchmark_id,
        benchmark_config_sha256=dataset.validation.config_sha256,
        benchmark_data_sha256=dataset.validation.data_sha256,
        frozen_seed=seed,
        row_count=len(rows_tuple),
        mapped_control_count=sum(row.mapping_status == "mapped" for row in rows_tuple),
        unmapped_control_count=sum(row.mapping_status == "unmapped" for row in rows_tuple),
        detector_inventory=tuple(
            DetectorInventoryEntry(
                detector_id=detector_id,
                family=inventory[detector_id],
                retained_anywhere=detector_id in observed_detectors,
            )
            for detector_id in detector_ids
        ),
        baseline_definitions=(
            BaselineDefinition(
                baseline_id="annotation_tfidf",
                definition=(
                    "cosine of sublinear-TF smooth-IDF L2 vectors over prefixed lemma, root, "
                    "part-of-speech, morphology, semantic-domain, entity, participant, and "
                    "frame annotations"
                ),
                original_language_only=True,
            ),
            BaselineDefinition(
                baseline_id="bm25",
                definition=(
                    "maximum directional BM25 over the same prefixed annotation inventory "
                    "with k1=1.2, b=0.75, and binary query term frequency"
                ),
                original_language_only=True,
            ),
            BaselineDefinition(
                baseline_id="m7_lexical_rrf",
                definition=(
                    "maximum retained canonical M7 lexical reciprocal-rank-fusion score; "
                    "wholly absent retained M7 evidence is reported unavailable"
                ),
                original_language_only=False,
            ),
            BaselineDefinition(
                baseline_id="deterministic_random",
                definition=(
                    "unsigned first 64 SHA-256 bits of frozen seed, control ID, role, and "
                    "canonical passage pair divided by 2^64"
                ),
                original_language_only=False,
            ),
        ),
        rows=rows_tuple,
        summaries=_method_summaries(rows_tuple),
    )
