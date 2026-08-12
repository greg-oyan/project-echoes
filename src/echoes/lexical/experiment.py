"""Production adapters for Milestone 7 null calibration and Tier 3 evaluation.

The adapters consume already-built lexical retrieval state.  They do not
acquire data, alter the frozen configuration, inspect candidate identities to
choose thresholds, or make a global all-pairs false-discovery claim.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import time
from array import array
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import groupby, pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal, Protocol, cast, overload

import duckdb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from echoes.benchmarks.metrics import (
    RankedQuery,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from echoes.lexical.candidates import CalibrationSelection
from echoes.lexical.config import LexicalConfig
from echoes.lexical.evaluation import (
    GOVERNED_VOTE_STRATA,
    OPENBIBLE_SOURCE_ID,
    REQUIRED_BASELINES,
    REQUIRED_STRATUM_DIMENSIONS,
    TIER3_LABEL_QUALITY,
    BaselineName,
    StratumDimension,
    Tier3EvaluationQuery,
    _stratum_value,
    deterministic_random_ranking,
    length_matched_ranking,
    unweighted_overlap_ranking,
)
from echoes.lexical.models import (
    EVALUATION_RESULTS_SCHEMA,
    NULL_REPLICATE_SUMMARIES_SCHEMA,
    THRESHOLD_CALIBRATION_SCHEMA,
)
from echoes.lexical.null_calibration import (
    CALIBRATION_PAIR_SAMPLE_SIZE,
    CANDIDATE_UNION_SAMPLE_SCOPE,
    NO_GLOBAL_ALL_PAIRS_CLAIM,
    REQUIRED_NULL_FAMILIES,
    CandidateUnionSample,
    _sample_unique_candidate_union_pairs,
    validate_null_replicate_conservation,
)
from echoes.lexical.nulls import (
    NullFamily,
    NullReplicate,
    NullSourceContext,
    PassageFeatures,
    frequency_preserving_synthetic,
    prepare_null_source,
    within_book_reassignment,
)
from echoes.lexical.phrases import (
    bigram_log_likelihood,
    contiguous_ngrams,
    pointwise_mutual_information,
    skip_grams,
)
from echoes.lexical.resources import LexicalResourceError, configure_duckdb_connection
from echoes.lexical.retrieval import DETECTOR_FAMILIES, CandidateAggregate, CandidateDirection
from echoes.lexical.sequences import PassageLexicalSequence
from echoes.lexical.statistics import calibrate_null_counts
from echoes.lexical.validation import null_replicate_logical_hash

PRIMARY_CORPUS_PAIRS: Final[tuple[str, ...]] = ("hb_hb", "gnt_gnt")
GOVERNED_CORPUS_PAIRS: Final[tuple[str, ...]] = (
    "hb_hb",
    "gnt_gnt",
    "hb_gnt_english_bridge",
)
COMPOSITE_DETECTOR: Final = "rrf_composite"
PRESUMED_NEGATIVE_BASELINE: Final = "presumed_negatives"
PERSISTED_BASELINES: Final = frozenset(REQUIRED_BASELINES)
BENCHMARK_FETCH_BATCH_SIZE: Final = 10_000
BENCHMARK_ROW_RESERVATION_BYTES: Final = 4_096
EXPANDED_QUERY_RESERVATION_BYTES: Final = 2_048
GROUP_POSITION_RESERVATION_BYTES: Final = 256
DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES: Final = 512 * 1024**2
CANDIDATE_UNIVERSE_BATCH_SIZE: Final = 256
CANDIDATE_UNIVERSE_ITEM_RESERVATION_BYTES: Final = 64
CANDIDATE_UNIVERSE_GROUP_RESERVATION_BYTES: Final = 1_024
RANKING_FRAME_ROW_RESERVATION_BYTES: Final = 512
RANKING_PYTHON_ROW_RESERVATION_BYTES: Final = 256
NULL_SOURCE_PASSAGE_RESERVATION_BYTES: Final = 512
NULL_SOURCE_TOKEN_RESERVATION_BYTES: Final = 64
NULL_SCORE_CANDIDATE_RESERVATION_BYTES: Final = 4_096
NULL_SCORE_FIXED_RESERVATION_BYTES: Final = 512 * 1024**2
TIER3_EVALUATION_CHECKPOINT_SCHEMA_VERSION: Final = 1

MetricName = Literal[
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "mean_reciprocal_rank",
    "ndcg_at_20",
    "precision_at_10",
    "coverage",
]
ScientificGateStatus = Literal["passed", "failed", "insufficient_data"]
PairGateStatus = Literal["passed", "failed", "insufficient_data_no_claim", "missing"]
type RankingInput = pl.DataFrame | Sequence[pl.DataFrame] | str | Path
AnalysisProfile = Literal["edition_complete", "critical_core"]


class ResourceCheck(Protocol):
    """Hard-memory checkpoint supporting conservative pre-allocation reservations."""

    def __call__(
        self,
        stage: str,
        *,
        estimated_additional_bytes: int = 0,
    ) -> None: ...


@contextmanager
def _experiment_duckdb_connection(
    database_path: Path,
    *,
    memory_limit_bytes: int,
    temp_directory: Path | None,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open one read-only child connection with verified governed settings."""

    temporary: TemporaryDirectory[str] | None = None
    configured_temp = temp_directory
    if configured_temp is None:
        temporary = TemporaryDirectory(prefix="echoes-experiment-duckdb-")
        configured_temp = Path(temporary.name)
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        configure_duckdb_connection(
            connection,
            memory_limit_bytes=memory_limit_bytes,
            temp_directory=configured_temp,
            thread_count=1,
        )
        yield connection
    except LexicalResourceError as exc:
        raise LexicalExperimentError(
            f"could not govern experiment DuckDB connection: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        if temporary is not None:
            temporary.cleanup()


class LexicalExperimentError(RuntimeError):
    """The production calibration/evaluation adapter could not satisfy its contract."""


@dataclass(frozen=True, slots=True)
class Tier3EvaluationScope:
    """One profile-specific ranking, representation, and sequence evaluation scope."""

    analysis_profile: AnalysisProfile
    directional_rankings: RankingInput
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]]
    representation_ids: Mapping[str, str]
    experiment_scope: str = "primary"


@dataclass(frozen=True, slots=True)
class ScientificGateDetail:
    """One primary corpus-pair recovery decision on held-out-genre test data."""

    corpus_pair: str
    status: PairGateStatus
    eligible_query_count: int
    eligible_relationship_count: int
    recall_at_20: float | None
    random_recall_at_20: float | None
    unweighted_overlap_recall_at_20: float | None
    difference_vs_random_interval_low: float | None
    difference_vs_unweighted_overlap_interval_low: float | None
    reason: str


@dataclass(frozen=True, slots=True)
class NullCalibrationArtifacts:
    """Typed calibration frames and the fail-closed candidate-policy facts."""

    null_replicate_summaries: pl.DataFrame
    threshold_calibration: pl.DataFrame
    candidate_samples: tuple[tuple[str, CandidateUnionSample], ...]
    selected_calibration: tuple[tuple[str, CalibrationSelection], ...]


@dataclass(frozen=True, slots=True)
class Tier3EvaluationArtifacts:
    """Typed Tier 3 evaluation frame and explicit scientific gate outcome."""

    evaluation_results: pl.DataFrame
    benchmark_version: str
    scientific_gate_status: ScientificGateStatus
    scientific_gate_details: tuple[ScientificGateDetail, ...]


@dataclass(frozen=True, slots=True)
class LexicalExperimentArtifacts:
    """All production outputs needed to replace the pipeline's fail-closed placeholders."""

    null_replicate_summaries: pl.DataFrame
    threshold_calibration: pl.DataFrame
    evaluation_results: pl.DataFrame
    selected_calibration: tuple[tuple[str, CalibrationSelection], ...]
    candidate_samples: tuple[tuple[str, CandidateUnionSample], ...]
    benchmark_version: str
    scientific_gate_status: ScientificGateStatus
    scientific_gate_details: tuple[ScientificGateDetail, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise LexicalExperimentError(f"{label} must be a lowercase SHA-256 digest")


def _derived_seed(base_seed: int, *parts: str) -> int:
    payload = "\x1f".join((str(base_seed), *parts)).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)
    return value or 1


def _threshold_id(corpus_pair: str, representation_id: str, detector: str, threshold: float) -> str:
    payload = (corpus_pair, representation_id, detector, format(threshold, ".17g"))
    return f"threshold_{_sha256_payload(payload)}"


def _null_run_id(
    *,
    experiment_run_id: str,
    corpus_pair: str,
    representation_id: str,
    family: NullFamily,
    iteration: int,
    seed: int,
    sample_digest: str,
) -> str:
    payload = {
        "experiment_run_id": experiment_run_id,
        "corpus_pair": corpus_pair,
        "representation_id": representation_id,
        "family": family,
        "iteration": iteration,
        "seed": seed,
        "candidate_sample_digest": sample_digest,
    }
    return f"null_{_sha256_payload(payload)}"


def _logical_null_row_hash(row: Mapping[str, object]) -> str:
    return null_replicate_logical_hash(row)


def _sequence_index(
    sequences: Sequence[PassageLexicalSequence], *, corpus_pair: str
) -> dict[str, PassageLexicalSequence]:
    indexed = {sequence.passage_id: sequence for sequence in sequences}
    if not indexed or len(indexed) != len(sequences):
        raise LexicalExperimentError(
            f"{corpus_pair} sequences must be nonempty with unique passage IDs"
        )
    if any(sequence.granularity != "verse" for sequence in sequences):
        raise LexicalExperimentError(f"{corpus_pair} full calibration must be verse-level")
    corpora = {sequence.corpus for sequence in sequences}
    expected = {"hebrew", "greek"} if corpus_pair == "hb_gnt_english_bridge" else None
    if expected is not None and corpora != expected:
        raise LexicalExperimentError("English bridge sequences must retain both source corpora")
    if corpus_pair == "hb_hb" and corpora != {"hebrew"}:
        raise LexicalExperimentError("hb_hb calibration contains a non-Hebrew passage")
    if corpus_pair == "gnt_gnt" and corpora != {"greek"}:
        raise LexicalExperimentError("gnt_gnt calibration contains a non-Greek passage")
    return indexed


def _active_family(corpus_pair: str) -> str:
    return "english_gloss" if corpus_pair == "hb_gnt_english_bridge" else "lemma"


def _namespace(sequence: PassageLexicalSequence) -> str:
    return "hb" if sequence.corpus == "hebrew" else "gk"


def _null_source_passages(
    sequences: Sequence[PassageLexicalSequence],
    *,
    corpus_pair: str,
    book_genres: Mapping[str, str],
) -> tuple[PassageFeatures, ...]:
    active_family = _active_family(corpus_pair)
    output: list[PassageFeatures] = []
    for sequence in sorted(sequences, key=lambda item: (item.corpus, item.passage_id)):
        genre = book_genres.get(sequence.book)
        if genre is None:
            raise LexicalExperimentError(f"book genre is missing for {sequence.book}")
        active_representation = (
            "en:gloss" if active_family == "english_gloss" else f"{_namespace(sequence)}:lemma"
        )
        output.append(
            PassageFeatures(
                passage_id=sequence.passage_id,
                corpus=sequence.corpus,
                book=sequence.book,
                broad_genre=genre,
                representation=active_representation,
                features=sequence.values(active_family),
            )
        )
        if active_family != "english_gloss":
            for family in ("part_of_speech", "morphology"):
                output.append(
                    PassageFeatures(
                        passage_id=sequence.passage_id,
                        corpus=sequence.corpus,
                        book=sequence.book,
                        broad_genre=genre,
                        representation=f"{_namespace(sequence)}:{family}",
                        features=sequence.values(family),
                    )
                )
    return tuple(output)


