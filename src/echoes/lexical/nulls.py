"""Deterministic transparent null generators for lexical passage features."""

from __future__ import annotations

import hashlib
import random
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

NullFamily = Literal["within_book_reassignment", "frequency_preserving_synthetic"]
ConditioningScope = Literal["book", "broad_genre"]
PartitionKey = tuple[str, str, str]
SourceKey = tuple[str, str, str]
ConditioningKey = tuple[str, str, ConditioningScope, str]
ConditionedSequenceKey = tuple[ConditioningKey, int]


@dataclass(frozen=True, slots=True)
class PassageFeatures:
    """One source passage's eligible feature sequence and conditioning labels."""

    passage_id: str
    corpus: str
    book: str
    broad_genre: str
    representation: str
    features: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            (self.passage_id, self.corpus, self.book, self.broad_genre, self.representation)
        ):
            raise ValueError("passage identity and conditioning fields cannot be empty")
        if any(not feature for feature in self.features):
            raise ValueError("passage features cannot contain empty values")


@dataclass(frozen=True, slots=True)
class SimulatedPassage:
    """One null passage with a new identity and retained source linkage."""

    source_passage_id: str
    simulated_passage_id: str
    corpus: str
    book: str
    broad_genre: str
    representation: str
    features: tuple[str, ...]
    conditioning_scope: ConditioningScope
    conditioning_value: str


@dataclass(frozen=True, slots=True)
class NullReplicate:
    """A complete deterministic null replicate."""

    family: NullFamily
    seed: int
    passages: tuple[SimulatedPassage, ...]
    minimum_book_token_count: int | None = None

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("null seed cannot be negative")
        if self.family == "frequency_preserving_synthetic":
            if self.minimum_book_token_count is None or self.minimum_book_token_count < 1:
                raise ValueError("synthetic nulls require a positive book support threshold")
        elif self.minimum_book_token_count is not None:
            raise ValueError("within-book nulls cannot declare a synthetic support threshold")


@dataclass(frozen=True, slots=True)
class FrequencyDeviation:
    """Actual minus expected synthetic feature count in one conditioning pool."""

    corpus: str
    representation: str
    conditioning_scope: ConditioningScope
    conditioning_value: str
    feature: str
    expected_count: float
    actual_count: int
    deviation: float


@dataclass(frozen=True, slots=True)
class NullValidationResult:
    """Conservation findings for one generated null replicate."""

    family: NullFamily
    passage_count_preserved: bool
    passage_lengths_preserved: bool
    conditioning_labels_preserved: bool
    source_identities_replaced: bool
    representation_isolation_preserved: bool
    exact_feature_totals_preserved: bool | None
    sequence_digest_changed: bool
    no_original_sequences_copied: bool | None
    degenerate_units: tuple[str, ...]
    frequency_deviations: tuple[FrequencyDeviation, ...]
    errors: tuple[str, ...]
    frequency_deviation_count: int = 0
    maximum_absolute_frequency_deviation: float | None = None
    mean_absolute_frequency_deviation: float | None = None

    @property
    def is_valid(self) -> bool:
        """Whether every family-specific conservation contract passed."""

        return not self.errors


@dataclass(frozen=True, slots=True)
class _DiscreteSampler:
    """One canonical integer-weighted distribution prepared for repeated draws."""

    features: tuple[str, ...]
    cumulative_counts: tuple[int, ...]
    total: int

    @classmethod
    def from_counts(cls, counts: Mapping[str, int]) -> _DiscreteSampler:
        ordered = tuple(sorted(counts.items()))
        cumulative: list[int] = []
        total = 0
        for feature, count in ordered:
            if not feature or count < 1:
                raise ValueError("feature distributions require positive nonempty entries")
            total += count
            cumulative.append(total)
        if total < 1:
            raise ValueError("cannot sample from an empty feature distribution")
        return cls(
            features=tuple(feature for feature, _ in ordered),
            cumulative_counts=tuple(cumulative),
            total=total,
        )

    def draw(self, random_source: random.Random) -> str:
        selection = random_source.randrange(self.total)
        position = bisect_right(self.cumulative_counts, selection)
        return self.features[position]


