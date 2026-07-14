"""Pure transparent lexical similarity detectors.

The functions in this module intentionally expose every formula input and
return decomposed evidence.  They do not depend on project configuration,
storage, sparse-index, or command-line code.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Feature = str
Normalization = Literal["shorter", "geometric", "mean"]
AlignmentMode = Literal["local", "global"]
QueryTermFrequencyMode = Literal["binary", "linear"]


@dataclass(frozen=True, slots=True)
class SharedFeature:
    """One shared feature and all zero-based positions on both sides."""

    feature: Feature
    positions_a: tuple[int, ...]
    positions_b: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class JaccardResult:
    """Decomposed unweighted Jaccard evidence."""

    score: float
    intersection_size: int
    union_size: int
    shared_features: tuple[SharedFeature, ...]


@dataclass(frozen=True, slots=True)
class WeightedFeatureContribution:
    """One feature's min/max contribution to weighted Jaccard."""

    feature: Feature
    count_a: int
    count_b: int
    weight: float
    numerator: float
    denominator: float
    positions_a: tuple[int, ...]
    positions_b: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WeightedJaccardResult:
    """Decomposed weighted multiset Jaccard evidence."""

    score: float
    numerator: float
    denominator: float
    contributions: tuple[WeightedFeatureContribution, ...]


@dataclass(frozen=True, slots=True)
class TfidfTermContribution:
    """One feature's contribution to explicit TF-IDF cosine."""

    feature: Feature
    count_a: int
    count_b: int
    document_frequency: int
    idf: float
    value_a: float
    value_b: float
    normalized_value_a: float
    normalized_value_b: float
    dot_contribution: float


@dataclass(frozen=True, slots=True)
class TfidfCosineResult:
    """Explicit TF-IDF cosine and its term-level decomposition."""

    score: float
    dot_product: float
    norm_a: float
    norm_b: float
    document_count: int
    sublinear_tf: bool
    smooth_idf: bool
    contributions: tuple[TfidfTermContribution, ...]


@dataclass(frozen=True, slots=True)
class BM25TermContribution:
    """One query feature's exact BM25 contribution."""

    feature: Feature
    query_count: int
    document_term_count: int
    document_frequency: int
    idf: float
    query_weight: float
    term_saturation: float
    contribution: float


@dataclass(frozen=True, slots=True)
class BM25Result:
    """Directional BM25 score with all formula inputs retained."""

    score: float
    corpus_document_count: int
    document_length: int
    average_document_length: float
    k1: float
    b: float
    query_term_frequency_mode: QueryTermFrequencyMode
    contributions: tuple[BM25TermContribution, ...]


@dataclass(frozen=True, slots=True)
class RareFeatureEvidence:
    """One shared feature meeting the configured corpus-frequency threshold."""

    feature: Feature
    corpus_frequency: int
    document_frequency: int
    inverse_frequency_weight: float
    positions_a: tuple[int, ...]
    positions_b: tuple[int, ...]
    alternative_passage_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RareOverlapResult:
    """Shared rare-feature evidence; it is not an eligibility decision."""

    score: float
    threshold: int
    evidence: tuple[RareFeatureEvidence, ...]


@dataclass(frozen=True, slots=True)
class LCSResult:
    """A deterministic longest common subsequence and normalizations."""

    length: int
    features: tuple[Feature, ...]
    positions_a: tuple[int, ...]
    positions_b: tuple[int, ...]
    normalized_by_shorter: float
    normalized_by_geometric: float
    normalized_by_mean: float
    normalized_score: float
    normalization: Normalization


AlignmentOperation = Literal["match", "mismatch", "gap_in_a", "gap_in_b"]


@dataclass(frozen=True, slots=True)
class AlignmentStep:
    """One explicit traceback step in a weighted sequence alignment."""

    operation: AlignmentOperation
    position_a: int | None
    position_b: int | None
    feature_a: Feature | None
    feature_b: Feature | None
    contribution: float


@dataclass(frozen=True, slots=True)
class WeightedAlignmentResult:
    """Deterministic IDF-weighted alignment with complete traceback."""

    score: float
    normalized_score: float
    normalization_denominator: float
    mode: AlignmentMode
    gap_penalty: float
    mismatch_score: float
    steps: tuple[AlignmentStep, ...]
    matched_features: tuple[Feature, ...]
    matched_positions_a: tuple[int, ...]
    matched_positions_b: tuple[int, ...]