def _active_simulated_features(
    replicate: NullReplicate,
    *,
    corpus_pair: str,
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    active: dict[str, tuple[str, ...]] = {}
    pos: dict[str, tuple[str, ...]] = {}
    morphology: dict[str, tuple[str, ...]] = {}
    for passage in replicate.passages:
        if corpus_pair == "hb_gnt_english_bridge":
            if passage.representation == "en:gloss":
                active[passage.source_passage_id] = passage.features
        elif passage.representation.endswith(":lemma"):
            active[passage.source_passage_id] = passage.features
        elif passage.representation.endswith(":part_of_speech"):
            pos[passage.source_passage_id] = passage.features
        elif passage.representation.endswith(":morphology"):
            morphology[passage.source_passage_id] = passage.features
    return active, pos, morphology


def _original_feature_maps(
    sequences: Sequence[PassageLexicalSequence],
    *,
    corpus_pair: str,
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    family = _active_family(corpus_pair)
    active = {sequence.passage_id: sequence.values(family) for sequence in sequences}
    if corpus_pair == "hb_gnt_english_bridge":
        return active, {}, {}
    return (
        active,
        {sequence.passage_id: sequence.values("part_of_speech") for sequence in sequences},
        {sequence.passage_id: sequence.values("morphology") for sequence in sequences},
    )


def _length_digest(features: Mapping[str, Sequence[str]]) -> str:
    return _sha256_payload([(key, len(features[key])) for key in sorted(features)])


def _frequency_digest(
    features: Mapping[str, Sequence[str]],
    sequence_index: Mapping[str, PassageLexicalSequence],
) -> str:
    counts: Counter[tuple[str, str, str]] = Counter()
    for passage_id, values in features.items():
        sequence = sequence_index[passage_id]
        counts.update((sequence.corpus, sequence.book, value) for value in values)
    return _sha256_payload([(*key, count) for key, count in sorted(counts.items())])


def _bitset_lcs_length(sequence_a: Sequence[str], sequence_b: Sequence[str]) -> int:
    positions: dict[str, int] = defaultdict(int)
    for index, value in enumerate(sequence_b):
        positions[value] |= 1 << index
    state = 0
    for value in sequence_a:
        matches = positions.get(value, 0)
        union = state | matches
        state = union & ~(union - ((state << 1) | 1))
    return state.bit_count()


def _weighted_local_alignment_score(
    sequence_a: Sequence[str],
    sequence_b: Sequence[str],
    idf: Mapping[str, float],
    *,
    gap_penalty: float,
    mismatch_score: float,
) -> float:
    if not sequence_a or not sequence_b:
        return 0.0
    penalty = abs(gap_penalty)
    previous = [0.0] * (len(sequence_b) + 1)
    best = 0.0
    for feature_a in sequence_a:
        current = [0.0] * (len(sequence_b) + 1)
        for index_b, feature_b in enumerate(sequence_b, start=1):
            diagonal = previous[index_b - 1] + (
                idf.get(feature_a, 1.0) if feature_a == feature_b else mismatch_score
            )
            current[index_b] = max(
                0.0,
                diagonal,
                previous[index_b] - penalty,
                current[index_b - 1] - penalty,
            )
            best = max(best, current[index_b])
        previous = current
    normalizer = min(
        math.fsum(idf.get(feature, 1.0) for feature in sequence_a),
        math.fsum(idf.get(feature, 1.0) for feature in sequence_b),
    )
    return best / normalizer if normalizer else 0.0


@dataclass(frozen=True, slots=True)
class _PhraseWeights:
    contiguous: Mapping[tuple[str, ...], float]
    skipped: Mapping[tuple[str, str], float]


def _phrase_weights(features: Mapping[str, Sequence[str]], config: LexicalConfig) -> _PhraseWeights:
    unigram_counts: Counter[str] = Counter()
    phrase_counts: Counter[tuple[str, ...]] = Counter()
    skipped_counts: Counter[tuple[str, str]] = Counter()
    bigram_first: Counter[str] = Counter()
    bigram_second: Counter[str] = Counter()
    bigram_slots = 0
    sizes = tuple(config.phrases.lemma_ngram_sizes)
    for values in features.values():
        unigram_counts.update(values)
        if 2 in sizes and len(values) >= 2:
            bigram_first.update(values[:-1])
            bigram_second.update(values[1:])
            bigram_slots += len(values) - 1
        for size in sizes:
            phrase_counts.update(item.features for item in contiguous_ngrams(values, size))
        skipped_counts.update(
            cast(tuple[str, str], item.features)
            for item in skip_grams(values, 2, max_gap=config.skipgrams.maximum_gap)
        )
    total = sum(unigram_counts.values())
    contiguous: dict[tuple[str, ...], float] = {}
    for phrase, count in sorted(phrase_counts.items()):
        if count < config.phrases.minimum_corpus_count or not total:
            continue
        pmi = pointwise_mutual_information(
            count,
            [unigram_counts[value] for value in phrase],
            total,
            minimum_count=config.phrases.minimum_corpus_count,
            cap=config.phrases.pmi_cap,
        ).value
        likelihood = 0.0
        if len(phrase) == 2 and bigram_slots:
            likelihood = max(
                0.0,
                bigram_log_likelihood(
                    count,
                    bigram_first[phrase[0]],
                    bigram_second[phrase[1]],
                    bigram_slots,
                ).signed_statistic,
            )
        contiguous[phrase] = (max(0.0, pmi) + math.log1p(likelihood)) / (1.0 + math.log(count))
    skipped = {
        phrase: 1.0 / count
        for phrase, count in sorted(skipped_counts.items())
        if count >= config.skipgrams.minimum_corpus_count
    }
    return _PhraseWeights(contiguous=contiguous, skipped=skipped)


def _passage_phrase_sets(
    values: Sequence[str], config: LexicalConfig, weights: _PhraseWeights
) -> tuple[set[tuple[str, ...]], set[tuple[str, str]]]:
    contiguous = {
        item.features
        for size in config.phrases.lemma_ngram_sizes
        for item in contiguous_ngrams(values, size)
        if item.features in weights.contiguous
    }
    skipped = {
        cast(tuple[str, str], item.features)
        for item in skip_grams(values, 2, max_gap=config.skipgrams.maximum_gap)
        if item.features in weights.skipped
    }
    return contiguous, skipped


def _score_shared_null_replicate(
    candidates: Sequence[CandidateAggregate],
    *,
    active_features: Mapping[str, Sequence[str]],
    pos_features: Mapping[str, Sequence[str]],
    morphology_features: Mapping[str, Sequence[str]],
    corpus_pair: str,
    config: LexicalConfig,
) -> dict[str, NDArray[np.float64]]:
    """Score all detectors in one pass over one shared, already-validated replicate."""

    if len(candidates) != CALIBRATION_PAIR_SAMPLE_SIZE:
        raise LexicalExperimentError("null scoring requires the exact 20,000-pair sample")
    document_count = len(active_features)
    if document_count < 1:
        raise LexicalExperimentError("null scoring has no active passages")
    corpus_frequency: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    counts: dict[str, Counter[str]] = {}
    sets: dict[str, set[str]] = {}
    for passage_id, values in active_features.items():
        passage_counts = Counter(values)
        counts[passage_id] = passage_counts
        sets[passage_id] = set(passage_counts)
        corpus_frequency.update(passage_counts)
        document_frequency.update(passage_counts.keys())
    idf = {
        feature: math.log((1.0 + document_count) / (1.0 + frequency)) + 1.0
        for feature, frequency in document_frequency.items()
    }
    tfidf_norms: dict[str, float] = {}
    for passage_id, passage_counts in counts.items():
        tfidf_norms[passage_id] = math.sqrt(
            math.fsum(
                ((1.0 + math.log(count)) * idf[feature]) ** 2
                for feature, count in passage_counts.items()
            )
        )
    average_length = math.fsum(len(values) for values in active_features.values()) / document_count
    if average_length <= 0.0:
        raise LexicalExperimentError("null scoring requires at least one active feature token")
    bm25_idf = {
        feature: math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
        for feature, frequency in document_frequency.items()
    }
    bm25_length_normalizers: dict[str, float] = {}
    for passage_id in counts:
        bm25_length_normalizers[passage_id] = config.bm25.k1 * (
            1.0 - config.bm25.b + config.bm25.b * len(active_features[passage_id]) / average_length
        )
    associations = _phrase_weights(active_features, config)
    phrase_sets = {
        passage_id: _passage_phrase_sets(values, config, associations)
        for passage_id, values in active_features.items()
    }
    raw_scores: dict[str, list[float]] = {detector: [] for detector in DETECTOR_FAMILIES}
    directional_bm25: dict[tuple[int, str, str], float] = {}
    directions_by_query: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    english_derived = corpus_pair == "hb_gnt_english_bridge"
    for candidate_index, candidate in enumerate(candidates):
        passage_a = candidate.passage_a_id
        passage_b = candidate.passage_b_id
        if passage_a not in active_features or passage_b not in active_features:
            raise LexicalExperimentError(
                f"sampled candidate {candidate.candidate_pair_id} references an absent passage"
            )
        values_a = active_features[passage_a]
        values_b = active_features[passage_b]
        counts_a = counts[passage_a]
        counts_b = counts[passage_b]
        set_a = sets[passage_a]
        set_b = sets[passage_b]
        shared = tuple(sorted(set_a.intersection(set_b)))
        union = tuple(sorted(set_a.union(set_b)))
        raw_scores["jaccard"].append(len(shared) / len(union) if union else 0.0)
        weighted_numerator = math.fsum(
            idf[feature] * min(counts_a[feature], counts_b[feature]) for feature in shared
        )
        weighted_denominator = math.fsum(
            idf[feature] * max(counts_a[feature], counts_b[feature]) for feature in union
        )
        raw_scores["weighted_jaccard"].append(
            weighted_numerator / weighted_denominator if weighted_denominator else 0.0
        )
        tfidf_norm = tfidf_norms[passage_a] * tfidf_norms[passage_b]
        raw_scores["tfidf_cosine"].append(
            math.fsum(
                (1.0 + math.log(counts_a[feature]))
                * idf[feature]
                * (1.0 + math.log(counts_b[feature]))
                * idf[feature]
                for feature in shared
            )
            / tfidf_norm
            if tfidf_norm
            else 0.0
        )
        bm25_ab = math.fsum(
            bm25_idf[feature]
            * counts_b[feature]
            * (config.bm25.k1 + 1.0)
            / (counts_b[feature] + bm25_length_normalizers[passage_b])
            for feature in sorted(set_a.intersection(counts_b))
        )
        bm25_ba = math.fsum(
            bm25_idf[feature]
            * counts_a[feature]
            * (config.bm25.k1 + 1.0)
            / (counts_a[feature] + bm25_length_normalizers[passage_a])
            for feature in sorted(set_b.intersection(counts_a))
        )
        raw_scores["bm25"].append(max(bm25_ab, bm25_ba))
        raw_scores["rare_lemma_root"].append(
            math.fsum(
                1.0 / corpus_frequency[feature]
                for feature in shared
                if corpus_frequency[feature] <= config.rare_evidence.maximum_corpus_frequency
            )
        )
        phrases_a, skipped_a = phrase_sets[passage_a]
        phrases_b, skipped_b = phrase_sets[passage_b]
        raw_scores["phrase_association"].append(
            math.fsum(
                associations.contiguous[phrase]
                for phrase in sorted(phrases_a.intersection(phrases_b))
            )
            + math.fsum(
                associations.skipped[phrase] for phrase in sorted(skipped_a.intersection(skipped_b))
            )
        )
        lcs_length = _bitset_lcs_length(values_a, values_b)
        shorter = min(len(values_a), len(values_b))
        raw_scores["longest_common_subsequence"].append(lcs_length / shorter if shorter else 0.0)
        raw_scores["weighted_sequence_alignment"].append(
            _weighted_local_alignment_score(
                values_a,
                values_b,
                idf,
                gap_penalty=config.sequence.gap_penalty,
                mismatch_score=config.sequence.mismatch_penalty,
            )
        )
        supports: list[float] = []
        if not english_derived:
            for feature_map in (pos_features, morphology_features):
                support_a = feature_map.get(passage_a, ())
                support_b = feature_map.get(passage_b, ())
                support_shorter = min(len(support_a), len(support_b))
                if support_shorter:
                    supports.append(_bitset_lcs_length(support_a, support_b) / support_shorter)
        raw_scores["pos_morphology_support"].append(
            math.fsum(supports) / len(supports) if supports else 0.0
        )

        seen_directions: set[tuple[str, str]] = set()
        for direction in candidate.directions.values():
            query_target = (direction.query_passage_id, direction.target_passage_id)
            if set(query_target) != {passage_a, passage_b} or query_target in seen_directions:
                raise LexicalExperimentError(
                    f"candidate {candidate.candidate_pair_id} has invalid directional evidence"
                )
            seen_directions.add(query_target)
            query_id, target_id = query_target
            directional_bm25[(candidate_index, query_id, target_id)] = (
                bm25_ab if query_id == passage_a else bm25_ba
            )
            directions_by_query[query_id].append((candidate_index, query_id, target_id))
        if not seen_directions:
            raise LexicalExperimentError(
                f"candidate {candidate.candidate_pair_id} lacks directional evidence"
            )

    del (
        associations,
        bm25_idf,
        bm25_length_normalizers,
        corpus_frequency,
        counts,
        document_frequency,
        idf,
        phrase_sets,
        sets,
        tfidf_norms,
    )
    decimals = config.statistics.score_quantization_decimals
    score_arrays = {
        detector: np.round(np.asarray(values, dtype=np.float64), decimals=decimals)
        for detector, values in raw_scores.items()
    }
    best_family_contribution: dict[tuple[int, str, str], dict[str, float]] = defaultdict(dict)
    for detector, family in DETECTOR_FAMILIES.items():
        for _query_id, directions in directions_by_query.items():
            ranked = sorted(
                (
                    (
                        direction,
                        (
                            directional_bm25[direction]
                            if detector == "bm25"
                            else float(score_arrays[detector][direction[0]])
                        ),
                    )
                    for direction in directions
                ),
                key=lambda item: (-round(item[1], decimals), item[0][2]),
            )
            rank = 0
            for direction_key, score in ranked:
                if score <= 0.0:
                    continue
                rank += 1
                contribution = 1.0 / (config.composite.rrf_k + rank)
                current = best_family_contribution[direction_key].get(family, 0.0)
                best_family_contribution[direction_key][family] = max(current, contribution)
    composite = np.zeros(len(candidates), dtype=np.float64)
    for direction_key, family_values in best_family_contribution.items():
        candidate_index = direction_key[0]
        composite[candidate_index] = max(
            composite[candidate_index],
            math.fsum(family_values.values()),
        )
    score_arrays[COMPOSITE_DETECTOR] = np.round(composite, decimals=decimals)
    expected_detectors = {*config.enabled_detectors, COMPOSITE_DETECTOR}
    if set(score_arrays) != expected_detectors:
        raise LexicalExperimentError("null scorer does not cover every enabled detector and RRF")
    return score_arrays


def _observed_sample_scores(
    candidates: Sequence[CandidateAggregate], config: LexicalConfig
) -> dict[str, NDArray[np.float64]]:
    output: dict[str, NDArray[np.float64]] = {}
    decimals = config.statistics.score_quantization_decimals
    for detector in config.enabled_detectors:
        values = [
            max(
                (
                    direction.scores.get(detector, 0.0)
                    for direction in candidate.directions.values()
                ),
                default=0.0,
            )
            for candidate in candidates
        ]
        output[detector] = np.round(np.asarray(values, dtype=np.float64), decimals=decimals)
    directions_by_query: dict[str, list[tuple[int, CandidateDirection]]] = defaultdict(list)
    for candidate_index, candidate in enumerate(candidates):
        for direction in candidate.directions.values():
            directions_by_query[direction.query_passage_id].append((candidate_index, direction))
    best_family_contribution: dict[tuple[int, str, str], dict[str, float]] = defaultdict(dict)
    for family_detector, family in DETECTOR_FAMILIES.items():
        for directions in directions_by_query.values():
            ranked = sorted(
                directions,
                key=lambda item: (
                    -round(item[1].scores.get(family_detector, 0.0), decimals),
                    item[1].target_passage_id,
                ),
            )
            rank = 0
            for candidate_index, direction in ranked:
                score = direction.scores.get(family_detector, 0.0)
                if score <= 0.0:
                    continue
                rank += 1
                key = (
                    candidate_index,
                    direction.query_passage_id,
                    direction.target_passage_id,
                )
                contribution = 1.0 / (config.composite.rrf_k + rank)
                best_family_contribution[key][family] = max(
                    best_family_contribution[key].get(family, 0.0),
                    contribution,
                )
    composite = np.zeros(len(candidates), dtype=np.float64)
    for (candidate_index, _, _), family_values in best_family_contribution.items():
        composite[candidate_index] = max(
            composite[candidate_index],
            math.fsum(family_values.values()),
        )
    output[COMPOSITE_DETECTOR] = np.round(composite, decimals=decimals)
    return output


def _typed_frame(rows: Sequence[Mapping[str, object]], schema: pl.Schema) -> pl.DataFrame:
    """Build an exactly ordered, exactly typed governed output frame."""

    if not rows:
        return pl.DataFrame(schema=schema)
    expected = set(schema.names())
    for row in rows:
        if set(row) != expected:
            missing = sorted(expected.difference(row))
            unexpected = sorted(set(row).difference(expected))
            raise LexicalExperimentError(
                f"governed row does not match schema; missing={missing}, unexpected={unexpected}"
            )
    return pl.DataFrame(rows, schema=schema, orient="row")


_EVALUATION_SORT_COLUMNS: Final[tuple[str, ...]] = (
    "analysis_profile",
    "corpus_pair",
    "representation_id",
    "stratum_dimension",
    "stratum_value",
    "split_strategy",
    "partition",
    "mapping_status",
    "vote_stratum",
    "detector",
    "metric",
    "k",
    "evaluation_id",
)


def _checkpoint_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _Tier3EvaluationCheckpoint:
    """Persist validated evaluation batches without retaining Python rows."""

    def __init__(
        self,
        root: Path,
        *,
        experiment_run_id: str,
        configuration_hash: str,
        preregistration_hash: str,
    ) -> None:
        self.root = root.resolve()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise LexicalExperimentError(
                "Tier 3 evaluation checkpoint must be a non-symlinked directory"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        self.experiment_run_id = experiment_run_id
        self.configuration_hash = configuration_hash
        self.preregistration_hash = preregistration_hash
        self._part_paths: dict[tuple[str, str, str], Path] = {}

    @staticmethod
    def _part_key(
        analysis_profile: AnalysisProfile,
        part_kind: Literal["baseline", "detector"],
        detector: str,
    ) -> tuple[str, str, str]:
        if not detector or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in detector
        ):
            raise LexicalExperimentError(f"unsafe Tier 3 checkpoint detector name: {detector!r}")
        return analysis_profile, part_kind, detector

    @staticmethod
    def _manifest_name(key: tuple[str, str, str]) -> str:
        return "-".join(key) + ".json"

    def _manifest_path(self, key: tuple[str, str, str]) -> Path:
        return self.root / self._manifest_name(key)

    def _validate_frame(
        self,
        frame: pl.DataFrame,
        *,
        analysis_profile: AnalysisProfile,
        detector: str,
        expected_row_count: int,
    ) -> None:
        if frame.schema != EVALUATION_RESULTS_SCHEMA:
            raise LexicalExperimentError("Tier 3 checkpoint schema differs")
        if frame.height != expected_row_count or frame.height < 1:
            raise LexicalExperimentError("Tier 3 checkpoint row count differs")
        if frame.get_column("evaluation_id").n_unique() != frame.height:
            raise LexicalExperimentError("Tier 3 checkpoint evaluation IDs are not unique")
        expected_singletons = {
            "experiment_run_id": self.experiment_run_id,
            "analysis_profile": analysis_profile,
            "detector": detector,
            "config_hash": self.configuration_hash,
            "preregistration_hash": self.preregistration_hash,
        }
        for column, expected in expected_singletons.items():
            values = frame.get_column(column).unique().to_list()
            if values != [expected]:
                raise LexicalExperimentError(f"Tier 3 checkpoint {column} identity differs")

    def load(
        self,
        *,
        analysis_profile: AnalysisProfile,
        part_kind: Literal["baseline", "detector"],
        detector: str,
    ) -> pl.DataFrame | None:
        key = self._part_key(analysis_profile, part_kind, detector)
        manifest_path = self._manifest_path(key)
        if not manifest_path.exists():
            return None
        if manifest_path.is_symlink() or manifest_path.resolve().parent != self.root:
            raise LexicalExperimentError("Tier 3 checkpoint manifest escaped its root")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LexicalExperimentError(
                f"Tier 3 checkpoint manifest is unreadable: {manifest_path.name}: {exc}"
            ) from exc
        expected_identity = {
            "schema_version": TIER3_EVALUATION_CHECKPOINT_SCHEMA_VERSION,
            "experiment_run_id": self.experiment_run_id,
            "configuration_hash": self.configuration_hash,
            "preregistration_hash": self.preregistration_hash,
            "analysis_profile": analysis_profile,
            "part_kind": part_kind,
            "detector": detector,
        }
        if not isinstance(manifest, dict) or any(
            manifest.get(field) != value for field, value in expected_identity.items()
        ):
            raise LexicalExperimentError(
                f"Tier 3 checkpoint identity differs: {manifest_path.name}"
            )
        filename = manifest.get("path")
        expected_hash = manifest.get("sha256")
        expected_row_count = manifest.get("row_count")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not isinstance(expected_hash, str)
            or not isinstance(expected_row_count, int)
        ):
            raise LexicalExperimentError(
                f"Tier 3 checkpoint metadata is invalid: {manifest_path.name}"
            )
        part_path = self.root / filename
        if (
            not part_path.is_file()
            or part_path.is_symlink()
            or part_path.resolve().parent != self.root
        ):
            raise LexicalExperimentError(f"Tier 3 checkpoint part is missing or unsafe: {filename}")
        if _checkpoint_file_sha256(part_path) != expected_hash:
            raise LexicalExperimentError(f"Tier 3 checkpoint physical hash differs: {filename}")
        try:
            frame = pl.read_parquet(part_path).cast(
                EVALUATION_RESULTS_SCHEMA,
                strict=True,
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(
                f"Tier 3 checkpoint part is unreadable: {filename}: {exc}"
            ) from exc
        self._validate_frame(
            frame,
            analysis_profile=analysis_profile,
            detector=detector,
            expected_row_count=expected_row_count,
        )
        self._part_paths[key] = part_path
        return frame

    def write(
        self,
        frame: pl.DataFrame,
        *,
        analysis_profile: AnalysisProfile,
        part_kind: Literal["baseline", "detector"],
        detector: str,
    ) -> None:
        key = self._part_key(analysis_profile, part_kind, detector)
        manifest_path = self._manifest_path(key)
        if manifest_path.exists():
            raise LexicalExperimentError(
                f"refusing to overwrite completed Tier 3 checkpoint: {manifest_path.name}"
            )
        self._validate_frame(
            frame,
            analysis_profile=analysis_profile,
            detector=detector,
            expected_row_count=frame.height,
        )
        suffix = time.time_ns()
        filename = f"{'-'.join(key)}-{suffix}.parquet"
        part_path = self.root / filename
        temporary_part = self.root / f".{filename}.writing"
        frame.write_parquet(
            temporary_part,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        temporary_part.replace(part_path)
        payload = {
            "schema_version": TIER3_EVALUATION_CHECKPOINT_SCHEMA_VERSION,
            "experiment_run_id": self.experiment_run_id,
            "configuration_hash": self.configuration_hash,
            "preregistration_hash": self.preregistration_hash,
            "analysis_profile": analysis_profile,
            "part_kind": part_kind,
            "detector": detector,
            "path": filename,
            "row_count": frame.height,
            "sha256": _checkpoint_file_sha256(part_path),
        }
        temporary_manifest = self.root / f".{manifest_path.name}.{suffix}.writing"
        temporary_manifest.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_manifest.replace(manifest_path)
        self._part_paths[key] = part_path

    def assemble(
        self,
        expected_keys: set[tuple[str, str, str]],
    ) -> pl.DataFrame:
        if set(self._part_paths) != expected_keys:
            missing = sorted(expected_keys.difference(self._part_paths))
            unexpected = sorted(set(self._part_paths).difference(expected_keys))
            raise LexicalExperimentError(
                f"Tier 3 checkpoint inventory differs; missing={missing}, unexpected={unexpected}"
            )
        paths = [self._part_paths[key] for key in sorted(expected_keys)]
        try:
            frame = (
                pl.scan_parquet(paths)
                .select(EVALUATION_RESULTS_SCHEMA.names())
                .sort(list(_EVALUATION_SORT_COLUMNS), nulls_last=True)
                .collect(engine="streaming")
                .cast(EVALUATION_RESULTS_SCHEMA, strict=True)
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(
                f"could not assemble Tier 3 evaluation checkpoints: {exc}"
            ) from exc
        if frame.get_column("evaluation_id").n_unique() != frame.height:
            raise LexicalExperimentError("assembled Tier 3 evaluation IDs are not globally unique")
        return frame


def _thresholds_for_detector(detector: str, config: LexicalConfig) -> tuple[float, ...]:
    values = (
        config.candidate_thresholds.rrf_score_grid
        if detector == COMPOSITE_DETECTOR
        else config.candidate_thresholds.detector_score_grid
    )
    return tuple(float(value) for value in values)


def _score_quantiles(scores: NDArray[np.float64]) -> str:
    if scores.size != CALIBRATION_PAIR_SAMPLE_SIZE or not np.all(np.isfinite(scores)):
        raise LexicalExperimentError("each null detector must return exactly 20,000 finite scores")
    quantiles = np.quantile(scores, (0.025, 0.5, 0.975), method="linear")
    return _canonical_json(
        {
            "q025": float(quantiles[0]),
            "q50": float(quantiles[1]),
            "q975": float(quantiles[2]),
        }
    )


def _calibration_selection(
    *,
    thresholds: Sequence[float],
    observed_counts: Mapping[float, int],
    counts_by_family: Mapping[NullFamily, Mapping[float, Sequence[int]]],
    maximum_fdr: float,
) -> CalibrationSelection:
    for threshold in thresholds:
        observed = observed_counts[threshold]
        if _threshold_qualifies_empirical_fdr(
            threshold=threshold,
            observed=observed,
            counts_by_family=counts_by_family,
            maximum_fdr=maximum_fdr,
        ):
            pooled_counts = tuple(
                count
                for family in REQUIRED_NULL_FAMILIES
                for count in counts_by_family[family][threshold]
            )
            mean_null = math.fsum(pooled_counts) / len(pooled_counts)
            return CalibrationSelection(
                score_threshold=threshold,
                estimated_empirical_fdr=mean_null / observed,
                empirical_rate=mean_null / CALIBRATION_PAIR_SAMPLE_SIZE,
                both_null_families_present=True,
            )
    return CalibrationSelection(
        score_threshold=math.inf,
        estimated_empirical_fdr=math.inf,
        empirical_rate=math.inf,
        both_null_families_present=True,
    )


def _threshold_qualifies_empirical_fdr(
    *,
    threshold: float,
    observed: int,
    counts_by_family: Mapping[NullFamily, Mapping[float, Sequence[int]]],
    maximum_fdr: float,
) -> bool:
    if observed <= 0:
        return False
    for family in REQUIRED_NULL_FAMILIES:
        counts = tuple(counts_by_family[family][threshold])
        if not counts:
            return False
        if math.fsum(counts) / len(counts) / observed > maximum_fdr:
            return False
    return True


def _threshold_selection_reason(
    *,
    detector: str,
    observed: int,
    qualifies: bool,
    selected: bool,
) -> str:
    if detector != COMPOSITE_DETECTOR:
        return "detector_threshold_reported_not_review_selection"
    if selected:
        return "lowest_registered_threshold_qualifying_both_null_families"
    if observed == 0:
        return "zero_observed_candidates"
    if qualifies:
        return "qualifies_but_not_lowest_selected_threshold"
    return "exceeds_maximum_empirical_fdr_in_at_least_one_null_family"


def run_null_calibration_experiment(
    candidates: Mapping[str, CandidateAggregate],
    *,
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    representation_ids: Mapping[str, str],
    config: LexicalConfig,
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    book_genres: Mapping[str, str],
    corpus_pairs: Sequence[str] = GOVERNED_CORPUS_PAIRS,
    detectors_by_corpus_pair: Mapping[str, Sequence[str]] | None = None,
    resource_check: ResourceCheck | None = None,
) -> NullCalibrationArtifacts:
    """Run the frozen two-family, shared-replicate calibration experiment.

    Each corpus pair uses one deterministic 20,000-member candidate-union sample.
    A generated replicate is scored by every detector before the next replicate is
    generated, so detector comparisons share the same stochastic realization.
    """

    if not experiment_run_id:
        raise LexicalExperimentError("experiment run ID cannot be empty")
    _require_sha256(configuration_hash, label="configuration hash")
    _require_sha256(preregistration_hash, label="preregistration hash")
    requested_pairs = tuple(corpus_pairs)
    pair_values = tuple(pair for pair in GOVERNED_CORPUS_PAIRS if pair in requested_pairs)
    if (
        not pair_values
        or len(requested_pairs) != len(set(requested_pairs))
        or not set(pair_values).issubset(GOVERNED_CORPUS_PAIRS)
        or set(pair_values) != set(requested_pairs)
    ):
        raise LexicalExperimentError("calibration corpus pairs must be unique and governed")
    if config.null_models.iterations_per_family != 100:
        raise LexicalExperimentError("the frozen experiment requires exactly 100 null replicates")
    if config.null_models.calibration_pair_sample_size != CALIBRATION_PAIR_SAMPLE_SIZE:
        raise LexicalExperimentError("the frozen calibration sample is exactly 20,000 pairs")

    candidate_counts_by_pair: Counter[str] = Counter()
    for mapping_key, candidate in candidates.items():
        if mapping_key != candidate.candidate_pair_id:
            raise LexicalExperimentError("candidate mapping keys must be candidate pair IDs")
        if candidate.corpus_pair in pair_values:
            candidate_counts_by_pair[candidate.corpus_pair] += 1

    null_rows: list[dict[str, object]] = []
    calibration_rows: list[dict[str, object]] = []
    samples: list[tuple[str, CandidateUnionSample]] = []
    selected: list[tuple[str, CalibrationSelection]] = []
    all_detectors = (*config.enabled_detectors, COMPOSITE_DETECTOR)

    for corpus_pair in pair_values:
        if resource_check is not None:
            resource_check(f"null:{corpus_pair}:start")
        if corpus_pair not in sequences_by_corpus_pair or corpus_pair not in representation_ids:
            raise LexicalExperimentError(
                f"sequences and representation identity are required for {corpus_pair}"
            )
        representation_id = representation_ids[corpus_pair]
        if not representation_id:
            raise LexicalExperimentError(f"representation ID is empty for {corpus_pair}")
        detector_order = tuple((detectors_by_corpus_pair or {}).get(corpus_pair, all_detectors))
        if (
            not detector_order
            or len(detector_order) != len(set(detector_order))
            or not set(detector_order).issubset(all_detectors)
            or COMPOSITE_DETECTOR not in detector_order
        ):
            raise LexicalExperimentError(
                f"persisted detector applicability is invalid for {corpus_pair}"
            )
        if corpus_pair in PRIMARY_CORPUS_PAIRS and set(detector_order) != set(all_detectors):
            raise LexicalExperimentError(
                f"original-language scoring strata omit enabled detectors for {corpus_pair}"
            )
        sequence_values = tuple(sequences_by_corpus_pair[corpus_pair])
        sequence_index = _sequence_index(sequence_values, corpus_pair=corpus_pair)
        source_passages = _null_source_passages(
            sequence_values,
            corpus_pair=corpus_pair,
            book_genres=book_genres,
        )
        source_token_count = sum(len(passage.features) for passage in source_passages)
        null_working_set_reservation = (
            NULL_SCORE_FIXED_RESERVATION_BYTES
            + len(source_passages) * NULL_SOURCE_PASSAGE_RESERVATION_BYTES
            + source_token_count * NULL_SOURCE_TOKEN_RESERVATION_BYTES
            + CALIBRATION_PAIR_SAMPLE_SIZE * NULL_SCORE_CANDIDATE_RESERVATION_BYTES
        )
        if resource_check is not None:
            resource_check(
                f"null:{corpus_pair}:prepare-source",
                estimated_additional_bytes=null_working_set_reservation,
            )
        prepared_source: NullSourceContext = prepare_null_source(source_passages)
        del source_passages
        sample_seed = _derived_seed(
            config.null_models.within_book_reassignment.seed,
            configuration_hash,
            preregistration_hash,
            corpus_pair,
            representation_id,
            "candidate-union-sample",
        )
        sample = _sample_unique_candidate_union_pairs(
            (
                mapping_key
                for mapping_key, candidate in candidates.items()
                if candidate.corpus_pair == corpus_pair
            ),
            seed=sample_seed,
        )
        if sample.source_candidate_count != candidate_counts_by_pair[corpus_pair]:
            raise LexicalExperimentError("candidate-union sampling count changed during iteration")
        sampled_candidates = tuple(candidates[pair_id] for pair_id in sample.pair_ids)
        samples.append((corpus_pair, sample))

        observed_active, observed_pos, observed_morphology = _original_feature_maps(
            sequence_values,
            corpus_pair=corpus_pair,
        )
        observed_scores = _score_shared_null_replicate(
            sampled_candidates,
            active_features=observed_active,
            pos_features=observed_pos,
            morphology_features=observed_morphology,
            corpus_pair=corpus_pair,
            config=config,
        )
        observed_counts: dict[str, dict[float, int]] = {}
        for detector in detector_order:
            observed_counts[detector] = {
                threshold: int(np.count_nonzero(observed_scores[detector] >= threshold))
                for threshold in _thresholds_for_detector(detector, config)
            }
        del observed_active, observed_morphology, observed_pos, observed_scores, sequence_values
        null_counts: dict[str, dict[NullFamily, dict[float, list[int]]]] = {
            detector: {
                family: {threshold: [] for threshold in _thresholds_for_detector(detector, config)}
                for family in REQUIRED_NULL_FAMILIES
            }
            for detector in detector_order
        }

        for family in REQUIRED_NULL_FAMILIES:
            family_config = (
                config.null_models.within_book_reassignment
                if family == "within_book_reassignment"
                else config.null_models.frequency_preserving_synthetic
            )
            for iteration in range(1, config.null_models.iterations_per_family + 1):
                if resource_check is not None:
                    resource_check(
                        f"null:{corpus_pair}:{family}:{iteration}",
                        estimated_additional_bytes=null_working_set_reservation,
                    )
                seed = _derived_seed(
                    family_config.seed,
                    f"{corpus_pair}|{representation_id}",
                    family,
                    str(iteration),
                )
                started = time.perf_counter()
                if family == "within_book_reassignment":
                    replicate = within_book_reassignment(prepared_source, seed=seed)
                else:
                    replicate = frequency_preserving_synthetic(
                        prepared_source,
                        seed=seed,
                        minimum_book_token_count=(
                            config.null_models.synthetic_minimum_book_token_count
                        ),
                    )
                validation = validate_null_replicate_conservation(
                    prepared_source,
                    replicate,
                    retain_frequency_deviation_details=False,
                )
                active, pos, morphology = _active_simulated_features(
                    replicate,
                    corpus_pair=corpus_pair,
                )
                if set(active) != set(sequence_index):
                    raise LexicalExperimentError(
                        f"{family} omitted active passages for {corpus_pair}"
                    )
                run_id = _null_run_id(
                    experiment_run_id=experiment_run_id,
                    corpus_pair=corpus_pair,
                    representation_id=representation_id,
                    family=family,
                    iteration=iteration,
                    seed=seed,
                    sample_digest=sample.logical_digest,
                )
                conditioning = _canonical_json(
                    {
                        "calibration_pair_scope": CANDIDATE_UNION_SAMPLE_SCOPE,
                        "candidate_sample_digest": sample.logical_digest,
                        "candidate_sample_seed": sample.seed,
                        "candidate_sample_size": CALIBRATION_PAIR_SAMPLE_SIZE,
                        "conditioning_labels_preserved": (validation.conditioning_labels_preserved),
                        "conditioning_scope": (
                            config.null_models.synthetic_primary_conditioning
                            if family == "frequency_preserving_synthetic"
                            else "book"
                        ),
                        "exact_feature_totals_preserved": (
                            validation.exact_feature_totals_preserved
                        ),
                        "global_all_pairs_claim_allowed": False,
                        "label_or_order_shuffle": False,
                        "minimum_book_token_count": (
                            config.null_models.synthetic_minimum_book_token_count
                            if family == "frequency_preserving_synthetic"
                            else None
                        ),
                        "no_original_sequences_copied": (validation.no_original_sequences_copied),
                        "frequency_deviation_count": validation.frequency_deviation_count,
                        "maximum_absolute_frequency_deviation": (
                            validation.maximum_absolute_frequency_deviation
                        ),
                        "mean_absolute_frequency_deviation": (
                            validation.mean_absolute_frequency_deviation
                        ),
                        "passage_count_preserved": validation.passage_count_preserved,
                        "passage_lengths_preserved": validation.passage_lengths_preserved,
                        "representation_isolation_preserved": (
                            validation.representation_isolation_preserved
                        ),
                        "scope_note": NO_GLOBAL_ALL_PAIRS_CLAIM,
                        "shared_across_detectors": True,
                        "source_identities_replaced": validation.source_identities_replaced,
                    }
                )
                passage_count = len(replicate.passages)
                token_count = sum(len(passage.features) for passage in replicate.passages)
                length_digest = _length_digest(active)
                frequency_digest = _frequency_digest(active, sequence_index)
                del replicate, validation
                scores_by_detector = _score_shared_null_replicate(
                    sampled_candidates,
                    active_features=active,
                    pos_features=pos,
                    morphology_features=morphology,
                    corpus_pair=corpus_pair,
                    config=config,
                )
                runtime_seconds = time.perf_counter() - started
                for detector in detector_order:
                    detector_scores = scores_by_detector[detector]
                    quantiles_json = _score_quantiles(detector_scores)
                    mean_score = float(np.mean(detector_scores))
                    for threshold in _thresholds_for_detector(detector, config):
                        count = int(np.count_nonzero(detector_scores >= threshold))
                        null_counts[detector][family][threshold].append(count)
                        threshold_id = _threshold_id(
                            corpus_pair,
                            representation_id,
                            detector,
                            threshold,
                        )
                        row: dict[str, object] = {
                            "null_run_id": run_id,
                            "experiment_run_id": experiment_run_id,
                            "null_family": family,
                            "iteration": iteration,
                            "seed": seed,
                            "corpus_pair": corpus_pair,
                            "representation_id": representation_id,
                            "detector": detector,
                            "threshold_id": threshold_id,
                            "candidate_count": count,
                            "mean_score": mean_score,
                            "score_quantiles_json": quantiles_json,
                            "conditioning_json": conditioning,
                            "passage_count": passage_count,
                            "token_count": token_count,
                            "length_digest": length_digest,
                            "frequency_digest": frequency_digest,
                            "logical_output_hash": "",
                            "runtime_seconds": runtime_seconds,
                        }
                        row["logical_output_hash"] = _logical_null_row_hash(row)
                        null_rows.append(row)
                del active, detector_scores, morphology, pos, scores_by_detector

        for detector in detector_order:
            thresholds = _thresholds_for_detector(detector, config)
            selection = _calibration_selection(
                thresholds=thresholds,
                observed_counts=observed_counts[detector],
                counts_by_family=null_counts[detector],
                maximum_fdr=config.candidate_thresholds.maximum_empirical_fdr,
            )
            selected_threshold = (
                selection.score_threshold if math.isfinite(selection.score_threshold) else None
            )
            for threshold in thresholds:
                qualifies = _threshold_qualifies_empirical_fdr(
                    threshold=threshold,
                    observed=observed_counts[detector][threshold],
                    counts_by_family=null_counts[detector],
                    maximum_fdr=config.candidate_thresholds.maximum_empirical_fdr,
                )
                is_selected = detector == COMPOSITE_DETECTOR and threshold == selected_threshold
                pooled_counts = tuple(
                    count
                    for family in REQUIRED_NULL_FAMILIES
                    for count in null_counts[detector][family][threshold]
                )
                calibration = calibrate_null_counts(
                    threshold,
                    observed_counts[detector][threshold],
                    pooled_counts,
                )
                calibration_rows.append(
                    {
                        "threshold_id": _threshold_id(
                            corpus_pair,
                            representation_id,
                            detector,
                            threshold,
                        ),
                        "experiment_run_id": experiment_run_id,
                        "corpus_pair": corpus_pair,
                        "representation_id": representation_id,
                        "detector": detector,
                        "score_threshold": threshold,
                        "observed_candidate_count": calibration.observed_count,
                        "mean_null_candidate_count": calibration.null_mean_count,
                        "null_interval_low": calibration.null_interval_low,
                        "null_interval_high": calibration.null_interval_high,
                        "observed_to_null_enrichment": (
                            calibration.enrichment
                            if calibration.enrichment is not None
                            and math.isfinite(calibration.enrichment)
                            else None
                        ),
                        "empirical_tail_probability": (
                            calibration.empirical_upper_tail_probability
                        ),
                        "estimated_empirical_fdr": calibration.raw_empirical_fdr,
                        "eligible_candidate_count": calibration.observed_count,
                        "threshold_selection_scope": CANDIDATE_UNION_SAMPLE_SCOPE,
                        "qualifies_empirical_fdr": qualifies,
                        "selected": is_selected,
                        "selection_reason": _threshold_selection_reason(
                            detector=detector,
                            observed=calibration.observed_count,
                            qualifies=qualifies,
                            selected=is_selected,
                        ),
                        "frozen_before_test": True,
                        "notes": NO_GLOBAL_ALL_PAIRS_CLAIM,
                    }
                )
            if detector == COMPOSITE_DETECTOR and selected_threshold is not None:
                selected.append(
                    (
                        corpus_pair,
                        selection,
                    )
                )

        selected_rows = sum(
            bool(row["selected"])
            for row in calibration_rows
            if row["corpus_pair"] == corpus_pair and row["detector"] == COMPOSITE_DETECTOR
        )
        if selected_rows not in {0, 1}:
            raise LexicalExperimentError(
                f"{corpus_pair} must persist zero or one selected RRF threshold"
            )
        del prepared_source, sampled_candidates, sequence_index

    return NullCalibrationArtifacts(
        null_replicate_summaries=_typed_frame(
            null_rows,
            NULL_REPLICATE_SUMMARIES_SCHEMA,
        ),
        threshold_calibration=_typed_frame(
            calibration_rows,
            THRESHOLD_CALIBRATION_SCHEMA,
        ),
        candidate_samples=tuple(samples),
        selected_calibration=tuple(selected),
    )


_RANKING_REQUIRED_COLUMNS: Final = frozenset(
    {
        "experiment_run_id",
        "query_passage_id",
        "target_passage_id",
        "corpus_pair",
        "representation_id",
        "detector",
        "rank",
        "quantized_score",
    }
)


def _filter_ranking_scope_frame(
    frame: pl.DataFrame,
    *,
    experiment_scope: str,
    analysis_profile: AnalysisProfile,
) -> pl.DataFrame:
    filtered = frame
    for column, expected, legacy_value in (
        ("experiment_scope", experiment_scope, "primary"),
        ("analysis_profile", analysis_profile, "edition_complete"),
    ):
        if column in filtered.columns:
            filtered = filtered.filter(pl.col(column) == expected)
        elif expected != legacy_value:
            raise LexicalExperimentError(
                f"directional rankings omit required sensitivity column: {column}"
            )
    return filtered


def _filter_ranking_scope_lazy(
    frame: pl.LazyFrame,
    *,
    experiment_scope: str,
    analysis_profile: AnalysisProfile,
) -> pl.LazyFrame:
    columns = set(frame.collect_schema().names())
    filtered = frame
    for column, expected, legacy_value in (
        ("experiment_scope", experiment_scope, "primary"),
        ("analysis_profile", analysis_profile, "edition_complete"),
    ):
        if column in columns:
            filtered = filtered.filter(pl.col(column) == expected)
        elif expected != legacy_value:
            raise LexicalExperimentError(
                f"directional rankings omit required sensitivity column: {column}"
            )
    return filtered


def _load_ranking_frames(
    source: RankingInput,
    *,
    experiment_run_id: str,
    query_passage_ids: Sequence[str] | None = None,
    detectors: Sequence[str] | None = None,
    allow_empty: bool = False,
    experiment_scope: str = "primary",
    analysis_profile: AnalysisProfile = "edition_complete",
) -> pl.DataFrame:
    if isinstance(source, pl.DataFrame):
        frame = _filter_ranking_scope_frame(
            source,
            experiment_scope=experiment_scope,
            analysis_profile=analysis_profile,
        )
    elif isinstance(source, (str, Path)):
        path_text = str(source)
        path = Path(path_text)
        if path.is_dir():
            path_text = str(path / "**" / "*.parquet")
        try:
            lazy = _filter_ranking_scope_lazy(
                pl.scan_parquet(path_text),
                experiment_scope=experiment_scope,
                analysis_profile=analysis_profile,
            ).filter(pl.col("experiment_run_id") == experiment_run_id)
            if query_passage_ids is not None:
                lazy = lazy.filter(pl.col("query_passage_id").is_in(query_passage_ids))
            if detectors is not None:
                lazy = lazy.filter(pl.col("detector").is_in(detectors))
            frame = lazy.select(*sorted(_RANKING_REQUIRED_COLUMNS)).collect(engine="streaming")
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(f"could not load directional rankings: {exc}") from exc
    else:
        frames = tuple(source)
        if not frames:
            raise LexicalExperimentError("at least one directional-ranking frame is required")
        if any(not isinstance(frame, pl.DataFrame) for frame in frames):
            raise LexicalExperimentError("ranking-frame sequences may contain only DataFrames")
        frame = _filter_ranking_scope_frame(
            pl.concat(frames, how="diagonal_relaxed"),
            experiment_scope=experiment_scope,
            analysis_profile=analysis_profile,
        )
    missing = _RANKING_REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise LexicalExperimentError(
            "directional rankings omit required columns: " + ", ".join(sorted(missing))
        )
    filtered = frame.filter(pl.col("experiment_run_id") == experiment_run_id)
    if query_passage_ids is not None:
        filtered = filtered.filter(pl.col("query_passage_id").is_in(query_passage_ids))
    if detectors is not None:
        filtered = filtered.filter(pl.col("detector").is_in(detectors))
    filtered = filtered.select(*sorted(_RANKING_REQUIRED_COLUMNS))
    if filtered.is_empty() and not allow_empty:
        raise LexicalExperimentError(
            f"directional rankings contain no rows for {experiment_run_id}"
        )
    invalid = filtered.filter(
        pl.col("query_passage_id").is_null()
        | pl.col("target_passage_id").is_null()
        | pl.col("detector").is_null()
        | (pl.col("rank") < 1)
        | ~pl.col("quantized_score").is_finite()
    )
    if invalid.height:
        raise LexicalExperimentError("directional rankings contain invalid identities or ranks")
    duplicate_count = (
        filtered.group_by(
            "query_passage_id",
            "target_passage_id",
            "corpus_pair",
            "representation_id",
            "detector",
        )
        .len()
        .filter(pl.col("len") != 1)
        .height
    )
    if duplicate_count:
        raise LexicalExperimentError(
            "directional rankings contain duplicate query/target/detector rows"
        )
    return filtered.sort(
        "corpus_pair",
        "representation_id",
        "query_passage_id",
        "detector",
        "rank",
        "target_passage_id",
    )


def _candidate_universe_by_query(
    source: RankingInput,
    *,
    experiment_run_id: str,
    query_passage_ids: Sequence[str],
    detectors: Sequence[str],
    maximum_targets_per_query: int,
    resource_check: ResourceCheck | None = None,
    experiment_scope: str = "primary",
    analysis_profile: AnalysisProfile = "edition_complete",
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    if maximum_targets_per_query < 1:
        raise LexicalExperimentError("candidate-universe target limit must be positive")
    columns = (
        "corpus_pair",
        "representation_id",
        "query_passage_id",
        "target_passage_id",
    )
    group_columns = columns[:-1]
    maximum_item_count = len(query_passage_ids) * maximum_targets_per_query
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:candidate_universe:reserve-grouped-build",
            estimated_additional_bytes=(
                maximum_item_count * CANDIDATE_UNIVERSE_ITEM_RESERVATION_BYTES
                + len(query_passage_ids) * CANDIDATE_UNIVERSE_GROUP_RESERVATION_BYTES
            ),
        )
    if isinstance(source, (str, Path)):
        path_text = str(source)
        path = Path(path_text)
        if path.is_dir():
            paths = sorted(path.rglob("*.parquet"))
            if not paths:
                raise LexicalExperimentError("persisted rankings yield an empty candidate universe")
            target_sets: dict[tuple[str, str, str], set[str]] = {}
            leaf_string_pool: dict[str, str] = {}

            def pooled_leaf_value(value: object) -> str:
                text = str(value)
                return leaf_string_pool.setdefault(text, text)

            try:
                for leaf_number, leaf in enumerate(paths, start=1):
                    lazy = _filter_ranking_scope_lazy(
                        pl.scan_parquet(leaf),
                        experiment_scope=experiment_scope,
                        analysis_profile=analysis_profile,
                    )
                    missing = _RANKING_REQUIRED_COLUMNS.difference(lazy.collect_schema().names())
                    if missing:
                        raise LexicalExperimentError(
                            "directional rankings omit required columns: "
                            + ", ".join(sorted(missing))
                        )
                    frame = (
                        lazy.filter(
                            (pl.col("experiment_run_id") == experiment_run_id)
                            & pl.col("query_passage_id").is_in(query_passage_ids)
                            & pl.col("detector").is_in(detectors)
                        )
                        .select(*columns)
                        .collect(engine="streaming")
                    )
                    for corpus_pair, representation_id, query_id, target_id in frame.iter_rows():
                        key = (
                            pooled_leaf_value(corpus_pair),
                            pooled_leaf_value(representation_id),
                            pooled_leaf_value(query_id),
                        )
                        targets = target_sets.setdefault(key, set())
                        targets.add(pooled_leaf_value(target_id))
                        if len(targets) > maximum_targets_per_query:
                            raise LexicalExperimentError(
                                "persisted rankings exceed the governed "
                                "candidate-union limit: "
                                f"query={key[2]}, observed={len(targets)}, "
                                f"maximum={maximum_targets_per_query}"
                            )
                    if resource_check is not None and leaf_number % 32 == 0:
                        resource_check(
                            f"evaluation:{analysis_profile}:candidate_universe:"
                            f"leaf-{leaf_number}:groups-{len(target_sets)}"
                        )
            except LexicalExperimentError:
                raise
            except (OSError, pl.exceptions.PolarsError) as exc:
                raise LexicalExperimentError(f"could not build candidate universe: {exc}") from exc
            if not target_sets:
                raise LexicalExperimentError("persisted rankings yield an empty candidate universe")
            return {key: tuple(sorted(target_sets[key])) for key in sorted(target_sets)}
        try:
            lazy = _filter_ranking_scope_lazy(
                pl.scan_parquet(path_text),
                experiment_scope=experiment_scope,
                analysis_profile=analysis_profile,
            )
            missing = _RANKING_REQUIRED_COLUMNS.difference(lazy.collect_schema().names())
            if missing:
                raise LexicalExperimentError(
                    "directional rankings omit required columns: " + ", ".join(sorted(missing))
                )
            selected = lazy.filter(
                (pl.col("experiment_run_id") == experiment_run_id)
                & pl.col("query_passage_id").is_in(query_passage_ids)
                & pl.col("detector").is_in(detectors)
            ).select(*columns)
        except LexicalExperimentError:
            raise
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(f"could not build candidate universe: {exc}") from exc
    else:
        selected = (
            _load_ranking_frames(
                source,
                experiment_run_id=experiment_run_id,
                query_passage_ids=query_passage_ids,
                detectors=detectors,
                experiment_scope=experiment_scope,
                analysis_profile=analysis_profile,
            )
            .select(*columns)
            .lazy()
        )
    grouped = selected.group_by(*group_columns).agg(pl.col("target_passage_id").unique().sort())
    output: dict[tuple[str, str, str], tuple[str, ...]] = {}
    pooled_strings: dict[str, str] = {}

    def pooled(value: object) -> str:
        text = str(value)
        return pooled_strings.setdefault(text, text)

    try:
        batches = grouped.collect_batches(
            chunk_size=CANDIDATE_UNIVERSE_BATCH_SIZE,
            maintain_order=False,
            engine="streaming",
        )
        for batch_number, batch in enumerate(batches, start=1):
            if resource_check is not None:
                resource_check(
                    f"evaluation:{analysis_profile}:candidate_universe:"
                    f"reserve-python-batch-{batch_number}",
                    estimated_additional_bytes=(
                        batch.height
                        * (
                            maximum_targets_per_query * CANDIDATE_UNIVERSE_ITEM_RESERVATION_BYTES
                            + CANDIDATE_UNIVERSE_GROUP_RESERVATION_BYTES
                        )
                    ),
                )
            for row in batch.iter_rows():
                values = cast(Sequence[object], row[3])
                if len(values) > maximum_targets_per_query:
                    raise LexicalExperimentError(
                        "persisted rankings exceed the governed candidate-union limit: "
                        f"query={row[2]}, observed={len(values)}, "
                        f"maximum={maximum_targets_per_query}"
                    )
                key = (pooled(row[0]), pooled(row[1]), pooled(row[2]))
                if key in output:
                    raise LexicalExperimentError(
                        f"candidate-universe grouping repeated query identity: {key}"
                    )
                output[key] = tuple(pooled(value) for value in values)
            if resource_check is not None:
                resource_check(
                    f"evaluation:{analysis_profile}:candidate_universe:"
                    f"batch-{batch_number}:groups-{len(output)}"
                )
    except LexicalExperimentError:
        raise
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalExperimentError(f"could not build candidate universe: {exc}") from exc
    if not output:
        raise LexicalExperimentError("persisted rankings yield an empty candidate universe")
    return output


def _ranking_strata(
    source: RankingInput,
    *,
    experiment_run_id: str,
    experiment_scope: str = "primary",
    analysis_profile: AnalysisProfile = "edition_complete",
) -> tuple[tuple[str, str, str], ...]:
    columns = ("corpus_pair", "representation_id", "detector")
    if isinstance(source, (str, Path)):
        path_text = str(source)
        path = Path(path_text)
        if path.is_dir():
            paths = sorted(path.rglob("*.parquet"))
            if not paths:
                raise LexicalExperimentError(
                    "directional rankings expose no persisted scoring strata"
                )
            observed: set[tuple[str, str, str]] = set()
            try:
                for leaf in paths:
                    frame = (
                        _filter_ranking_scope_lazy(
                            pl.scan_parquet(leaf),
                            experiment_scope=experiment_scope,
                            analysis_profile=analysis_profile,
                        )
                        .filter(pl.col("experiment_run_id") == experiment_run_id)
                        .select(*columns)
                        .unique()
                        .collect(engine="streaming")
                    )
                    observed.update(
                        (str(pair), str(representation), str(detector))
                        for pair, representation, detector in frame.iter_rows()
                    )
            except (OSError, pl.exceptions.PolarsError) as exc:
                raise LexicalExperimentError(f"could not inspect ranking strata: {exc}") from exc
            strata = tuple(sorted(observed))
            if not strata:
                raise LexicalExperimentError(
                    "directional rankings expose no persisted scoring strata"
                )
            return strata
        try:
            frame = (
                _filter_ranking_scope_lazy(
                    pl.scan_parquet(path_text),
                    experiment_scope=experiment_scope,
                    analysis_profile=analysis_profile,
                )
                .filter(pl.col("experiment_run_id") == experiment_run_id)
                .select(*columns)
                .unique()
                .collect(engine="streaming")
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(f"could not inspect ranking strata: {exc}") from exc
    else:
        frame = (
            _load_ranking_frames(
                source,
                experiment_run_id=experiment_run_id,
                experiment_scope=experiment_scope,
                analysis_profile=analysis_profile,
            )
            .select(*columns)
            .unique()
        )
    strata = tuple(
        sorted(
            (str(pair), str(representation), str(detector))
            for pair, representation, detector in frame.iter_rows()
        )
    )
    if not strata:
        raise LexicalExperimentError("directional rankings expose no persisted scoring strata")
    return strata


def _json_string_list(value: object, *, label: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise LexicalExperimentError(f"{label} is not valid JSON") from exc
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(parsed) != len(set(parsed))
    ):
        raise LexicalExperimentError(f"{label} must be a unique nonempty string array")
    return tuple(parsed)


def _vote_stratum(value: int) -> str:
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    if value <= 2:
        return "one_to_two"
    if value <= 5:
        return "three_to_five"
    if value <= 10:
        return "six_to_ten"
    if value <= 25:
        return "eleven_to_twenty_five"
    return "twenty_six_plus"


def _combined_mapping_status(first: str, second: str) -> str:
    precedence = {
        "mapped_verified": 0,
        "mapped_provisional": 1,
        "mapped_partial": 2,
    }
    if first not in precedence or second not in precedence:
        raise LexicalExperimentError("an ineligible endpoint mapping entered evaluation")
    return max((first, second), key=precedence.__getitem__)


def _pair_for_corpora(first: str, second: str) -> str:
    if first == second == "hebrew":
        return "hb_hb"
    if first == second == "greek":
        return "gnt_gnt"
    if {first, second} == {"hebrew", "greek"}:
        return "hb_gnt_english_bridge"
    raise LexicalExperimentError(f"unsupported benchmark corpus direction: {first}/{second}")


@dataclass(frozen=True, slots=True)
class _ExcludedEvaluationFact:
    corpus_pair: str
    split_strategy: str
    excluded_query_count: int
    excluded_relationship_count: int


@dataclass(frozen=True, slots=True)
class _PresumedNegativePair:
    contrastive_id: str
    passage_a_id: str
    passage_b_id: str
    corpus_pair: str
    split_strategy: str
    partition: str


def _presumed_negative_corpus_pair(value: str) -> str:
    if value == "hebrew|hebrew":
        return "hb_hb"
    if value == "greek|greek":
        return "gnt_gnt"
    if value in {"greek|hebrew", "hebrew|greek"}:
        return "hb_gnt_english_bridge"
    raise LexicalExperimentError(f"unsupported presumed-negative corpus pair: {value}")


def _load_presumed_negative_pairs(
    database_path: Path,
    *,
    benchmark_version: str,
    analysis_profile: AnalysisProfile,
    corpus_pairs: Sequence[str],
    split_strategies: Sequence[str],
    resource_check: ResourceCheck | None = None,
    duckdb_memory_limit_bytes: int = DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES,
    duckdb_temp_directory: Path | None = None,
) -> tuple[_PresumedNegativePair, ...]:
    if analysis_profile != "edition_complete":
        return ()
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:presumed_negatives:before")
    rows: list[_PresumedNegativePair] = []
    seen_ids: set[str] = set()
    connection_context = _experiment_duckdb_connection(
        database_path,
        memory_limit_bytes=duckdb_memory_limit_bytes,
        temp_directory=duckdb_temp_directory,
    )
    connection = connection_context.__enter__()
    try:
        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        if "benchmark_presumed_negative_pairs" not in tables:
            raise LexicalExperimentError(
                "edition-complete evaluation requires benchmark_presumed_negative_pairs"
            )
        cursor = connection.execute(
            "SELECT contrastive_id,passage_a_id,passage_b_id,corpus_pair,"
            "split_strategy,partition,presumed_negative,positive_graph_checked,"
            "reverse_pair_checked,passage_overlap_checked,leakage_checked "
            "FROM benchmark_presumed_negative_pairs WHERE benchmark_version=? "
            "ORDER BY corpus_pair,split_strategy,partition,contrastive_id",
            [benchmark_version],
        )
        batch_number = 0
        while True:
            if resource_check is not None:
                resource_check(
                    f"evaluation:{analysis_profile}:presumed_negatives:reserve-batch-"
                    f"{batch_number + 1}",
                    estimated_additional_bytes=(
                        BENCHMARK_FETCH_BATCH_SIZE * BENCHMARK_ROW_RESERVATION_BYTES
                    ),
                )
            values = cursor.fetchmany(BENCHMARK_FETCH_BATCH_SIZE)
            if not values:
                break
            batch_number += 1
            if resource_check is not None:
                resource_check(
                    f"evaluation:{analysis_profile}:presumed_negatives:batch-{batch_number}"
                )
            for value in values:
                contrastive_id = str(value[0])
                corpus_pair = _presumed_negative_corpus_pair(str(value[3]))
                split_strategy = str(value[4])
                if corpus_pair not in corpus_pairs or split_strategy not in split_strategies:
                    continue
                if contrastive_id in seen_ids:
                    raise LexicalExperimentError("presumed-negative contrastive IDs are not unique")
                seen_ids.add(contrastive_id)
                if not all(bool(flag) for flag in value[6:]):
                    raise LexicalExperimentError(
                        f"presumed-negative governance checks failed for {contrastive_id}"
                    )
                passage_a_id = str(value[1])
                passage_b_id = str(value[2])
                if not passage_a_id or not passage_b_id or passage_a_id == passage_b_id:
                    raise LexicalExperimentError(
                        f"presumed-negative pair identity is invalid for {contrastive_id}"
                    )
                rows.append(
                    _PresumedNegativePair(
                        contrastive_id=contrastive_id,
                        passage_a_id=passage_a_id,
                        passage_b_id=passage_b_id,
                        corpus_pair=corpus_pair,
                        split_strategy=split_strategy,
                        partition=str(value[5]),
                    )
                )
    finally:
        connection_context.__exit__(None, None, None)
    result = tuple(rows)
    rows.clear()
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:presumed_negatives:complete-{len(result)}")
    return result


@contextmanager
def _benchmark_rows(
    database_path: Path,
    *,
    analysis_profile: AnalysisProfile,
    eligible_mapping_statuses: Sequence[str],
    split_strategies: Sequence[str],
    resource_check: ResourceCheck | None = None,
    duckdb_memory_limit_bytes: int = DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES,
    duckdb_temp_directory: Path | None = None,
) -> Iterator[
    tuple[
        str,
        Iterator[dict[str, object]],
        tuple[_ExcludedEvaluationFact, ...],
    ]
]:
    if not database_path.is_file():
        raise LexicalExperimentError(f"benchmark database does not exist: {database_path}")
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:benchmark:before_connect")
    connection_context = _experiment_duckdb_connection(
        database_path,
        memory_limit_bytes=duckdb_memory_limit_bytes,
        temp_directory=duckdb_temp_directory,
    )
    connection = connection_context.__enter__()
    try:
        required_tables = {
            "benchmark_relationships",
            "benchmark_endpoints",
            "benchmark_endpoint_mappings",
            "benchmark_leakage_groups",
            "benchmark_split_assignments",
        }
        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        missing = required_tables.difference(tables)
        if missing:
            raise LexicalExperimentError(
                "benchmark database omits required tables: " + ", ".join(sorted(missing))
            )
        tier1_row = connection.execute(
            "SELECT count(*) FROM benchmark_relationships WHERE tier=1"
        ).fetchone()
        if tier1_row is None:
            raise LexicalExperimentError("could not read the Tier 1 row count")
        tier1_count = int(tier1_row[0])
        if tier1_count != 0:
            raise LexicalExperimentError(
                f"Tier 1 must remain empty; database contains {tier1_count} rows"
            )
        versions = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT benchmark_version FROM benchmark_split_assignments "
                "ORDER BY benchmark_version"
            ).fetchall()
        )
        if len(versions) != 1 or not versions[0]:
            raise LexicalExperimentError(
                "evaluation requires exactly one anchored benchmark version"
            )
        statuses = ",".join(f"'{status}'" for status in eligible_mapping_statuses)
        splits = ",".join(f"'{strategy}'" for strategy in split_strategies)
        sql = f"""
            SELECT
              r.relationship_id,
              r.source_weight_sum,
              r.source_weight_max,
              r.weak_supervision_eligible,
              ea.parsed_book AS book_a,
              eb.parsed_book AS book_b,
              ma.target_corpus AS corpus_a,
              mb.target_corpus AS corpus_b,
              ma.target_analysis_profile AS profile_a,
              mb.target_analysis_profile AS profile_b,
              ma.target_passage_ids_json AS passage_ids_a,
              mb.target_passage_ids_json AS passage_ids_b,
              ma.mapping_status AS mapping_status_a,
              mb.mapping_status AS mapping_status_b,
              ma.reference_gap AS reference_gap_a,
              mb.reference_gap AS reference_gap_b,
              ma.disputed_passage_flag AS disputed_a,
              mb.disputed_passage_flag AS disputed_b,
              s.split_strategy,
              s.partition,
              s.leakage_group_id,
              s.eligibility_status,
              s.exclusion_reason,
              EXISTS(
                SELECT 1 FROM benchmark_leakage_groups l
                WHERE l.relationship_id=r.relationship_id
                  AND l.leakage_group_id=s.leakage_group_id
              ) AS leakage_membership_present
            FROM benchmark_relationships r
            JOIN benchmark_endpoints ea
              ON ea.relationship_id=r.relationship_id AND ea.endpoint_side='a'
            JOIN benchmark_endpoints eb
              ON eb.relationship_id=r.relationship_id AND eb.endpoint_side='b'
            JOIN benchmark_endpoint_mappings ma
              ON ma.endpoint_id=ea.endpoint_id
             AND ma.target_analysis_profile=?
             AND ma.target_granularity='verse'
             AND ma.mapping_status IN ({statuses})
            JOIN benchmark_endpoint_mappings mb
              ON mb.endpoint_id=eb.endpoint_id
             AND mb.target_analysis_profile=?
             AND mb.target_granularity='verse'
             AND mb.mapping_status IN ({statuses})
            JOIN benchmark_split_assignments s
              ON s.relationship_id=r.relationship_id
             AND s.benchmark_version=?
            WHERE r.tier=3 AND r.source_id=?
              AND r.weak_supervision_eligible
              AND s.eligibility_status='eligible'
              AND s.partition<>'excluded'
              AND s.split_strategy IN ({splits})
            ORDER BY r.relationship_id,s.split_strategy
        """
        excluded_sql = f"""
            SELECT
              CASE
                WHEN ma.target_corpus='hebrew' AND mb.target_corpus='hebrew' THEN 'hb_hb'
                WHEN ma.target_corpus='greek' AND mb.target_corpus='greek' THEN 'gnt_gnt'
                ELSE 'hb_gnt_english_bridge'
              END AS corpus_pair,
              s.split_strategy,
              CAST(sum(
                greatest(json_array_length(ma.target_passage_ids_json),1)
                + greatest(json_array_length(mb.target_passage_ids_json),1)
              ) AS BIGINT) AS excluded_query_count,
              count(DISTINCT r.relationship_id) AS excluded_relationship_count
            FROM benchmark_relationships r
            JOIN benchmark_endpoints ea
              ON ea.relationship_id=r.relationship_id AND ea.endpoint_side='a'
            JOIN benchmark_endpoints eb
              ON eb.relationship_id=r.relationship_id AND eb.endpoint_side='b'
            JOIN benchmark_endpoint_mappings ma
              ON ma.endpoint_id=ea.endpoint_id
             AND ma.target_analysis_profile=?
             AND ma.target_granularity='verse'
            JOIN benchmark_endpoint_mappings mb
              ON mb.endpoint_id=eb.endpoint_id
             AND mb.target_analysis_profile=?
             AND mb.target_granularity='verse'
            JOIN benchmark_split_assignments s
              ON s.relationship_id=r.relationship_id
             AND s.benchmark_version=?
            WHERE r.tier=3 AND r.source_id=?
              AND s.split_strategy IN ({splits})
              AND (
                NOT r.weak_supervision_eligible
                OR s.eligibility_status<>'eligible'
                OR s.partition='excluded'
                OR ma.mapping_status NOT IN ({statuses})
                OR mb.mapping_status NOT IN ({statuses})
              )
            GROUP BY corpus_pair,s.split_strategy
            ORDER BY corpus_pair,s.split_strategy
        """
        excluded = tuple(
            _ExcludedEvaluationFact(
                corpus_pair=str(pair),
                split_strategy=str(strategy),
                excluded_query_count=int(query_count),
                excluded_relationship_count=int(relationship_count),
            )
            for pair, strategy, query_count, relationship_count in connection.execute(
                excluded_sql,
                [analysis_profile, analysis_profile, versions[0], OPENBIBLE_SOURCE_ID],
            ).fetchall()
        )
        if resource_check is not None:
            resource_check(f"evaluation:{analysis_profile}:benchmark:before_stream")
        cursor = connection.execute(
            sql,
            [analysis_profile, analysis_profile, versions[0], OPENBIBLE_SOURCE_ID],
        )
        columns = tuple(description[0] for description in cursor.description)

        def rows() -> Iterator[dict[str, object]]:
            row_count = 0
            batch_number = 0
            while True:
                if resource_check is not None:
                    resource_check(
                        f"evaluation:{analysis_profile}:benchmark:reserve-batch-{batch_number + 1}",
                        estimated_additional_bytes=(
                            BENCHMARK_FETCH_BATCH_SIZE * BENCHMARK_ROW_RESERVATION_BYTES
                        ),
                    )
                values = cursor.fetchmany(BENCHMARK_FETCH_BATCH_SIZE)
                if not values:
                    break
                batch_number += 1
                row_count += len(values)
                if resource_check is not None:
                    resource_check(
                        f"evaluation:{analysis_profile}:benchmark:batch-{batch_number}:"
                        f"rows-{row_count}"
                    )
                for row in values:
                    yield dict(zip(columns, row, strict=True))
            if row_count == 0:
                raise LexicalExperimentError("no eligible anchored Tier 3 mappings were found")

        yield versions[0], rows(), excluded
    finally:
        connection_context.__exit__(None, None, None)


def _load_tier3_queries(
    database_path: Path,
    *,
    analysis_profile: AnalysisProfile,
    corpus_pairs: Sequence[str],
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    book_genres: Mapping[str, str],
    config: LexicalConfig,
    resource_check: ResourceCheck | None = None,
    duckdb_memory_limit_bytes: int = DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES,
    duckdb_temp_directory: Path | None = None,
) -> tuple[
    str,
    tuple[Tier3EvaluationQuery, ...],
    dict[str, str],
    tuple[_ExcludedEvaluationFact, ...],
]:
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:queries:before_sequence_indexes")
    sequence_indexes = {
        pair: _sequence_index(tuple(sequences), corpus_pair=pair)
        for pair, sequences in sequences_by_corpus_pair.items()
        if pair in GOVERNED_CORPUS_PAIRS
    }
    with _benchmark_rows(
        database_path,
        analysis_profile=analysis_profile,
        eligible_mapping_statuses=config.benchmark_evaluation.eligible_mapping_statuses,
        split_strategies=config.benchmark_evaluation.split_strategies,
        resource_check=resource_check,
        duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
        duckdb_temp_directory=duckdb_temp_directory,
    ) as (benchmark_version, rows, excluded):
        return _expand_tier3_queries(
            benchmark_version,
            rows,
            excluded,
            analysis_profile=analysis_profile,
            corpus_pairs=corpus_pairs,
            sequence_indexes=sequence_indexes,
            book_genres=book_genres,
            resource_check=resource_check,
        )


def _expand_tier3_queries(
    benchmark_version: str,
    rows: Iterator[dict[str, object]],
    excluded: tuple[_ExcludedEvaluationFact, ...],
    *,
    analysis_profile: AnalysisProfile,
    corpus_pairs: Sequence[str],
    sequence_indexes: Mapping[str, Mapping[str, PassageLexicalSequence]],
    book_genres: Mapping[str, str],
    resource_check: ResourceCheck | None,
) -> tuple[
    str,
    tuple[Tier3EvaluationQuery, ...],
    dict[str, str],
    tuple[_ExcludedEvaluationFact, ...],
]:
    queries: list[Tier3EvaluationQuery] = []
    source_passage_ids: dict[str, str] = {}
    relevant_sets: dict[tuple[str, ...], frozenset[str]] = {}
    relationship_sets: dict[str, frozenset[str]] = {}
    leakage_partitions: dict[tuple[str, str], str] = {}
    shared_strings: dict[str, str] = {}
    query_count = 0

    def shared_string(value: str) -> str:
        existing = shared_strings.get(value)
        if existing is not None:
            return existing
        shared_strings[value] = value
        return value

    for row in rows:
        if row["profile_a"] != analysis_profile or row["profile_b"] != analysis_profile:
            raise LexicalExperimentError("non-governed analysis profile entered evaluation")
        if not bool(row["leakage_membership_present"]) or not row["leakage_group_id"]:
            raise LexicalExperimentError(
                f"split assignment lacks anchored leakage membership: {row['relationship_id']}"
            )
        passage_ids_a = tuple(
            shared_string(value)
            for value in _json_string_list(
                row["passage_ids_a"],
                label=f"{row['relationship_id']} endpoint a passage IDs",
            )
        )
        passage_ids_b = tuple(
            shared_string(value)
            for value in _json_string_list(
                row["passage_ids_b"],
                label=f"{row['relationship_id']} endpoint b passage IDs",
            )
        )
        mapping_status = _combined_mapping_status(
            str(row["mapping_status_a"]),
            str(row["mapping_status_b"]),
        )
        relationship_id = shared_string(str(row["relationship_id"]))
        split_strategy = shared_string(str(row["split_strategy"]))
        partition = shared_string(str(row["partition"]))
        leakage_group_id = shared_string(str(row["leakage_group_id"]))
        leakage_key = (split_strategy, leakage_group_id)
        prior_partition = leakage_partitions.setdefault(leakage_key, partition)
        if prior_partition != partition:
            raise LexicalExperimentError(
                f"leakage group crosses governed partitions: {split_strategy}/{leakage_group_id}"
            )
        relationship_identity = relationship_sets.get(relationship_id)
        if relationship_identity is None:
            relationship_identity = frozenset({relationship_id})
            relationship_sets[relationship_id] = relationship_identity
        vote_value = (
            int(str(row["source_weight_max"]))
            if row["source_weight_max"] is not None
            else int(str(row["source_weight_sum"]))
        )
        if resource_check is not None:
            estimated_query_count = len(passage_ids_a) + len(passage_ids_b)
            estimated_target_members = len(passage_ids_a) + len(passage_ids_b)
            resource_check(
                f"evaluation:{analysis_profile}:queries:reserve:{relationship_id}:{split_strategy}",
                estimated_additional_bytes=(
                    estimated_query_count * EXPANDED_QUERY_RESERVATION_BYTES
                    + estimated_target_members * 128
                ),
            )
        for direction, source_ids, target_ids, source_corpus, target_corpus, book_a, book_b in (
            (
                "a_to_b",
                passage_ids_a,
                passage_ids_b,
                str(row["corpus_a"]),
                str(row["corpus_b"]),
                row["book_a"],
                row["book_b"],
            ),
            (
                "b_to_a",
                passage_ids_b,
                passage_ids_a,
                str(row["corpus_b"]),
                str(row["corpus_a"]),
                row["book_b"],
                row["book_a"],
            ),
        ):
            corpus_pair = _pair_for_corpora(source_corpus, target_corpus)
            if corpus_pair not in corpus_pairs:
                continue
            sequence_index = sequence_indexes.get(corpus_pair, {})
            relevant_passage_ids = relevant_sets.get(target_ids)
            if relevant_passage_ids is None:
                relevant_passage_ids = frozenset(target_ids)
                relevant_sets[target_ids] = relevant_passage_ids
            target_sequences = tuple(
                sequence_index[target_id] for target_id in target_ids if target_id in sequence_index
            )
            target_book = target_sequences[0].book if target_sequences else str(book_b or "unknown")
            base_reasons: list[str] = []
            if str(row["eligibility_status"]) != "eligible":
                base_reasons.append(str(row["exclusion_reason"] or "split_ineligible"))
            if partition == "excluded" and not base_reasons:
                base_reasons.append(str(row["exclusion_reason"] or "split_excluded"))
            if not bool(row["weak_supervision_eligible"]):
                base_reasons.append("weak_supervision_ineligible")
            if len(target_sequences) != len(target_ids):
                base_reasons.append("missing_target_anchor")
            for source_id in source_ids:
                source_sequence = sequence_index.get(source_id)
                reasons = list(base_reasons)
                if source_sequence is None:
                    reasons.append("missing_source_anchor")
                source_book = (
                    source_sequence.book
                    if source_sequence is not None
                    else str(book_a or "unknown")
                )
                if source_sequence is not None and source_book not in book_genres:
                    raise LexicalExperimentError(f"book genre is missing for {source_book}")
                source_book = shared_string(source_book)
                broad_genre = shared_string(book_genres.get(source_book, "unknown"))
                query_id = "tier3_" + _sha256_payload(
                    {
                        "benchmark_version": benchmark_version,
                        "relationship_id": relationship_id,
                        "split_strategy": split_strategy,
                        "analysis_profile": analysis_profile,
                        "direction": direction,
                        "source_passage_id": source_id,
                    }
                )
                query = Tier3EvaluationQuery(
                    query_id=query_id,
                    relevant_passage_ids=relevant_passage_ids,
                    relationship_ids=relationship_identity,
                    analysis_profile=analysis_profile,
                    mapping_status=shared_string(mapping_status),
                    corpus_pair=shared_string(corpus_pair),
                    split_strategy=split_strategy,
                    partition=partition,
                    source_book=source_book,
                    target_book=shared_string(target_book),
                    broad_genre=broad_genre,
                    passage_length=(source_sequence.token_count if source_sequence else 0),
                    vote_stratum=shared_string(_vote_stratum(vote_value)),
                    disputed_passage=bool(row["disputed_a"] or row["disputed_b"]),
                    reference_gap=bool(row["reference_gap_a"] or row["reference_gap_b"]),
                    leakage_group_id=leakage_group_id,
                    exclusion_reason=(
                        shared_string(";".join(sorted(set(reasons)))) if reasons else None
                    ),
                )
                queries.append(query)
                source_passage_ids[query_id] = source_id
                query_count += 1
                if resource_check is not None and query_count % BENCHMARK_FETCH_BATCH_SIZE == 0:
                    resource_check(f"evaluation:{analysis_profile}:queries:expanded-{query_count}")
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:queries:reserve-sort-{len(queries)}",
            estimated_additional_bytes=len(queries) * 16,
        )
    queries.sort(key=lambda item: item.query_id)
    if any(first.query_id == second.query_id for first, second in pairwise(queries)):
        raise LexicalExperimentError("expanded benchmark query identities are not unique")
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:queries:reserve-tuple-{len(queries)}",
            estimated_additional_bytes=len(queries) * 8,
        )
    query_values = tuple(queries)
    queries.clear()
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:queries:complete-{len(query_values)}")
    return benchmark_version, query_values, source_passage_ids, excluded


@dataclass(frozen=True, slots=True)
class _PrecomputedMetricTable:
    query_positions: Mapping[str, int]
    values: NDArray[np.float64]


def _precompute_baseline_metrics(
    baseline: BaselineName,
    candidate_universe: Mapping[tuple[str, str, str], tuple[str, ...]],
    queries: Sequence[Tier3EvaluationQuery],
    *,
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    representation_ids: Mapping[str, str],
    source_passage_ids: Mapping[str, str],
    config: LexicalConfig,
) -> _PrecomputedMetricTable:
    sequence_indexes = {
        pair: _sequence_index(tuple(sequences), corpus_pair=pair)
        for pair, sequences in sequences_by_corpus_pair.items()
        if pair in GOVERNED_CORPUS_PAIRS
    }
    ordered_queries = tuple(sorted(queries, key=lambda item: item.query_id))
    query_positions = {query.query_id: position for position, query in enumerate(ordered_queries)}
    values = np.empty((len(ordered_queries), len(_EVALUATION_METRICS)), dtype=np.float64)
    ranking_cache: dict[tuple[str, str], tuple[str, ...]] = {}
    for corpus_pair, pair_queries_iter in groupby(
        sorted(ordered_queries, key=lambda item: (item.corpus_pair, item.query_id)),
        key=lambda item: item.corpus_pair,
    ):
        pair_queries = tuple(pair_queries_iter)
        representation_id = representation_ids.get(corpus_pair)
        if not representation_id:
            raise LexicalExperimentError(
                f"evaluation representation ID is missing for {corpus_pair}"
            )
        sequence_index = sequence_indexes.get(corpus_pair)
        if not sequence_index:
            raise LexicalExperimentError(f"evaluation sequences are missing for {corpus_pair}")
        for query in pair_queries:
            source_passage_id = source_passage_ids.get(query.query_id)
            if source_passage_id is None:
                raise LexicalExperimentError("benchmark query lacks its anchored source passage")
            candidate_ids = candidate_universe.get(
                (corpus_pair, representation_id, source_passage_id),
                (),
            )
            source_sequence = sequence_index.get(source_passage_id)
            missing_targets = set(candidate_ids).difference(sequence_index)
            if missing_targets:
                raise LexicalExperimentError(
                    "ranked targets are absent from lexical sequences: "
                    + ", ".join(sorted(missing_targets)[:5])
                )
            cache_key = (corpus_pair, source_passage_id)
            if baseline == "random":
                ranking = deterministic_random_ranking(
                    candidate_ids,
                    query_id=query.query_id,
                    seed=config.statistics.bootstrap_seed,
                )
            else:
                cached_ranking = ranking_cache.get(cache_key)
                if cached_ranking is None:
                    if baseline == "length_matched":
                        ranking = length_matched_ranking(
                            candidate_ids,
                            query_length=query.passage_length,
                            target_lengths={
                                target_id: sequence_index[target_id].token_count
                                for target_id in candidate_ids
                            },
                        )
                    else:
                        ranking = unweighted_overlap_ranking(
                            candidate_ids,
                            query_features=(
                                source_sequence.values(_active_family(corpus_pair))
                                if source_sequence is not None
                                else ()
                            ),
                            target_features={
                                target_id: sequence_index[target_id].values(
                                    _active_family(corpus_pair)
                                )
                                for target_id in candidate_ids
                            },
                        )
                    ranking_cache[cache_key] = ranking
                else:
                    ranking = cached_ranking
            row_index = query_positions[query.query_id]
            for metric_index, (metric, _) in enumerate(_EVALUATION_METRICS):
                values[row_index, metric_index] = _query_metric(query, ranking, metric)
    return _PrecomputedMetricTable(query_positions=query_positions, values=values)


def _detector_rankings_for_queries(
    ranking_source: RankingInput,
    queries: Sequence[Tier3EvaluationQuery],
    *,
    detector: str,
    experiment_run_id: str,
    query_passage_ids: Sequence[str],
    maximum_targets_per_query: int,
    representation_ids: Mapping[str, str],
    source_passage_ids: Mapping[str, str],
    resource_check: ResourceCheck | None = None,
    experiment_scope: str = "primary",
    analysis_profile: AnalysisProfile = "edition_complete",
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[tuple[str, str, str], tuple[tuple[str, float], ...]],
]:
    if maximum_targets_per_query < 1:
        raise LexicalExperimentError("detector ranking target limit must be positive")
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:detector:{detector}:reserve-streamed-rankings",
            estimated_additional_bytes=(
                len(query_passage_ids)
                * maximum_targets_per_query
                * RANKING_PYTHON_ROW_RESERVATION_BYTES
            ),
        )
    columns = (
        "corpus_pair",
        "representation_id",
        "query_passage_id",
        "detector",
        "rank",
        "target_passage_id",
        "quantized_score",
    )
    pooled_strings: dict[str, str] = {}
    members_by_source: dict[tuple[str, str, str], list[tuple[int, str, float]]] = {}

    def pooled(value: object) -> str:
        text = str(value)
        return pooled_strings.setdefault(text, text)

    def register(row: tuple[object, ...]) -> None:
        if any(value is None for value in row[:6]):
            raise LexicalExperimentError("directional rankings contain null ranking identities")
        row_detector = pooled(row[3])
        rank = int(cast(int, row[4]))
        score = float(cast(float, row[6]))
        if row_detector != detector:
            raise LexicalExperimentError("detector-filtered ranking frame contains another method")
        if rank < 1 or not math.isfinite(score):
            raise LexicalExperimentError("directional rankings contain invalid ranks or scores")
        key = (pooled(row[0]), pooled(row[1]), pooled(row[2]))
        members = members_by_source.setdefault(key, [])
        members.append((rank, pooled(row[5]), score))
        if len(members) > maximum_targets_per_query:
            raise LexicalExperimentError(
                "persisted detector rankings exceed the governed target limit: "
                f"query={key[2]}, observed={len(members)}, "
                f"maximum={maximum_targets_per_query}"
            )

    path = Path(ranking_source) if isinstance(ranking_source, (str, Path)) else None
    if path is not None and path.is_dir():
        paths = sorted(path.rglob("*.parquet"))
        if not paths:
            raise LexicalExperimentError("directional rankings contain no Parquet leaves")
        try:
            for leaf_number, leaf in enumerate(paths, start=1):
                lazy = _filter_ranking_scope_lazy(
                    pl.scan_parquet(leaf),
                    experiment_scope=experiment_scope,
                    analysis_profile=analysis_profile,
                )
                missing = _RANKING_REQUIRED_COLUMNS.difference(lazy.collect_schema().names())
                if missing:
                    raise LexicalExperimentError(
                        "directional rankings omit required columns: " + ", ".join(sorted(missing))
                    )
                frame = (
                    lazy.filter(
                        (pl.col("experiment_run_id") == experiment_run_id)
                        & pl.col("query_passage_id").is_in(query_passage_ids)
                        & (pl.col("detector") == detector)
                    )
                    .select(*columns)
                    .collect(engine="streaming")
                )
                for row in frame.iter_rows():
                    register(row)
                if resource_check is not None and leaf_number % 32 == 0:
                    resource_check(
                        f"evaluation:{analysis_profile}:detector:{detector}:"
                        f"leaf-{leaf_number}:groups-{len(members_by_source)}"
                    )
        except LexicalExperimentError:
            raise
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise LexicalExperimentError(f"could not stream detector rankings: {exc}") from exc
    else:
        ranking_frame = _load_ranking_frames(
            ranking_source,
            experiment_run_id=experiment_run_id,
            query_passage_ids=query_passage_ids,
            detectors=(detector,),
            allow_empty=True,
            experiment_scope=experiment_scope,
            analysis_profile=analysis_profile,
        )
        for row in ranking_frame.select(*columns).iter_rows():
            register(row)

    scored_by_source: dict[tuple[str, str, str], tuple[tuple[str, float], ...]] = {}
    targets_by_source: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for key in sorted(members_by_source):
        members = tuple(members_by_source[key])
        if members != tuple(sorted(members, key=lambda item: (item[0], item[1]))):
            raise LexicalExperimentError("directional ranking rows are not canonically ordered")
        targets = tuple(target_id for _, target_id, _ in members)
        if len(targets) != len(set(targets)):
            raise LexicalExperimentError(
                "directional rankings contain duplicate query/target/detector rows"
            )
        targets_by_source[key] = targets
        scored_by_source[key] = tuple((target_id, score) for _, target_id, score in members)
    output: dict[str, tuple[str, ...]] = {}
    for query in queries:
        source_passage_id = source_passage_ids.get(query.query_id)
        representation_id = representation_ids.get(query.corpus_pair)
        if source_passage_id is None or representation_id is None:
            raise LexicalExperimentError("benchmark query lacks governed ranking identity")
        output[query.query_id] = targets_by_source.get(
            (query.corpus_pair, representation_id, source_passage_id),
            (),
        )
    return output, scored_by_source


