"""Pure, retrieval-model-independent benchmark metric contracts."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

MetricStratum = Literal[
    "book",
    "broad_genre",
    "passage_length_bucket",
    "corpus_pair",
    "relationship_class",
    "benchmark_tier",
    "mapping_confidence",
]
LabelQuality = Literal[
    "high_confidence",
    "weak_supervision",
    "presumed_negatives",
    "tier3_weak_supervision_recovery",
]

OPENBIBLE_SOURCE_ID = "openbible-cross-references"
OPENBIBLE_LABEL_QUALITY = "tier3_weak_supervision_recovery"


@dataclass(frozen=True, slots=True)
class MetricContext:
    """Mandatory provenance carried by every reported metric."""

    benchmark_version: str
    included_tiers: tuple[int, ...]
    mapping_eligibility: str
    split_strategy: str
    label_quality: LabelQuality
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            (
                self.benchmark_version,
                self.mapping_eligibility,
                self.split_strategy,
                self.label_quality,
            )
        ):
            raise ValueError("metric provenance fields cannot be empty")
        if not self.included_tiers or any(tier not in {1, 2, 3} for tier in self.included_tiers):
            raise ValueError("metrics require one or more governed benchmark tiers")
        if len(set(self.included_tiers)) != len(self.included_tiers):
            raise ValueError("included metric tiers must be unique")
        if not self.source_ids or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("metric source IDs must be nonempty and unique")
        if set(self.source_ids) == {OPENBIBLE_SOURCE_ID} and (
            self.label_quality != OPENBIBLE_LABEL_QUALITY
        ):
            raise ValueError(
                "OpenBible-only metrics must be labeled Tier 3 weak-supervision recovery"
            )


@dataclass(frozen=True, slots=True)
class RankedQuery:
    """One synthetic or future retrieval result with benchmark strata."""

    query_id: str
    ranked_passage_ids: tuple[str, ...]
    relevant_passage_ids: frozenset[str]
    book: str
    broad_genre: str
    passage_length: int
    corpus_pair: str
    relationship_class: str
    benchmark_tier: int
    mapping_confidence: str
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise ValueError("metric query_id is required")
        if len(self.ranked_passage_ids) != len(set(self.ranked_passage_ids)):
            raise ValueError("ranked results cannot contain duplicate passage IDs")
        if self.passage_length < 0:
            raise ValueError("query passage length cannot be negative")
        if self.benchmark_tier not in {1, 2, 3}:
            raise ValueError("query benchmark tier must be 1, 2, or 3")
        if self.exclusion_reason == "":
            raise ValueError("query exclusion reasons cannot be empty")


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One exact aggregate with complete benchmark and exclusion metadata."""

    metric_name: str
    k: int | None
    value: float
    benchmark_version: str
    included_tiers: tuple[int, ...]
    mapping_eligibility: str
    split_strategy: str
    label_quality: LabelQuality
    source_ids: tuple[str, ...]
    eligible_queries: int
    excluded_queries: int
    exclusion_reasons: tuple[tuple[str, int], ...]
    stratum_dimension: str | None = None
    stratum_value: str | None = None


def recall_at_k(query: RankedQuery, k: int) -> float:
    """Binary relevance recall at K for one query."""

    if k < 1:
        raise ValueError("recall K must be positive")
    if not query.relevant_passage_ids:
        return 0.0
    hits = len(query.relevant_passage_ids.intersection(query.ranked_passage_ids[:k]))
    return hits / len(query.relevant_passage_ids)


def precision_at_k(query: RankedQuery, k: int) -> float:
    """Binary relevance precision at K with the conventional fixed K denominator."""

    if k < 1:
        raise ValueError("precision K must be positive")
    hits = len(query.relevant_passage_ids.intersection(query.ranked_passage_ids[:k]))
    return hits / k


