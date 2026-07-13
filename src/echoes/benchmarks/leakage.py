"""Explicit, non-global leakage views for known-link relationships.

The benchmark keeps several small, inspectable group systems instead of
collapsing the graph into one unrestricted connected component.  Interval
overlaps use atomic book-and-ordinal membership keys: a hub reference produces
one group with N membership rows, not all N-squared relationship pairs.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby, pairwise
from typing import Literal

from echoes.benchmarks.models import BenchmarkLeakageGroupRow

LeakageGroupType = Literal[
    "exact_directed_pair",
    "exact_unordered_pair",
    "duplicate_source_records",
    "shared_endpoint",
    "overlapping_endpoint_range",
    "shared_target_passage",
    "overlapping_target_passage",
    "canonical_book_pair",
    "relationship_family",
    "shared_source_provenance",
]


@dataclass(frozen=True, slots=True)
class LeakageEndpoint:
    """The source and mapped interval facts needed for leakage grouping.

    ``source_start_ordinal`` and ``source_end_ordinal`` are ordinals within the
    named source-scheme book.  Upstream parsing owns their derivation.  Target
    ordinals have the same meaning for the mapped passage corpus and are
    optional when no interval mapping is available.
    """

    endpoint_key: str
    source_book: str
    source_start_ordinal: int
    source_end_ordinal: int
    target_passage_ids: tuple[str, ...] = ()
    target_book: str | None = None
    target_start_ordinal: int | None = None
    target_end_ordinal: int | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_key or not self.source_book:
            raise ValueError("leakage endpoints require a key and source book")
        if self.source_start_ordinal < 1 or self.source_end_ordinal < self.source_start_ordinal:
            raise ValueError("source endpoint ordinals must form a positive ordered interval")
        target_coordinates = (
            self.target_book,
            self.target_start_ordinal,
            self.target_end_ordinal,
        )
        populated = sum(value is not None for value in target_coordinates)
        if populated not in {0, 3}:
            raise ValueError("target interval coordinates must be wholly present or absent")
        if self.target_start_ordinal is not None and (
            self.target_start_ordinal < 1
            or self.target_end_ordinal is None
            or self.target_end_ordinal < self.target_start_ordinal
        ):
            raise ValueError("target endpoint ordinals must form a positive ordered interval")


@dataclass(frozen=True, slots=True)
class RelationshipLeakageInput:
    """One relationship's stable pair, endpoint, and provenance facts."""

    relationship_id: str
    canonical_directed_pair_id: str
    canonical_undirected_pair_id: str
    endpoints: tuple[LeakageEndpoint, LeakageEndpoint]
    duplicate_source_record_keys: tuple[str, ...] = ()
    source_provenance_keys: tuple[str, ...] = ()
    relationship_family_key: str | None = None

    def __post_init__(self) -> None:
        if not self.relationship_id:
            raise ValueError("relationship_id is required")
        if not self.canonical_directed_pair_id or not self.canonical_undirected_pair_id:
            raise ValueError("directed and unordered pair IDs are required")
        if len(self.endpoints) != 2:
            raise ValueError("leakage grouping requires exactly two endpoints")


@dataclass(frozen=True, slots=True)
class _Interval:
    book: str
    start: int
    end: int
    relationship_id: str


def _group_id(group_type: str, group_key: str, group_method: str) -> str:
    payload = json.dumps(
        {"group_key": group_key, "group_method": group_method, "group_type": group_type},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"BLG_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _group_rows(
    *,
    group_type: LeakageGroupType,
    group_key: str,
    group_method: str,
    notes: str,
    relationship_ids: Iterable[str],
) -> Iterator[BenchmarkLeakageGroupRow]:
    group_id = _group_id(group_type, group_key, group_method)
    for relationship_id in relationship_ids:
        yield BenchmarkLeakageGroupRow(
            leakage_group_id=group_id,
            relationship_id=relationship_id,
            group_type=group_type,
            group_key=group_key,
            group_method=group_method,
            notes=notes,
        )