@dataclass(frozen=True, slots=True)
class _IndexedQueryView(Sequence[Tier3EvaluationQuery]):
    """Compact shared-query view backed by unsigned 32-bit positions."""

    source: Sequence[Tier3EvaluationQuery]
    positions: array[int]

    def __len__(self) -> int:
        return len(self.positions)

    @overload
    def __getitem__(self, index: int) -> Tier3EvaluationQuery: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Tier3EvaluationQuery]: ...

    def __getitem__(
        self, index: int | slice
    ) -> Tier3EvaluationQuery | Sequence[Tier3EvaluationQuery]:
        if isinstance(index, slice):
            return tuple(self.source[position] for position in self.positions[index])
        return self.source[int(self.positions[index])]

    def __iter__(self) -> Iterator[Tier3EvaluationQuery]:
        return (self.source[position] for position in self.positions)

    @property
    def position_storage_bytes(self) -> int:
        """Return the exact compact index-buffer size for bounded-memory tests."""

        return len(self.positions) * self.positions.itemsize


@dataclass(frozen=True, slots=True)
class _EvaluationGroup:
    analysis_profile: AnalysisProfile
    corpus_pair: str
    stratum_dimension: StratumDimension
    stratum_value: str
    queries: Sequence[Tier3EvaluationQuery]
    preaggregated_excluded_queries: int = 0

    @property
    def split_strategy(self) -> str:
        if self.stratum_dimension == "split_strategy":
            return self.stratum_value
        if self.stratum_dimension == "split_strategy_partition":
            return self.stratum_value.split("|", maxsplit=1)[0]
        return "all_strategies"

    @property
    def partition(self) -> str:
        if self.stratum_dimension == "partition":
            return self.stratum_value
        if self.stratum_dimension == "split_strategy_partition":
            return self.stratum_value.split("|", maxsplit=1)[1]
        return "all_partitions"

    @property
    def mapping_status(self) -> str:
        if self.stratum_dimension == "mapping_status":
            return self.stratum_value
        if self.stratum_dimension == "corpus_pair_mapping_status":
            return self.stratum_value.rsplit("|", maxsplit=1)[1]
        return "all_eligible"

    @property
    def vote_stratum(self) -> str:
        return self.stratum_value if self.stratum_dimension == "vote_stratum" else "all_votes"