def reciprocal_rank(query: RankedQuery) -> float:
    """Return reciprocal rank of the first relevant result, or zero."""

    for rank, passage_id in enumerate(query.ranked_passage_ids, start=1):
        if passage_id in query.relevant_passage_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(query: RankedQuery, k: int) -> float:
    """Binary normalized discounted cumulative gain at K."""

    if k < 1:
        raise ValueError("nDCG K must be positive")
    if not query.relevant_passage_ids:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, passage_id in enumerate(query.ranked_passage_ids[:k], start=1)
        if passage_id in query.relevant_passage_ids
    )
    ideal_hits = min(len(query.relevant_passage_ids), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal


def _eligible(
    queries: tuple[RankedQuery, ...] | list[RankedQuery],
    *,
    require_relevance: bool,
) -> tuple[list[RankedQuery], Counter[str]]:
    eligible: list[RankedQuery] = []
    excluded: Counter[str] = Counter()
    for query in queries:
        if query.exclusion_reason is not None:
            excluded[query.exclusion_reason] += 1
        elif require_relevance and not query.relevant_passage_ids:
            excluded["missing_relevance"] += 1
        else:
            eligible.append(query)
    return eligible, excluded


def _result(
    *,
    metric_name: str,
    k: int | None,
    value: float,
    context: MetricContext,
    eligible_count: int,
    excluded: Counter[str],
    stratum_dimension: str | None,
    stratum_value: str | None,
) -> MetricResult:
    return MetricResult(
        metric_name=metric_name,
        k=k,
        value=value,
        benchmark_version=context.benchmark_version,
        included_tiers=context.included_tiers,
        mapping_eligibility=context.mapping_eligibility,
        split_strategy=context.split_strategy,
        label_quality=context.label_quality,
        source_ids=context.source_ids,
        eligible_queries=eligible_count,
        excluded_queries=sum(excluded.values()),
        exclusion_reasons=tuple(sorted(excluded.items())),
        stratum_dimension=stratum_dimension,
        stratum_value=stratum_value,
    )


def _mean_metric(
    queries: tuple[RankedQuery, ...] | list[RankedQuery],
    *,
    context: MetricContext,
    metric_name: str,
    k: int | None,
    function: Callable[[RankedQuery], float],
    stratum_dimension: str | None = None,
    stratum_value: str | None = None,
) -> MetricResult:
    eligible, excluded = _eligible(queries, require_relevance=True)
    value = sum(function(query) for query in eligible) / len(eligible) if eligible else 0.0
    return _result(
        metric_name=metric_name,
        k=k,
        value=value,
        context=context,
        eligible_count=len(eligible),
        excluded=excluded,
        stratum_dimension=stratum_dimension,
        stratum_value=stratum_value,
    )


def _recall_function(k: int) -> Callable[[RankedQuery], float]:
    def calculate(query: RankedQuery) -> float:
        return recall_at_k(query, k)

    return calculate


def _precision_function(k: int) -> Callable[[RankedQuery], float]:
    def calculate(query: RankedQuery) -> float:
        return precision_at_k(query, k)

    return calculate


def evaluate_metrics(
    queries: tuple[RankedQuery, ...] | list[RankedQuery],
    context: MetricContext,
    *,
    additional_precision_ks: tuple[int, ...] = (),
    stratum_dimension: str | None = None,
    stratum_value: str | None = None,
) -> tuple[MetricResult, ...]:
    """Evaluate all Milestone 6 contracts without invoking retrieval."""

    if any(k < 1 for k in additional_precision_ks):
        raise ValueError("additional precision cutoffs must be positive")
    precision_ks = tuple(sorted({10, *additional_precision_ks}))
    results: list[MetricResult] = []
    for k in (5, 10, 20):
        results.append(
            _mean_metric(
                queries,
                context=context,
                metric_name=f"recall_at_{k}",
                k=k,
                function=_recall_function(k),
                stratum_dimension=stratum_dimension,
                stratum_value=stratum_value,
            )
        )
    results.append(
        _mean_metric(
            queries,
            context=context,
            metric_name="mean_reciprocal_rank",
            k=None,
            function=reciprocal_rank,
            stratum_dimension=stratum_dimension,
            stratum_value=stratum_value,
        )
    )
    results.append(
        _mean_metric(
            queries,
            context=context,
            metric_name="ndcg_at_20",
            k=20,
            function=lambda query: ndcg_at_k(query, 20),
            stratum_dimension=stratum_dimension,
            stratum_value=stratum_value,
        )
    )
    for k in precision_ks:
        results.append(
            _mean_metric(
                queries,
                context=context,
                metric_name="precision_at_10" if k == 10 else "precision_at_k",
                k=k,
                function=_precision_function(k),
                stratum_dimension=stratum_dimension,
                stratum_value=stratum_value,
            )
        )

    coverage_eligible, coverage_excluded = _eligible(queries, require_relevance=False)
    coverage = (
        sum(bool(query.ranked_passage_ids) for query in coverage_eligible) / len(coverage_eligible)
        if coverage_eligible
        else 0.0
    )
    results.append(
        _result(
            metric_name="coverage",
            k=None,
            value=coverage,
            context=context,
            eligible_count=len(coverage_eligible),
            excluded=coverage_excluded,
            stratum_dimension=stratum_dimension,
            stratum_value=stratum_value,
        )
    )
    return tuple(results)


def passage_length_bucket(length: int) -> str:
    """Return the transparent project bucket used for benchmark stratification."""

    if length < 0:
        raise ValueError("passage length cannot be negative")
    if length <= 5:
        return "short_0_5"
    if length <= 15:
        return "medium_6_15"
    return "long_16_plus"


def _stratum(query: RankedQuery, dimension: MetricStratum) -> str:
    values: dict[MetricStratum, str] = {
        "book": query.book,
        "broad_genre": query.broad_genre,
        "passage_length_bucket": passage_length_bucket(query.passage_length),
        "corpus_pair": query.corpus_pair,
        "relationship_class": query.relationship_class,
        "benchmark_tier": str(query.benchmark_tier),
        "mapping_confidence": query.mapping_confidence,
    }
    return values[dimension]


def evaluate_metrics_by_stratum(
    queries: tuple[RankedQuery, ...] | list[RankedQuery],
    context: MetricContext,
    *,
    dimension: MetricStratum,
    additional_precision_ks: tuple[int, ...] = (),
) -> tuple[MetricResult, ...]:
    """Evaluate the complete contract separately for one governed stratum."""

    grouped: dict[str, list[RankedQuery]] = {}
    for query in queries:
        grouped.setdefault(_stratum(query, dimension), []).append(query)
    return tuple(
        result
        for value, members in sorted(grouped.items())
        for result in evaluate_metrics(
            members,
            context,
            additional_precision_ks=additional_precision_ks,
            stratum_dimension=dimension,
            stratum_value=value,
        )
    )