def _validated_sequence(features: Sequence[Feature], *, name: str) -> tuple[Feature, ...]:
    values = tuple(features)
    if any(not feature for feature in values):
        raise ValueError(f"{name} cannot contain an empty feature")
    return values


def _positions(features: Sequence[Feature]) -> dict[Feature, tuple[int, ...]]:
    mutable: dict[Feature, list[int]] = {}
    for position, feature in enumerate(features):
        mutable.setdefault(feature, []).append(position)
    return {feature: tuple(values) for feature, values in mutable.items()}


def jaccard_similarity(
    features_a: Sequence[Feature], features_b: Sequence[Feature]
) -> JaccardResult:
    """Calculate Jaccard over distinct features; two empty sets score zero."""

    sequence_a = _validated_sequence(features_a, name="features_a")
    sequence_b = _validated_sequence(features_b, name="features_b")
    positions_a = _positions(sequence_a)
    positions_b = _positions(sequence_b)
    shared = sorted(set(positions_a).intersection(positions_b))
    union_size = len(set(positions_a).union(positions_b))
    return JaccardResult(
        score=len(shared) / union_size if union_size else 0.0,
        intersection_size=len(shared),
        union_size=union_size,
        shared_features=tuple(
            SharedFeature(feature, positions_a[feature], positions_b[feature]) for feature in shared
        ),
    )


def weighted_jaccard_similarity(
    features_a: Sequence[Feature],
    features_b: Sequence[Feature],
    feature_weights: Mapping[Feature, float],
) -> WeightedJaccardResult:
    """Calculate weighted multiset Jaccard as ``sum(w*min)/sum(w*max)``."""

    sequence_a = _validated_sequence(features_a, name="features_a")
    sequence_b = _validated_sequence(features_b, name="features_b")
    counts_a = Counter(sequence_a)
    counts_b = Counter(sequence_b)
    positions_a = _positions(sequence_a)
    positions_b = _positions(sequence_b)
    contributions: list[WeightedFeatureContribution] = []
    for feature in sorted(set(counts_a).union(counts_b)):
        if feature not in feature_weights:
            raise ValueError(f"missing weight for feature {feature!r}")
        weight = float(feature_weights[feature])
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("feature weights must be finite and nonnegative")
        count_a = counts_a[feature]
        count_b = counts_b[feature]
        contributions.append(
            WeightedFeatureContribution(
                feature=feature,
                count_a=count_a,
                count_b=count_b,
                weight=weight,
                numerator=weight * min(count_a, count_b),
                denominator=weight * max(count_a, count_b),
                positions_a=positions_a.get(feature, ()),
                positions_b=positions_b.get(feature, ()),
            )
        )
    numerator = math.fsum(item.numerator for item in contributions)
    denominator = math.fsum(item.denominator for item in contributions)
    return WeightedJaccardResult(
        score=numerator / denominator if denominator else 0.0,
        numerator=numerator,
        denominator=denominator,
        contributions=tuple(contributions),
    )


def _validated_counts(counts: Mapping[Feature, int], *, name: str) -> dict[Feature, int]:
    validated: dict[Feature, int] = {}
    for feature, count in counts.items():
        if not feature:
            raise ValueError(f"{name} cannot contain an empty feature")
        if isinstance(count, bool) or count < 0:
            raise ValueError(f"{name} counts must be nonnegative integers")
        if count:
            validated[feature] = count
    return validated


def tfidf_idf(document_frequency: int, document_count: int, *, smooth_idf: bool = True) -> float:
    """Return explicit natural-log IDF, matching the registered sklearn formula."""

    if document_count < 1:
        raise ValueError("document_count must be positive")
    if document_frequency < 0 or document_frequency > document_count:
        raise ValueError("document_frequency must be between zero and document_count")
    if smooth_idf:
        return math.log((1.0 + document_count) / (1.0 + document_frequency)) + 1.0
    if document_frequency == 0:
        raise ValueError("unsmoothed IDF is undefined for zero document frequency")
    return math.log(document_count / document_frequency) + 1.0