def _required_stratum_values(
    dimension: StratumDimension,
    members: Sequence[Tier3EvaluationQuery],
    *,
    analysis_profile: AnalysisProfile,
    corpus_pair: str,
    split_strategies: Sequence[str],
    mapping_statuses: Sequence[str],
) -> tuple[str, ...]:
    values = {_stratum_value(query, dimension) for query in members}
    if dimension == "analysis_profile":
        values.add(analysis_profile)
    elif dimension == "corpus_pair":
        values.add(corpus_pair)
    elif dimension == "mapping_status":
        values.update(mapping_statuses)
    elif dimension == "split_strategy":
        values.update(split_strategies)
    elif dimension == "partition":
        values.add("test")
    elif dimension == "split_strategy_partition":
        values.update(f"{strategy}|test" for strategy in split_strategies)
    elif dimension == "vote_stratum":
        values.update(GOVERNED_VOTE_STRATA)
    elif dimension == "disputed_passage_status":
        values.update(("disputed", "not_disputed"))
    elif dimension == "reference_gap_status":
        values.update(("reference_gap", "no_reference_gap"))
    elif dimension == "corpus_pair_mapping_status":
        values.update(f"{corpus_pair}|{status}" for status in mapping_statuses)
    return tuple(sorted(values))


def _evaluation_groups(
    queries: Sequence[Tier3EvaluationQuery],
    *,
    analysis_profile: AnalysisProfile,
    corpus_pairs: Sequence[str],
    split_strategies: Sequence[str],
    mapping_statuses: Sequence[str],
    excluded_facts: Sequence[_ExcludedEvaluationFact],
    resource_check: ResourceCheck | None = None,
) -> tuple[_EvaluationGroup, ...]:
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:groups:reserve-corpus-index-{len(queries)}",
            estimated_additional_bytes=(len(queries) * GROUP_POSITION_RESERVATION_BYTES),
        )
    if len(queries) > (1 << 32) - 1:
        raise LexicalExperimentError("evaluation query count exceeds compact index capacity")
    by_corpus_pair: dict[str, array[int]] = defaultdict(lambda: array("I"))
    for position, query in enumerate(queries):
        if query.analysis_profile != analysis_profile:
            raise LexicalExperimentError("evaluation queries mix analysis profiles")
        if query.corpus_pair in corpus_pairs:
            by_corpus_pair[query.corpus_pair].append(position)
    groups: list[_EvaluationGroup] = []
    for corpus_pair in corpus_pairs:
        member_positions = by_corpus_pair.get(corpus_pair, array("I"))
        if any(
            queries[first].query_id > queries[second].query_id
            for first, second in pairwise(member_positions)
        ):
            member_positions = array(
                "I",
                sorted(member_positions, key=lambda position: queries[position].query_id),
            )
        members = _IndexedQueryView(queries, member_positions)
        groups.append(
            _EvaluationGroup(
                analysis_profile=analysis_profile,
                corpus_pair=corpus_pair,
                stratum_dimension="global",
                stratum_value="all",
                queries=members,
            )
        )
        for dimension in REQUIRED_STRATUM_DIMENSIONS:
            if resource_check is not None:
                resource_check(
                    f"evaluation:{analysis_profile}:groups:reserve:{corpus_pair}:"
                    f"{dimension}:{len(member_positions)}",
                    estimated_additional_bytes=(
                        len(member_positions) * GROUP_POSITION_RESERVATION_BYTES
                    ),
                )
            members_by_value: dict[str, array[int]] = defaultdict(lambda: array("I"))
            for position in member_positions:
                query = queries[position]
                members_by_value[_stratum_value(query, dimension)].append(position)
            for value in _required_stratum_values(
                dimension,
                members,
                analysis_profile=analysis_profile,
                corpus_pair=corpus_pair,
                split_strategies=split_strategies,
                mapping_statuses=mapping_statuses,
            ):
                groups.append(
                    _EvaluationGroup(
                        analysis_profile=analysis_profile,
                        corpus_pair=corpus_pair,
                        stratum_dimension=dimension,
                        stratum_value=value,
                        queries=_IndexedQueryView(
                            queries,
                            members_by_value.get(value, array("I")),
                        ),
                    )
                )
            if resource_check is not None:
                resource_check(f"evaluation:{analysis_profile}:groups:{corpus_pair}:{dimension}")
    excluded_by_pair: dict[str, int] = defaultdict(int)
    for fact in excluded_facts:
        if fact.corpus_pair not in corpus_pairs or fact.split_strategy not in split_strategies:
            continue
        excluded_by_pair[fact.corpus_pair] += fact.excluded_query_count
        groups.append(
            _EvaluationGroup(
                analysis_profile=analysis_profile,
                corpus_pair=fact.corpus_pair,
                stratum_dimension="split_strategy_partition",
                stratum_value=f"{fact.split_strategy}|excluded",
                queries=(),
                preaggregated_excluded_queries=fact.excluded_query_count,
            )
        )
    groups.extend(
        _EvaluationGroup(
            analysis_profile=analysis_profile,
            corpus_pair=corpus_pair,
            stratum_dimension="partition",
            stratum_value="excluded",
            queries=(),
            preaggregated_excluded_queries=excluded_query_count,
        )
        for corpus_pair, excluded_query_count in sorted(excluded_by_pair.items())
    )
    if resource_check is not None:
        resource_check(
            f"evaluation:{analysis_profile}:groups:reserve-tuple-{len(groups)}",
            estimated_additional_bytes=len(groups) * 8,
        )
    result = tuple(groups)
    groups.clear()
    if resource_check is not None:
        resource_check(f"evaluation:{analysis_profile}:groups:complete-{len(result)}")
    return result