def _atomic_overlap_group_rows(
    intervals: list[_Interval],
    *,
    group_type: Literal["overlapping_endpoint_range", "overlapping_target_passage"],
) -> Iterator[BenchmarkLeakageGroupRow]:
    """Detect closed-interval overlaps by real starts without pair expansion.

    The sweep compares packed chapter/verse coordinates lexicographically but
    never enumerates the integers between them. Cross-chapter spans therefore
    cannot invent pseudo-verses. Groups are emitted at real interval starts,
    avoiding both pair generation and transitive graph closure.
    """

    intervals.sort(key=lambda item: (item.book, item.start, item.end, item.relationship_id))
    active_heap: list[tuple[int, int, str]] = []
    active_counts: Counter[str] = Counter()
    current_book: str | None = None
    serial = 0
    for (book, ordinal), starting in groupby(intervals, key=lambda item: (item.book, item.start)):
        if book != current_book:
            active_heap.clear()
            active_counts.clear()
            current_book = book
        while active_heap and active_heap[0][0] < ordinal:
            _end, _serial, relationship_id = heapq.heappop(active_heap)
            active_counts[relationship_id] -= 1
            if active_counts[relationship_id] == 0:
                del active_counts[relationship_id]
        for interval in starting:
            heapq.heappush(active_heap, (interval.end, serial, interval.relationship_id))
            active_counts[interval.relationship_id] += 1
            serial += 1
        if len(active_counts) < 2:
            continue
        yield from _group_rows(
            group_type=group_type,
            group_key=f"{book}|{ordinal}",
            group_method="interval_start_sweep_no_global_component",
            notes=(
                "Closed intervals overlap at this real interval start; "
                "no pair expansion, fabricated coordinate, or graph closure is applied."
            ),
            relationship_ids=sorted(active_counts),
        )


