"""Blockwise candidate-union retrieval and decomposable lexical reranking."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, cast

import polars as pl

from echoes.lexical.composite import reciprocal_rank_fusion
from echoes.lexical.config import AnalysisProfile, CorpusPair, Granularity
from echoes.lexical.identity import (
    CandidatePairIdentityPayload,
    RankingIdentityPayload,
    build_candidate_pair_identity,
    build_ranking_identity,
)
from echoes.lexical.models import ABLATION_RESULTS_SCHEMA, DIRECTIONAL_RANKINGS_SCHEMA
from echoes.lexical.phrases import (
    bigram_log_likelihood,
    pointwise_mutual_information,
)
from echoes.lexical.sequences import PassageLexicalSequence
from echoes.lexical.sparse import (
    RetrievalHit,
    SparseLexicalIndex,
    prepare_sparse_retrieval,
    retrieve_prepared_bm25,
    retrieve_prepared_overlap,
    retrieve_prepared_rare,
    retrieve_prepared_tfidf,
)


class LexicalRetrievalError(RuntimeError):
    """Raised when governed retrieval cannot be completed deterministically."""


class RetrievalResourceCheck(Protocol):
    def __call__(self, stage: str, *, estimated_additional_bytes: int = 0) -> None: ...


_MEBIBYTE = 1024**2
_DEFAULT_MATERIALIZATION_TARGET_BYTES = 256 * _MEBIBYTE
_RANKING_ROW_FIXED_BYTES = 4096
_CANDIDATE_UPDATE_FIXED_BYTES = 4096
_FRAME_CONSTRUCTION_MULTIPLIER = 3


DETECTOR_FAMILIES: dict[str, str] = {
    "jaccard": "set_overlap",
    "weighted_jaccard": "set_overlap",
    "tfidf_cosine": "vector_space",
    "bm25": "vector_space",
    "rare_lemma_root": "rare_lexical",
    "phrase_association": "phrase",
    "longest_common_subsequence": "ordered_sequence",
    "weighted_sequence_alignment": "ordered_sequence",
    "pos_morphology_support": "pos_morphology",
}


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """One directional candidate with every transparent detector score."""

    query_index: int
    target_index: int
    scores: dict[str, float]
    independent_co_signal_count: int
    rare_rule_passed: bool
    proposal_detectors: tuple[str, ...] = ()
    alignment_evaluated: bool = False


@dataclass(frozen=True, slots=True)
class CandidateDirection:
    """Persisted best directional evidence for one canonical candidate pair."""

    direction: Literal["a_to_b", "b_to_a"]
    query_passage_id: str
    target_passage_id: str
    scores: dict[str, float]
    ranks: dict[str, int]
    rrf_score: float
    proposal_detectors: tuple[str, ...] = ()
    alignment_evaluated: bool = False
    score_trace_version: str = "legacy_fixture_unverified"


@dataclass(slots=True)
class CandidateAggregate:
    """Canonical unordered candidate accumulated across query directions."""

    candidate_pair_id: str
    canonical_unordered_pair_id: str
    passage_a_id: str
    passage_b_id: str
    corpus_pair: str
    analysis_profile: str
    granularity: str
    directions: dict[str, CandidateDirection] = field(default_factory=dict)
    best_rrf_score: float = 0.0

    def add_direction(self, evidence: CandidateDirection) -> None:
        previous = self.directions.get(evidence.direction)
        if previous is None or (evidence.rrf_score, evidence.query_passage_id) > (
            previous.rrf_score,
            previous.query_passage_id,
        ):
            self.directions[evidence.direction] = evidence
        self.best_rrf_score = max(self.best_rrf_score, evidence.rrf_score)


@dataclass(frozen=True, slots=True)
class RetrievalBatch:
    """One bounded ranking frame plus candidate aggregate updates."""

    rankings: pl.DataFrame
    ablation_results: pl.DataFrame
    candidates: tuple[CandidateAggregate, ...]


@dataclass(frozen=True, slots=True)
class PhraseAssociationIndex:
    """Corpus-scoped, frequency-controlled phrase weights for exact reranking."""

    weights: Mapping[tuple[str, ...], float]
    corpus_frequency: Mapping[tuple[str, ...], int]
    document_frequency: Mapping[tuple[str, ...], int]
    pmi: Mapping[tuple[str, ...], float]
    log_likelihood: Mapping[tuple[str, ...], float]
    skipgram_weights: Mapping[tuple[str, str], float]
    skipgram_corpus_frequency: Mapping[tuple[str, str], int]
    skipgram_document_frequency: Mapping[tuple[str, str], int]


@dataclass(frozen=True, slots=True)
class _PassagePhraseFeatures:
    """Raw phrase identities retained once while corpus weights are derived."""

    phrases: frozenset[tuple[str, ...]]
    skipgrams: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _PassageScoreContext:
    """Immutable passage features reused across every candidate-pair comparison."""

    passage: PassageLexicalSequence
    sequence_values: tuple[str, ...]
    value_counts: Mapping[str, int]
    lcs_position_masks: Mapping[str, int]
    phrase_features: frozenset[tuple[str, ...]]
    skipgram_features: frozenset[tuple[str, str]]
    part_of_speech_values: tuple[str, ...]
    part_of_speech_lcs_position_masks: Mapping[str, int]
    morphology_values: tuple[str, ...]
    morphology_lcs_position_masks: Mapping[str, int]
    gloss_values: frozenset[str]
    gloss_feature_count: int
    gloss_coverage: float


@dataclass(frozen=True, slots=True)
class _PairRankingContext:
    """Pair evidence that is identical across every persisted detector row."""

    target: PassageLexicalSequence
    passage_overlap: bool
    nearby_context: bool
    same_book: bool
    gloss_overlap_count: int


def _extract_phrase_occurrences(
    values: Sequence[str],
    *,
    ngram_sizes: Sequence[int],
    skipgram_max_gap: int,
) -> tuple[
    list[tuple[str, ...]],
    list[tuple[str, str]],
    _PassagePhraseFeatures,
]:
    """Extract the exact governed n=2/3 and two-item skip-gram identities once."""

    if any(not value for value in values):
        raise ValueError("feature sequences cannot contain empty values")
    if any(size < 1 for size in ngram_sizes):
        raise ValueError("n must be positive")
    if skipgram_max_gap < 0:
        raise ValueError("max_gap cannot be negative")
    contiguous_occurrences = [
        tuple(values[start : start + size])
        for size in ngram_sizes
        for start in range(len(values) - size + 1)
    ]
    skipgram_occurrences = [
        (values[left], values[right])
        for left in range(len(values))
        for right in range(
            left + 2,
            min(len(values), left + skipgram_max_gap + 2),
        )
    ]
    return (
        contiguous_occurrences,
        skipgram_occurrences,
        _PassagePhraseFeatures(
            phrases=frozenset(contiguous_occurrences),
            skipgrams=frozenset(skipgram_occurrences),
        ),
    )


def _build_phrase_association_index_with_features(
    sequences: Sequence[PassageLexicalSequence],
    *,
    sequence_family: str,
    ngram_sizes: Sequence[int],
    minimum_corpus_count: int,
    pmi_cap: float,
    skipgram_max_gap: int,
    skipgram_minimum_corpus_count: int,
    retain_passage_features: bool,
) -> tuple[PhraseAssociationIndex, tuple[_PassagePhraseFeatures, ...]]:
    """Build corpus weights and optionally retain the already-extracted passage sets."""

    sizes = tuple(ngram_sizes)
    if sizes != tuple(sorted(set(sizes))) or any(size not in {2, 3} for size in sizes):
        raise LexicalRetrievalError("phrase n-gram sizes must be a sorted unique subset of {2, 3}")
    if minimum_corpus_count < 2 or skipgram_minimum_corpus_count < 2:
        raise LexicalRetrievalError("phrase and skip-gram minimum counts must be at least two")
    if not math.isfinite(pmi_cap) or pmi_cap <= 0.0:
        raise LexicalRetrievalError("PMI cap must be finite and positive")
    if skipgram_max_gap < 1:
        raise LexicalRetrievalError("skip-gram maximum gap must be positive")
    unigram_counts: Counter[str] = Counter()
    phrase_counts: Counter[tuple[str, ...]] = Counter()
    phrase_documents: Counter[tuple[str, ...]] = Counter()
    skipped_counts: Counter[tuple[str, str]] = Counter()
    skipped_documents: Counter[tuple[str, str]] = Counter()
    bigram_first_counts: Counter[str] = Counter()
    bigram_second_counts: Counter[str] = Counter()
    bigram_slot_count = 0
    retained_features: list[_PassagePhraseFeatures] = []
    for passage in sequences:
        values = passage.values(sequence_family)
        unigram_counts.update(values)
        if 2 in sizes and len(values) >= 2:
            bigram_first_counts.update(values[:-1])
            bigram_second_counts.update(values[1:])
            bigram_slot_count += len(values) - 1
        phrase_occurrences, skipgram_occurrences, passage_features = _extract_phrase_occurrences(
            values,
            ngram_sizes=sizes,
            skipgram_max_gap=skipgram_max_gap,
        )
        phrase_counts.update(phrase_occurrences)
        phrase_documents.update(passage_features.phrases)
        skipped_counts.update(skipgram_occurrences)
        skipped_documents.update(passage_features.skipgrams)
        if retain_passage_features:
            retained_features.append(passage_features)
    total_count = sum(unigram_counts.values())
    weights: dict[tuple[str, ...], float] = {}
    pmi_values: dict[tuple[str, ...], float] = {}
    likelihood_values: dict[tuple[str, ...], float] = {}
    if total_count:
        for phrase, count in sorted(phrase_counts.items()):
            if count < minimum_corpus_count:
                continue
            pmi_result = pointwise_mutual_information(
                count,
                [unigram_counts[value] for value in phrase],
                total_count,
                minimum_count=minimum_corpus_count,
                cap=pmi_cap,
            )
            likelihood = 0.0
            if len(phrase) == 2 and bigram_slot_count:
                likelihood = max(
                    0.0,
                    bigram_log_likelihood(
                        count,
                        bigram_first_counts[phrase[0]],
                        bigram_second_counts[phrase[1]],
                        bigram_slot_count,
                    ).signed_statistic,
                )
            pmi_value = max(0.0, pmi_result.value)
            # Penalize corpus-common phrases without discarding their raw evidence.
            frequency_control = 1.0 + math.log(count)
            weights[phrase] = (pmi_value + math.log1p(likelihood)) / frequency_control
            pmi_values[phrase] = pmi_result.value
            likelihood_values[phrase] = likelihood
    eligible_skips = {
        phrase: count
        for phrase, count in sorted(skipped_counts.items())
        if count >= skipgram_minimum_corpus_count
    }
    return (
        PhraseAssociationIndex(
            weights=weights,
            corpus_frequency={phrase: phrase_counts[phrase] for phrase in weights},
            document_frequency={phrase: phrase_documents[phrase] for phrase in weights},
            pmi=pmi_values,
            log_likelihood=likelihood_values,
            skipgram_weights={phrase: 1.0 / count for phrase, count in eligible_skips.items()},
            skipgram_corpus_frequency=eligible_skips,
            skipgram_document_frequency={
                phrase: skipped_documents[phrase] for phrase in eligible_skips
            },
        ),
        tuple(retained_features),
    )


def build_phrase_association_index(
    sequences: Sequence[PassageLexicalSequence],
    *,
    sequence_family: str,
    ngram_sizes: Sequence[int],
    minimum_corpus_count: int,
    pmi_cap: float,
    skipgram_max_gap: int,
    skipgram_minimum_corpus_count: int,
) -> PhraseAssociationIndex:
    """Build transparent PMI/LL phrase weights once per governed representation."""

    associations, _ = _build_phrase_association_index_with_features(
        sequences,
        sequence_family=sequence_family,
        ngram_sizes=ngram_sizes,
        minimum_corpus_count=minimum_corpus_count,
        pmi_cap=pmi_cap,
        skipgram_max_gap=skipgram_max_gap,
        skipgram_minimum_corpus_count=skipgram_minimum_corpus_count,
        retain_passage_features=False,
    )
    return associations


def _raw_value_map(index: SparseLexicalIndex, values: Iterable[float]) -> dict[str, float]:
    prefix = f"{index.namespace}:{index.family}:"
    result: dict[str, float] = {}
    for feature, value in zip(index.vocabulary, values, strict=True):
        if not feature.startswith(prefix) or feature == prefix:
            raise LexicalRetrievalError("sparse vocabulary violates its registered namespace")
        result[feature[len(prefix) :]] = float(value)
    return result


_NO_SPLIT_PROVENANCE = '{"status":"no_eligible_benchmark_assignment"}'


def _validated_split_provenance(
    values: Mapping[str, str], passage_ids: Sequence[str]
) -> dict[str, str]:
    """Return canonical per-passage split provenance with explicit nonassignment rows."""

    unknown = sorted(set(values).difference(passage_ids))
    if unknown:
        raise LexicalRetrievalError(f"split provenance references unknown passages: {unknown[:5]}")
    output: dict[str, str] = {}
    for passage_id in passage_ids:
        encoded = values.get(passage_id, _NO_SPLIT_PROVENANCE)
        try:
            parsed = json.loads(encoded)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LexicalRetrievalError(
                f"split provenance for {passage_id} is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict) or not parsed:
            raise LexicalRetrievalError(
                f"split provenance for {passage_id} must be a nonempty JSON object"
            )
        canonical = json.dumps(parsed, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if canonical != encoded:
            raise LexicalRetrievalError(f"split provenance for {passage_id} is not canonical JSON")
        output[passage_id] = canonical
    return output


def _lcs_position_masks(sequence: Sequence[str]) -> Mapping[str, int]:
    """Build immutable value-position masks for the exact bit-parallel LCS recurrence."""

    positions: dict[str, int] = defaultdict(int)
    for index, value in enumerate(sequence):
        positions[value] |= 1 << index
    return MappingProxyType(dict(positions))


def _bitset_lcs_length_from_masks(
    sequence_a: Sequence[str], position_masks: Mapping[str, int]
) -> int:
    """Calculate exact LCS length against immutable precomputed target masks."""

    state = 0
    for value in sequence_a:
        matches = position_masks.get(value, 0)
        union = state | matches
        state = union & ~(union - ((state << 1) | 1))
    return state.bit_count()


def _bitset_lcs_length(sequence_a: Sequence[str], sequence_b: Sequence[str]) -> int:
    """Calculate exact LCS length with a deterministic bit-parallel recurrence."""

    return _bitset_lcs_length_from_masks(sequence_a, _lcs_position_masks(sequence_b))


def _phrase_features(
    values: Sequence[str],
    *,
    ngram_sizes: Sequence[int],
    skipgram_max_gap: int,
) -> tuple[set[tuple[str, ...]], set[tuple[str, str]]]:
    _, _, features = _extract_phrase_occurrences(
        values,
        ngram_sizes=ngram_sizes,
        skipgram_max_gap=skipgram_max_gap,
    )
    return set(features.phrases), set(features.skipgrams)


def _build_passage_score_context(
    passage: PassageLexicalSequence,
    *,
    sequence_family: str,
    english_derived: bool,
    phrase_associations: PhraseAssociationIndex,
    phrase_ngram_sizes: Sequence[int],
    skipgram_max_gap: int,
    precomputed_phrase_features: _PassagePhraseFeatures | None = None,
) -> _PassageScoreContext:
    """Precompute immutable features whose values do not depend on the paired passage."""

    sequence_values = passage.values(sequence_family)
    if precomputed_phrase_features is None:
        extracted_phrases, extracted_skipgrams = _phrase_features(
            sequence_values,
            ngram_sizes=phrase_ngram_sizes,
            skipgram_max_gap=skipgram_max_gap,
        )
        raw_phrases = frozenset(extracted_phrases)
        raw_skipgrams = frozenset(extracted_skipgrams)
    else:
        raw_phrases = precomputed_phrase_features.phrases
        raw_skipgrams = precomputed_phrase_features.skipgrams
    phrase_features = frozenset(
        phrase for phrase in raw_phrases if phrase in phrase_associations.weights
    )
    skipgram_features = frozenset(
        skipgram for skipgram in raw_skipgrams if skipgram in phrase_associations.skipgram_weights
    )
    if english_derived:
        part_of_speech_values: tuple[str, ...] = ()
        morphology_values: tuple[str, ...] = ()
    else:
        part_of_speech_values = passage.values("part_of_speech")
        morphology_values = passage.values("morphology")
    gloss_values = passage.values("english_gloss")
    gloss_coverage = (
        len({feature.token_id for feature in passage.english_gloss}) / passage.token_count
        if passage.token_count
        else 0.0
    )
    return _PassageScoreContext(
        passage=passage,
        sequence_values=sequence_values,
        value_counts=MappingProxyType(dict(Counter(sequence_values))),
        lcs_position_masks=_lcs_position_masks(sequence_values),
        phrase_features=phrase_features,
        skipgram_features=skipgram_features,
        part_of_speech_values=part_of_speech_values,
        part_of_speech_lcs_position_masks=_lcs_position_masks(part_of_speech_values),
        morphology_values=morphology_values,
        morphology_lcs_position_masks=_lcs_position_masks(morphology_values),
        gloss_values=frozenset(gloss_values),
        gloss_feature_count=len(passage.english_gloss),
        gloss_coverage=gloss_coverage,
    )


def _pair_score_from_context(
    query: _PassageScoreContext,
    target: _PassageScoreContext,
    *,
    proposal_scores: Mapping[str, float],
    idf: Mapping[str, float],
    corpus_frequency: Mapping[str, int],
    rare_threshold: int,
    english_derived: bool,
    phrase_associations: PhraseAssociationIndex,
) -> ScoredCandidate:
    """Score a pair using precomputed passage features without changing the arithmetic."""

    counts_a = query.value_counts
    counts_b = target.value_counts
    set_a = set(counts_a)
    set_b = set(counts_b)
    shared = tuple(sorted(set_a & set_b))
    union = set_a | set_b
    jaccard = len(shared) / len(union) if union else 0.0
    weighted_numerator = math.fsum(
        idf.get(value, 1.0) * min(counts_a[value], counts_b[value]) for value in shared
    )
    weighted_denominator = math.fsum(
        idf.get(value, 1.0) * max(counts_a.get(value, 0), counts_b.get(value, 0)) for value in union
    )
    weighted_jaccard = weighted_numerator / weighted_denominator if weighted_denominator else 0.0
    shared_rare = tuple(
        value for value in shared if 0 < corpus_frequency.get(value, 0) <= rare_threshold
    )
    rare_score = math.fsum(1.0 / corpus_frequency[value] for value in shared_rare)
    shared_phrases_tuples = sorted(query.phrase_features & target.phrase_features)
    shared_skip_tuples = sorted(query.skipgram_features & target.skipgram_features)
    phrase_score = math.fsum(
        phrase_associations.weights[phrase] for phrase in shared_phrases_tuples
    ) + math.fsum(phrase_associations.skipgram_weights[phrase] for phrase in shared_skip_tuples)
    lcs_length = _bitset_lcs_length_from_masks(query.sequence_values, target.lcs_position_masks)
    shorter = min(len(query.sequence_values), len(target.sequence_values))
    normalized_lcs = lcs_length / shorter if shorter else 0.0
    sequence_support: list[float] = []
    if not english_derived:
        for support_a, support_b, support_b_masks in (
            (
                query.part_of_speech_values,
                target.part_of_speech_values,
                target.part_of_speech_lcs_position_masks,
            ),
            (
                query.morphology_values,
                target.morphology_values,
                target.morphology_lcs_position_masks,
            ),
        ):
            shorter_support = min(len(support_a), len(support_b))
            if shorter_support:
                sequence_support.append(
                    _bitset_lcs_length_from_masks(support_a, support_b_masks) / shorter_support
                )
    pos_morph = math.fsum(sequence_support) / len(sequence_support) if sequence_support else 0.0
    co_signal_count = 0
    if len(shared_rare) >= 2:
        co_signal_count += 1
    if any(len(set(phrase).difference(shared_rare[:1])) >= 1 for phrase in shared_phrases_tuples):
        co_signal_count += 1
    if lcs_length >= 3 and len(set(shared).difference(shared_rare[:1])) >= 2:
        co_signal_count += 1
    if pos_morph > 0.5 and len(shared) >= 2:
        co_signal_count += 1
    rare_rule_passed = not english_derived and (not shared_rare or co_signal_count > 0)
    scores = {
        "jaccard": jaccard,
        "weighted_jaccard": weighted_jaccard,
        "tfidf_cosine": float(proposal_scores.get("tfidf_cosine", 0.0)),
        "bm25": float(proposal_scores.get("bm25", 0.0)),
        "rare_lemma_root": max(rare_score, float(proposal_scores.get("rare_lemma_root", 0.0))),
        "phrase_association": phrase_score,
        "longest_common_subsequence": normalized_lcs,
        "weighted_sequence_alignment": 0.0,
        "pos_morphology_support": pos_morph,
    }
    return ScoredCandidate(
        query_index=-1,
        target_index=-1,
        scores=scores,
        independent_co_signal_count=co_signal_count,
        rare_rule_passed=rare_rule_passed,
        proposal_detectors=tuple(sorted(proposal_scores)),
    )


def _pair_score(
    query: PassageLexicalSequence,
    target: PassageLexicalSequence,
    *,
    proposal_scores: Mapping[str, float],
    idf: Mapping[str, float],
    corpus_frequency: Mapping[str, int],
    rare_threshold: int,
    sequence_family: str,
    english_derived: bool,
    phrase_associations: PhraseAssociationIndex,
    phrase_ngram_sizes: Sequence[int],
    skipgram_max_gap: int,
) -> ScoredCandidate:
    query_context = _build_passage_score_context(
        query,
        sequence_family=sequence_family,
        english_derived=english_derived,
        phrase_associations=phrase_associations,
        phrase_ngram_sizes=phrase_ngram_sizes,
        skipgram_max_gap=skipgram_max_gap,
    )
    target_context = _build_passage_score_context(
        target,
        sequence_family=sequence_family,
        english_derived=english_derived,
        phrase_associations=phrase_associations,
        phrase_ngram_sizes=phrase_ngram_sizes,
        skipgram_max_gap=skipgram_max_gap,
    )
    return _pair_score_from_context(
        query_context,
        target_context,
        proposal_scores=proposal_scores,
        idf=idf,
        corpus_frequency=corpus_frequency,
        rare_threshold=rare_threshold,
        english_derived=english_derived,
        phrase_associations=phrase_associations,
    )


def _weighted_local_alignment_normalized_score(
    sequence_a: Sequence[str],
    sequence_b: Sequence[str],
    feature_weights: Mapping[str, float],
    *,
    gap_penalty: float,
    mismatch_score: float,
) -> float:
    """Return the detector's exact local score using two rolling score rows."""

    if not sequence_a or not sequence_b:
        return 0.0
    previous = [0.0] * (len(sequence_b) + 1)
    best_score = 0.0
    for feature_a in sequence_a:
        current = [0.0] * (len(sequence_b) + 1)
        for index_b, feature_b in enumerate(sequence_b, start=1):
            diagonal_delta = (
                feature_weights[feature_a] if feature_a == feature_b else mismatch_score
            )
            cell_score = max(
                previous[index_b - 1] + diagonal_delta,
                previous[index_b] - gap_penalty,
                current[index_b - 1] - gap_penalty,
            )
            if cell_score > 0.0:
                current[index_b] = cell_score
                if cell_score > best_score:
                    best_score = cell_score
        previous = current
    normalizer = min(
        math.fsum(feature_weights[feature] for feature in sequence_a),
        math.fsum(feature_weights[feature] for feature in sequence_b),
    )
    return best_score / normalizer if normalizer else 0.0