def tfidf_vector(
    term_counts: Mapping[Feature, int],
    document_frequencies: Mapping[Feature, int],
    document_count: int,
    *,
    sublinear_tf: bool = True,
    smooth_idf: bool = True,
    l2_normalize: bool = True,
) -> dict[Feature, float]:
    """Build one explicit deterministic float64-compatible TF-IDF vector."""

    counts = _validated_counts(term_counts, name="term_counts")
    values: dict[Feature, float] = {}
    for feature in sorted(counts):
        if feature not in document_frequencies:
            raise ValueError(f"missing document frequency for feature {feature!r}")
        tf = 1.0 + math.log(counts[feature]) if sublinear_tf else float(counts[feature])
        values[feature] = tf * tfidf_idf(
            document_frequencies[feature], document_count, smooth_idf=smooth_idf
        )
    if l2_normalize:
        norm = math.sqrt(math.fsum(value * value for value in values.values()))
        if norm:
            values = {feature: value / norm for feature, value in values.items()}
    return values


def tfidf_cosine_similarity(
    counts_a: Mapping[Feature, int],
    counts_b: Mapping[Feature, int],
    document_frequencies: Mapping[Feature, int],
    document_count: int,
    *,
    sublinear_tf: bool = True,
    smooth_idf: bool = True,
) -> TfidfCosineResult:
    """Calculate explicit TF-IDF cosine with natural-log TF and IDF formulas."""

    validated_a = _validated_counts(counts_a, name="counts_a")
    validated_b = _validated_counts(counts_b, name="counts_b")
    raw_a = tfidf_vector(
        validated_a,
        document_frequencies,
        document_count,
        sublinear_tf=sublinear_tf,
        smooth_idf=smooth_idf,
        l2_normalize=False,
    )
    raw_b = tfidf_vector(
        validated_b,
        document_frequencies,
        document_count,
        sublinear_tf=sublinear_tf,
        smooth_idf=smooth_idf,
        l2_normalize=False,
    )
    norm_a = math.sqrt(math.fsum(value * value for value in raw_a.values()))
    norm_b = math.sqrt(math.fsum(value * value for value in raw_b.values()))
    contributions: list[TfidfTermContribution] = []
    for feature in sorted(set(validated_a).union(validated_b)):
        document_frequency = document_frequencies.get(feature)
        if document_frequency is None:
            raise ValueError(f"missing document frequency for feature {feature!r}")
        idf = tfidf_idf(document_frequency, document_count, smooth_idf=smooth_idf)
        value_a = raw_a.get(feature, 0.0)
        value_b = raw_b.get(feature, 0.0)
        normalized_a = value_a / norm_a if norm_a else 0.0
        normalized_b = value_b / norm_b if norm_b else 0.0
        contributions.append(
            TfidfTermContribution(
                feature=feature,
                count_a=validated_a.get(feature, 0),
                count_b=validated_b.get(feature, 0),
                document_frequency=document_frequency,
                idf=idf,
                value_a=value_a,
                value_b=value_b,
                normalized_value_a=normalized_a,
                normalized_value_b=normalized_b,
                dot_contribution=normalized_a * normalized_b,
            )
        )
    dot_product = math.fsum(item.value_a * item.value_b for item in contributions)
    score = dot_product / (norm_a * norm_b) if norm_a and norm_b else 0.0
    return TfidfCosineResult(
        score=score,
        dot_product=dot_product,
        norm_a=norm_a,
        norm_b=norm_b,
        document_count=document_count,
        sublinear_tf=sublinear_tf,
        smooth_idf=smooth_idf,
        contributions=tuple(contributions),
    )


def bm25_idf(document_frequency: int, document_count: int) -> float:
    """Return Robertson BM25 IDF with the positive ``log(1 + ratio)`` form."""

    if document_count < 1:
        raise ValueError("document_count must be positive")
    if document_frequency < 0 or document_frequency > document_count:
        raise ValueError("document_frequency must be between zero and document_count")
    return math.log(1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))