def iter_leakage_group_rows(
    relationships: tuple[RelationshipLeakageInput, ...] | list[RelationshipLeakageInput],
) -> Iterator[BenchmarkLeakageGroupRow]:
    """Yield deterministic leakage memberships without retaining row models.

    Production builds consume this iterator in bounded columnar chunks.  Only
    compact group-membership indexes and interval facts remain live while rows
    are emitted, avoiding the multi-million-Pydantic-row peak of the fixture
    convenience API below.
    """

    ordered = sorted(relationships, key=lambda item: item.relationship_id)
    for first, second in pairwise(ordered):
        if first.relationship_id == second.relationship_id:
            raise ValueError("relationship IDs must be unique before leakage grouping")

    shared: dict[tuple[LeakageGroupType, str], list[str]] = defaultdict(list)
    source_intervals: list[_Interval] = []
    target_intervals: list[_Interval] = []

    for relationship in ordered:
        yield from _group_rows(
            group_type="exact_directed_pair",
            group_key=relationship.canonical_directed_pair_id,
            group_method="canonical_directed_pair_identity",
            notes="Source direction is preserved.",
            relationship_ids=(relationship.relationship_id,),
        )
        yield from _group_rows(
            group_type="exact_unordered_pair",
            group_key=relationship.canonical_undirected_pair_id,
            group_method="canonical_unordered_pair_identity",
            notes="Reverse pairs share this unordered identity without symmetrization.",
            relationship_ids=(relationship.relationship_id,),
        )
        book_pair = "|".join(sorted(endpoint.source_book for endpoint in relationship.endpoints))
        yield from _group_rows(
            group_type="canonical_book_pair",
            group_key=book_pair,
            group_method="canonical_unordered_source_book_pair",
            notes="The unordered source-scheme book pair remains inspectable.",
            relationship_ids=(relationship.relationship_id,),
        )

        for duplicate_key in set(relationship.duplicate_source_record_keys):
            shared[("duplicate_source_records", duplicate_key)].append(relationship.relationship_id)
        for provenance_key in set(relationship.source_provenance_keys):
            shared[("shared_source_provenance", provenance_key)].append(
                relationship.relationship_id
            )
        if relationship.relationship_family_key is not None:
            shared[("relationship_family", relationship.relationship_family_key)].append(
                relationship.relationship_id
            )

        endpoint_keys = {endpoint.endpoint_key for endpoint in relationship.endpoints}
        target_ids = {
            passage_id
            for endpoint in relationship.endpoints
            for passage_id in endpoint.target_passage_ids
        }
        for endpoint_key in endpoint_keys:
            shared[("shared_endpoint", endpoint_key)].append(relationship.relationship_id)
        for passage_id in target_ids:
            shared[("shared_target_passage", passage_id)].append(relationship.relationship_id)
        for endpoint in relationship.endpoints:
            source_intervals.append(
                _Interval(
                    book=endpoint.source_book,
                    start=endpoint.source_start_ordinal,
                    end=endpoint.source_end_ordinal,
                    relationship_id=relationship.relationship_id,
                )
            )
            if (
                endpoint.target_book is not None
                and endpoint.target_start_ordinal is not None
                and endpoint.target_end_ordinal is not None
            ):
                target_intervals.append(
                    _Interval(
                        book=endpoint.target_book,
                        start=endpoint.target_start_ordinal,
                        end=endpoint.target_end_ordinal,
                        relationship_id=relationship.relationship_id,
                    )
                )

    shared_methods: dict[LeakageGroupType, tuple[str, str]] = {
        "duplicate_source_records": (
            "canonical_raw_record_content_key",
            "Duplicate source occurrences remain in one split.",
        ),
        "shared_endpoint": (
            "normalized_source_endpoint_identity",
            "Relationships share an exact source-scheme endpoint.",
        ),
        "shared_target_passage": (
            "mapped_target_passage_identity",
            "Relationships share an exact mapped verse passage.",
        ),
        "relationship_family": (
            "governed_relationship_family_label",
            "Family labels are retained only when supplied; none are inferred.",
        ),
        "shared_source_provenance": (
            "governed_source_provenance_key",
            "Relationships share a declared source provenance family.",
        ),
        "exact_directed_pair": ("", ""),
        "exact_unordered_pair": ("", ""),
        "overlapping_endpoint_range": ("", ""),
        "overlapping_target_passage": ("", ""),
        "canonical_book_pair": ("", ""),
    }
    for (group_type, group_key), members in sorted(shared.items()):
        if len(members) < 2 and group_type not in {
            "duplicate_source_records",
            "relationship_family",
        }:
            continue
        method, notes = shared_methods[group_type]
        yield from _group_rows(
            group_type=group_type,
            group_key=group_key,
            group_method=method,
            notes=notes,
            relationship_ids=members,
        )
    shared.clear()

    yield from _atomic_overlap_group_rows(
        source_intervals,
        group_type="overlapping_endpoint_range",
    )
    source_intervals.clear()
    yield from _atomic_overlap_group_rows(
        target_intervals,
        group_type="overlapping_target_passage",
    )


def build_leakage_groups(
    relationships: tuple[RelationshipLeakageInput, ...] | list[RelationshipLeakageInput],
) -> tuple[BenchmarkLeakageGroupRow, ...]:
    """Build deterministic independent leakage-group views.

    Exact pair groups are retained even when singleton so every relationship
    has inspectable directed and unordered grouping identities.  Shared and
    provenance groups are emitted only when at least two relationships share
    the key; interval overlaps use atomic coordinate-membership groups.
    """

    return tuple(
        sorted(
            iter_leakage_group_rows(relationships),
            key=lambda row: (
                row.group_type,
                row.group_key,
                row.group_method,
                row.notes,
                row.relationship_id,
            ),
        )
    )


def leakage_members_by_group(
    groups: tuple[BenchmarkLeakageGroupRow, ...] | list[BenchmarkLeakageGroupRow],
    *,
    group_types: frozenset[str] | None = None,
) -> dict[str, frozenset[str]]:
    """Return stable group membership for selected explicit leakage views."""

    members: dict[str, set[str]] = defaultdict(set)
    for row in groups:
        if group_types is None or row.group_type in group_types:
            members[row.leakage_group_id].add(row.relationship_id)
    return {group_id: frozenset(values) for group_id, values in sorted(members.items())}
