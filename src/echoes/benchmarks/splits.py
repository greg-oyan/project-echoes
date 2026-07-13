"""Deterministic, group-preserving benchmark split strategies."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from echoes.benchmarks.models import BenchmarkLeakageGroupRow, BenchmarkSplitAssignmentRow

SplitStrategy = Literal[
    "held_out_book",
    "held_out_book_pair",
    "held_out_source_passage",
    "held_out_relationship_family",
    "held_out_genre",
]
HeldOutPartition = Literal["development", "test"]

_MAPPING_DEPENDENT_STRATEGIES: frozenset[SplitStrategy] = frozenset({"held_out_source_passage"})
_REQUIRED_GROUP_TYPES: dict[SplitStrategy, frozenset[str]] = {
    "held_out_book": frozenset({"exact_unordered_pair"}),
    "held_out_book_pair": frozenset({"exact_unordered_pair"}),
    "held_out_source_passage": frozenset(
        {"exact_unordered_pair", "shared_endpoint", "shared_target_passage"}
    ),
    "held_out_relationship_family": frozenset({"exact_unordered_pair", "relationship_family"}),
    "held_out_genre": frozenset({"exact_unordered_pair"}),
}


@dataclass(frozen=True, slots=True)
class SplitRelationship:
    """Relationship facts needed by all non-random held-out strategies."""

    relationship_id: str
    tier: int
    mapping_eligible: bool
    endpoint_books: tuple[str, str]
    endpoint_keys: tuple[str, str]
    broad_genres: tuple[str, str]
    relationship_family_key: str | None = None

    def __post_init__(self) -> None:
        if not self.relationship_id:
            raise ValueError("relationship_id is required")
        if self.tier not in {1, 2, 3}:
            raise ValueError("benchmark tier must be 1, 2, or 3")
        if len(self.endpoint_books) != 2 or not all(self.endpoint_books):
            raise ValueError("split inputs require exactly two endpoint books")
        if len(self.endpoint_keys) != 2 or not all(self.endpoint_keys):
            raise ValueError("split inputs require exactly two endpoint keys")
        if len(self.broad_genres) != 2 or not all(self.broad_genres):
            raise ValueError("split inputs require exactly two broad genres")

    @property
    def canonical_book_pair(self) -> str:
        return "|".join(sorted(self.endpoint_books))


@dataclass(frozen=True, slots=True)
class SplitDefinition:
    """One governed held-out split definition.

    No strategy performs row-level random assignment.  ``seed`` is retained
    only for manifest/config compatibility and has no effect on these exact
    held-out rules.
    """

    name: str
    strategy: SplitStrategy
    benchmark_version: str
    config_hash: str
    held_out_values: tuple[str, ...]
    included_tiers: tuple[int, ...] = (3,)
    require_mapping: bool = False
    enforced_group_types: tuple[str, ...] = (
        "exact_directed_pair",
        "exact_unordered_pair",
        "duplicate_source_records",
    )
    held_out_partition: HeldOutPartition = "test"
    seed: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.benchmark_version:
            raise ValueError("split name and benchmark version are required")
        if len(self.config_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.config_hash
        ):
            raise ValueError("split config_hash must be a lowercase SHA-256")
        if not self.held_out_values:
            raise ValueError("held-out split definitions require at least one held-out value")
        if len(set(self.held_out_values)) != len(self.held_out_values):
            raise ValueError("held-out values must be unique")
        if not self.included_tiers or any(tier not in {1, 2, 3} for tier in self.included_tiers):
            raise ValueError("included_tiers must contain governed benchmark tiers")
        if self.seed is not None and self.seed < 0:
            raise ValueError("split seeds cannot be negative")

    @property
    def effective_group_types(self) -> frozenset[str]:
        return frozenset(self.enforced_group_types) | _REQUIRED_GROUP_TYPES[self.strategy]

    @property
    def mapping_required(self) -> bool:
        return self.require_mapping or self.strategy in _MAPPING_DEPENDENT_STRATEGIES


class _DisjointSet:
    def __init__(self, values: list[str]) -> None:
        self._parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, first: str, second: str) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return
        smaller, larger = sorted((first_root, second_root))
        self._parent[larger] = smaller


def _assignment_id(definition: SplitDefinition, relationship_id: str) -> str:
    payload = json.dumps(
        {
            "benchmark_version": definition.benchmark_version,
            "config_hash": definition.config_hash,
            "relationship_id": relationship_id,
            "split_name": definition.name,
            "strategy": definition.strategy,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"BSA_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _base_exclusion_reason(
    relationship: SplitRelationship, definition: SplitDefinition
) -> str | None:
    if relationship.tier not in definition.included_tiers:
        return "tier_not_included"
    if definition.mapping_required and not relationship.mapping_eligible:
        return "mapping_ineligible"
    if (
        definition.strategy == "held_out_relationship_family"
        and relationship.relationship_family_key is None
    ):
        return "relationship_family_unavailable"
    return None


def _is_held_out(relationship: SplitRelationship, definition: SplitDefinition) -> bool:
    held = frozenset(definition.held_out_values)
    if definition.strategy == "held_out_book":
        return bool(held.intersection(relationship.endpoint_books))
    if definition.strategy == "held_out_book_pair":
        return relationship.canonical_book_pair in held
    if definition.strategy == "held_out_source_passage":
        return bool(held.intersection(relationship.endpoint_keys))
    if definition.strategy == "held_out_relationship_family":
        return relationship.relationship_family_key in held
    if definition.strategy == "held_out_genre":
        return bool(held.intersection(relationship.broad_genres))
    raise AssertionError(f"unsupported split strategy: {definition.strategy}")


def generate_split_assignments(
    relationships: tuple[SplitRelationship, ...] | list[SplitRelationship],
    leakage_groups: tuple[BenchmarkLeakageGroupRow, ...] | list[BenchmarkLeakageGroupRow],
    definition: SplitDefinition,
) -> tuple[BenchmarkSplitAssignmentRow, ...]:
    """Assign relationships without splitting any configured leakage group."""

    ordered = sorted(relationships, key=lambda item: item.relationship_id)
    by_id = {item.relationship_id: item for item in ordered}
    if len(by_id) != len(ordered):
        raise ValueError("relationship IDs must be unique before split generation")

    enforced_rows = sorted(
        (
            row
            for row in leakage_groups
            if row.group_type in definition.effective_group_types and row.relationship_id in by_id
        ),
        key=lambda row: (row.leakage_group_id, row.relationship_id),
    )
    group_members: dict[str, list[str]] = defaultdict(list)
    relationship_groups: dict[str, list[str]] = defaultdict(list)
    for row in enforced_rows:
        group_members[row.leakage_group_id].append(row.relationship_id)
        relationship_groups[row.relationship_id].append(row.leakage_group_id)

    disjoint = _DisjointSet(list(by_id))
    for members in group_members.values():
        if members:
            first = members[0]
            for member in members[1:]:
                disjoint.union(first, member)

    components: dict[str, list[str]] = defaultdict(list)
    for relationship_id in by_id:
        components[disjoint.find(relationship_id)].append(relationship_id)

    base_reasons = {
        relationship_id: _base_exclusion_reason(relationship, definition)
        for relationship_id, relationship in by_id.items()
    }
    component_reasons: dict[str, str | None] = {}
    component_partitions: dict[str, Literal["train", "development", "test", "excluded"]] = {}
    for root, members in sorted(components.items()):
        reasons = sorted({reason for member in members if (reason := base_reasons[member])})
        if reasons:
            component_reasons[root] = ";".join(reasons)
            component_partitions[root] = "excluded"
            continue
        component_reasons[root] = None
        component_partitions[root] = (
            definition.held_out_partition
            if any(_is_held_out(by_id[member], definition) for member in members)
            else "train"
        )

    rows: list[BenchmarkSplitAssignmentRow] = []
    for relationship in ordered:
        root = disjoint.find(relationship.relationship_id)
        reason = component_reasons[root]
        if reason is not None and base_reasons[relationship.relationship_id] is None:
            reason = f"leakage_group_contains_ineligible_member:{reason}"
        group_ids = sorted(set(relationship_groups.get(relationship.relationship_id, [])))
        rows.append(
            BenchmarkSplitAssignmentRow(
                split_assignment_id=_assignment_id(definition, relationship.relationship_id),
                benchmark_version=definition.benchmark_version,
                relationship_id=relationship.relationship_id,
                split_strategy=definition.name,
                partition=component_partitions[root],
                leakage_group_id=group_ids[0] if group_ids else None,
                seed=definition.seed,
                eligibility_status="excluded" if reason is not None else "eligible",
                exclusion_reason=reason,
                config_hash=definition.config_hash,
            )
        )
    return tuple(rows)


def split_leakage_violations(
    assignments: tuple[BenchmarkSplitAssignmentRow, ...] | list[BenchmarkSplitAssignmentRow],
    leakage_groups: tuple[BenchmarkLeakageGroupRow, ...] | list[BenchmarkLeakageGroupRow],
    *,
    enforced_group_types: frozenset[str],
) -> tuple[str, ...]:
    """Return configured groups whose eligible members cross partitions."""

    partitions = {
        row.relationship_id: row.partition for row in assignments if row.partition != "excluded"
    }
    by_group: dict[str, set[str]] = defaultdict(set)
    for group in leakage_groups:
        if group.group_type in enforced_group_types and group.relationship_id in partitions:
            by_group[group.leakage_group_id].add(partitions[group.relationship_id])
    return tuple(sorted(group_id for group_id, values in by_group.items() if len(values) > 1))