def _evaluation_exclusion(query: Tier3EvaluationQuery, metric: MetricName) -> str | None:
    if query.exclusion_reason is not None:
        return query.exclusion_reason
    if metric != "coverage" and not query.relevant_passage_ids:
        return "missing_relevance"
    if metric != "coverage" and not query.relationship_ids:
        return "missing_relationship_identity"
    return None


def _query_metric(
    query: Tier3EvaluationQuery,
    ranking: Sequence[str],
    metric: MetricName,
) -> float:
    if metric == "coverage":
        return float(bool(ranking))
    ranked = RankedQuery(
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
    if metric == "recall_at_5":
        return recall_at_k(ranked, 5)
    if metric == "recall_at_10":
        return recall_at_k(ranked, 10)
    if metric == "recall_at_20":
        return recall_at_k(ranked, 20)
    if metric == "mean_reciprocal_rank":
        return reciprocal_rank(ranked)
    if metric == "ndcg_at_20":
        return ndcg_at_k(ranked, 20)
    return precision_at_k(ranked, 10)


def _group_metric_scores(
    group: _EvaluationGroup,
    rankings: Mapping[str, Sequence[str]],
    metric: MetricName,
) -> tuple[tuple[float, ...], Counter[str], int]:
    scores: list[float] = []
    exclusions: Counter[str] = Counter(
        {"governance_excluded": group.preaggregated_excluded_queries}
        if group.preaggregated_excluded_queries
        else {}
    )
    relationship_ids: set[str] = set()
    for query in group.queries:
        reason = _evaluation_exclusion(query, metric)
        if reason is not None:
            exclusions[reason] += 1
            continue
        ranking = rankings.get(query.query_id)
        if ranking is None:
            raise LexicalExperimentError(f"rankings do not cover benchmark query {query.query_id}")
        scores.append(_query_metric(query, ranking, metric))
        relationship_ids.update(query.relationship_ids)
    return tuple(scores), exclusions, len(relationship_ids)


def _bootstrap_bounds(
    scores: Sequence[float],
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float]:
    values = np.asarray(scores, dtype=np.float64)
    if not values.size:
        return 0.0, 0.0
    unique, counts = np.unique(values, return_counts=True)
    if unique.size == 1:
        value = float(unique[0])
        return value, value
    probabilities = counts.astype(np.float64) / values.size
    random_source = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=np.float64)
    chunk_size = max(1, min(iterations, 2_000_000 // max(1, unique.size)))
    for offset in range(0, iterations, chunk_size):
        draws = min(chunk_size, iterations - offset)
        category_counts = random_source.multinomial(
            values.size,
            probabilities,
            size=draws,
        )
        means[offset : offset + draws] = category_counts @ unique / values.size
    bounds = np.quantile(means, (0.025, 0.975), method="linear")
    return float(bounds[0]), float(bounds[1])


type _ScoredSourceRankings = Mapping[tuple[str, str, str], tuple[tuple[str, float], ...]]


def _persisted_directional_score(
    rankings: _ScoredSourceRankings,
    *,
    corpus_pair: str,
    representation_id: str,
    query_passage_id: str,
    target_passage_ids: Sequence[str],
) -> float:
    target_set = set(target_passage_ids)
    if not target_set:
        return 0.0
    return max(
        (
            score
            for target_id, score in rankings.get(
                (corpus_pair, representation_id, query_passage_id), ()
            )
            if target_id in target_set
        ),
        default=0.0,
    )


def _positive_relationship_scores(
    queries: Sequence[Tier3EvaluationQuery],
    *,
    source_passage_ids: Mapping[str, str],
    representation_ids: Mapping[str, str],
    rankings: _ScoredSourceRankings,
) -> dict[tuple[str, str, str], tuple[float, ...]]:
    grouped: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    for query in queries:
        source_passage_id = source_passage_ids[query.query_id]
        score = _persisted_directional_score(
            rankings,
            corpus_pair=query.corpus_pair,
            representation_id=representation_ids[query.corpus_pair],
            query_passage_id=source_passage_id,
            target_passage_ids=tuple(query.relevant_passage_ids),
        )
        key = (query.corpus_pair, query.split_strategy, query.partition)
        for relationship_id in query.relationship_ids:
            grouped[key][relationship_id] = max(
                grouped[key].get(relationship_id, 0.0),
                score,
            )
    return {
        key: tuple(score for _, score in sorted(relationship_scores.items()))
        for key, relationship_scores in grouped.items()
    }


def _presumed_negative_scores(
    presumed_negatives: Sequence[_PresumedNegativePair],
    *,
    representation_ids: Mapping[str, str],
    rankings: _ScoredSourceRankings,
) -> dict[tuple[str, str, str], tuple[float, ...]]:
    grouped: dict[tuple[str, str, str], list[tuple[str, float]]] = defaultdict(list)
    for pair in presumed_negatives:
        representation_id = representation_ids[pair.corpus_pair]
        forward = _persisted_directional_score(
            rankings,
            corpus_pair=pair.corpus_pair,
            representation_id=representation_id,
            query_passage_id=pair.passage_a_id,
            target_passage_ids=(pair.passage_b_id,),
        )
        reverse = _persisted_directional_score(
            rankings,
            corpus_pair=pair.corpus_pair,
            representation_id=representation_id,
            query_passage_id=pair.passage_b_id,
            target_passage_ids=(pair.passage_a_id,),
        )
        grouped[(pair.corpus_pair, pair.split_strategy, pair.partition)].append(
            (pair.contrastive_id, max(forward, reverse))
        )
    return {key: tuple(score for _, score in sorted(scores)) for key, scores in grouped.items()}


def _positive_auroc_contributions(
    positive_scores: Sequence[float],
    negative_scores: Sequence[float],
) -> tuple[float, ...]:
    if not positive_scores or not negative_scores:
        return ()
    negatives = np.sort(np.asarray(negative_scores, dtype=np.float64))
    output: list[float] = []
    for score in positive_scores:
        below = int(np.searchsorted(negatives, score, side="left"))
        at_or_below = int(np.searchsorted(negatives, score, side="right"))
        output.append((below + 0.5 * (at_or_below - below)) / negatives.size)
    return tuple(output)


def _append_presumed_negative_discrimination_rows(
    rows: list[dict[str, object]],
    *,
    detector: str,
    queries: Sequence[Tier3EvaluationQuery],
    source_passage_ids: Mapping[str, str],
    presumed_negatives: Sequence[_PresumedNegativePair],
    scored_rankings: _ScoredSourceRankings,
    analysis_profile: AnalysisProfile,
    representation_ids: Mapping[str, str],
    experiment_run_id: str,
    benchmark_version: str,
    configuration_hash: str,
    preregistration_hash: str,
    bootstrap_seed: int,
    bootstrap_iterations: int,
) -> None:
    if analysis_profile != "edition_complete" or not presumed_negatives:
        return
    positives = _positive_relationship_scores(
        queries,
        source_passage_ids=source_passage_ids,
        representation_ids=representation_ids,
        rankings=scored_rankings,
    )
    negatives = _presumed_negative_scores(
        presumed_negatives,
        representation_ids=representation_ids,
        rankings=scored_rankings,
    )
    for corpus_pair, split_strategy, partition in sorted(negatives):
        positive_scores = positives.get((corpus_pair, split_strategy, partition), ())
        negative_scores = negatives[(corpus_pair, split_strategy, partition)]
        contributions = _positive_auroc_contributions(positive_scores, negative_scores)
        seed = _derived_seed(
            bootstrap_seed,
            preregistration_hash,
            detector,
            PRESUMED_NEGATIVE_BASELINE,
            corpus_pair,
            split_strategy,
            partition,
        )
        interval_low, interval_high = _bootstrap_bounds(
            contributions,
            iterations=bootstrap_iterations,
            seed=seed,
        )
        group = _EvaluationGroup(
            analysis_profile=analysis_profile,
            corpus_pair=corpus_pair,
            stratum_dimension="split_strategy_partition",
            stratum_value=f"{split_strategy}|{partition}",
            queries=(),
        )
        exclusion_reasons = (
            {}
            if contributions
            else {"presumed_negative_discrimination_missing_positive_examples": 1}
        )
        rows.append(
            _evaluation_row(
                experiment_run_id=experiment_run_id,
                detector=detector,
                representation_id=representation_ids[corpus_pair],
                benchmark_version=benchmark_version,
                group=group,
                metric="presumed_negative_auroc",
                k=None,
                value=(math.fsum(contributions) / len(contributions) if contributions else 0.0),
                interval_low=interval_low,
                interval_high=interval_high,
                eligible_query_count=len(positive_scores),
                eligible_relationship_count=len(positive_scores),
                excluded_count=sum(exclusion_reasons.values()),
                exclusion_reasons=exclusion_reasons,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=seed,
                comparison_baseline=PRESUMED_NEGATIVE_BASELINE,
                comparison_count=len(negative_scores),
                notes=(
                    "AUROC compares known Tier 3 relationships with governed unlinked "
                    "contrast pairs. Presumed negatives are not proven nonrelationships; "
                    "a missing persisted directional pair receives score 0."
                ),
            )
        )


_EVALUATION_METRICS: Final[tuple[tuple[MetricName, int | None], ...]] = (
    ("recall_at_5", 5),
    ("recall_at_10", 10),
    ("recall_at_20", 20),
    ("mean_reciprocal_rank", None),
    ("ndcg_at_20", 20),
    ("precision_at_10", 10),
    ("coverage", None),
)


def _evaluation_row(
    *,
    experiment_run_id: str,
    detector: str,
    representation_id: str,
    benchmark_version: str,
    group: _EvaluationGroup,
    metric: str,
    k: int | None,
    value: float,
    interval_low: float,
    interval_high: float,
    eligible_query_count: int,
    eligible_relationship_count: int,
    excluded_count: int,
    exclusion_reasons: Mapping[str, int],
    configuration_hash: str,
    preregistration_hash: str,
    bootstrap_iterations: int,
    bootstrap_seed: int,
    comparison_baseline: str = "none",
    comparison_count: int = 0,
    notes: str = "Tier 3 weak supervision; metrics are not scholarly ground truth.",
) -> dict[str, object]:
    ranking_role = "baseline" if detector in PERSISTED_BASELINES else "system"
    identity = {
        "experiment_run_id": experiment_run_id,
        "detector": detector,
        "representation_id": representation_id,
        "benchmark_version": benchmark_version,
        "analysis_profile": group.analysis_profile,
        "corpus_pair": group.corpus_pair,
        "stratum_dimension": group.stratum_dimension,
        "stratum_value": group.stratum_value,
        "comparison_baseline": comparison_baseline,
        "split_strategy": group.split_strategy,
        "partition": group.partition,
        "mapping_status": group.mapping_status,
        "vote_stratum": group.vote_stratum,
        "metric": metric,
        "k": k,
    }
    return {
        "evaluation_id": f"evaluation_{_sha256_payload(identity)}",
        "experiment_run_id": experiment_run_id,
        "detector": detector,
        "representation_id": representation_id,
        "benchmark_version": benchmark_version,
        "benchmark_tier": 3,
        "label_quality": TIER3_LABEL_QUALITY,
        "analysis_profile": group.analysis_profile,
        "ranking_name": detector,
        "ranking_role": ranking_role,
        "comparison_baseline": comparison_baseline,
        "comparison_count": comparison_count,
        "stratum_dimension": group.stratum_dimension,
        "stratum_value": group.stratum_value,
        "mapping_status": group.mapping_status,
        "corpus_pair": group.corpus_pair,
        "split_strategy": group.split_strategy,
        "partition": group.partition,
        "vote_stratum": group.vote_stratum,
        "metric": metric,
        "k": k,
        "value": value,
        "bootstrap_interval_low": interval_low,
        "bootstrap_interval_high": interval_high,
        "bootstrap_iterations": bootstrap_iterations,
        "bootstrap_seed": bootstrap_seed,
        "eligible_query_count": eligible_query_count,
        "eligible_relationship_count": eligible_relationship_count,
        "excluded_count": excluded_count,
        "exclusion_reasons_json": _canonical_json(dict(sorted(exclusion_reasons.items()))),
        "config_hash": configuration_hash,
        "preregistration_hash": preregistration_hash,
        "frozen_before_test": True,
        "notes": notes,
    }


def _scientific_gate(
    rows: Sequence[Mapping[str, object]],
    *,
    config: LexicalConfig,
) -> tuple[ScientificGateStatus, tuple[ScientificGateDetail, ...]]:
    details: list[ScientificGateDetail] = []
    eligible_statuses: list[PairGateStatus] = []

    def match(corpus_pair: str, detector: str, metric: str) -> Mapping[str, object] | None:
        matches = [
            row
            for row in rows
            if row["corpus_pair"] == corpus_pair
            and row["analysis_profile"] == "edition_complete"
            and row["detector"] == detector
            and row["metric"] == metric
            and row["stratum_dimension"] == "split_strategy_partition"
            and row["stratum_value"] == "held_out_genre|test"
            and row["split_strategy"] == "held_out_genre"
            and row["partition"] == "test"
            and row["mapping_status"] == "all_eligible"
            and row["vote_stratum"] == "all_votes"
        ]
        if len(matches) > 1:
            raise LexicalExperimentError("scientific gate has duplicate aggregate rows")
        return matches[0] if matches else None

    for corpus_pair in PRIMARY_CORPUS_PAIRS:
        composite = match(corpus_pair, COMPOSITE_DETECTOR, "recall_at_20")
        random = match(corpus_pair, "random", "recall_at_20")
        overlap = match(corpus_pair, "unweighted_overlap", "recall_at_20")
        difference_random = match(
            corpus_pair,
            COMPOSITE_DETECTOR,
            "recall_at_20_difference_vs_random",
        )
        difference_overlap = match(
            corpus_pair,
            COMPOSITE_DETECTOR,
            "recall_at_20_difference_vs_unweighted_overlap",
        )
        evidence = (composite, random, overlap, difference_random, difference_overlap)
        if any(row is None for row in evidence):
            details.append(
                ScientificGateDetail(
                    corpus_pair=corpus_pair,
                    status="missing",
                    eligible_query_count=0,
                    eligible_relationship_count=0,
                    recall_at_20=None,
                    random_recall_at_20=None,
                    unweighted_overlap_recall_at_20=None,
                    difference_vs_random_interval_low=None,
                    difference_vs_unweighted_overlap_interval_low=None,
                    reason="held-out-genre test evidence is missing",
                )
            )
            eligible_statuses.append("missing")
            continue
        composite_row = cast(Mapping[str, object], composite)
        random_row = cast(Mapping[str, object], random)
        overlap_row = cast(Mapping[str, object], overlap)
        random_difference_row = cast(Mapping[str, object], difference_random)
        overlap_difference_row = cast(Mapping[str, object], difference_overlap)
        query_count = int(str(composite_row["eligible_query_count"]))
        relationship_count = int(str(composite_row["eligible_relationship_count"]))
        if (
            query_count < config.benchmark_evaluation.minimum_eligible_queries_per_primary_stratum
            or relationship_count
            < config.benchmark_evaluation.minimum_eligible_relationships_per_primary_stratum
        ):
            status: PairGateStatus = "insufficient_data_no_claim"
            reason = "below the frozen eligible-query or eligible-relationship minimum"
        else:
            passes = (
                float(str(composite_row["value"])) > float(str(random_row["value"]))
                and float(str(composite_row["value"])) > float(str(overlap_row["value"]))
                and float(str(random_difference_row["value"])) > 0.0
                and float(str(random_difference_row["bootstrap_interval_low"])) > 0.0
                and float(str(overlap_difference_row["value"])) > 0.0
                and float(str(overlap_difference_row["bootstrap_interval_low"])) > 0.0
            )
            status = "passed" if passes else "failed"
            reason = (
                "strict paired-bootstrap recovery gate passed"
                if passes
                else "composite recovery lacks strict positive separation from both baselines"
            )
        details.append(
            ScientificGateDetail(
                corpus_pair=corpus_pair,
                status=status,
                eligible_query_count=query_count,
                eligible_relationship_count=relationship_count,
                recall_at_20=float(str(composite_row["value"])),
                random_recall_at_20=float(str(random_row["value"])),
                unweighted_overlap_recall_at_20=float(str(overlap_row["value"])),
                difference_vs_random_interval_low=float(
                    str(random_difference_row["bootstrap_interval_low"])
                ),
                difference_vs_unweighted_overlap_interval_low=float(
                    str(overlap_difference_row["bootstrap_interval_low"])
                ),
                reason=reason,
            )
        )
        eligible_statuses.append(status)
    claim_statuses = [status for status in eligible_statuses if status in {"passed", "failed"}]
    if not claim_statuses:
        overall: ScientificGateStatus = "insufficient_data"
    elif all(status == "passed" for status in claim_statuses):
        overall = "passed"
    else:
        overall = "failed"
    return overall, tuple(details)


type _RecallGroupFact = tuple[tuple[float, ...], Counter[str], int]


def _append_precomputed_evaluation_rows(
    rows: list[dict[str, object]],
    *,
    detector: str,
    table: _PrecomputedMetricTable,
    groups: Sequence[_EvaluationGroup],
    representation_ids: Mapping[str, str],
    experiment_run_id: str,
    benchmark_version: str,
    configuration_hash: str,
    preregistration_hash: str,
    bootstrap_seed: int,
    bootstrap_iterations: int,
) -> tuple[_RecallGroupFact, ...]:
    recall_facts: list[_RecallGroupFact] = []
    for group in groups:
        representation_id = representation_ids[group.corpus_pair]
        for metric_index, (metric, k) in enumerate(_EVALUATION_METRICS):
            scores: list[float] = []
            exclusions: Counter[str] = Counter(
                {"governance_excluded": group.preaggregated_excluded_queries}
                if group.preaggregated_excluded_queries
                else {}
            )
            relationship_ids: set[str] = set()
            for query in group.queries:
                reason = _evaluation_exclusion(query, metric)
                if reason is not None:
                    exclusions[reason] += 1
                    continue
                position = table.query_positions.get(query.query_id)
                if position is None:
                    raise LexicalExperimentError(
                        f"precomputed baseline omits query {query.query_id}"
                    )
                scores.append(float(table.values[position, metric_index]))
                relationship_ids.update(query.relationship_ids)
            score_values = tuple(scores)
            seed = _derived_seed(
                bootstrap_seed,
                preregistration_hash,
                detector,
                group.analysis_profile,
                group.corpus_pair,
                group.stratum_dimension,
                group.stratum_value,
                group.split_strategy,
                group.partition,
                group.mapping_status,
                group.vote_stratum,
                metric,
            )
            interval_low, interval_high = _bootstrap_bounds(
                score_values,
                iterations=bootstrap_iterations,
                seed=seed,
            )
            rows.append(
                _evaluation_row(
                    experiment_run_id=experiment_run_id,
                    detector=detector,
                    representation_id=representation_id,
                    benchmark_version=benchmark_version,
                    group=group,
                    metric=metric,
                    k=k,
                    value=(math.fsum(score_values) / len(score_values) if score_values else 0.0),
                    interval_low=interval_low,
                    interval_high=interval_high,
                    eligible_query_count=len(score_values),
                    eligible_relationship_count=len(relationship_ids),
                    excluded_count=sum(exclusions.values()),
                    exclusion_reasons=exclusions,
                    configuration_hash=configuration_hash,
                    preregistration_hash=preregistration_hash,
                    bootstrap_iterations=bootstrap_iterations,
                    bootstrap_seed=seed,
                )
            )
            if metric == "recall_at_20":
                recall_facts.append((score_values, exclusions, len(relationship_ids)))
    if len(recall_facts) != len(groups):
        raise LexicalExperimentError("Recall@20 aggregation does not cover every group")
    return tuple(recall_facts)


def _append_absolute_evaluation_rows(
    rows: list[dict[str, object]],
    *,
    detector: str,
    rankings: Mapping[str, Sequence[str]],
    groups: Sequence[_EvaluationGroup],
    representation_ids: Mapping[str, str],
    experiment_run_id: str,
    benchmark_version: str,
    configuration_hash: str,
    preregistration_hash: str,
    bootstrap_seed: int,
    bootstrap_iterations: int,
) -> tuple[_RecallGroupFact, ...]:
    recall_facts: list[_RecallGroupFact] = []
    for group in groups:
        representation_id = representation_ids[group.corpus_pair]
        for metric, k in _EVALUATION_METRICS:
            scores, exclusions, relationship_count = _group_metric_scores(
                group,
                rankings,
                metric,
            )
            seed = _derived_seed(
                bootstrap_seed,
                preregistration_hash,
                detector,
                group.analysis_profile,
                group.corpus_pair,
                group.stratum_dimension,
                group.stratum_value,
                group.split_strategy,
                group.partition,
                group.mapping_status,
                group.vote_stratum,
                metric,
            )
            interval_low, interval_high = _bootstrap_bounds(
                scores,
                iterations=bootstrap_iterations,
                seed=seed,
            )
            rows.append(
                _evaluation_row(
                    experiment_run_id=experiment_run_id,
                    detector=detector,
                    representation_id=representation_id,
                    benchmark_version=benchmark_version,
                    group=group,
                    metric=metric,
                    k=k,
                    value=math.fsum(scores) / len(scores) if scores else 0.0,
                    interval_low=interval_low,
                    interval_high=interval_high,
                    eligible_query_count=len(scores),
                    eligible_relationship_count=relationship_count,
                    excluded_count=sum(exclusions.values()),
                    exclusion_reasons=exclusions,
                    configuration_hash=configuration_hash,
                    preregistration_hash=preregistration_hash,
                    bootstrap_iterations=bootstrap_iterations,
                    bootstrap_seed=seed,
                )
            )
            if metric == "recall_at_20":
                recall_facts.append((scores, exclusions, relationship_count))
    if len(recall_facts) != len(groups):
        raise LexicalExperimentError("Recall@20 aggregation does not cover every group")
    return tuple(recall_facts)


def _append_paired_evaluation_rows(
    rows: list[dict[str, object]],
    *,
    detector: str,
    method_recall: Sequence[_RecallGroupFact],
    baseline_recall: Mapping[str, Sequence[_RecallGroupFact]],
    groups: Sequence[_EvaluationGroup],
    representation_ids: Mapping[str, str],
    experiment_run_id: str,
    benchmark_version: str,
    configuration_hash: str,
    preregistration_hash: str,
    bootstrap_seed: int,
    bootstrap_iterations: int,
) -> None:
    for group_index, group in enumerate(groups):
        method_scores, method_exclusions, relationship_count = method_recall[group_index]
        for baseline in ("random", "unweighted_overlap"):
            baseline_scores = baseline_recall[baseline][group_index][0]
            if len(method_scores) != len(baseline_scores):
                raise LexicalExperimentError(
                    "paired evaluation rows do not share the same eligible queries"
                )
            differences = tuple(
                method - comparison
                for method, comparison in zip(
                    method_scores,
                    baseline_scores,
                    strict=True,
                )
            )
            metric_name = f"recall_at_20_difference_vs_{baseline}"
            seed = _derived_seed(
                bootstrap_seed,
                preregistration_hash,
                detector,
                baseline,
                group.analysis_profile,
                group.corpus_pair,
                group.stratum_dimension,
                group.stratum_value,
                group.split_strategy,
                group.partition,
                group.mapping_status,
                group.vote_stratum,
                "paired-recall-at-20",
            )
            interval_low, interval_high = _bootstrap_bounds(
                differences,
                iterations=bootstrap_iterations,
                seed=seed,
            )
            rows.append(
                _evaluation_row(
                    experiment_run_id=experiment_run_id,
                    detector=detector,
                    representation_id=representation_ids[group.corpus_pair],
                    benchmark_version=benchmark_version,
                    group=group,
                    metric=metric_name,
                    k=20,
                    value=(math.fsum(differences) / len(differences) if differences else 0.0),
                    interval_low=interval_low,
                    interval_high=interval_high,
                    eligible_query_count=len(differences),
                    eligible_relationship_count=relationship_count,
                    excluded_count=sum(method_exclusions.values()),
                    exclusion_reasons=method_exclusions,
                    configuration_hash=configuration_hash,
                    preregistration_hash=preregistration_hash,
                    bootstrap_iterations=bootstrap_iterations,
                    bootstrap_seed=seed,
                    comparison_baseline=baseline,
                    comparison_count=len(baseline_scores),
                )
            )


def _validate_evaluation_scope(scope: Tier3EvaluationScope) -> tuple[str, ...]:
    if not scope.experiment_scope:
        raise LexicalExperimentError("evaluation experiment scope cannot be empty")
    if scope.analysis_profile not in {"edition_complete", "critical_core"}:
        raise LexicalExperimentError(
            f"unsupported evaluation analysis profile: {scope.analysis_profile}"
        )
    representation_pairs = set(scope.representation_ids)
    sequence_pairs = set(scope.sequences_by_corpus_pair)
    if (
        not representation_pairs
        or not representation_pairs.issubset(GOVERNED_CORPUS_PAIRS)
        or not representation_pairs.issubset(sequence_pairs)
    ):
        raise LexicalExperimentError(
            f"{scope.analysis_profile} evaluation requires matching governed sequence and "
            "representation strata"
        )
    for corpus_pair in representation_pairs:
        if not scope.representation_ids[corpus_pair]:
            raise LexicalExperimentError(
                f"{scope.analysis_profile}/{corpus_pair} representation ID is empty"
            )
        sequences = tuple(scope.sequences_by_corpus_pair[corpus_pair])
        if not sequences:
            raise LexicalExperimentError(
                f"{scope.analysis_profile}/{corpus_pair} evaluation sequences are empty"
            )
        if any(sequence.analysis_profile != scope.analysis_profile for sequence in sequences):
            raise LexicalExperimentError(
                f"{scope.analysis_profile}/{corpus_pair} sequences mix analysis profiles"
            )
    return tuple(pair for pair in GOVERNED_CORPUS_PAIRS if pair in representation_pairs)


def _evaluate_tier3_scope(
    scope: Tier3EvaluationScope,
    *,
    config: LexicalConfig,
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    benchmark_database_path: str | Path,
    book_genres: Mapping[str, str],
    resource_check: ResourceCheck | None,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path | None,
    checkpoint: _Tier3EvaluationCheckpoint | None,
) -> tuple[str, list[pl.DataFrame]]:
    corpus_pairs = _validate_evaluation_scope(scope)
    if resource_check is not None:
        resource_check(f"evaluation:{scope.analysis_profile}:scope:start")
    ranking_strata = _ranking_strata(
        scope.directional_rankings,
        experiment_run_id=experiment_run_id,
        experiment_scope=scope.experiment_scope,
        analysis_profile=scope.analysis_profile,
    )
    observed_ranking_pairs: set[str] = set()
    for corpus_pair, representation_id, _ in ranking_strata:
        if scope.representation_ids.get(corpus_pair) != representation_id:
            raise LexicalExperimentError(
                f"{scope.analysis_profile} ranking representation is not governed for {corpus_pair}"
            )
        observed_ranking_pairs.add(corpus_pair)
    if observed_ranking_pairs != set(corpus_pairs):
        raise LexicalExperimentError(
            f"{scope.analysis_profile} ranking corpus-pair strata do not match its scope"
        )
    if resource_check is not None:
        resource_check(f"evaluation:{scope.analysis_profile}:rankings:validated")
    benchmark_version, queries, source_passage_ids, excluded_facts = _load_tier3_queries(
        Path(benchmark_database_path),
        analysis_profile=scope.analysis_profile,
        corpus_pairs=corpus_pairs,
        sequences_by_corpus_pair=scope.sequences_by_corpus_pair,
        book_genres=book_genres,
        config=config,
        resource_check=resource_check,
        duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
        duckdb_temp_directory=duckdb_temp_directory,
    )
    systems = (*config.enabled_detectors, COMPOSITE_DETECTOR)
    if resource_check is not None:
        resource_check(f"evaluation:{scope.analysis_profile}:query_ids:before")
    ranked_query_ids = tuple(sorted(set(source_passage_ids.values())))
    presumed_negatives = _load_presumed_negative_pairs(
        Path(benchmark_database_path),
        benchmark_version=benchmark_version,
        analysis_profile=scope.analysis_profile,
        corpus_pairs=corpus_pairs,
        split_strategies=config.benchmark_evaluation.split_strategies,
        resource_check=resource_check,
        duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
        duckdb_temp_directory=duckdb_temp_directory,
    )
    detector_query_ids = tuple(
        sorted(
            set(ranked_query_ids)
            .union(pair.passage_a_id for pair in presumed_negatives)
            .union(pair.passage_b_id for pair in presumed_negatives)
        )
    )
    if resource_check is not None:
        resource_check(
            f"evaluation:{scope.analysis_profile}:query_ids:complete-{len(detector_query_ids)}"
        )
        resource_check(f"evaluation:{scope.analysis_profile}:candidate_universe:before")
    candidate_universe = _candidate_universe_by_query(
        scope.directional_rankings,
        experiment_run_id=experiment_run_id,
        query_passage_ids=ranked_query_ids,
        detectors=systems,
        maximum_targets_per_query=config.retrieval.candidate_union_k,
        resource_check=resource_check,
        experiment_scope=scope.experiment_scope,
        analysis_profile=scope.analysis_profile,
    )
    if resource_check is not None:
        resource_check(f"evaluation:{scope.analysis_profile}:candidate_universe:complete")
    groups = _evaluation_groups(
        queries,
        analysis_profile=scope.analysis_profile,
        corpus_pairs=corpus_pairs,
        split_strategies=config.benchmark_evaluation.split_strategies,
        mapping_statuses=config.benchmark_evaluation.eligible_mapping_statuses,
        excluded_facts=excluded_facts,
        resource_check=resource_check,
    )
    iterations = config.statistics.bootstrap_iterations
    bootstrap_seed = config.statistics.bootstrap_seed
    frames: list[pl.DataFrame] = []
    baseline_recall: dict[str, tuple[_RecallGroupFact, ...]] = {}
    for baseline in REQUIRED_BASELINES:
        if resource_check is not None:
            resource_check(f"evaluation:{scope.analysis_profile}:baseline:{baseline}")
        completed = (
            checkpoint.load(
                analysis_profile=scope.analysis_profile,
                part_kind="baseline",
                detector=baseline,
            )
            if checkpoint is not None
            else None
        )
        if completed is not None:
            del completed
        table = _precompute_baseline_metrics(
            baseline,
            candidate_universe,
            queries,
            sequences_by_corpus_pair=scope.sequences_by_corpus_pair,
            representation_ids=scope.representation_ids,
            source_passage_ids=source_passage_ids,
            config=config,
        )
        batch_rows: list[dict[str, object]] = []
        recall = _append_precomputed_evaluation_rows(
            batch_rows,
            detector=baseline,
            table=table,
            groups=groups,
            representation_ids=scope.representation_ids,
            experiment_run_id=experiment_run_id,
            benchmark_version=benchmark_version,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            bootstrap_seed=bootstrap_seed,
            bootstrap_iterations=iterations,
        )
        if baseline in {"random", "unweighted_overlap"}:
            baseline_recall[baseline] = recall
        del table
        if (
            checkpoint is None
            or (
                scope.analysis_profile,
                "baseline",
                baseline,
            )
            not in checkpoint._part_paths
        ):
            frame = _typed_frame(batch_rows, EVALUATION_RESULTS_SCHEMA)
            if checkpoint is None:
                frames.append(frame)
            else:
                checkpoint.write(
                    frame,
                    analysis_profile=scope.analysis_profile,
                    part_kind="baseline",
                    detector=baseline,
                )
                del frame
        del batch_rows
        gc.collect()
        if resource_check is not None:
            resource_check(f"evaluation:{scope.analysis_profile}:checkpoint:baseline:{baseline}")
    del candidate_universe
    for detector in systems:
        if resource_check is not None:
            resource_check(f"evaluation:{scope.analysis_profile}:detector:{detector}")
        completed = (
            checkpoint.load(
                analysis_profile=scope.analysis_profile,
                part_kind="detector",
                detector=detector,
            )
            if checkpoint is not None
            else None
        )
        if completed is not None:
            del completed
            gc.collect()
            if resource_check is not None:
                resource_check(
                    f"evaluation:{scope.analysis_profile}:checkpoint:detector:{detector}:reused"
                )
            continue
        rankings, scored_rankings = _detector_rankings_for_queries(
            scope.directional_rankings,
            queries,
            detector=detector,
            experiment_run_id=experiment_run_id,
            query_passage_ids=detector_query_ids,
            maximum_targets_per_query=config.retrieval.persisted_top_k,
            representation_ids=scope.representation_ids,
            source_passage_ids=source_passage_ids,
            resource_check=resource_check,
            experiment_scope=scope.experiment_scope,
            analysis_profile=scope.analysis_profile,
        )
        batch_rows = []
        method_recall = _append_absolute_evaluation_rows(
            batch_rows,
            detector=detector,
            rankings=rankings,
            groups=groups,
            representation_ids=scope.representation_ids,
            experiment_run_id=experiment_run_id,
            benchmark_version=benchmark_version,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            bootstrap_seed=bootstrap_seed,
            bootstrap_iterations=iterations,
        )
        _append_paired_evaluation_rows(
            batch_rows,
            detector=detector,
            method_recall=method_recall,
            baseline_recall=baseline_recall,
            groups=groups,
            representation_ids=scope.representation_ids,
            experiment_run_id=experiment_run_id,
            benchmark_version=benchmark_version,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            bootstrap_seed=bootstrap_seed,
            bootstrap_iterations=iterations,
        )
        _append_presumed_negative_discrimination_rows(
            batch_rows,
            detector=detector,
            queries=queries,
            source_passage_ids=source_passage_ids,
            presumed_negatives=presumed_negatives,
            scored_rankings=scored_rankings,
            analysis_profile=scope.analysis_profile,
            representation_ids=scope.representation_ids,
            experiment_run_id=experiment_run_id,
            benchmark_version=benchmark_version,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            bootstrap_seed=bootstrap_seed,
            bootstrap_iterations=iterations,
        )
        del rankings, scored_rankings, method_recall
        frame = _typed_frame(batch_rows, EVALUATION_RESULTS_SCHEMA)
        if checkpoint is None:
            frames.append(frame)
        else:
            checkpoint.write(
                frame,
                analysis_profile=scope.analysis_profile,
                part_kind="detector",
                detector=detector,
            )
            del frame
        del batch_rows
        gc.collect()
        if resource_check is not None:
            resource_check(f"evaluation:{scope.analysis_profile}:checkpoint:detector:{detector}")
    return benchmark_version, frames


def run_tier3_evaluation_experiment(
    directional_rankings: RankingInput,
    *,
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    representation_ids: Mapping[str, str],
    config: LexicalConfig,
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    benchmark_database_path: str | Path,
    book_genres: Mapping[str, str],
    additional_evaluation_scopes: Sequence[Tier3EvaluationScope] = (),
    resource_check: ResourceCheck | None = None,
    duckdb_memory_limit_bytes: int = DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES,
    duckdb_temp_directory: Path | None = None,
    checkpoint_directory: Path | None = None,
) -> Tier3EvaluationArtifacts:
    """Evaluate transparent rankings across edition-complete and sensitivity scopes."""

    if not experiment_run_id:
        raise LexicalExperimentError("experiment run ID cannot be empty")
    _require_sha256(configuration_hash, label="configuration hash")
    _require_sha256(preregistration_hash, label="preregistration hash")
    scopes = (
        Tier3EvaluationScope(
            analysis_profile="edition_complete",
            directional_rankings=directional_rankings,
            sequences_by_corpus_pair=sequences_by_corpus_pair,
            representation_ids=representation_ids,
        ),
        *tuple(additional_evaluation_scopes),
    )
    profiles = tuple(scope.analysis_profile for scope in scopes)
    if len(profiles) != len(set(profiles)):
        raise LexicalExperimentError("evaluation scopes must have unique analysis profiles")
    checkpoint = (
        _Tier3EvaluationCheckpoint(
            checkpoint_directory,
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
        )
        if checkpoint_directory is not None
        else None
    )
    frames: list[pl.DataFrame] = []
    expected_checkpoint_keys: set[tuple[str, str, str]] = set()
    benchmark_versions: set[str] = set()
    for scope in scopes:
        systems = (*config.enabled_detectors, COMPOSITE_DETECTOR)
        expected_checkpoint_keys.update(
            (scope.analysis_profile, "baseline", baseline) for baseline in REQUIRED_BASELINES
        )
        expected_checkpoint_keys.update(
            (scope.analysis_profile, "detector", detector) for detector in systems
        )
        benchmark_version, scope_frames = _evaluate_tier3_scope(
            scope,
            config=config,
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            benchmark_database_path=benchmark_database_path,
            book_genres=book_genres,
            resource_check=resource_check,
            duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
            duckdb_temp_directory=duckdb_temp_directory,
            checkpoint=checkpoint,
        )
        benchmark_versions.add(benchmark_version)
        frames.extend(scope_frames)
    if len(benchmark_versions) != 1:
        raise LexicalExperimentError("evaluation scopes do not share one benchmark version")
    benchmark_version = next(iter(benchmark_versions))
    if resource_check is not None:
        resource_check("evaluation:checkpoint:assemble:before")
    if checkpoint is not None:
        evaluation_results = checkpoint.assemble(expected_checkpoint_keys)
    else:
        evaluation_results = pl.concat(frames, rechunk=False).sort(
            list(_EVALUATION_SORT_COLUMNS),
            nulls_last=True,
        )
    gate_rows = evaluation_results.filter(
        (pl.col("analysis_profile") == "edition_complete")
        & (pl.col("stratum_dimension") == "split_strategy_partition")
        & (pl.col("stratum_value") == "held_out_genre|test")
        & (pl.col("split_strategy") == "held_out_genre")
        & (pl.col("partition") == "test")
        & (pl.col("mapping_status") == "all_eligible")
        & (pl.col("vote_stratum") == "all_votes")
        & pl.col("detector").is_in([COMPOSITE_DETECTOR, "random", "unweighted_overlap"])
        & pl.col("metric").is_in(
            [
                "recall_at_20",
                "recall_at_20_difference_vs_random",
                "recall_at_20_difference_vs_unweighted_overlap",
            ]
        )
    )
    status, details = _scientific_gate(gate_rows.to_dicts(), config=config)
    if resource_check is not None:
        resource_check(f"evaluation:checkpoint:assemble:complete-{evaluation_results.height}")
    return Tier3EvaluationArtifacts(
        evaluation_results=evaluation_results,
        benchmark_version=benchmark_version,
        scientific_gate_status=status,
        scientific_gate_details=details,
    )


def run_lexical_experiment(
    candidates: Mapping[str, CandidateAggregate],
    *,
    sequences_by_corpus_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    representation_ids: Mapping[str, str],
    directional_rankings: RankingInput,
    config: LexicalConfig,
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    benchmark_database_path: str | Path,
    book_genres: Mapping[str, str],
    additional_evaluation_scopes: Sequence[Tier3EvaluationScope] = (),
    resource_check: ResourceCheck | None = None,
    duckdb_memory_limit_bytes: int = DEFAULT_EXPERIMENT_DUCKDB_MEMORY_BYTES,
    duckdb_temp_directory: Path | None = None,
) -> LexicalExperimentArtifacts:
    """Run and return all production Milestone 7 calibration/evaluation artifacts."""

    detectors_by_pair = governed_detectors_by_corpus_pair(
        directional_rankings,
        experiment_run_id=experiment_run_id,
        representation_ids=representation_ids,
    )
    evaluation = run_tier3_evaluation_experiment(
        directional_rankings,
        sequences_by_corpus_pair=sequences_by_corpus_pair,
        representation_ids=representation_ids,
        config=config,
        experiment_run_id=experiment_run_id,
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        benchmark_database_path=benchmark_database_path,
        book_genres=book_genres,
        additional_evaluation_scopes=additional_evaluation_scopes,
        resource_check=resource_check,
        duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
        duckdb_temp_directory=duckdb_temp_directory,
    )
    calibration = run_null_calibration_experiment(
        candidates,
        sequences_by_corpus_pair=sequences_by_corpus_pair,
        representation_ids=representation_ids,
        config=config,
        experiment_run_id=experiment_run_id,
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        book_genres=book_genres,
        detectors_by_corpus_pair=detectors_by_pair,
        resource_check=resource_check,
    )
    return combine_lexical_experiment_artifacts(calibration, evaluation)


def governed_detectors_by_corpus_pair(
    directional_rankings: RankingInput,
    *,
    experiment_run_id: str,
    representation_ids: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """Reconcile primary persisted detector strata with governed representations."""

    strata = _ranking_strata(
        directional_rankings,
        experiment_run_id=experiment_run_id,
    )
    detectors_by_pair: dict[str, list[str]] = defaultdict(list)
    for corpus_pair, representation_id, detector in strata:
        expected_representation = representation_ids.get(corpus_pair)
        if expected_representation != representation_id:
            raise LexicalExperimentError(
                f"persisted ranking representation is not governed for {corpus_pair}"
            )
        detectors_by_pair[corpus_pair].append(detector)
    if set(detectors_by_pair) != set(representation_ids):
        raise LexicalExperimentError(
            "persisted ranking corpus-pair strata do not match governed representations"
        )
    return {pair: tuple(detectors) for pair, detectors in detectors_by_pair.items()}


def combine_lexical_experiment_artifacts(
    calibration: NullCalibrationArtifacts,
    evaluation: Tier3EvaluationArtifacts,
) -> LexicalExperimentArtifacts:
    """Combine independently materialized calibration and evaluation outputs."""

    return LexicalExperimentArtifacts(
        null_replicate_summaries=calibration.null_replicate_summaries,
        threshold_calibration=calibration.threshold_calibration,
        evaluation_results=evaluation.evaluation_results,
        selected_calibration=calibration.selected_calibration,
        candidate_samples=calibration.candidate_samples,
        benchmark_version=evaluation.benchmark_version,
        scientific_gate_status=evaluation.scientific_gate_status,
        scientific_gate_details=evaluation.scientific_gate_details,
    )