def bm25_score(
    query_counts: Mapping[Feature, int],
    document_counts: Mapping[Feature, int],
    document_frequencies: Mapping[Feature, int],
    document_count: int,
    *,
    document_length: int,
    average_document_length: float,
    k1: float = 1.2,
    b: float = 0.75,
    query_term_frequency_mode: QueryTermFrequencyMode = "binary",
) -> BM25Result:
    """Calculate directional BM25 with explicit query-frequency behavior."""

    query = _validated_counts(query_counts, name="query_counts")
    document = _validated_counts(document_counts, name="document_counts")
    if document_length < 0:
        raise ValueError("document_length cannot be negative")
    if sum(document.values()) > document_length:
        raise ValueError("document term counts cannot exceed document_length")
    if not math.isfinite(average_document_length) or average_document_length <= 0.0:
        raise ValueError("average_document_length must be finite and positive")
    if not math.isfinite(k1) or k1 <= 0.0:
        raise ValueError("k1 must be finite and positive")
    if not math.isfinite(b) or not 0.0 <= b <= 1.0:
        raise ValueError("b must be between zero and one")
    if query_term_frequency_mode not in {"binary", "linear"}:
        raise ValueError("query_term_frequency_mode must be binary or linear")
    length_normalizer = k1 * (1.0 - b + b * document_length / average_document_length)
    contributions: list[BM25TermContribution] = []
    for feature in sorted(query):
        if feature not in document_frequencies:
            raise ValueError(f"missing document frequency for feature {feature!r}")
        document_frequency = document_frequencies[feature]
        idf = bm25_idf(document_frequency, document_count)
        term_count = document.get(feature, 0)
        saturation = (
            term_count * (k1 + 1.0) / (term_count + length_normalizer) if term_count else 0.0
        )
        query_weight = 1.0 if query_term_frequency_mode == "binary" else float(query[feature])
        contributions.append(
            BM25TermContribution(
                feature=feature,
                query_count=query[feature],
                document_term_count=term_count,
                document_frequency=document_frequency,
                idf=idf,
                query_weight=query_weight,
                term_saturation=saturation,
                contribution=idf * query_weight * saturation,
            )
        )
    return BM25Result(
        score=math.fsum(item.contribution for item in contributions),
        corpus_document_count=document_count,
        document_length=document_length,
        average_document_length=average_document_length,
        k1=k1,
        b=b,
        query_term_frequency_mode=query_term_frequency_mode,
        contributions=tuple(contributions),
    )


def rare_feature_overlap(
    features_a: Sequence[Feature],
    features_b: Sequence[Feature],
    corpus_frequencies: Mapping[Feature, int],
    document_frequencies: Mapping[Feature, int],
    *,
    maximum_corpus_frequency: int,
    feature_passage_ids: Mapping[Feature, Sequence[str]] | None = None,
    passage_a_id: str | None = None,
    passage_b_id: str | None = None,
) -> RareOverlapResult:
    """Score shared rare features by the transparent sum of ``1 / corpus_frequency``.

    This function deliberately does not decide review eligibility: a single rare
    item still requires an independent co-signal at the candidate-policy layer.
    """

    if maximum_corpus_frequency < 1:
        raise ValueError("maximum_corpus_frequency must be positive")
    sequence_a = _validated_sequence(features_a, name="features_a")
    sequence_b = _validated_sequence(features_b, name="features_b")
    positions_a = _positions(sequence_a)
    positions_b = _positions(sequence_b)
    evidence: list[RareFeatureEvidence] = []
    excluded_passages = {value for value in (passage_a_id, passage_b_id) if value is not None}
    for feature in sorted(set(positions_a).intersection(positions_b)):
        if feature not in corpus_frequencies or feature not in document_frequencies:
            raise ValueError(f"missing frequency statistics for feature {feature!r}")
        corpus_frequency = corpus_frequencies[feature]
        document_frequency = document_frequencies[feature]
        if corpus_frequency < 1 or document_frequency < 1:
            raise ValueError("shared features require positive corpus and document frequencies")
        if document_frequency > corpus_frequency:
            raise ValueError("document frequency cannot exceed corpus frequency")
        if corpus_frequency <= maximum_corpus_frequency:
            alternatives = (
                tuple(
                    sorted(set(feature_passage_ids.get(feature, ())).difference(excluded_passages))
                )
                if feature_passage_ids is not None
                else ()
            )
            evidence.append(
                RareFeatureEvidence(
                    feature=feature,
                    corpus_frequency=corpus_frequency,
                    document_frequency=document_frequency,
                    inverse_frequency_weight=1.0 / corpus_frequency,
                    positions_a=positions_a[feature],
                    positions_b=positions_b[feature],
                    alternative_passage_ids=alternatives,
                )
            )
    return RareOverlapResult(
        score=math.fsum(item.inverse_frequency_weight for item in evidence),
        threshold=maximum_corpus_frequency,
        evidence=tuple(evidence),
    )


