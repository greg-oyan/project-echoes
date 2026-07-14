"""Leakage-aware Tier 3 recovery evaluation for transparent lexical methods.

OpenBible results produced here are always weak-supervision recovery results.
They are not ground-truth quotation accuracy, scholarly validation, or a
high-confidence Tier 1 benchmark.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
from numpy.typing import NDArray

from echoes.benchmarks.metrics import (
    RankedQuery,
    ndcg_at_k,
    passage_length_bucket,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

TIER3_LABEL_QUALITY: Final = "tier3_weak_supervision_recovery"
TIER3_DISPLAY_LABEL: Final = "Tier 3 weak-supervision recovery"
OPENBIBLE_SOURCE_ID: Final = "openbible-cross-references"
MINIMUM_BOOTSTRAP_ITERATIONS: Final = 1_000

BaselineName = Literal["random", "length_matched", "unweighted_overlap"]
RankingRole = Literal["system", "baseline"]
MetricName = Literal[
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "mean_reciprocal_rank",
    "ndcg_at_20",
    "precision_at_10",
    "coverage",
]
StratumDimension = Literal[
    "global",
    "analysis_profile",
    "mapping_status",
    "corpus_pair",
    "split_strategy",
    "partition",
    "split_strategy_partition",
    "book",
    "broad_genre",
    "book_pair",
    "passage_length_bucket",
    "vote_stratum",
    "disputed_passage_status",
    "reference_gap_status",
    "corpus_pair_mapping_status",
]
GateStatus = Literal["passes", "fails", "insufficient_data_no_claim"]

REQUIRED_BASELINES: Final[tuple[BaselineName, ...]] = (
    "random",
    "length_matched",
    "unweighted_overlap",
)
REQUIRED_STRATUM_DIMENSIONS: Final[tuple[StratumDimension, ...]] = (
    "analysis_profile",
    "mapping_status",
    "corpus_pair",
    "split_strategy",
    "partition",
    "split_strategy_partition",
    "book",
    "broad_genre",
    "book_pair",
    "passage_length_bucket",
    "vote_stratum",
    "disputed_passage_status",
    "reference_gap_status",
    "corpus_pair_mapping_status",
)
PRIMARY_ORIGINAL_LANGUAGE_CORPUS_PAIRS: Final[tuple[str, ...]] = ("hb_hb", "gnt_gnt")
GOVERNED_SPLIT_STRATEGIES: Final = frozenset(
    {
        "held_out_book",
        "held_out_book_pair",
        "held_out_source_passage",
        "held_out_genre",
    }
)
GOVERNED_MAPPING_STATUSES: Final = frozenset(
    {"mapped_verified", "mapped_provisional", "mapped_partial"}
)
GOVERNED_VOTE_STRATA: Final = frozenset(
    {
        "negative",
        "zero",
        "one_to_two",
        "three_to_five",
        "six_to_ten",
        "eleven_to_twenty_five",
        "twenty_six_plus",
    }
)


class Tier3EvaluationContractError(ValueError):
    """A frozen Tier 3 evaluation or leakage contract was violated."""


@dataclass(frozen=True, slots=True)
class Tier3EvaluationQuery:
    """One governed benchmark query with all required recovery strata."""

    query_id: str
    relevant_passage_ids: frozenset[str]
    relationship_ids: frozenset[str]
    analysis_profile: str
    mapping_status: str
    corpus_pair: str
    split_strategy: str
    partition: str
    source_book: str
    target_book: str
    broad_genre: str
    passage_length: int
    vote_stratum: str
    disputed_passage: bool
    reference_gap: bool
    leakage_group_id: str
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        text_fields = (
            self.query_id,
            self.analysis_profile,
            self.mapping_status,
            self.corpus_pair,
            self.split_strategy,
            self.partition,
            self.source_book,
            self.target_book,
            self.broad_genre,
            self.vote_stratum,
            self.leakage_group_id,
        )
        if not all(text_fields):
            raise Tier3EvaluationContractError("Tier 3 query identity and strata cannot be empty")
        if self.mapping_status not in GOVERNED_MAPPING_STATUSES:
            raise Tier3EvaluationContractError(f"ineligible mapping status: {self.mapping_status}")
        if self.split_strategy not in GOVERNED_SPLIT_STRATEGIES:
            raise Tier3EvaluationContractError(f"ungoverned split strategy: {self.split_strategy}")
        if self.vote_stratum not in GOVERNED_VOTE_STRATA:
            raise Tier3EvaluationContractError(f"ungoverned vote stratum: {self.vote_stratum}")
        if self.passage_length < 0:
            raise Tier3EvaluationContractError("query passage length cannot be negative")
        if any(not passage_id for passage_id in self.relevant_passage_ids):
            raise Tier3EvaluationContractError("relevant passage IDs cannot be empty")
        if any(not relationship_id for relationship_id in self.relationship_ids):
            raise Tier3EvaluationContractError("relationship IDs cannot be empty")
        if self.exclusion_reason == "":
            raise Tier3EvaluationContractError("query exclusion reason cannot be empty")


def _validate_unique_ids(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not value for value in result):
        raise Tier3EvaluationContractError(f"{label} cannot contain empty IDs")
    if len(result) != len(set(result)):
        raise Tier3EvaluationContractError(f"{label} cannot contain duplicate IDs")
    return result


def deterministic_random_ranking(
    candidate_passage_ids: Sequence[str], *, query_id: str, seed: int
) -> tuple[str, ...]:
    """Return an order-invariant deterministic random-ranking baseline."""

    candidates = _validate_unique_ids(candidate_passage_ids, label="random candidates")
    if not query_id:
        raise Tier3EvaluationContractError("random ranking requires a query ID")
    if seed < 0:
        raise Tier3EvaluationContractError("random baseline seed cannot be negative")

    def key(passage_id: str) -> tuple[bytes, str]:
        payload = f"{seed}\x1f{query_id}\x1f{passage_id}".encode()
        return (hashlib.sha256(payload).digest(), passage_id)

    return tuple(sorted(candidates, key=key))


def length_matched_ranking(
    candidate_passage_ids: Sequence[str],
    *,
    query_length: int,
    target_lengths: Mapping[str, int],
) -> tuple[str, ...]:
    """Rank candidates only by absolute passage-length difference."""

    candidates = _validate_unique_ids(candidate_passage_ids, label="length candidates")
    if query_length < 0:
        raise Tier3EvaluationContractError("query length cannot be negative")
    missing = set(candidates).difference(target_lengths)
    if missing:
        raise Tier3EvaluationContractError(
            "target lengths missing for: " + ", ".join(sorted(missing)[:5])
        )
    if any(target_lengths[candidate] < 0 for candidate in candidates):
        raise Tier3EvaluationContractError("target lengths cannot be negative")
    return tuple(
        sorted(candidates, key=lambda item: (abs(target_lengths[item] - query_length), item))
    )


def unweighted_overlap_ranking(
    candidate_passage_ids: Sequence[str],
    *,
    query_features: Sequence[str],
    target_features: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """Rank by transparent binary Jaccard overlap with passage-ID tie-breaking."""

    candidates = _validate_unique_ids(candidate_passage_ids, label="overlap candidates")
    missing = set(candidates).difference(target_features)
    if missing:
        raise Tier3EvaluationContractError(
            "target features missing for: " + ", ".join(sorted(missing)[:5])
        )
    query_set = frozenset(query_features)

    def score(passage_id: str) -> float:
        target_set = frozenset(target_features[passage_id])
        union = query_set.union(target_set)
        return len(query_set.intersection(target_set)) / len(union) if union else 0.0

    return tuple(sorted(candidates, key=lambda item: (-score(item), item)))


type BaselineRankings = dict[BaselineName, dict[str, tuple[str, ...]]]


def build_required_baseline_rankings(
    queries: Sequence[Tier3EvaluationQuery],
    *,
    candidate_passage_ids_by_query: Mapping[str, Sequence[str]],
    target_lengths: Mapping[str, int],
    query_features: Mapping[str, Sequence[str]],
    target_features: Mapping[str, Sequence[str]],
    random_seed: int,
) -> BaselineRankings:
    """Build all three governed baselines from the same candidate universe."""

    query_values = tuple(queries)
    query_ids = {query.query_id for query in query_values}
    if set(candidate_passage_ids_by_query) != query_ids or set(query_features) != query_ids:
        raise Tier3EvaluationContractError(
            "baseline candidates and query features must exactly cover evaluation queries"
        )
    baselines: BaselineRankings = {name: {} for name in REQUIRED_BASELINES}
    for query in sorted(query_values, key=lambda item: item.query_id):
        candidates = candidate_passage_ids_by_query[query.query_id]
        baselines["random"][query.query_id] = deterministic_random_ranking(
            candidates,
            query_id=query.query_id,
            seed=random_seed,
        )
        baselines["length_matched"][query.query_id] = length_matched_ranking(
            candidates,
            query_length=query.passage_length,
            target_lengths=target_lengths,
        )
        baselines["unweighted_overlap"][query.query_id] = unweighted_overlap_ranking(
            candidates,
            query_features=query_features[query.query_id],
            target_features=target_features,
        )
    return baselines


def validate_leakage_partitions(queries: Sequence[Tier3EvaluationQuery]) -> None:
    """Reject any leakage group crossing a partition within a governed split."""

    seen: dict[tuple[str, str], str] = {}
    for query in queries:
        key = (query.split_strategy, query.leakage_group_id)
        prior = seen.setdefault(key, query.partition)
        if prior != query.partition:
            raise Tier3EvaluationContractError(
                "leakage group crosses governed partitions: "
                f"{query.split_strategy}/{query.leakage_group_id}"
            )


def _sha256_digest(value: str, *, label: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise Tier3EvaluationContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _derived_seed(base_seed: int, *parts: str) -> int:
    payload = "\x1f".join((str(base_seed), *parts)).encode()
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)
    return value or 1


def _bootstrap_means(scores: Sequence[float], *, iterations: int, seed: int) -> NDArray[np.float64]:
    """Draw exact empirical query bootstraps, grouped by equal score values."""

    values = np.asarray(scores, dtype=np.float64)
    if values.size == 0:
        return np.zeros(iterations, dtype=np.float64)
    unique_values, counts = np.unique(values, return_counts=True)
    probabilities = counts.astype(np.float64) / values.size
    random_source = np.random.default_rng(seed)
    result = np.empty(iterations, dtype=np.float64)
    # Keep temporary multinomial matrices bounded even when scores are all unique.
    chunk_size = max(1, min(iterations, 2_000_000 // max(1, unique_values.size)))
    offset = 0
    while offset < iterations:
        draws = min(chunk_size, iterations - offset)
        category_counts = random_source.multinomial(values.size, probabilities, size=draws)
        result[offset : offset + draws] = category_counts @ unique_values / values.size
        offset += draws
    return result


def _bootstrap_interval(
    scores: Sequence[float], *, iterations: int, seed: int
) -> tuple[float, float]:
    if not scores:
        return (0.0, 0.0)
    means = _bootstrap_means(scores, iterations=iterations, seed=seed)
    bounds = np.quantile(means, (0.025, 0.975), method="linear")
    return (float(bounds[0]), float(bounds[1]))


def _paired_bootstrap_interval(
    method_scores: Sequence[float],
    baseline_scores: Sequence[float],
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float]:
    if len(method_scores) != len(baseline_scores):
        raise Tier3EvaluationContractError("paired bootstrap inputs have different query counts")
    if not method_scores:
        return (0.0, 0.0, 0.0)
    differences = tuple(
        method - baseline for method, baseline in zip(method_scores, baseline_scores, strict=True)
    )
    low, high = _bootstrap_interval(differences, iterations=iterations, seed=seed)
    return (math.fsum(differences) / len(differences), low, high)


def _as_ranked_query(query: Tier3EvaluationQuery, ranking: Sequence[str]) -> RankedQuery:
    return RankedQuery(
        query_id=query.query_id,
        ranked_passage_ids=tuple(ranking),
        relevant_passage_ids=query.relevant_passage_ids,
        book=query.source_book,
        broad_genre=query.broad_genre,
        passage_length=query.passage_length,
        corpus_pair=query.corpus_pair,
        relationship_class="openbible_tier3",
        benchmark_tier=3,
        mapping_confidence=query.mapping_status,
    )


def _metric_value(query: Tier3EvaluationQuery, ranking: Sequence[str], metric: MetricName) -> float:
    if metric == "coverage":
        return float(bool(ranking))
    ranked_query = _as_ranked_query(query, ranking)
    if metric == "recall_at_5":
        return recall_at_k(ranked_query, 5)
    if metric == "recall_at_10":
        return recall_at_k(ranked_query, 10)
    if metric == "recall_at_20":
        return recall_at_k(ranked_query, 20)
    if metric == "mean_reciprocal_rank":
        return reciprocal_rank(ranked_query)
    if metric == "ndcg_at_20":
        return ndcg_at_k(ranked_query, 20)
    return precision_at_k(ranked_query, 10)


METRICS: Final[tuple[tuple[MetricName, int | None], ...]] = (
    ("recall_at_5", 5),
    ("recall_at_10", 10),
    ("recall_at_20", 20),
    ("mean_reciprocal_rank", None),
    ("ndcg_at_20", 20),
    ("precision_at_10", 10),
    ("coverage", None),
)


def _stratum_value(query: Tier3EvaluationQuery, dimension: StratumDimension) -> str:
    values: dict[StratumDimension, str] = {
        "global": "all",
        "analysis_profile": query.analysis_profile,
        "mapping_status": query.mapping_status,
        "corpus_pair": query.corpus_pair,
        "split_strategy": query.split_strategy,
        "partition": query.partition,
        "split_strategy_partition": f"{query.split_strategy}|{query.partition}",
        "book": query.source_book,
        "broad_genre": query.broad_genre,
        "book_pair": f"{query.source_book}|{query.target_book}",
        "passage_length_bucket": passage_length_bucket(query.passage_length),
        "vote_stratum": query.vote_stratum,
        "disputed_passage_status": "disputed" if query.disputed_passage else "not_disputed",
        "reference_gap_status": "reference_gap" if query.reference_gap else "no_reference_gap",
        "corpus_pair_mapping_status": f"{query.corpus_pair}|{query.mapping_status}",
    }
    return values[dimension]


def _group_queries(
    queries: Sequence[Tier3EvaluationQuery], dimensions: Sequence[StratumDimension]
) -> tuple[tuple[StratumDimension, str, tuple[Tier3EvaluationQuery, ...]], ...]:
    groups: list[tuple[StratumDimension, str, tuple[Tier3EvaluationQuery, ...]]] = [
        ("global", "all", tuple(sorted(queries, key=lambda item: item.query_id)))
    ]
    for dimension in dimensions:
        if dimension == "global":
            continue
        members_by_value: dict[str, list[Tier3EvaluationQuery]] = {}
        for query in queries:
            members_by_value.setdefault(_stratum_value(query, dimension), []).append(query)
        groups.extend(
            (dimension, value, tuple(sorted(members, key=lambda item: item.query_id)))
            for value, members in sorted(members_by_value.items())
        )
    return tuple(groups)


def _exclusion_reason(query: Tier3EvaluationQuery, metric: MetricName) -> str | None:
    if query.exclusion_reason is not None:
        return query.exclusion_reason
    if metric != "coverage" and not query.relevant_passage_ids:
        return "missing_relevance"
    if metric != "coverage" and not query.relationship_ids:
        return "missing_relationship_identity"
    return None


@dataclass(frozen=True, slots=True)
class Tier3MetricResult:
    """One method/baseline aggregate with a query-bootstrap interval."""

    detector: str
    representation_id: str
    ranking_name: str
    ranking_role: RankingRole
    benchmark_version: str
    benchmark_tier: Literal[3]
    label_quality: str
    display_label: str
    stratum_dimension: StratumDimension
    stratum_value: str
    metric: MetricName
    k: int | None
    value: float
    bootstrap_interval_low: float
    bootstrap_interval_high: float
    bootstrap_iterations: int
    bootstrap_seed: int
    eligible_query_count: int
    eligible_relationship_count: int
    excluded_count: int
    exclusion_reasons: tuple[tuple[str, int], ...]
    config_hash: str
    preregistration_digest: str
    frozen_before_test: bool
    source_id: str = OPENBIBLE_SOURCE_ID
    votes_are_calibrated_confidence: bool = False
    high_confidence_benchmark: bool = False


@dataclass(frozen=True, slots=True)
class PairedBaselineComparison:
    """A paired query-bootstrap difference from one required baseline."""

    detector: str
    representation_id: str
    baseline: BaselineName
    stratum_dimension: StratumDimension
    stratum_value: str
    metric: MetricName
    k: int | None
    observed_difference: float
    bootstrap_interval_low: float
    bootstrap_interval_high: float
    bootstrap_iterations: int
    bootstrap_seed: int
    paired_query_count: int
    label_quality: str = TIER3_LABEL_QUALITY


@dataclass(frozen=True, slots=True)
class PrimaryStratumRecoveryGate:
    """The stricter sufficient-data gate for one original-language corpus pair."""

    corpus_pair: str
    eligible_query_count: int
    eligible_relationship_count: int
    minimum_query_count: int
    minimum_relationship_count: int
    sufficient_data: bool
    recall_at_20_beats_random: bool | None
    recall_at_20_beats_unweighted_overlap: bool | None
    status: GateStatus
    reason: str
    tier3_only: bool = True
    high_confidence_claim_allowed: bool = False


@dataclass(frozen=True, slots=True)
class Tier3EvaluationReport:
    """Complete global/stratified metrics, paired comparisons, and gates."""

    detector: str
    representation_id: str
    metrics: tuple[Tier3MetricResult, ...]
    baseline_comparisons: tuple[PairedBaselineComparison, ...]
    primary_stratum_gates: tuple[PrimaryStratumRecoveryGate, ...]
    benchmark_version: str
    config_hash: str
    preregistration_digest: str
    label_quality: str = TIER3_LABEL_QUALITY
    display_label: str = TIER3_DISPLAY_LABEL
    benchmark_tier: Literal[3] = 3
    tier1_claim_tested: bool = False
    source_id: str = OPENBIBLE_SOURCE_ID
    votes_are_calibrated_confidence: bool = False
    high_confidence_benchmark: bool = False


def _validate_rankings(
    *,
    queries: Sequence[Tier3EvaluationQuery],
    method_rankings: Mapping[str, Sequence[str]],
    baseline_rankings: Mapping[BaselineName, Mapping[str, Sequence[str]]],
) -> None:
    query_ids = {query.query_id for query in queries}
    if set(method_rankings) != query_ids:
        raise Tier3EvaluationContractError("method rankings must exactly cover evaluation queries")
    if set(baseline_rankings) != set(REQUIRED_BASELINES):
        raise Tier3EvaluationContractError(
            "random, length-matched, and overlap baselines are required"
        )
    for baseline in REQUIRED_BASELINES:
        if set(baseline_rankings[baseline]) != query_ids:
            raise Tier3EvaluationContractError(f"{baseline} rankings do not cover every query")
    for query_id in sorted(query_ids):
        _validate_unique_ids(method_rankings[query_id], label="method ranking")
        for baseline in REQUIRED_BASELINES:
            _validate_unique_ids(
                baseline_rankings[baseline][query_id],
                label=f"{baseline} ranking",
            )


def _metric_scores(
    queries: Sequence[Tier3EvaluationQuery],
    rankings: Mapping[str, Sequence[str]],
    metric: MetricName,
) -> tuple[tuple[float, ...], Counter[str], frozenset[str]]:
    scores: list[float] = []
    exclusions: Counter[str] = Counter()
    relationship_ids: set[str] = set()
    for query in queries:
        reason = _exclusion_reason(query, metric)
        if reason is not None:
            exclusions[reason] += 1
            continue
        scores.append(_metric_value(query, rankings[query.query_id], metric))
        relationship_ids.update(query.relationship_ids)
    return (tuple(scores), exclusions, frozenset(relationship_ids))


def _gate_for_corpus_pair(
    *,
    corpus_pair: str,
    queries: Sequence[Tier3EvaluationQuery],
    comparisons: Sequence[PairedBaselineComparison],
    minimum_query_count: int,
    minimum_relationship_count: int,
) -> PrimaryStratumRecoveryGate:
    eligible = tuple(
        query
        for query in queries
        if query.corpus_pair == corpus_pair and _exclusion_reason(query, "recall_at_20") is None
    )
    relationship_count = len(
        {relationship_id for query in eligible for relationship_id in query.relationship_ids}
    )
    sufficient = (
        len(eligible) >= minimum_query_count and relationship_count >= minimum_relationship_count
    )
    if not sufficient:
        return PrimaryStratumRecoveryGate(
            corpus_pair=corpus_pair,
            eligible_query_count=len(eligible),
            eligible_relationship_count=relationship_count,
            minimum_query_count=minimum_query_count,
            minimum_relationship_count=minimum_relationship_count,
            sufficient_data=False,
            recall_at_20_beats_random=None,
            recall_at_20_beats_unweighted_overlap=None,
            status="insufficient_data_no_claim",
            reason=(
                f"insufficient Tier 3 mappings: {len(eligible)} eligible queries and "
                f"{relationship_count} eligible relationships; no recovery claim"
            ),
        )
    matching = {
        comparison.baseline: comparison
        for comparison in comparisons
        if comparison.stratum_dimension == "corpus_pair"
        and comparison.stratum_value == corpus_pair
        and comparison.metric == "recall_at_20"
    }
    if set(matching) != set(REQUIRED_BASELINES):
        raise Tier3EvaluationContractError(
            "primary gate lacks required paired baseline comparisons"
        )
    beats_random = matching["random"].bootstrap_interval_low > 0.0
    beats_overlap = matching["unweighted_overlap"].bootstrap_interval_low > 0.0
    passes = beats_random and beats_overlap
    return PrimaryStratumRecoveryGate(
        corpus_pair=corpus_pair,
        eligible_query_count=len(eligible),
        eligible_relationship_count=relationship_count,
        minimum_query_count=minimum_query_count,
        minimum_relationship_count=minimum_relationship_count,
        sufficient_data=True,
        recall_at_20_beats_random=beats_random,
        recall_at_20_beats_unweighted_overlap=beats_overlap,
        status="passes" if passes else "fails",
        reason=(
            "positive paired-bootstrap Recall@20 improvement over both random and "
            "unweighted overlap"
            if passes
            else "Recall@20 does not have a positive paired-bootstrap interval over both "
            "random and unweighted overlap"
        ),
    )


def evaluate_tier3_recovery(
    queries: Sequence[Tier3EvaluationQuery],
    *,
    detector: str,
    representation_id: str,
    method_rankings: Mapping[str, Sequence[str]],
    baseline_rankings: Mapping[BaselineName, Mapping[str, Sequence[str]]],
    benchmark_version: str,
    config_hash: str,
    preregistration_digest: str,
    bootstrap_iterations: int = MINIMUM_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int,
    minimum_eligible_queries: int,
    minimum_eligible_relationships: int,
    stratum_dimensions: Sequence[StratumDimension] = REQUIRED_STRATUM_DIMENSIONS,
    primary_original_language_corpus_pairs: Sequence[str] = PRIMARY_ORIGINAL_LANGUAGE_CORPUS_PAIRS,
) -> Tier3EvaluationReport:
    """Evaluate a transparent method globally and across every required Tier 3 stratum."""

    if not all((detector, representation_id, benchmark_version)):
        raise Tier3EvaluationContractError("evaluation identity fields cannot be empty")
    _sha256_digest(config_hash, label="config hash")
    _sha256_digest(preregistration_digest, label="preregistration digest")
    if bootstrap_iterations < MINIMUM_BOOTSTRAP_ITERATIONS:
        raise Tier3EvaluationContractError("Tier 3 evaluation requires at least 1,000 bootstraps")
    if bootstrap_seed < 1:
        raise Tier3EvaluationContractError("bootstrap seed must be positive")
    if minimum_eligible_queries < 1 or minimum_eligible_relationships < 1:
        raise Tier3EvaluationContractError("sufficient-data minima must be positive")
    dimensions = tuple(stratum_dimensions)
    if len(dimensions) != len(set(dimensions)):
        raise Tier3EvaluationContractError("evaluation stratum dimensions must be unique")
    missing_dimensions = set(REQUIRED_STRATUM_DIMENSIONS).difference(dimensions)
    if missing_dimensions:
        raise Tier3EvaluationContractError(
            "required evaluation strata missing: " + ", ".join(sorted(missing_dimensions))
        )
    query_values = tuple(queries)
    query_ids = tuple(query.query_id for query in query_values)
    if not query_values or len(query_ids) != len(set(query_ids)):
        raise Tier3EvaluationContractError(
            "evaluation queries must be nonempty and uniquely identified"
        )
    primary_pairs = tuple(primary_original_language_corpus_pairs)
    if not primary_pairs or len(primary_pairs) != len(set(primary_pairs)):
        raise Tier3EvaluationContractError("primary original-language corpus pairs must be unique")
    validate_leakage_partitions(query_values)
    _validate_rankings(
        queries=query_values,
        method_rankings=method_rankings,
        baseline_rankings=baseline_rankings,
    )

    groups = _group_queries(query_values, dimensions)
    metric_rows: list[Tier3MetricResult] = []
    comparison_rows: list[PairedBaselineComparison] = []
    ranking_sets: tuple[tuple[str, RankingRole, Mapping[str, Sequence[str]]], ...] = (
        (detector, "system", method_rankings),
        *((name, "baseline", baseline_rankings[name]) for name in REQUIRED_BASELINES),
    )
    for dimension, stratum_value, members in groups:
        for metric, k in METRICS:
            method_scores, _, _ = _metric_scores(members, method_rankings, metric)
            for ranking_name, ranking_role, rankings in ranking_sets:
                scores, exclusions, relationships = _metric_scores(members, rankings, metric)
                seed = _derived_seed(
                    bootstrap_seed,
                    detector,
                    ranking_name,
                    dimension,
                    stratum_value,
                    metric,
                )
                interval_low, interval_high = _bootstrap_interval(
                    scores,
                    iterations=bootstrap_iterations,
                    seed=seed,
                )
                metric_rows.append(
                    Tier3MetricResult(
                        detector=detector,
                        representation_id=representation_id,
                        ranking_name=ranking_name,
                        ranking_role=ranking_role,
                        benchmark_version=benchmark_version,
                        benchmark_tier=3,
                        label_quality=TIER3_LABEL_QUALITY,
                        display_label=TIER3_DISPLAY_LABEL,
                        stratum_dimension=dimension,
                        stratum_value=stratum_value,
                        metric=metric,
                        k=k,
                        value=math.fsum(scores) / len(scores) if scores else 0.0,
                        bootstrap_interval_low=interval_low,
                        bootstrap_interval_high=interval_high,
                        bootstrap_iterations=bootstrap_iterations,
                        bootstrap_seed=seed,
                        eligible_query_count=len(scores),
                        eligible_relationship_count=len(relationships),
                        excluded_count=sum(exclusions.values()),
                        exclusion_reasons=tuple(sorted(exclusions.items())),
                        config_hash=config_hash,
                        preregistration_digest=preregistration_digest,
                        frozen_before_test=True,
                    )
                )
            for baseline in REQUIRED_BASELINES:
                baseline_scores, _, _ = _metric_scores(
                    members,
                    baseline_rankings[baseline],
                    metric,
                )
                comparison_seed = _derived_seed(
                    bootstrap_seed,
                    detector,
                    baseline,
                    dimension,
                    stratum_value,
                    metric,
                    "paired",
                )
                difference, interval_low, interval_high = _paired_bootstrap_interval(
                    method_scores,
                    baseline_scores,
                    iterations=bootstrap_iterations,
                    seed=comparison_seed,
                )
                comparison_rows.append(
                    PairedBaselineComparison(
                        detector=detector,
                        representation_id=representation_id,
                        baseline=baseline,
                        stratum_dimension=dimension,
                        stratum_value=stratum_value,
                        metric=metric,
                        k=k,
                        observed_difference=difference,
                        bootstrap_interval_low=interval_low,
                        bootstrap_interval_high=interval_high,
                        bootstrap_iterations=bootstrap_iterations,
                        bootstrap_seed=comparison_seed,
                        paired_query_count=len(method_scores),
                    )
                )

    gates = tuple(
        _gate_for_corpus_pair(
            corpus_pair=corpus_pair,
            queries=query_values,
            comparisons=comparison_rows,
            minimum_query_count=minimum_eligible_queries,
            minimum_relationship_count=minimum_eligible_relationships,
        )
        for corpus_pair in primary_pairs
    )
    return Tier3EvaluationReport(
        detector=detector,
        representation_id=representation_id,
        metrics=tuple(metric_rows),
        baseline_comparisons=tuple(comparison_rows),
        primary_stratum_gates=gates,
        benchmark_version=benchmark_version,
        config_hash=config_hash,
        preregistration_digest=preregistration_digest,
    )