@dataclass(frozen=True, slots=True)
class _ConditioningIndexes:
    """Reusable distributions and same-length source sequences for both null stages."""

    distributions: Mapping[ConditioningKey, Counter[str]]
    samplers: Mapping[ConditioningKey, _DiscreteSampler]
    forbidden_sequences: Mapping[ConditionedSequenceKey, frozenset[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class NullSourceContext:
    """Canonical, indexed source state reused by every null replicate and audit."""

    passages: tuple[PassageFeatures, ...]
    partitions: Mapping[PartitionKey, tuple[PassageFeatures, ...]]
    conditioning_indexes: _ConditioningIndexes
    source_by_key: Mapping[SourceKey, PassageFeatures]
    allowed_by_representation: Mapping[tuple[str, str], frozenset[str]]
    source_ids: frozenset[str]
    feature_totals_by_book: Mapping[PartitionKey, Counter[str]]
    sequence_digest: str
    nonempty_passage_count: int


type NullSourceInput = Sequence[PassageFeatures] | NullSourceContext


def _conditioning_key(
    passage: PassageFeatures | SimulatedPassage,
    *,
    scope: ConditioningScope,
) -> ConditioningKey:
    value = passage.book if scope == "book" else passage.broad_genre
    return (passage.corpus, passage.representation, scope, value)


def _build_conditioning_indexes(
    source: Sequence[PassageFeatures],
) -> _ConditioningIndexes:
    distributions: dict[ConditioningKey, Counter[str]] = {}
    mutable_forbidden: dict[ConditionedSequenceKey, set[tuple[str, ...]]] = {}
    for passage in source:
        for scope in ("book", "broad_genre"):
            key = _conditioning_key(passage, scope=scope)
            distributions.setdefault(key, Counter()).update(passage.features)
            mutable_forbidden.setdefault((key, len(passage.features)), set()).add(passage.features)
    samplers = {
        key: _DiscreteSampler.from_counts(counts) for key, counts in distributions.items() if counts
    }
    return _ConditioningIndexes(
        distributions=distributions,
        samplers=samplers,
        forbidden_sequences={key: frozenset(values) for key, values in mutable_forbidden.items()},
    )


def _source_key(passage: PassageFeatures | SimulatedPassage) -> SourceKey:
    passage_id = (
        passage.passage_id if isinstance(passage, PassageFeatures) else passage.source_passage_id
    )
    return (passage.corpus, passage.representation, passage_id)


def _partition_key(passage: PassageFeatures | SimulatedPassage) -> PartitionKey:
    return (passage.corpus, passage.representation, passage.book)


def _canonical_source(passages: Sequence[PassageFeatures]) -> tuple[PassageFeatures, ...]:
    supplied = tuple(passages)
    if all(
        _source_key(supplied[index - 1]) <= _source_key(supplied[index])
        for index in range(1, len(supplied))
    ):
        canonical = supplied
    else:
        canonical = tuple(sorted(supplied, key=_source_key))
    previous: SourceKey | None = None
    for passage in canonical:
        key = _source_key(passage)
        if key == previous:
            raise ValueError("source passages must be unique within corpus and representation")
        previous = key
    return canonical


def _derived_seed(seed: int, *parts: str) -> int:
    payload = "\x1f".join((str(seed), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _simulated_id(
    family: NullFamily, seed: int, corpus: str, representation: str, source_passage_id: str
) -> str:
    payload = "\x1f".join((family, str(seed), corpus, representation, source_passage_id)).encode(
        "utf-8"
    )
    return f"null_{hashlib.sha256(payload).hexdigest()}"


def _rotate_until_changed(values: list[str], original: Sequence[str]) -> list[str]:
    if values != list(original) or len(set(values)) <= 1:
        return values
    for offset in range(1, len(values)):
        rotated = values[offset:] + values[:offset]
        if rotated != list(original):
            return rotated
    return values


def within_book_reassignment(passages: NullSourceInput, *, seed: int) -> NullReplicate:
    """Permute each book's feature-token pool and repartition to exact lengths."""

    if seed < 0:
        raise ValueError("null seed cannot be negative")
    context = _coerce_null_source(passages)
    source = context.passages
    simulated_by_key: dict[SourceKey, SimulatedPassage] = {}
    for key in sorted(context.partitions):
        members = context.partitions[key]
        original_pool = [feature for passage in members for feature in passage.features]
        reassigned_pool = list(original_pool)
        random_source = random.Random(_derived_seed(seed, "within_book_reassignment", *key))
        random_source.shuffle(reassigned_pool)
        reassigned_pool = _rotate_until_changed(reassigned_pool, original_pool)
        offset = 0
        for passage in members:
            length = len(passage.features)
            features = tuple(reassigned_pool[offset : offset + length])
            offset += length
            simulated = SimulatedPassage(
                source_passage_id=passage.passage_id,
                simulated_passage_id=_simulated_id(
                    "within_book_reassignment",
                    seed,
                    passage.corpus,
                    passage.representation,
                    passage.passage_id,
                ),
                corpus=passage.corpus,
                book=passage.book,
                broad_genre=passage.broad_genre,
                representation=passage.representation,
                features=features,
                conditioning_scope="book",
                conditioning_value=passage.book,
            )
            simulated_by_key[_source_key(simulated)] = simulated
    return NullReplicate(
        family="within_book_reassignment",
        seed=seed,
        passages=tuple(simulated_by_key[_source_key(passage)] for passage in source),
    )


def _avoid_copied_sequences(
    sampled: list[str],
    forbidden: frozenset[tuple[str, ...]],
    sampler: _DiscreteSampler,
    random_source: random.Random,
) -> list[str]:
    if tuple(sampled) not in forbidden or not sampled or len(sampler.features) <= 1:
        return sampled
    for offset in range(1, len(sampled)):
        rotated = sampled[offset:] + sampled[:offset]
        if tuple(rotated) not in forbidden:
            return rotated
    for _ in range(256):
        redrawn = [sampler.draw(random_source) for _ in sampled]
        if tuple(redrawn) not in forbidden:
            return redrawn
    for position in range(len(sampled)):
        original_feature = sampled[position]
        for alternative in sampler.features:
            if alternative == original_feature:
                continue
            changed = list(sampled)
            changed[position] = alternative
            if tuple(changed) not in forbidden:
                return changed
    return sampled


def frequency_preserving_synthetic(
    passages: NullSourceInput,
    *,
    seed: int,
    minimum_book_token_count: int,
) -> NullReplicate:
    """Sample exact-length passages from book or fallback genre distributions."""

    if seed < 0:
        raise ValueError("null seed cannot be negative")
    if minimum_book_token_count < 1:
        raise ValueError("minimum_book_token_count must be positive")
    context = _coerce_null_source(passages)
    source = context.passages
    indexes = context.conditioning_indexes
    book_totals = {
        key: sampler.total for key, sampler in indexes.samplers.items() if key[2] == "book"
    }

    simulated: list[SimulatedPassage] = []
    for passage in source:
        book_key = _conditioning_key(passage, scope="book")
        if book_totals.get(book_key, 0) >= minimum_book_token_count:
            scope: ConditioningScope = "book"
            conditioning_value = passage.book
            conditioning_key = book_key
        else:
            scope = "broad_genre"
            conditioning_value = passage.broad_genre
            conditioning_key = _conditioning_key(passage, scope="broad_genre")
        sampler = indexes.samplers.get(conditioning_key)
        if sampler is None and passage.features:
            raise ValueError(f"conditioning distribution is empty: {conditioning_key!r}")
        random_source = random.Random(
            _derived_seed(
                seed,
                "frequency_preserving_synthetic",
                passage.corpus,
                passage.representation,
                passage.passage_id,
            )
        )
        sampled = (
            [sampler.draw(random_source) for _ in passage.features] if sampler is not None else []
        )
        forbidden = indexes.forbidden_sequences.get(
            (conditioning_key, len(passage.features)),
            frozenset(),
        )
        if sampler is not None:
            sampled = _avoid_copied_sequences(sampled, forbidden, sampler, random_source)
        simulated.append(
            SimulatedPassage(
                source_passage_id=passage.passage_id,
                simulated_passage_id=_simulated_id(
                    "frequency_preserving_synthetic",
                    seed,
                    passage.corpus,
                    passage.representation,
                    passage.passage_id,
                ),
                corpus=passage.corpus,
                book=passage.book,
                broad_genre=passage.broad_genre,
                representation=passage.representation,
                features=tuple(sampled),
                conditioning_scope=scope,
                conditioning_value=conditioning_value,
            )
        )
    return NullReplicate(
        family="frequency_preserving_synthetic",
        seed=seed,
        passages=tuple(simulated),
        minimum_book_token_count=minimum_book_token_count,
    )


def _feature_totals_by_book(
    passages: Iterable[PassageFeatures | SimulatedPassage],
) -> dict[PartitionKey, Counter[str]]:
    totals: dict[PartitionKey, Counter[str]] = {}
    for passage in passages:
        totals.setdefault(_partition_key(passage), Counter()).update(passage.features)
    return totals


def _sequence_digest(passages: Iterable[PassageFeatures | SimulatedPassage]) -> str:
    digest = hashlib.sha256()
    for passage in sorted(passages, key=_source_key):
        digest.update("\x1e".join(_source_key(passage)).encode("utf-8"))
        digest.update(b"\x00")
        for feature in passage.features:
            digest.update(feature.encode("utf-8"))
            digest.update(b"\x1f")
    return digest.hexdigest()


def prepare_null_source(passages: Sequence[PassageFeatures]) -> NullSourceContext:
    """Canonicalize and index immutable source invariants exactly once."""

    source = _canonical_source(passages)
    partitions: dict[PartitionKey, list[PassageFeatures]] = {}
    source_by_key: dict[SourceKey, PassageFeatures] = {}
    allowed: dict[tuple[str, str], set[str]] = {}
    for passage in source:
        partitions.setdefault(_partition_key(passage), []).append(passage)
        source_by_key[_source_key(passage)] = passage
        allowed.setdefault((passage.corpus, passage.representation), set()).update(passage.features)
    return NullSourceContext(
        passages=source,
        partitions={key: tuple(values) for key, values in partitions.items()},
        conditioning_indexes=_build_conditioning_indexes(source),
        source_by_key=source_by_key,
        allowed_by_representation={key: frozenset(values) for key, values in allowed.items()},
        source_ids=frozenset(passage.passage_id for passage in source),
        feature_totals_by_book=_feature_totals_by_book(source),
        sequence_digest=_sequence_digest(source),
        nonempty_passage_count=sum(bool(passage.features) for passage in source),
    )


def _coerce_null_source(passages: NullSourceInput) -> NullSourceContext:
    if isinstance(passages, NullSourceContext):
        return passages
    return prepare_null_source(passages)


def _base_validation(
    context: NullSourceContext, replicate: NullReplicate
) -> tuple[
    Mapping[SourceKey, PassageFeatures],
    dict[SourceKey, SimulatedPassage],
    bool,
    bool,
    bool,
    bool,
    bool,
    list[str],
]:
    source_by_key = context.source_by_key
    simulated_by_key = {_source_key(passage): passage for passage in replicate.passages}
    passage_count_preserved = len(context.passages) == len(replicate.passages)
    same_keys = set(source_by_key) == set(simulated_by_key)
    lengths_preserved = same_keys and all(
        len(source_by_key[key].features) == len(simulated_by_key[key].features)
        for key in source_by_key
    )
    labels_preserved = same_keys and all(
        (
            source_by_key[key].corpus,
            source_by_key[key].book,
            source_by_key[key].broad_genre,
            source_by_key[key].representation,
        )
        == (
            simulated_by_key[key].corpus,
            simulated_by_key[key].book,
            simulated_by_key[key].broad_genre,
            simulated_by_key[key].representation,
        )
        for key in source_by_key
    )
    simulated_ids = [passage.simulated_passage_id for passage in replicate.passages]
    identities_replaced = len(simulated_ids) == len(set(simulated_ids)) and not set(
        simulated_ids
    ).intersection(context.source_ids)
    representation_isolated = all(
        set(passage.features).issubset(
            context.allowed_by_representation[(passage.corpus, passage.representation)]
        )
        for passage in replicate.passages
    )
    errors: list[str] = []
    if not passage_count_preserved or not same_keys:
        errors.append("passage_count_or_source_keys_changed")
    if not lengths_preserved:
        errors.append("passage_lengths_changed")
    if not labels_preserved:
        errors.append("conditioning_labels_changed")
    if not identities_replaced:
        errors.append("simulated_identities_not_unique_or_replaced")
    if not representation_isolated:
        errors.append("corpus_or_representation_vocabulary_mixed")
    return (
        source_by_key,
        simulated_by_key,
        passage_count_preserved,
        lengths_preserved,
        labels_preserved,
        identities_replaced,
        representation_isolated,
        errors,
    )


def validate_within_book_reassignment(
    passages: NullSourceInput, replicate: NullReplicate
) -> NullValidationResult:
    """Validate exact token, length, identity, conditioning, and sequence contracts."""

    if replicate.family != "within_book_reassignment":
        raise ValueError("replicate is not a within-book reassignment null")
    context = _coerce_null_source(passages)
    (
        _,
        _,
        passage_count_preserved,
        lengths_preserved,
        labels_preserved,
        identities_replaced,
        representation_isolated,
        errors,
    ) = _base_validation(context, replicate)
    within_book_conditioning = all(
        passage.conditioning_scope == "book" and passage.conditioning_value == passage.book
        for passage in replicate.passages
    )
    labels_preserved = labels_preserved and within_book_conditioning
    if not within_book_conditioning:
        errors.append("within_book_conditioning_changed")
    source_totals = context.feature_totals_by_book
    simulated_totals = _feature_totals_by_book(replicate.passages)
    exact_totals = source_totals == simulated_totals
    if not exact_totals:
        errors.append("within_book_feature_totals_changed")
    degenerate = tuple(
        "|".join(key)
        for key, counts in sorted(source_totals.items())
        if sum(counts.values()) <= 1 or len(counts) <= 1
    )
    changed = context.sequence_digest != _sequence_digest(replicate.passages)
    if not changed and len(degenerate) != len(source_totals):
        errors.append("nondegenerate_sequence_digest_unchanged")
    return NullValidationResult(
        family=replicate.family,
        passage_count_preserved=passage_count_preserved,
        passage_lengths_preserved=lengths_preserved,
        conditioning_labels_preserved=labels_preserved,
        source_identities_replaced=identities_replaced,
        representation_isolation_preserved=representation_isolated,
        exact_feature_totals_preserved=exact_totals,
        sequence_digest_changed=changed,
        no_original_sequences_copied=None,
        degenerate_units=degenerate,
        frequency_deviations=(),
        errors=tuple(errors),
    )


def _conditioning_distribution(
    indexes: _ConditioningIndexes, passage: SimulatedPassage
) -> Counter[str]:
    key: ConditioningKey = (
        passage.corpus,
        passage.representation,
        passage.conditioning_scope,
        passage.conditioning_value,
    )
    return indexes.distributions.get(key, Counter())


def _synthetic_deviations(
    indexes: _ConditioningIndexes,
    simulated: tuple[SimulatedPassage, ...],
    *,
    retain_details: bool,
) -> tuple[tuple[FrequencyDeviation, ...], int, float | None, float | None]:
    grouped: dict[tuple[str, str, ConditioningScope, str], list[SimulatedPassage]] = {}
    for passage in simulated:
        key = (
            passage.corpus,
            passage.representation,
            passage.conditioning_scope,
            passage.conditioning_value,
        )
        grouped.setdefault(key, []).append(passage)
    deviations: list[FrequencyDeviation] = []
    deviation_count = 0
    absolute_deviation_sum = 0.0
    maximum_absolute_deviation = 0.0
    for key, members in sorted(grouped.items()):
        distribution = _conditioning_distribution(indexes, members[0])
        distribution_total = sum(distribution.values())
        draws = sum(len(member.features) for member in members)
        actual = Counter(feature for member in members for feature in member.features)
        for feature in sorted(set(distribution).union(actual)):
            expected = (
                draws * distribution.get(feature, 0) / distribution_total
                if distribution_total
                else 0.0
            )
            actual_count = actual.get(feature, 0)
            deviation = actual_count - expected
            absolute_deviation = abs(deviation)
            deviation_count += 1
            absolute_deviation_sum += absolute_deviation
            maximum_absolute_deviation = max(maximum_absolute_deviation, absolute_deviation)
            if retain_details:
                deviations.append(
                    FrequencyDeviation(
                        corpus=key[0],
                        representation=key[1],
                        conditioning_scope=key[2],
                        conditioning_value=key[3],
                        feature=feature,
                        expected_count=expected,
                        actual_count=actual_count,
                        deviation=deviation,
                    )
                )
    return (
        tuple(deviations),
        deviation_count,
        maximum_absolute_deviation if deviation_count else None,
        absolute_deviation_sum / deviation_count if deviation_count else None,
    )


def _all_possible_sequences_are_forbidden(
    vocabulary_size: int, sequence_length: int, forbidden_count: int
) -> bool:
    possible_count = 1
    for _ in range(sequence_length):
        possible_count *= vocabulary_size
        if possible_count > forbidden_count:
            return False
    return forbidden_count >= possible_count


def validate_frequency_preserving_synthetic(
    passages: NullSourceInput,
    replicate: NullReplicate,
    *,
    retain_frequency_deviation_details: bool = True,
) -> NullValidationResult:
    """Validate exact synthetic lengths/labels and measure frequency deviations."""

    if replicate.family != "frequency_preserving_synthetic":
        raise ValueError("replicate is not a frequency-preserving synthetic null")
    context = _coerce_null_source(passages)
    (
        source_by_key,
        simulated_by_key,
        passage_count_preserved,
        lengths_preserved,
        labels_preserved,
        identities_replaced,
        representation_isolated,
        errors,
    ) = _base_validation(context, replicate)
    minimum_book_token_count = replicate.minimum_book_token_count
    assert minimum_book_token_count is not None
    indexes = context.conditioning_indexes
    book_totals = {
        (key[0], key[1], key[3]): sum(counts.values())
        for key, counts in indexes.distributions.items()
        if key[2] == "book"
    }
    synthetic_conditioning = all(
        (
            passage.conditioning_scope,
            passage.conditioning_value,
        )
        == (
            ("book", passage.book)
            if book_totals[_partition_key(passage)] >= minimum_book_token_count
            else ("broad_genre", passage.broad_genre)
        )
        for passage in replicate.passages
    )
    labels_preserved = labels_preserved and synthetic_conditioning
    if not synthetic_conditioning:
        errors.append("synthetic_conditioning_changed")
    conditioning_vocabulary_preserved = all(
        set(passage.features).issubset(_conditioning_distribution(indexes, passage))
        for passage in replicate.passages
    )
    if not conditioning_vocabulary_preserved:
        errors.append("synthetic_conditioning_vocabulary_mixed")
    degenerate: list[str] = []
    copied_nondegenerate: list[str] = []
    for key in sorted(set(source_by_key).intersection(simulated_by_key)):
        original = source_by_key[key]
        simulated = simulated_by_key[key]
        distribution = _conditioning_distribution(indexes, simulated)
        unit_id = "|".join(key)
        conditioning_key: ConditioningKey = (
            simulated.corpus,
            simulated.representation,
            simulated.conditioning_scope,
            simulated.conditioning_value,
        )
        forbidden = indexes.forbidden_sequences.get(
            (conditioning_key, len(original.features)),
            frozenset(),
        )
        if original.features and simulated.features in forbidden:
            if _all_possible_sequences_are_forbidden(
                len(distribution), len(original.features), len(forbidden)
            ):
                degenerate.append(unit_id)
            else:
                copied_nondegenerate.append(unit_id)
    no_copies = not copied_nondegenerate
    if not no_copies:
        errors.append("synthetic_original_sequence_copied")
    changed = context.sequence_digest != _sequence_digest(replicate.passages)
    if not changed and len(degenerate) != context.nonempty_passage_count:
        errors.append("nondegenerate_sequence_digest_unchanged")
    deviations, deviation_count, maximum_deviation, mean_deviation = _synthetic_deviations(
        indexes,
        replicate.passages,
        retain_details=retain_frequency_deviation_details,
    )
    return NullValidationResult(
        family=replicate.family,
        passage_count_preserved=passage_count_preserved,
        passage_lengths_preserved=lengths_preserved,
        conditioning_labels_preserved=labels_preserved,
        source_identities_replaced=identities_replaced,
        representation_isolation_preserved=representation_isolated,
        exact_feature_totals_preserved=None,
        sequence_digest_changed=changed,
        no_original_sequences_copied=no_copies,
        degenerate_units=tuple(degenerate),
        frequency_deviations=deviations,
        errors=tuple(errors),
        frequency_deviation_count=deviation_count,
        maximum_absolute_frequency_deviation=maximum_deviation,
        mean_absolute_frequency_deviation=mean_deviation,
    )


def validate_null_replicate(
    passages: NullSourceInput, replicate: NullReplicate
) -> NullValidationResult:
    """Dispatch to the complete conservation contract for ``replicate.family``."""

    if replicate.family == "within_book_reassignment":
        return validate_within_book_reassignment(passages, replicate)
    return validate_frequency_preserving_synthetic(passages, replicate)