def longest_common_subsequence(
    features_a: Sequence[Feature],
    features_b: Sequence[Feature],
    *,
    normalization: Normalization = "shorter",
) -> LCSResult:
    """Return one stable LCS, preferring an upward traceback on equal-length ties."""

    if normalization not in {"shorter", "geometric", "mean"}:
        raise ValueError("unknown LCS normalization")
    sequence_a = _validated_sequence(features_a, name="features_a")
    sequence_b = _validated_sequence(features_b, name="features_b")
    rows = len(sequence_a) + 1
    columns = len(sequence_b) + 1
    lengths = [[0] * columns for _ in range(rows)]
    for index_a, feature_a in enumerate(sequence_a, start=1):
        for index_b, feature_b in enumerate(sequence_b, start=1):
            if feature_a == feature_b:
                lengths[index_a][index_b] = lengths[index_a - 1][index_b - 1] + 1
            else:
                lengths[index_a][index_b] = max(
                    lengths[index_a - 1][index_b], lengths[index_a][index_b - 1]
                )
    position_pairs: list[tuple[int, int]] = []
    index_a = len(sequence_a)
    index_b = len(sequence_b)
    while index_a and index_b:
        if sequence_a[index_a - 1] == sequence_b[index_b - 1]:
            position_pairs.append((index_a - 1, index_b - 1))
            index_a -= 1
            index_b -= 1
        elif lengths[index_a - 1][index_b] >= lengths[index_a][index_b - 1]:
            index_a -= 1
        else:
            index_b -= 1
    position_pairs.reverse()
    length = len(position_pairs)
    shorter_denominator = min(len(sequence_a), len(sequence_b))
    geometric_denominator = math.sqrt(len(sequence_a) * len(sequence_b))
    mean_denominator = (len(sequence_a) + len(sequence_b)) / 2.0
    normalized_by_shorter = length / shorter_denominator if shorter_denominator else 0.0
    normalized_by_geometric = length / geometric_denominator if geometric_denominator else 0.0
    normalized_by_mean = length / mean_denominator if mean_denominator else 0.0
    selected = {
        "shorter": normalized_by_shorter,
        "geometric": normalized_by_geometric,
        "mean": normalized_by_mean,
    }[normalization]
    return LCSResult(
        length=length,
        features=tuple(sequence_a[position_a] for position_a, _ in position_pairs),
        positions_a=tuple(position_a for position_a, _ in position_pairs),
        positions_b=tuple(position_b for _, position_b in position_pairs),
        normalized_by_shorter=normalized_by_shorter,
        normalized_by_geometric=normalized_by_geometric,
        normalized_by_mean=normalized_by_mean,
        normalized_score=selected,
        normalization=normalization,
    )