def _exact_alignment_score(
    query: _PassageScoreContext,
    target: _PassageScoreContext,
    *,
    idf: Mapping[str, float],
    gap_penalty: float,
    mismatch_score: float,
) -> float:
    values = set(query.sequence_values) | set(target.sequence_values)
    if not values:
        return 0.0
    return _weighted_local_alignment_normalized_score(
        query.sequence_values,
        target.sequence_values,
        {value: max(1e-12, idf.get(value, 1.0)) for value in values},
        gap_penalty=abs(gap_penalty),
        mismatch_score=mismatch_score,
    )


def _hits_by_query(hits: Sequence[RetrievalHit]) -> dict[int, list[RetrievalHit]]:
    grouped: dict[int, list[RetrievalHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.query_index].append(hit)
    return grouped


def _book_ordinals(sequences: Sequence[PassageLexicalSequence]) -> dict[str, int]:
    result: dict[str, int] = {}
    grouped: dict[tuple[str, str], list[PassageLexicalSequence]] = defaultdict(list)
    for passage in sequences:
        grouped[(passage.corpus, passage.book)].append(passage)
    for members in grouped.values():
        for ordinal, passage in enumerate(
            sorted(members, key=lambda item: item.start_stream_position_in_corpus)
        ):
            result[passage.passage_id] = ordinal
    return result


def iter_retrieval_batches(
    index: SparseLexicalIndex,
    sequences: Sequence[PassageLexicalSequence],
    *,
    experiment_run_id: str,
    configuration_hash: str,
    experiment_scope: str,
    corpus_pair: CorpusPair,
    query_indices: Sequence[int],
    target_indices: Sequence[int],
    candidate_union_k: int,
    persisted_top_k: int,
    persisted_candidate_pool_k: int,
    expensive_sequence_rerank_k: int,
    block_size: int,
    maximum_proposal_document_frequency: int,
    score_quantization_decimals: int,
    bm25_k1: float,
    bm25_b: float,
    rare_threshold: int,
    rrf_k: int,
    gap_penalty: float,
    mismatch_score: float,
    nearby_context_distance: int,
    phrase_ngram_sizes: Sequence[int],
    phrase_minimum_corpus_count: int,
    phrase_pmi_cap: float,
    skipgram_max_gap: int,
    skipgram_minimum_corpus_count: int,
    split_provenance_by_passage_id: Mapping[str, str],
    materialization_target_bytes: int = _DEFAULT_MATERIALIZATION_TARGET_BYTES,
    resource_check: RetrievalResourceCheck | None = None,
) -> Iterator[RetrievalBatch]:
    """Run four sparse proposals, exact reranking, and RRF in bounded batches."""

    ordered = sorted(sequences, key=lambda item: item.passage_id)
    if tuple(item.passage_id for item in ordered) != index.passage_ids:
        raise LexicalRetrievalError("sequence and sparse-index passage order differ")
    if not experiment_run_id:
        raise LexicalRetrievalError("experiment_run_id must be nonempty")
    if len(configuration_hash) != 64 or any(
        value not in "0123456789abcdef" for value in configuration_hash
    ):
        raise LexicalRetrievalError("configuration_hash must be a lowercase SHA-256 digest")
    if not experiment_scope:
        raise LexicalRetrievalError("experiment_scope must be nonempty")
    if not math.isfinite(gap_penalty) or gap_penalty > 0.0:
        raise LexicalRetrievalError("configured gap penalty must be finite and nonpositive")
    if not math.isfinite(mismatch_score) or mismatch_score > 0.0:
        raise LexicalRetrievalError("configured mismatch score must be finite and nonpositive")
    if any(
        value < 1
        for value in (
            candidate_union_k,
            persisted_top_k,
            persisted_candidate_pool_k,
            expensive_sequence_rerank_k,
            block_size,
            maximum_proposal_document_frequency,
            rare_threshold,
            rrf_k,
            nearby_context_distance,
        )
    ):
        raise LexicalRetrievalError("retrieval depths, thresholds, and block size must be positive")
    if candidate_union_k < persisted_top_k:
        raise LexicalRetrievalError("candidate union K cannot be below persisted top K")
    if persisted_top_k < persisted_candidate_pool_k:
        raise LexicalRetrievalError("persisted top K cannot be below candidate pool K")
    if persisted_candidate_pool_k < expensive_sequence_rerank_k:
        raise LexicalRetrievalError("candidate pool K cannot be below sequence rerank K")
    if not 0 <= score_quantization_decimals <= 15:
        raise LexicalRetrievalError("score quantization decimals must be in [0, 15]")
    if materialization_target_bytes < 1:
        raise LexicalRetrievalError("materialization target bytes must be positive")

    def validated_indices(values: Sequence[int], *, label: str) -> tuple[int, ...]:
        selected = tuple(values)
        if len(selected) != len(set(selected)):
            raise LexicalRetrievalError(f"{label} indices must be unique")
        if any(value < 0 or value >= len(ordered) for value in selected):
            raise LexicalRetrievalError(f"{label} index is outside the passage range")
        return selected

    query_values = validated_indices(query_indices, label="query")
    target_values = validated_indices(target_indices, label="target")
    expected_namespace = {
        "hb_hb": "hb",
        "gnt_gnt": "gk",
        "hb_gnt_english_bridge": "en",
    }[corpus_pair]
    if index.namespace != expected_namespace:
        raise LexicalRetrievalError(
            f"{corpus_pair} requires namespace {expected_namespace}, not {index.namespace}"
        )
    query_corpora = {ordered[value].corpus for value in query_values}
    target_corpora = {ordered[value].corpus for value in target_values}
    if corpus_pair == "hb_gnt_english_bridge":
        if (
            len(query_corpora) != 1
            or len(target_corpora) != 1
            or {
                *query_corpora,
                *target_corpora,
            }
            != {"hebrew", "greek"}
        ):
            raise LexicalRetrievalError(
                "English bridge retrieval requires one source corpus per side in either direction"
            )
    else:
        expected_corpus = "hebrew" if corpus_pair == "hb_hb" else "greek"
        if query_corpora != {expected_corpus} or target_corpora != {expected_corpus}:
            raise LexicalRetrievalError(f"{corpus_pair} indices cross the governed corpus boundary")
    if set(query_values).intersection(target_values) and query_corpora != target_corpora:
        raise LexicalRetrievalError(
            "cross-corpus retrieval cannot reuse a passage row on both sides"
        )
    provenance_sets = tuple(frozenset(item.provenance_token_ids) for item in ordered)
    split_provenance = _validated_split_provenance(
        split_provenance_by_passage_id, index.passage_ids
    )
    split_utf8_bytes = {
        passage_id: len(payload.encode("utf-8")) for passage_id, payload in split_provenance.items()
    }
    maximum_target_split_bytes = max(
        split_utf8_bytes[index.passage_ids[target_index]] for target_index in target_values
    )
    idf = _raw_value_map(index, index.inverse_document_frequency)
    corpus_frequency = {
        key: int(value) for key, value in _raw_value_map(index, index.corpus_frequency).items()
    }
    ordinals = _book_ordinals(ordered)
    sequence_family = {
        "lemma": "lemma",
        "english_gloss": "english_gloss",
        "normalized_surface": "surface",
    }.get(index.family, index.family)
    english_derived = index.namespace == "en"
    phrase_associations, passage_phrase_features = _build_phrase_association_index_with_features(
        ordered,
        sequence_family=sequence_family,
        ngram_sizes=phrase_ngram_sizes,
        minimum_corpus_count=phrase_minimum_corpus_count,
        pmi_cap=phrase_pmi_cap,
        skipgram_max_gap=skipgram_max_gap,
        skipgram_minimum_corpus_count=skipgram_minimum_corpus_count,
        retain_passage_features=True,
    )
    score_contexts = tuple(
        _build_passage_score_context(
            passage,
            sequence_family=sequence_family,
            english_derived=english_derived,
            phrase_associations=phrase_associations,
            phrase_ngram_sizes=phrase_ngram_sizes,
            skipgram_max_gap=skipgram_max_gap,
            precomputed_phrase_features=passage_phrase_features[index],
        )
        for index, passage in enumerate(ordered)
    )
    del passage_phrase_features
    prepared_sparse = prepare_sparse_retrieval(
        index,
        target_indices=target_values,
        maximum_proposal_document_frequency=maximum_proposal_document_frequency,
        maximum_corpus_frequency=rare_threshold,
        k1=bm25_k1,
        b=bm25_b,
        resource_check=resource_check,
        resource_stage=f"retrieval:{corpus_pair}:sparse-preparation",
    )
    materialization_batch_index = 0

    def materialize(
        ranking_rows: list[dict[str, object]],
        aggregate_updates: list[CandidateAggregate],
        estimated_bytes: int,
    ) -> RetrievalBatch:
        nonlocal materialization_batch_index
        if resource_check is not None:
            resource_check(
                f"retrieval:{corpus_pair}:materialize:{materialization_batch_index}",
                estimated_additional_bytes=max(
                    64 * _MEBIBYTE,
                    estimated_bytes * _FRAME_CONSTRUCTION_MULTIPLIER,
                ),
            )
        materialization_batch_index += 1
        ranking_frame = pl.DataFrame(
            ranking_rows,
            schema=DIRECTIONAL_RANKINGS_SCHEMA,
            orient="row",
        ).sort("query_passage_id", "detector", "rank", "target_passage_id")
        return RetrievalBatch(
            rankings=ranking_frame,
            ablation_results=pl.DataFrame(schema=ABLATION_RESULTS_SCHEMA),
            candidates=tuple(aggregate_updates),
        )

    for batch_start in range(0, len(query_values), block_size):
        queries = query_values[batch_start : batch_start + block_size]
        hit_groups: dict[str, dict[int, list[RetrievalHit]]] = {}
        hit_groups["tfidf_cosine"] = _hits_by_query(
            retrieve_prepared_tfidf(
                prepared_sparse,
                query_indices=queries,
                top_k=candidate_union_k,
                block_size=block_size,
                quantization_decimals=score_quantization_decimals,
                exclude_self=True,
            )
        )
        hit_groups["jaccard"] = _hits_by_query(
            retrieve_prepared_overlap(
                prepared_sparse,
                query_indices=queries,
                top_k=candidate_union_k,
                block_size=block_size,
                quantization_decimals=score_quantization_decimals,
                exclude_self=True,
            )
        )
        hit_groups["bm25"] = _hits_by_query(
            retrieve_prepared_bm25(
                prepared_sparse,
                query_indices=queries,
                top_k=candidate_union_k,
                block_size=block_size,
                quantization_decimals=score_quantization_decimals,
                exclude_self=True,
            )
        )
        hit_groups["rare_lemma_root"] = _hits_by_query(
            retrieve_prepared_rare(
                prepared_sparse,
                query_indices=queries,
                top_k=candidate_union_k,
                block_size=block_size,
                quantization_decimals=score_quantization_decimals,
                exclude_self=True,
            )
        )
        ranking_rows: list[dict[str, object]] = []
        aggregate_updates: list[CandidateAggregate] = []
        estimated_materialization_bytes = 0
        emitted_for_proposal_block = False
        for query_index in queries:
            query_split_bytes = split_utf8_bytes[index.passage_ids[query_index]]
            maximum_rows_for_query = (len(DETECTOR_FAMILIES) + 1) * persisted_top_k
            estimated_query_bytes = (
                maximum_rows_for_query
                * (query_split_bytes + maximum_target_split_bytes + _RANKING_ROW_FIXED_BYTES)
                + persisted_candidate_pool_k * _CANDIDATE_UPDATE_FIXED_BYTES
            )
            if (
                ranking_rows
                and estimated_materialization_bytes + estimated_query_bytes
                > materialization_target_bytes
            ):
                yield materialize(
                    ranking_rows,
                    aggregate_updates,
                    estimated_materialization_bytes,
                )
                emitted_for_proposal_block = True
                ranking_rows = []
                aggregate_updates = []
                estimated_materialization_bytes = 0
            if resource_check is not None:
                resource_check(
                    f"retrieval:{corpus_pair}:query:{index.passage_ids[query_index]}",
                    estimated_additional_bytes=max(
                        64 * _MEBIBYTE,
                        estimated_query_bytes * _FRAME_CONSTRUCTION_MULTIPLIER,
                    ),
                )
            proposal_by_target: dict[int, dict[str, tuple[int, float]]] = defaultdict(dict)
            for detector, grouped in hit_groups.items():
                for rank, hit in enumerate(grouped.get(query_index, ()), start=1):
                    proposal_by_target[hit.target_index][detector] = (rank, hit.score)
            proposal_rrf = {
                target: math.fsum(1.0 / (rrf_k + rank) for rank, _ in detector_hits.values())
                for target, detector_hits in proposal_by_target.items()
            }
            union_targets = sorted(
                proposal_rrf,
                key=lambda target: (-proposal_rrf[target], index.passage_ids[target]),
            )[:candidate_union_k]
            scored: list[ScoredCandidate] = []
            for target_index in union_targets:
                proposal_scores = {
                    detector: value
                    for detector, (_, value) in proposal_by_target[target_index].items()
                }
                base = _pair_score_from_context(
                    score_contexts[query_index],
                    score_contexts[target_index],
                    proposal_scores=proposal_scores,
                    idf=idf,
                    corpus_frequency=corpus_frequency,
                    rare_threshold=rare_threshold,
                    english_derived=english_derived,
                    phrase_associations=phrase_associations,
                )
                scored.append(
                    ScoredCandidate(
                        query_index=query_index,
                        target_index=target_index,
                        scores=base.scores,
                        independent_co_signal_count=base.independent_co_signal_count,
                        rare_rule_passed=base.rare_rule_passed,
                        proposal_detectors=base.proposal_detectors,
                    )
                )
            alignment_targets = sorted(
                scored,
                key=lambda item: (
                    -item.scores["longest_common_subsequence"],
                    -item.scores["tfidf_cosine"],
                    index.passage_ids[item.target_index],
                ),
            )[:expensive_sequence_rerank_k]
            alignment_ids = {item.target_index for item in alignment_targets}
            rescored: list[ScoredCandidate] = []
            for item in scored:
                scores = dict(item.scores)
                if item.target_index in alignment_ids:
                    scores["weighted_sequence_alignment"] = _exact_alignment_score(
                        score_contexts[query_index],
                        score_contexts[item.target_index],
                        idf=idf,
                        gap_penalty=gap_penalty,
                        mismatch_score=mismatch_score,
                    )
                rescored.append(
                    ScoredCandidate(
                        query_index=item.query_index,
                        target_index=item.target_index,
                        scores=scores,
                        independent_co_signal_count=item.independent_co_signal_count,
                        rare_rule_passed=item.rare_rule_passed,
                        proposal_detectors=item.proposal_detectors,
                        alignment_evaluated=item.target_index in alignment_ids,
                    )
                )
            detector_rankings: dict[str, list[ScoredCandidate]] = {}
            detector_ranks_by_target: dict[int, dict[str, int]] = defaultdict(dict)
            for detector in DETECTOR_FAMILIES:
                ranked = sorted(
                    (item for item in rescored if item.scores[detector] > 0.0),
                    key=lambda item: (
                        -round(item.scores[detector], score_quantization_decimals),
                        index.passage_ids[item.target_index],
                    ),
                )[:persisted_top_k]
                detector_rankings[detector] = ranked
                for rank, item in enumerate(ranked, start=1):
                    detector_ranks_by_target[item.target_index][detector] = rank
            fusion = reciprocal_rank_fusion(
                {
                    detector: [index.passage_ids[item.target_index] for item in ranking]
                    for detector, ranking in detector_rankings.items()
                },
                DETECTOR_FAMILIES,
                rrf_k=rrf_k,
                family_policy="best",
            )
            rescored_by_target = {item.target_index: item for item in rescored}
            target_by_passage_id = {
                index.passage_ids[item.target_index]: item.target_index for item in rescored
            }
            composite_by_target = {
                target_by_passage_id[fused.candidate_id]: fused
                for fused in fusion.candidates[:persisted_top_k]
            }
            query = ordered[query_index]
            query_score_context = score_contexts[query_index]
            query_gloss_count = query_score_context.gloss_feature_count
            query_gloss_coverage = query_score_context.gloss_coverage
            pair_ranking_contexts: dict[int, _PairRankingContext] = {}
            for item in rescored:
                target = ordered[item.target_index]
                target_score_context = score_contexts[item.target_index]
                same_book = query.corpus == target.corpus and query.book == target.book
                pair_ranking_contexts[item.target_index] = _PairRankingContext(
                    target=target,
                    passage_overlap=(
                        query.corpus == target.corpus
                        and not provenance_sets[item.query_index].isdisjoint(
                            provenance_sets[item.target_index]
                        )
                    ),
                    nearby_context=(
                        same_book
                        and abs(ordinals[query.passage_id] - ordinals[target.passage_id])
                        <= nearby_context_distance
                    ),
                    same_book=same_book,
                    gloss_overlap_count=len(
                        query_score_context.gloss_values & target_score_context.gloss_values
                    ),
                )
            ranking_sources: dict[str, list[tuple[ScoredCandidate, float]]] = {
                detector: [(item, item.scores[detector]) for item in ranking]
                for detector, ranking in detector_rankings.items()
            }
            ranking_sources["rrf_composite"] = [
                (
                    rescored_by_target[target_index],
                    fused.score,
                )
                for target_index, fused in composite_by_target.items()
            ]
            for detector, ranking in ranking_sources.items():
                for rank, (item, raw_score) in enumerate(ranking, start=1):
                    pair_context = pair_ranking_contexts[item.target_index]
                    target = pair_context.target
                    target_score_context = score_contexts[item.target_index]
                    ranking_direction: Literal["forward", "reverse"] = (
                        "forward" if query.passage_id < target.passage_id else "reverse"
                    )
                    ranking_id = build_ranking_identity(
                        RankingIdentityPayload(
                            experiment_run_id=experiment_run_id,
                            query_passage_id=query.passage_id,
                            target_passage_id=target.passage_id,
                            detector=detector,
                            representation_id=index.representation_id,
                            direction=ranking_direction,
                        )
                    ).identifier
                    target_gloss_count = target_score_context.gloss_feature_count
                    target_gloss_coverage = target_score_context.gloss_coverage
                    gloss_overlap_count = pair_context.gloss_overlap_count
                    english_score_after = 0.0 if english_derived else raw_score
                    english_rank_after = None if english_derived else rank
                    non_english_remains = not english_derived
                    classification_after = (
                        "english_mediated_lead_without_non_english_score"
                        if english_derived
                        else "original_language_ranking_unchanged"
                    )
                    estimated_materialization_bytes += (
                        query_split_bytes
                        + split_utf8_bytes[target.passage_id]
                        + _RANKING_ROW_FIXED_BYTES
                    )
                    ranking_rows.append(
                        {
                            "ranking_id": ranking_id,
                            "experiment_run_id": experiment_run_id,
                            "query_passage_id": query.passage_id,
                            "target_passage_id": target.passage_id,
                            "corpus_pair": corpus_pair,
                            "experiment_scope": experiment_scope,
                            "analysis_profile": query.analysis_profile,
                            "query_reading": query.analysis_reading,
                            "target_reading": target.analysis_reading,
                            "granularity": query.granularity,
                            "representation_id": index.representation_id,
                            "detector": detector,
                            "rank": rank,
                            "raw_score": raw_score,
                            "quantized_score": round(raw_score, score_quantization_decimals),
                            "query_split": split_provenance[query.passage_id],
                            "target_split": split_provenance[target.passage_id],
                            "mapping_scope": "tier3_weak_supervision_recovery",
                            "is_self": False,
                            "passage_overlap": pair_context.passage_overlap,
                            "nearby_context": pair_context.nearby_context,
                            "same_book": pair_context.same_book,
                            "contains_english_derived_evidence": english_derived,
                            "query_gloss_feature_count": query_gloss_count,
                            "target_gloss_feature_count": target_gloss_count,
                            "query_gloss_coverage": query_gloss_coverage,
                            "target_gloss_coverage": target_gloss_coverage,
                            "gloss_overlap_count": gloss_overlap_count,
                            "score_after_removing_all_english_features": english_score_after,
                            "rank_after_removing_all_english_features": english_rank_after,
                            "non_english_evidence_remains": non_english_remains,
                            "english_ablation_survives": non_english_remains,
                            "classification_after_english_ablation": classification_after,
                            "tie_break_key": target.passage_id,
                        }
                    )
            for target_index, fused in list(composite_by_target.items())[
                :persisted_candidate_pool_k
            ]:
                target = ordered[target_index]
                first, second = sorted((query.passage_id, target.passage_id))
                pair_identity = build_candidate_pair_identity(
                    CandidatePairIdentityPayload(
                        analysis_profile=cast(AnalysisProfile, query.analysis_profile),
                        granularity=cast(Granularity, query.granularity),
                        passage_id_a=first,
                        passage_id_b=second,
                    )
                )
                item = rescored_by_target[target_index]
                pair_direction: Literal["a_to_b", "b_to_a"] = (
                    "a_to_b" if query.passage_id == first else "b_to_a"
                )
                aggregate = CandidateAggregate(
                    candidate_pair_id=pair_identity.identifier,
                    canonical_unordered_pair_id=pair_identity.identifier,
                    passage_a_id=first,
                    passage_b_id=second,
                    corpus_pair=corpus_pair,
                    analysis_profile=cast(AnalysisProfile, query.analysis_profile),
                    granularity=query.granularity,
                )
                aggregate.add_direction(
                    CandidateDirection(
                        direction=pair_direction,
                        query_passage_id=query.passage_id,
                        target_passage_id=target.passage_id,
                        scores=dict(item.scores),
                        ranks=dict(detector_ranks_by_target[target_index]),
                        rrf_score=fused.score,
                        proposal_detectors=item.proposal_detectors,
                        alignment_evaluated=item.alignment_evaluated,
                        score_trace_version="governed_v1",
                    )
                )
                estimated_materialization_bytes += _CANDIDATE_UPDATE_FIXED_BYTES
                aggregate_updates.append(aggregate)
        if ranking_rows or aggregate_updates or not emitted_for_proposal_block:
            yield materialize(
                ranking_rows,
                aggregate_updates,
                estimated_materialization_bytes,
            )
