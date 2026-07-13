"""Deterministic nonlexical presumed-negative generation.

The generator uses indexed passage pools and bounded deterministic probing.  It
never constructs a passage Cartesian product and never describes absence from
the known-link graph as proof of nonrelationship.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Set
from dataclasses import dataclass
from typing import Literal

from echoes.benchmarks.models import BenchmarkPresumedNegativeRow

NegativeStrategy = Literal[
    "length_matched_random_unlinked",
    "same_book_unlinked",
    "same_book_pair_unlinked",
    "same_broad_genre_unlinked",
    "nearby_context_unlinked",
]
Partition = Literal["train", "development", "test"]
CanonicalPassagePair = tuple[str, str]


class PresumedNegativeGenerationError(ValueError):
    """Raised when governed constraints cannot produce the requested ratio."""


@dataclass(frozen=True, slots=True)
class NegativePassage:
    """Minimal verse-passage facts used by nonlexical sampling."""

    passage_id: str
    corpus: str
    book: str
    broad_genre: str
    token_count: int
    ordinal_in_book: int
    partition: Partition
    overlapping_passage_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not all((self.passage_id, self.corpus, self.book, self.broad_genre)):
            raise ValueError("negative-passage identity and strata are required")
        if self.token_count < 1 or self.ordinal_in_book < 1:
            raise ValueError("negative passages require positive length and book ordinal")


@dataclass(frozen=True, slots=True)
class KnownPositivePair:
    """One split-eligible mapped positive used as a sampling template."""

    relationship_id: str
    passage_a_id: str
    passage_b_id: str

    def __post_init__(self) -> None:
        if not self.relationship_id or not self.passage_a_id or not self.passage_b_id:
            raise ValueError("known-positive relationship and passage IDs are required")
        if self.passage_a_id == self.passage_b_id:
            raise ValueError("known-positive passages must be distinct")


@dataclass(frozen=True, slots=True)
class PresumedNegativeDefinition:
    """One deterministic presumed-negative generation contract."""

    benchmark_version: str
    strategy: NegativeStrategy
    split_strategy: str
    generation_config_hash: str
    seed: int
    ratio: float = 1.0
    length_tolerance: int = 2
    nearby_distance: int = 5
    max_candidate_attempts: int = 128

    def __post_init__(self) -> None:
        if not self.benchmark_version or not self.split_strategy:
            raise ValueError("benchmark version and split strategy are required")
        if len(self.generation_config_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.generation_config_hash
        ):
            raise ValueError("generation_config_hash must be a lowercase SHA-256")
        if self.seed < 0 or self.ratio < 0:
            raise ValueError("seed and presumed-negative ratio cannot be negative")
        if self.length_tolerance < 0 or self.nearby_distance < 1:
            raise ValueError("length tolerance and nearby distance are invalid")
        if self.max_candidate_attempts < 1:
            raise ValueError("max_candidate_attempts must be positive")


def canonical_passage_pair(first: str, second: str) -> CanonicalPassagePair:
    """Return the direction-independent key shared with persisted validation."""

    return tuple(sorted((first, second)))  # type: ignore[return-value]


def iter_mapped_positive_pairs(
    first_target_ids: Iterable[str], second_target_ids: Iterable[str]
) -> Iterator[CanonicalPassagePair]:
    """Expand two mapped endpoint spans into canonical passage-pair graph keys."""

    second_targets = tuple(second_target_ids)
    for first in first_target_ids:
        for second in second_targets:
            if first != second:
                yield canonical_passage_pair(first, second)


def _probe_order(
    pool: tuple[str, ...],
    *,
    seed: int,
    strategy: str,
    anchor_id: str,
    round_number: int,
    limit: int,
) -> tuple[str, ...]:
    """Return a bounded deterministic probe without materializing a full permutation."""

    if len(pool) < 2 or limit >= len(pool):
        return pool[:limit]
    material = f"{seed}|{strategy}|{anchor_id}|{round_number}".encode()
    digest = hashlib.sha256(material).digest()
    start = int.from_bytes(digest[:8], "big") % len(pool)
    step = int.from_bytes(digest[8:16], "big") % len(pool)
    step = step or 1
    while math.gcd(step, len(pool)) != 1:
        step += 1
    return tuple(pool[(start + offset * step) % len(pool)] for offset in range(limit))


def _contrastive_id(
    definition: PresumedNegativeDefinition, passage_a_id: str, passage_b_id: str
) -> str:
    payload = json.dumps(
        {
            "benchmark_version": definition.benchmark_version,
            "generation_config_hash": definition.generation_config_hash,
            "negative_strategy": definition.strategy,
            "passage_a_id": passage_a_id,
            "passage_b_id": passage_b_id,
            "seed": definition.seed,
            "split_strategy": definition.split_strategy,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"BC_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _pair_label(first: str, second: str) -> str:
    return "|".join(sorted((first, second)))


class _PassageIndexes:
    def __init__(self, passages: list[NegativePassage]) -> None:
        self.by_id = {passage.passage_id: passage for passage in passages}
        self.by_partition: dict[str, list[str]] = defaultdict(list)
        self.by_book: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.by_genre: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.by_length: dict[tuple[str, int], list[str]] = defaultdict(list)
        self.by_context: dict[tuple[str, str], list[str]] = defaultdict(list)
        for passage in passages:
            self.by_partition[passage.partition].append(passage.passage_id)
            self.by_book[(passage.partition, passage.book)].append(passage.passage_id)
            self.by_genre[(passage.partition, passage.broad_genre)].append(passage.passage_id)
            self.by_length[(passage.partition, passage.token_count)].append(passage.passage_id)
            self.by_context[(passage.partition, passage.book)].append(passage.passage_id)
        for values in (
            *self.by_partition.values(),
            *self.by_book.values(),
            *self.by_genre.values(),
            *self.by_length.values(),
        ):
            values.sort()
        for values in self.by_context.values():
            values.sort(key=lambda passage_id: (self.by_id[passage_id].ordinal_in_book, passage_id))

    def pool(
        self,
        *,
        anchor: NegativePassage,
        template_other: NegativePassage,
        definition: PresumedNegativeDefinition,
    ) -> tuple[str, ...]:
        if definition.strategy == "length_matched_random_unlinked":
            candidates: list[str] = []
            for length in range(
                max(1, anchor.token_count - definition.length_tolerance),
                anchor.token_count + definition.length_tolerance + 1,
            ):
                candidates.extend(self.by_length.get((anchor.partition, length), ()))
            return tuple(sorted(set(candidates)))
        if definition.strategy == "same_book_unlinked":
            return tuple(self.by_book.get((anchor.partition, anchor.book), ()))
        if definition.strategy == "same_book_pair_unlinked":
            return tuple(self.by_book.get((anchor.partition, template_other.book), ()))
        if definition.strategy == "same_broad_genre_unlinked":
            return tuple(self.by_genre.get((anchor.partition, anchor.broad_genre), ()))
        if definition.strategy == "nearby_context_unlinked":
            values = self.by_context.get((anchor.partition, anchor.book), ())
            return tuple(
                passage_id
                for passage_id in values
                if abs(self.by_id[passage_id].ordinal_in_book - anchor.ordinal_in_book)
                <= definition.nearby_distance
            )
        raise AssertionError(f"unsupported negative strategy: {definition.strategy}")


def _candidate_is_valid(
    anchor: NegativePassage,
    candidate: NegativePassage,
    *,
    definition: PresumedNegativeDefinition,
    known_pairs: Set[CanonicalPassagePair],
    generated_pairs: set[tuple[str, str]],
) -> bool:
    pair = canonical_passage_pair(anchor.passage_id, candidate.passage_id)
    if anchor.passage_id == candidate.passage_id:
        return False
    if pair in known_pairs or pair in generated_pairs:
        return False
    if candidate.partition != anchor.partition:
        return False
    if (
        candidate.passage_id in anchor.overlapping_passage_ids
        or anchor.passage_id in candidate.overlapping_passage_ids
    ):
        return False
    if definition.strategy == "length_matched_random_unlinked" and (
        abs(anchor.token_count - candidate.token_count) > definition.length_tolerance
    ):
        return False
    if definition.strategy == "same_book_unlinked" and candidate.book != anchor.book:
        return False
    if (
        definition.strategy == "same_broad_genre_unlinked"
        and candidate.broad_genre != anchor.broad_genre
    ):
        return False
    return not (
        definition.strategy == "nearby_context_unlinked"
        and (
            candidate.book != anchor.book
            or abs(candidate.ordinal_in_book - anchor.ordinal_in_book) > definition.nearby_distance
        )
    )


def generate_presumed_negatives(
    passages: tuple[NegativePassage, ...] | list[NegativePassage],
    known_positives: tuple[KnownPositivePair, ...] | list[KnownPositivePair],
    definition: PresumedNegativeDefinition,
    *,
    positive_graph_pairs: Set[CanonicalPassagePair] | None = None,
) -> tuple[BenchmarkPresumedNegativeRow, ...]:
    """Generate negatives from eligible templates against the complete positive graph.

    ``known_positives`` defines eligible sampling templates.  The optional
    ``positive_graph_pairs`` contains every mapped positive passage pair,
    including range expansions and relationships excluded from the template
    split.  Keeping those roles separate prevents an excluded or range-mapped
    known link from being mislabeled as a presumed negative.
    """

    ordered_passages = sorted(passages, key=lambda item: item.passage_id)
    indexes = _PassageIndexes(ordered_passages)
    if len(indexes.by_id) != len(ordered_passages):
        raise ValueError("passage IDs must be unique before negative generation")

    ordered_positives = sorted(
        known_positives,
        key=lambda item: (item.relationship_id, item.passage_a_id, item.passage_b_id),
    )
    template_pairs = frozenset(
        canonical_passage_pair(item.passage_a_id, item.passage_b_id) for item in ordered_positives
    )
    known_pairs = template_pairs if positive_graph_pairs is None else positive_graph_pairs
    if not template_pairs.issubset(known_pairs):
        raise ValueError("positive graph must include every eligible positive template pair")
    templates: list[tuple[NegativePassage, NegativePassage]] = []
    for item in ordered_positives:
        first = indexes.by_id.get(item.passage_a_id)
        second = indexes.by_id.get(item.passage_b_id)
        if first is None or second is None:
            raise ValueError(f"known positive {item.relationship_id} references an unknown passage")
        if first.partition != second.partition:
            raise ValueError(f"known positive {item.relationship_id} crosses split partitions")
        templates.append((first, second))

    requested_count = math.ceil(len(templates) * definition.ratio)
    if requested_count == 0:
        return ()

    generated_pairs: set[tuple[str, str]] = set()
    rows: list[BenchmarkPresumedNegativeRow] = []
    rounds = max(1, math.ceil(definition.ratio) + 1)
    for round_number in range(rounds):
        for template_index, (first, second) in enumerate(templates):
            if len(rows) >= requested_count:
                break
            anchor, template_other = (
                (first, second) if (template_index + round_number) % 2 == 0 else (second, first)
            )
            pool = indexes.pool(
                anchor=anchor,
                template_other=template_other,
                definition=definition,
            )
            candidate: NegativePassage | None = None
            for passage_id in _probe_order(
                pool,
                seed=definition.seed,
                strategy=definition.strategy,
                anchor_id=anchor.passage_id,
                round_number=round_number,
                limit=definition.max_candidate_attempts,
            ):
                proposed = indexes.by_id[passage_id]
                if _candidate_is_valid(
                    anchor,
                    proposed,
                    definition=definition,
                    known_pairs=known_pairs,
                    generated_pairs=generated_pairs,
                ):
                    candidate = proposed
                    break
            if candidate is None:
                continue

            passage_a_id, passage_b_id = canonical_passage_pair(
                anchor.passage_id, candidate.passage_id
            )
            passage_a = indexes.by_id[passage_a_id]
            passage_b = indexes.by_id[passage_b_id]
            pair = (passage_a_id, passage_b_id)
            generated_pairs.add(pair)
            rows.append(
                BenchmarkPresumedNegativeRow(
                    contrastive_id=_contrastive_id(definition, passage_a_id, passage_b_id),
                    benchmark_version=definition.benchmark_version,
                    passage_a_id=passage_a_id,
                    passage_b_id=passage_b_id,
                    corpus_pair=_pair_label(passage_a.corpus, passage_b.corpus),
                    negative_strategy=definition.strategy,
                    presumed_negative=True,
                    positive_graph_checked=True,
                    reverse_pair_checked=True,
                    passage_overlap_checked=True,
                    leakage_checked=True,
                    length_difference=abs(passage_a.token_count - passage_b.token_count),
                    book_pair=_pair_label(passage_a.book, passage_b.book),
                    genre_pair=_pair_label(passage_a.broad_genre, passage_b.broad_genre),
                    split_strategy=definition.split_strategy,
                    partition=passage_a.partition,
                    seed=definition.seed,
                    generation_config_hash=definition.generation_config_hash,
                    notes=(
                        "Presumed negative only: absence from configured known-link sources "
                        "is not proof of nonrelationship."
                    ),
                )
            )
        if len(rows) >= requested_count:
            break

    if len(rows) != requested_count:
        raise PresumedNegativeGenerationError(
            f"requested {requested_count} presumed negatives for {definition.strategy}, "
            f"but governed constraints produced {len(rows)}"
        )
    return tuple(sorted(rows, key=lambda row: row.contrastive_id))