def weighted_sequence_alignment(
    features_a: Sequence[Feature],
    features_b: Sequence[Feature],
    feature_weights: Mapping[Feature, float],
    *,
    gap_penalty: float,
    mismatch_score: float,
    mode: AlignmentMode = "local",
) -> WeightedAlignmentResult:
    """Align sequences with exact-match weights and a stable linear-gap traceback.

    Diagonal, gap-in-B, and gap-in-A transitions are considered in that order,
    which completely specifies tie behavior.  Local alignments choose the first
    maximum endpoint in row-major order.
    """

    sequence_a = _validated_sequence(features_a, name="features_a")
    sequence_b = _validated_sequence(features_b, name="features_b")
    if mode not in {"local", "global"}:
        raise ValueError("alignment mode must be local or global")
    if not math.isfinite(gap_penalty) or gap_penalty < 0.0:
        raise ValueError("gap_penalty must be finite and nonnegative")
    if not math.isfinite(mismatch_score) or mismatch_score > 0.0:
        raise ValueError("mismatch_score must be finite and nonpositive")
    weights: dict[Feature, float] = {}
    for feature in sorted(set(sequence_a).union(sequence_b)):
        if feature not in feature_weights:
            raise ValueError(f"missing alignment weight for feature {feature!r}")
        weight = float(feature_weights[feature])
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError("alignment feature weights must be finite and positive")
        weights[feature] = weight

    row_count = len(sequence_a) + 1
    column_count = len(sequence_b) + 1
    scores = [[0.0] * column_count for _ in range(row_count)]
    pointers: list[list[str | None]] = [[None] * column_count for _ in range(row_count)]
    if mode == "global":
        for index_a in range(1, row_count):
            scores[index_a][0] = -gap_penalty * index_a
            pointers[index_a][0] = "up"
        for index_b in range(1, column_count):
            scores[0][index_b] = -gap_penalty * index_b
            pointers[0][index_b] = "left"

    best_score = 0.0
    best_endpoint = (0, 0)
    for index_a in range(1, row_count):
        for index_b in range(1, column_count):
            feature_a = sequence_a[index_a - 1]
            feature_b = sequence_b[index_b - 1]
            diagonal_delta = weights[feature_a] if feature_a == feature_b else mismatch_score
            candidates = (
                (scores[index_a - 1][index_b - 1] + diagonal_delta, "diagonal"),
                (scores[index_a - 1][index_b] - gap_penalty, "up"),
                (scores[index_a][index_b - 1] - gap_penalty, "left"),
            )
            cell_score, pointer = max(candidates, key=lambda item: item[0])
            if mode == "local" and cell_score <= 0.0:
                scores[index_a][index_b] = 0.0
                pointers[index_a][index_b] = None
            else:
                scores[index_a][index_b] = cell_score
                pointers[index_a][index_b] = pointer
                if mode == "local" and cell_score > best_score:
                    best_score = cell_score
                    best_endpoint = (index_a, index_b)

    if mode == "global":
        best_endpoint = (len(sequence_a), len(sequence_b))
        best_score = scores[-1][-1]

    steps: list[AlignmentStep] = []
    index_a, index_b = best_endpoint
    while index_a or index_b:
        traceback_pointer = pointers[index_a][index_b]
        if traceback_pointer is None:
            break
        if traceback_pointer == "diagonal":
            position_a = index_a - 1
            position_b = index_b - 1
            feature_a = sequence_a[position_a]
            feature_b = sequence_b[position_b]
            is_match = feature_a == feature_b
            steps.append(
                AlignmentStep(
                    operation="match" if is_match else "mismatch",
                    position_a=position_a,
                    position_b=position_b,
                    feature_a=feature_a,
                    feature_b=feature_b,
                    contribution=weights[feature_a] if is_match else mismatch_score,
                )
            )
            index_a -= 1
            index_b -= 1
        elif traceback_pointer == "up":
            position_a = index_a - 1
            steps.append(
                AlignmentStep(
                    operation="gap_in_b",
                    position_a=position_a,
                    position_b=None,
                    feature_a=sequence_a[position_a],
                    feature_b=None,
                    contribution=-gap_penalty,
                )
            )
            index_a -= 1
        else:
            position_b = index_b - 1
            steps.append(
                AlignmentStep(
                    operation="gap_in_a",
                    position_a=None,
                    position_b=position_b,
                    feature_a=None,
                    feature_b=sequence_b[position_b],
                    contribution=-gap_penalty,
                )
            )
            index_b -= 1
    steps.reverse()
    matches = tuple(step for step in steps if step.operation == "match")
    normalizer = min(
        math.fsum(weights[feature] for feature in sequence_a),
        math.fsum(weights[feature] for feature in sequence_b),
    )
    return WeightedAlignmentResult(
        score=best_score,
        normalized_score=best_score / normalizer if normalizer else 0.0,
        normalization_denominator=normalizer,
        mode=mode,
        gap_penalty=gap_penalty,
        mismatch_score=mismatch_score,
        steps=tuple(steps),
        matched_features=tuple(step.feature_a for step in matches if step.feature_a is not None),
        matched_positions_a=tuple(
            step.position_a for step in matches if step.position_a is not None
        ),
        matched_positions_b=tuple(
            step.position_b for step in matches if step.position_b is not None
        ),
    )
