"""Deterministic candidate evidence, statistics, and unreviewed queue materialization."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast

import duckdb
import polars as pl

from echoes.lexical.config import LexicalConfig
from echoes.lexical.detectors import (
    bm25_score,
    jaccard_similarity,
    longest_common_subsequence,
    tfidf_cosine_similarity,
    weighted_jaccard_similarity,
    weighted_sequence_alignment,
)
from echoes.lexical.models import (
    ABLATION_RESULTS_SCHEMA,
    CANDIDATE_DETECTOR_SCORES_SCHEMA,
    CANDIDATE_EVIDENCE_SCHEMA,
    CANDIDATE_PAIRS_SCHEMA,
    CANDIDATE_REVIEW_QUEUE_SCHEMA,
    SHARED_EVIDENCE_SCHEMA,
)
from echoes.lexical.resources import (
    MEBIBYTE,
    LexicalResourceError,
    configure_duckdb_connection,
)
from echoes.lexical.retrieval import (
    DETECTOR_FAMILIES,
    CandidateAggregate,
    CandidateDirection,
    PhraseAssociationIndex,
    build_phrase_association_index,
)
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence
from echoes.lexical.statistics import benjamini_hochberg, hypergeometric_upper_tail
from echoes.lexical.validation import (
    ablation_family_digest,
    ablation_result_digest,
    candidate_evidence_digest,
    detector_trace_digest,
    shared_evidence_digest,
)


class CandidateMaterializationError(RuntimeError):
    """Raised when candidate evidence cannot reproduce from governed inputs."""


class CandidateResourceCheck(Protocol):
    def __call__(self, stage: str, *, estimated_additional_bytes: int = 0) -> None: ...


_ABLATION_NAMES = (
    "remove_tfidf",
    "remove_bm25",
    "remove_rare_evidence",
    "remove_phrase_evidence",
    "remove_ordered_sequence",
    "remove_formulaic_penalty",
    "remove_local_context_penalty",
    "remove_all_english_derived_features",
)

_CANDIDATE_OUTPUT_TARGET_BYTES = 256 * MEBIBYTE
_CANDIDATE_OUTPUT_ROW_BYTES = 4096
_CANDIDATE_FRAME_MULTIPLIER = 3


@dataclass(frozen=True, slots=True)
class KnownPair:
    """Tier 3 OpenBible representation facts for one mapped unordered pair."""

    relationship_ids: tuple[str, ...]
    highest_vote: int
    mapping_quality: str


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    """Frozen null-calibrated review threshold for one corpus pair."""

    score_threshold: float
    estimated_empirical_fdr: float
    empirical_rate: float
    both_null_families_present: bool


@dataclass(frozen=True, slots=True)
class CandidateEvidenceContext:
    """Read-only facts needed to reproduce all candidate evidence."""

    experiment_run_id: str
    configuration_hash: str
    sequences: Mapping[str, PassageLexicalSequence]
    feature_statistics: Mapping[tuple[str, str, str], tuple[str, int, int, bool, bool]]
    feature_passages: Mapping[tuple[str, str, str], tuple[str, ...]]
    representation_ids: Mapping[str, str]
    known_pairs: Mapping[tuple[str, str], KnownPair]
    calibration: Mapping[str, CalibrationSelection]
    config: LexicalConfig
    feature_population_counts: Mapping[tuple[str, str], int] = field(init=False, repr=False)
    document_counts_by_namespace: Mapping[str, int] = field(init=False, repr=False)
    representation_statistics: Mapping[str, tuple[int, float]] = field(init=False, repr=False)
    book_ordinals: Mapping[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        populations = Counter(
            (namespace, family) for namespace, family, _ in self.feature_statistics
        )
        ordered = sorted(self.sequences.values(), key=lambda item: item.passage_id)
        hebrew = [item for item in ordered if item.corpus == "hebrew"]
        greek = [item for item in ordered if item.corpus == "greek"]

        def statistics(
            sequences: Sequence[PassageLexicalSequence], family: str
        ) -> tuple[int, float]:
            if not sequences:
                return 0, 0.0
            lengths = [len(item.values(family)) for item in sequences]
            return len(sequences), math.fsum(lengths) / len(lengths)

        object.__setattr__(self, "feature_population_counts", dict(populations))
        object.__setattr__(
            self,
            "document_counts_by_namespace",
            {"en": len(ordered), "hb": len(hebrew), "gk": len(greek)},
        )
        object.__setattr__(
            self,
            "representation_statistics",
            {
                "hb_hb": statistics(hebrew, "lemma"),
                "gnt_gnt": statistics(greek, "lemma"),
                "hb_gnt_english_bridge": statistics(ordered, "english_gloss"),
            },
        )
        object.__setattr__(self, "book_ordinals", _book_ordinals(ordered))


@dataclass(frozen=True, slots=True)
class CandidateArtifactBatch:
    """Bounded candidate artifact frames sharing a candidate-ID range."""

    candidate_pairs: pl.DataFrame
    detector_scores: pl.DataFrame
    candidate_evidence: pl.DataFrame
    shared_evidence: pl.DataFrame
    ablation_results: pl.DataFrame
    queue_candidates: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class SharedSummary:
    """Typed summary of shared source features for one candidate."""

    shared: tuple[str, ...]
    shared_roots: tuple[str, ...]
    shared_surfaces: tuple[str, ...]
    shared_rare: tuple[str, ...]
    shared_rare_roots: tuple[str, ...]
    shared_phrases: tuple[tuple[str, ...], ...]
    shared_root_phrases: tuple[tuple[str, ...], ...]
    shared_skips: tuple[tuple[str, str], ...]
    shared_root_skips: tuple[tuple[str, str], ...]
    formulaic_count: int


@dataclass(frozen=True, slots=True)
class RareRuleResult:
    """Auditable outcome of the conjunctive rare-evidence rule."""

    independent_co_signal_count: int
    passed: bool


def _candidate_output_reservation_bytes(
    candidate: CandidateAggregate,
    context: CandidateEvidenceContext,
) -> int:
    """Bound one candidate's decomposed rows from actual passage feature lengths."""

    passage_a = context.sequences[candidate.passage_a_id]
    passage_b = context.sequences[candidate.passage_b_id]
    shorter_token_count = min(passage_a.token_count, passage_b.token_count)
    shorter_lemma_count = min(len(passage_a.lemma), len(passage_b.lemma))
    shorter_root_count = min(len(passage_a.root), len(passage_b.root))
    base_feature_rows = shorter_token_count * 5
    derived_multiplier = (
        len(context.config.phrases.lemma_ngram_sizes) + context.config.skipgrams.maximum_gap
    )
    derived_rows = (shorter_lemma_count + shorter_root_count) * derived_multiplier
    detector_rows = (len(DETECTOR_FAMILIES) + 1) * max(1, len(candidate.directions))
    fixed_rows = 2 + detector_rows + len(context.config.ablations.names) + 4
    estimated_rows = base_feature_rows + derived_rows + fixed_rows
    return max(MEBIBYTE // 2, estimated_rows * _CANDIDATE_OUTPUT_ROW_BYTES)


@dataclass(frozen=True, slots=True)
class CandidatePenaltyState:
    """Frozen penalty inputs and the reconciled adjusted composite."""

    formulaic_fraction: float
    local_context_fraction: float
    short_passage_fraction: float
    adjusted_score: float
    contributions: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class CandidateAblationValue:
    """One candidate-level ablated score and remaining penalty magnitude."""

    score: float
    penalty_magnitude: float


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash_id(prefix: str, value: object) -> str:
    return f"{prefix}_{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def merge_candidate_aggregates(
    batches: Iterable[Sequence[CandidateAggregate]],
) -> dict[str, CandidateAggregate]:
    """Merge bounded directional updates into canonical unordered candidates."""

    merged: dict[str, CandidateAggregate] = {}
    for batch in batches:
        for update in batch:
            current = merged.get(update.candidate_pair_id)
            if current is None:
                current = CandidateAggregate(
                    candidate_pair_id=update.candidate_pair_id,
                    canonical_unordered_pair_id=update.canonical_unordered_pair_id,
                    passage_a_id=update.passage_a_id,
                    passage_b_id=update.passage_b_id,
                    corpus_pair=update.corpus_pair,
                    analysis_profile=update.analysis_profile,
                    granularity=update.granularity,
                )
                merged[update.candidate_pair_id] = current
            elif (
                current.canonical_unordered_pair_id,
                current.passage_a_id,
                current.passage_b_id,
                current.corpus_pair,
                current.analysis_profile,
                current.granularity,
            ) != (
                update.canonical_unordered_pair_id,
                update.passage_a_id,
                update.passage_b_id,
                update.corpus_pair,
                update.analysis_profile,
                update.granularity,
            ):
                raise CandidateMaterializationError(
                    f"candidate identity collision: {update.candidate_pair_id}"
                )
            for direction in update.directions.values():
                current.add_direction(direction)
    return merged


def load_known_pair_index(
    database_path: Path,
    *,
    duckdb_memory_limit_bytes: int = 512 * MEBIBYTE,
    duckdb_temp_directory: Path | None = None,
    resource_check: CandidateResourceCheck | None = None,
) -> dict[tuple[str, str], KnownPair]:
    """Load mapped OpenBible pairs in both directions without treating them as truth."""

    if duckdb_temp_directory is None:
        with TemporaryDirectory(prefix="echoes-known-pairs-") as temporary:
            return load_known_pair_index(
                database_path,
                duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
                duckdb_temp_directory=Path(temporary) / "spill",
                resource_check=resource_check,
            )

    sql = """
        WITH targets AS (
          SELECT e.relationship_id, e.endpoint_side, m.mapping_status,
                 t.target_passage_id
          FROM benchmark_endpoints e
          JOIN benchmark_endpoint_mappings m USING (endpoint_id)
          JOIN benchmark_mapping_target_passages t USING (mapping_id, endpoint_id)
          WHERE m.target_analysis_profile = 'edition_complete'
            AND m.target_granularity = 'verse'
            AND m.mapping_status IN
                ('mapped_verified', 'mapped_provisional', 'mapped_partial')
        ), pairs AS (
          SELECT least(a.target_passage_id, b.target_passage_id) passage_a_id,
                 greatest(a.target_passage_id, b.target_passage_id) passage_b_id,
                 a.relationship_id,
                 greatest(
                   CASE a.mapping_status WHEN 'mapped_partial' THEN 3
                     WHEN 'mapped_provisional' THEN 2 ELSE 1 END,
                   CASE b.mapping_status WHEN 'mapped_partial' THEN 3
                     WHEN 'mapped_provisional' THEN 2 ELSE 1 END
                 ) quality_rank
          FROM targets a
          JOIN targets b USING (relationship_id)
          WHERE a.endpoint_side = 'a' AND b.endpoint_side = 'b'
            AND a.target_passage_id <> b.target_passage_id
        )
        SELECT p.passage_a_id, p.passage_b_id,
               list_sort(list_distinct(list(p.relationship_id))) relationship_ids,
               max(r.source_weight_max) highest_vote,
               max(p.quality_rank) quality_rank
        FROM pairs p
        JOIN benchmark_relationships r USING (relationship_id)
        WHERE r.tier = 3 AND r.source_id = 'openbible-cross-references'
        GROUP BY p.passage_a_id, p.passage_b_id
        ORDER BY p.passage_a_id, p.passage_b_id
    """
    known_pairs: dict[tuple[str, str], KnownPair] = {}
    quality = {1: "mapped_verified", 2: "mapped_provisional", 3: "mapped_partial"}
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            cursor = connection.execute(sql)
            while True:
                if resource_check is not None:
                    resource_check(
                        "known_pair_index:fetch_batch",
                        estimated_additional_bytes=40_960_000,
                    )
                rows = cursor.fetchmany(10_000)
                if not rows:
                    break
                for row in rows:
                    known_pairs[(str(row[0]), str(row[1]))] = KnownPair(
                        relationship_ids=tuple(sorted(str(value) for value in row[2])),
                        highest_vote=int(row[3]),
                        mapping_quality=quality[int(row[4])],
                    )
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise CandidateMaterializationError(
            f"could not load mapped benchmark pairs: {exc}"
        ) from exc
    return known_pairs


def build_feature_evidence_indexes(
    sequences: Sequence[PassageLexicalSequence],
    vocabulary: pl.DataFrame,
) -> tuple[
    dict[tuple[str, str, str], tuple[str, int, int, bool, bool]],
    dict[tuple[str, str, str], tuple[str, ...]],
]:
    """Create text-free feature statistics and alternative-passage indexes."""

    statistics = {
        (str(row["language_namespace"]), str(row["feature_family"]), str(row["feature_value"])): (
            str(row["feature_id"]),
            int(row["corpus_frequency"]),
            int(row["document_frequency"]),
            bool(row["is_rare"]),
            bool(row["is_formulaic"]),
        )
        for row in vocabulary.iter_rows(named=True)
    }
    postings: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for passage in sorted(sequences, key=lambda item: item.passage_id):
        namespace = "hb" if passage.corpus == "hebrew" else "gk"
        for family, sequence_family in (
            ("lemma", "lemma"),
            ("root", "root"),
            ("normalized_surface", "surface"),
            ("part_of_speech", "part_of_speech"),
            ("morphology", "morphology"),
        ):
            for value in sorted(set(passage.values(sequence_family))):
                postings[(namespace, family, value)].append(passage.passage_id)
        for value in sorted(set(passage.values("english_gloss"))):
            postings[("en", "english_gloss", value)].append(passage.passage_id)
        for source_family in ("lemma", "root"):
            phrases, skips = _phrases(passage.values(source_family))
            for phrase in sorted(phrases):
                value = "\u241f".join(phrase)
                key = (namespace, f"{source_family}_ngram", value)
                if key in statistics:
                    postings[key].append(passage.passage_id)
            for skip in sorted(skips):
                value = "\u241f*\u241f".join(skip)
                key = (namespace, f"{source_family}_skipgram", value)
                if key in statistics:
                    postings[key].append(passage.passage_id)
    return statistics, {key: tuple(values) for key, values in postings.items()}


def _active_family(candidate: CandidateAggregate) -> tuple[str, bool]:
    if candidate.corpus_pair == "hb_gnt_english_bridge":
        return "english_gloss", True
    return "lemma", False


def _phrase_association_indexes(
    context: CandidateEvidenceContext,
) -> dict[str, PhraseAssociationIndex]:
    """Rebuild each governed phrase index once for evidence-score reconciliation."""

    hebrew = sorted(
        (item for item in context.sequences.values() if item.corpus == "hebrew"),
        key=lambda item: item.passage_id,
    )
    greek = sorted(
        (item for item in context.sequences.values() if item.corpus == "greek"),
        key=lambda item: item.passage_id,
    )

    def build(
        sequences: Sequence[PassageLexicalSequence], sequence_family: str
    ) -> PhraseAssociationIndex:
        return build_phrase_association_index(
            sequences,
            sequence_family=sequence_family,
            ngram_sizes=context.config.phrases.lemma_ngram_sizes,
            minimum_corpus_count=context.config.phrases.minimum_corpus_count,
            pmi_cap=context.config.phrases.pmi_cap,
            skipgram_max_gap=context.config.skipgrams.maximum_gap,
            skipgram_minimum_corpus_count=context.config.skipgrams.minimum_corpus_count,
        )

    return {
        "hb_hb": build(hebrew, "lemma"),
        "gnt_gnt": build(greek, "lemma"),
        "hb_gnt_english_bridge": build([*hebrew, *greek], "english_gloss"),
    }


def _namespace(passage: PassageLexicalSequence, *, english: bool) -> str:
    if english:
        return "en"
    return "hb" if passage.corpus == "hebrew" else "gk"


def _validate_candidate_corpora(
    candidate: CandidateAggregate,
    passage_a: PassageLexicalSequence,
    passage_b: PassageLexicalSequence,
) -> None:
    expected = {
        "hb_hb": ("hebrew", "hebrew"),
        "gnt_gnt": ("greek", "greek"),
    }
    if candidate.passage_a_id >= candidate.passage_b_id:
        raise CandidateMaterializationError(
            f"candidate passages are not canonically ordered: {candidate.candidate_pair_id}"
        )
    if candidate.corpus_pair in expected:
        if (passage_a.corpus, passage_b.corpus) != expected[candidate.corpus_pair]:
            raise CandidateMaterializationError(
                f"{candidate.corpus_pair} candidate crosses source-language namespaces: "
                f"{passage_a.corpus!r}, {passage_b.corpus!r}"
            )
    elif candidate.corpus_pair == "hb_gnt_english_bridge":
        if {passage_a.corpus, passage_b.corpus} != {"hebrew", "greek"}:
            raise CandidateMaterializationError(
                "English bridge candidates require exactly one Hebrew and one Greek passage"
            )
    else:
        raise CandidateMaterializationError(
            f"unsupported candidate corpus pair: {candidate.corpus_pair!r}"
        )
    for passage in (passage_a, passage_b):
        if (
            passage.analysis_profile != candidate.analysis_profile
            or passage.granularity != candidate.granularity
        ):
            raise CandidateMaterializationError(
                f"candidate profile/granularity does not match passage {passage.passage_id}"
            )
    allowed_directions = {"a_to_b", "b_to_a"}
    if not candidate.directions or not set(candidate.directions).issubset(allowed_directions):
        raise CandidateMaterializationError(
            f"candidate has invalid directional support: {candidate.candidate_pair_id}"
        )
    for direction_name, direction in candidate.directions.items():
        expected_query, expected_target = (
            (candidate.passage_a_id, candidate.passage_b_id)
            if direction_name == "a_to_b"
            else (candidate.passage_b_id, candidate.passage_a_id)
        )
        if (
            direction.direction != direction_name
            or direction.query_passage_id != expected_query
            or direction.target_passage_id != expected_target
        ):
            raise CandidateMaterializationError(
                f"directional evidence does not reconcile for {candidate.candidate_pair_id}"
            )


def _book_ordinals(
    sequences: Iterable[PassageLexicalSequence],
) -> dict[str, int]:
    grouped: dict[tuple[str, str, str, str, str], list[PassageLexicalSequence]] = defaultdict(list)
    for passage in sequences:
        grouped[
            (
                passage.corpus,
                passage.book,
                passage.analysis_profile,
                passage.analysis_reading,
                passage.granularity,
            )
        ].append(passage)
    result: dict[str, int] = {}
    for members in grouped.values():
        for ordinal, passage in enumerate(
            sorted(
                members,
                key=lambda item: (
                    item.start_stream_position_in_corpus,
                    item.passage_id,
                ),
            )
        ):
            result[passage.passage_id] = ordinal
    return result


def _passages_overlap(
    passage_a: PassageLexicalSequence,
    passage_b: PassageLexicalSequence,
) -> bool:
    return passage_a.corpus == passage_b.corpus and not set(
        passage_a.provenance_token_ids
    ).isdisjoint(passage_b.provenance_token_ids)


def _reconciled_known_pair(
    context: CandidateEvidenceContext,
    passage_a_id: str,
    passage_b_id: str,
) -> KnownPair | None:
    forward = context.known_pairs.get((passage_a_id, passage_b_id))
    reverse = context.known_pairs.get((passage_b_id, passage_a_id))
    available = [item for item in (forward, reverse) if item is not None]
    if not available:
        return None
    quality_rank = {"mapped_verified": 1, "mapped_provisional": 2, "mapped_partial": 3}
    try:
        mapping_quality = max(
            available,
            key=lambda item: quality_rank[item.mapping_quality],
        ).mapping_quality
    except KeyError as exc:
        raise CandidateMaterializationError(
            f"unsupported known-pair mapping quality: {exc.args[0]!r}"
        ) from exc
    return KnownPair(
        relationship_ids=tuple(
            sorted({value for item in available for value in item.relationship_ids})
        ),
        highest_vote=max(item.highest_vote for item in available),
        mapping_quality=mapping_quality,
    )


def _occurrence_positions(occurrences: Sequence[FeatureOccurrence], value: str) -> tuple[int, ...]:
    return tuple(index for index, item in enumerate(occurrences) if item.value == value)


def _phrase_positions(
    occurrences: Sequence[FeatureOccurrence], phrase: Sequence[str]
) -> tuple[int, ...]:
    values = tuple(item.value for item in occurrences)
    size = len(phrase)
    return tuple(
        index
        for index in range(len(values) - size + 1)
        if values[index : index + size] == tuple(phrase)
    )


def _skipgram_positions(
    occurrences: Sequence[FeatureOccurrence],
    skip: tuple[str, str],
    *,
    maximum_gap: int,
) -> tuple[int, ...]:
    positions: set[int] = set()
    for first in range(len(occurrences)):
        for second in range(first + 2, min(len(occurrences), first + maximum_gap + 2)):
            if (occurrences[first].value, occurrences[second].value) == skip:
                positions.add(first)
                positions.add(second)
    return tuple(sorted(positions))


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


def _phrases(
    values: Sequence[str],
    *,
    ngram_sizes: Sequence[int] = (2, 3),
    maximum_gap: int = 2,
) -> tuple[set[tuple[str, ...]], set[tuple[str, str]]]:
    contiguous: set[tuple[str, ...]] = set()
    for size in ngram_sizes:
        contiguous.update(zip(*(values[offset:] for offset in range(size)), strict=False))
    skipped: set[tuple[str, str]] = set()
    for first in range(len(values)):
        for second in range(first + 2, min(len(values), first + maximum_gap + 2)):
            skipped.add((values[first], values[second]))
    return contiguous, skipped


def _best_scores(candidate: CandidateAggregate) -> dict[str, float]:
    detectors = set(DETECTOR_FAMILIES) | {"rrf_composite"}
    scores: dict[str, float] = {}
    for detector in detectors:
        if detector == "rrf_composite":
            scores[detector] = candidate.best_rrf_score
        else:
            scores[detector] = max(
                (
                    direction.scores.get(detector, 0.0)
                    for direction in candidate.directions.values()
                ),
                default=0.0,
            )
    return scores


def _governed_score_reconciliation(
    *,
    detector: str,
    candidate_pair_id: str,
    persisted: float,
    recomputed: float,
    decimals: int,
) -> dict[str, object] | None:
    """Reconcile only adjacent governed decimal bins without changing either score."""

    if not math.isfinite(persisted) or not math.isfinite(recomputed):
        raise CandidateMaterializationError(
            f"{detector} evidence is non-finite for {candidate_pair_id}: "
            f"persisted={persisted}, recomputed={recomputed}"
        )
    persisted_decimal = format(persisted, f".{decimals}f")
    recomputed_decimal = format(recomputed, f".{decimals}f")
    scale = Decimal(10) ** decimals
    persisted_bin = int(Decimal(persisted_decimal) * scale)
    recomputed_bin = int(Decimal(recomputed_decimal) * scale)
    bin_delta = persisted_bin - recomputed_bin
    if abs(bin_delta) > 1:
        raise CandidateMaterializationError(
            f"{detector} evidence does not reproduce for {candidate_pair_id}: "
            f"persisted={persisted}, recomputed={recomputed}, "
            f"persisted_minus_recomputed_bin_delta={bin_delta}"
        )
    if bin_delta == 0:
        return None
    return {
        "status": "accepted_adjacent_float64_reduction_bin",
        "score_quantization_decimals": decimals,
        "persisted_quantized_decimal": persisted_decimal,
        "recomputed_quantized_decimal": recomputed_decimal,
        "persisted_minus_recomputed_bin_delta": bin_delta,
        "maximum_allowed_absolute_bin_delta": 1,
    }


def _detector_score_traces(
    candidate: CandidateAggregate,
    direction: CandidateDirection,
    *,
    context: CandidateEvidenceContext,
    phrase_associations: PhraseAssociationIndex,
) -> dict[str, dict[str, object]]:
    """Recompute every directional detector with its exact governed inputs."""

    query = context.sequences[direction.query_passage_id]
    target = context.sequences[direction.target_passage_id]
    family, english = _active_family(candidate)
    namespace = _namespace(query, english=english)
    query_values = query.values(family)
    target_values = target.values(family)
    representation_statistics = context.representation_statistics.get(candidate.corpus_pair)
    if representation_statistics is None:
        raise CandidateMaterializationError(
            f"detector trace has no representation statistics for {candidate.corpus_pair}"
        )
    document_count, average_length = representation_statistics
    if document_count < 1:
        raise CandidateMaterializationError("detector trace requires a nonempty representation")
    document_frequencies: dict[str, int] = {}
    corpus_frequencies: dict[str, int] = {}
    for value in sorted(set(query_values).union(target_values)):
        feature = context.feature_statistics.get((namespace, family, value))
        if feature is None:
            raise CandidateMaterializationError(
                f"missing feature statistics while tracing {namespace}:{family}:{value}"
            )
        corpus_frequencies[value] = feature[1]
        document_frequencies[value] = feature[2]
    idf = {
        value: math.log((1.0 + document_count) / (1.0 + frequency)) + 1.0
        for value, frequency in document_frequencies.items()
    }
    jaccard = jaccard_similarity(query_values, target_values)
    weighted = weighted_jaccard_similarity(query_values, target_values, idf)
    tfidf = tfidf_cosine_similarity(
        Counter(query_values),
        Counter(target_values),
        document_frequencies,
        document_count,
        sublinear_tf=context.config.tfidf.sublinear_tf,
        smooth_idf=context.config.tfidf.smooth_idf,
    )
    maximum_df = max(
        1,
        math.floor(
            document_count
            * context.config.feature_frequency_thresholds.proposal_maximum_document_frequency_ratio
        ),
    )
    tfidf_selected_dot = math.fsum(
        item.dot_contribution
        for item in tfidf.contributions
        if item.document_frequency <= maximum_df
    )
    tfidf_score = (
        round(tfidf_selected_dot, context.config.statistics.score_quantization_decimals)
        if "tfidf_cosine" in direction.proposal_detectors
        else 0.0
    )
    selected_query_counts = Counter(
        value for value in query_values if document_frequencies[value] <= maximum_df
    )
    selected_target_counts = Counter(
        value for value in target_values if document_frequencies[value] <= maximum_df
    )
    bm25 = bm25_score(
        selected_query_counts,
        selected_target_counts,
        document_frequencies,
        document_count,
        document_length=len(target_values),
        average_document_length=average_length,
        k1=context.config.bm25.k1,
        b=context.config.bm25.b,
        query_term_frequency_mode="binary",
    )
    bm25_value = (
        round(bm25.score, context.config.statistics.score_quantization_decimals)
        if "bm25" in direction.proposal_detectors
        else 0.0
    )
    rare_items = [
        value
        for value in sorted(set(query_values).intersection(target_values))
        if 0 < corpus_frequencies[value] <= context.config.rare_evidence.maximum_corpus_frequency
    ]
    rare_value = round(
        math.fsum(1.0 / corpus_frequencies[value] for value in rare_items),
        context.config.statistics.score_quantization_decimals,
    )
    phrases_a, skips_a = _phrases(
        query_values,
        ngram_sizes=context.config.phrases.lemma_ngram_sizes,
        maximum_gap=context.config.skipgrams.maximum_gap,
    )
    phrases_b, skips_b = _phrases(
        target_values,
        ngram_sizes=context.config.phrases.lemma_ngram_sizes,
        maximum_gap=context.config.skipgrams.maximum_gap,
    )
    shared_phrases = sorted((phrases_a & phrases_b).intersection(phrase_associations.weights))
    shared_skips = sorted((skips_a & skips_b).intersection(phrase_associations.skipgram_weights))
    phrase_components = [
        {
            "feature": "\u241f".join(value),
            "corpus_frequency": phrase_associations.corpus_frequency[value],
            "document_frequency": phrase_associations.document_frequency[value],
            "pmi": phrase_associations.pmi[value],
            "log_likelihood": phrase_associations.log_likelihood[value],
            "frequency_control": 1.0 + math.log(phrase_associations.corpus_frequency[value]),
            "contribution": phrase_associations.weights[value],
        }
        for value in shared_phrases
    ]
    skip_components = [
        {
            "feature": "\u241f*\u241f".join(value),
            "corpus_frequency": phrase_associations.skipgram_corpus_frequency[value],
            "document_frequency": phrase_associations.skipgram_document_frequency[value],
            "contribution": phrase_associations.skipgram_weights[value],
        }
        for value in shared_skips
    ]
    phrase_score = math.fsum(
        cast(float, item["contribution"]) for item in [*phrase_components, *skip_components]
    )
    lcs = longest_common_subsequence(query_values, target_values, normalization="shorter")
    alignment_weights = {
        value: max(1e-12, idf[value]) for value in set(query_values).union(target_values)
    }
    alignment = weighted_sequence_alignment(
        query_values,
        target_values,
        alignment_weights,
        gap_penalty=abs(context.config.sequence.gap_penalty),
        mismatch_score=context.config.sequence.mismatch_penalty,
        mode="local",
    )
    pos_morph_components: list[dict[str, object]] = []
    if not english:
        for support_family in ("part_of_speech", "morphology"):
            support = longest_common_subsequence(
                query.values(support_family),
                target.values(support_family),
                normalization="shorter",
            )
            pos_morph_components.append(
                {
                    "family": support_family,
                    "normalized_score": support.normalized_score,
                    "features": support.features,
                    "positions_a": support.positions_a,
                    "positions_b": support.positions_b,
                }
            )
    pos_morph_score = (
        math.fsum(cast(float, item["normalized_score"]) for item in pos_morph_components)
        / len(pos_morph_components)
        if pos_morph_components
        else 0.0
    )
    traces: dict[str, dict[str, object]] = {
        "jaccard": {"formula": "intersection_size/union_size", **asdict(jaccard)},
        "weighted_jaccard": {
            "formula": "sum(idf*min(tf_a,tf_b))/sum(idf*max(tf_a,tf_b))",
            **asdict(weighted),
        },
        "tfidf_cosine": {
            "formula": "selected_feature_dot_of_full_l2_normalized_tfidf_vectors",
            **asdict(tfidf),
            "maximum_proposal_document_frequency": maximum_df,
            "proposal_evaluated": "tfidf_cosine" in direction.proposal_detectors,
            "selected_dot_score": tfidf_score,
        },
        "bm25": {
            "formula": "sum(idf*binary_query_weight*bm25_term_saturation)",
            **asdict(bm25),
            "maximum_proposal_document_frequency": maximum_df,
            "proposal_evaluated": "bm25" in direction.proposal_detectors,
            "selected_score": bm25_value,
        },
        "rare_lemma_root": {
            "formula": "sum(1/corpus_frequency) for shared governed rare features",
            "threshold": context.config.rare_evidence.maximum_corpus_frequency,
            "features": [
                {"feature": value, "corpus_frequency": corpus_frequencies[value]}
                for value in rare_items
            ],
            "proposal_evaluated": "rare_lemma_root" in direction.proposal_detectors,
            "score": rare_value,
        },
        "phrase_association": {
            "formula": "sum((pmi+log1p(ll))/(1+log(cf)))+sum(1/skip_cf)",
            "phrases": phrase_components,
            "skipgrams": skip_components,
            "score": phrase_score,
        },
        "longest_common_subsequence": {
            "formula": "lcs_length/min(sequence_lengths)",
            **asdict(lcs),
        },
        "weighted_sequence_alignment": {
            "formula": "local_idf_weighted_alignment/maximum_self_alignment",
            "evaluated_in_bounded_rerank": direction.alignment_evaluated,
            **asdict(alignment),
            "persisted_score": (
                alignment.normalized_score if direction.alignment_evaluated else 0.0
            ),
        },
        "pos_morphology_support": {
            "formula": "mean(normalized_lcs(pos),normalized_lcs(morphology))",
            "components": pos_morph_components,
            "score": pos_morph_score,
        },
    }
    expected = {
        "jaccard": jaccard.score,
        "weighted_jaccard": weighted.score,
        "tfidf_cosine": tfidf_score,
        "bm25": bm25_value,
        "rare_lemma_root": rare_value,
        "phrase_association": phrase_score,
        "longest_common_subsequence": lcs.normalized_score,
        "weighted_sequence_alignment": (
            alignment.normalized_score if direction.alignment_evaluated else 0.0
        ),
        "pos_morphology_support": pos_morph_score,
    }
    for detector, expected_score in expected.items():
        persisted = direction.scores.get(detector, 0.0)
        decimals = context.config.statistics.score_quantization_decimals
        if direction.score_trace_version == "governed_v1":
            reconciliation = _governed_score_reconciliation(
                detector=detector,
                candidate_pair_id=candidate.candidate_pair_id,
                persisted=persisted,
                recomputed=expected_score,
                decimals=decimals,
            )
            if reconciliation is not None:
                traces[detector]["quantization_reconciliation"] = reconciliation
        elif round(persisted, decimals) != round(expected_score, decimals):
            traces[detector]["legacy_fixture_recomputed_score"] = expected_score
            traces[detector]["legacy_fixture_score_not_governed"] = True
        traces[detector]["persisted_score"] = persisted
    return traces


def _hypergeometric_inputs(
    candidate: CandidateAggregate,
    context: CandidateEvidenceContext,
) -> tuple[int, int, int, int]:
    passage_a = context.sequences[candidate.passage_a_id]
    passage_b = context.sequences[candidate.passage_b_id]
    family, english = _active_family(candidate)
    values_a = set(passage_a.values(family))
    values_b = set(passage_b.values(family))
    namespace = _namespace(passage_a, english=english)
    population = context.feature_population_counts.get((namespace, family), 0)
    return population, len(values_a), len(values_b), len(values_a & values_b)


def candidate_q_values(
    candidates: Mapping[str, CandidateAggregate],
    context: CandidateEvidenceContext,
) -> dict[str, float]:
    """Apply BH separately to each registered corpus-pair hypothesis family."""

    grouped: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for candidate_id, candidate in sorted(candidates.items()):
        passage_a = context.sequences.get(candidate.passage_a_id)
        passage_b = context.sequences.get(candidate.passage_b_id)
        if passage_a is None or passage_b is None:
            raise CandidateMaterializationError(
                f"candidate references an unavailable passage: {candidate_id}"
            )
        _validate_candidate_corpora(candidate, passage_a, passage_b)
        population, success_states, draws, observed = _hypergeometric_inputs(candidate, context)
        result = hypergeometric_upper_tail(population, success_states, draws, observed)
        representation_id = context.representation_ids.get(candidate.corpus_pair)
        if representation_id is None:
            raise CandidateMaterializationError(
                f"missing representation for corpus pair {candidate.corpus_pair!r}"
            )
        hypothesis_family = (candidate.corpus_pair, representation_id)
        grouped[hypothesis_family].append((candidate_id, result.upper_tail_p_value))
    output: dict[str, float] = {}
    for items in grouped.values():
        adjusted = benjamini_hochberg([p_value for _, p_value in items])
        output.update(
            (candidate_id, q_value)
            for (candidate_id, _), q_value in zip(items, adjusted, strict=True)
        )
    return output


def _shared_evidence_rows(
    candidate: CandidateAggregate,
    passage_a: PassageLexicalSequence,
    passage_b: PassageLexicalSequence,
    *,
    context: CandidateEvidenceContext,
    phrase_associations: PhraseAssociationIndex,
) -> tuple[list[dict[str, object]], SharedSummary]:
    family, english = _active_family(candidate)
    namespace = _namespace(passage_a, english=english)
    rows: list[dict[str, object]] = []
    formulaic_count = 0
    shared_by_family: dict[str, tuple[str, ...]] = {}
    rare_by_family: dict[str, tuple[str, ...]] = {}
    document_count = context.document_counts_by_namespace.get(namespace, 0)

    def append_base_rows(evidence_family: str, sequence_family: str) -> None:
        nonlocal formulaic_count
        occurrences_a = getattr(passage_a, sequence_family)
        occurrences_b = getattr(passage_b, sequence_family)
        values = tuple(
            sorted(set(passage_a.values(sequence_family)) & set(passage_b.values(sequence_family)))
        )
        shared_by_family[evidence_family] = values
        rare_values: list[str] = []
        for value in values:
            key = (namespace, evidence_family, value)
            feature = context.feature_statistics.get(key)
            if feature is None:
                raise CandidateMaterializationError(f"missing vocabulary row for {key!r}")
            feature_id, corpus_frequency, document_frequency, is_rare, is_formulaic = feature
            source_rare = evidence_family in {"lemma", "root"} and is_rare
            if source_rare:
                rare_values.append(value)
            if evidence_family == family:
                formulaic_count += int(is_formulaic)
            positions_a = _occurrence_positions(occurrences_a, value)
            positions_b = _occurrence_positions(occurrences_b, value)
            if not positions_a or not positions_b:
                raise CandidateMaterializationError(
                    f"shared feature {key!r} has no positions in both passages"
                )
            alternatives = [
                passage_id
                for passage_id in context.feature_passages.get(key, ())
                if passage_id not in {passage_a.passage_id, passage_b.passage_id}
            ][:5]
            payload = {
                "candidate_pair_id": candidate.candidate_pair_id,
                "evidence_family": evidence_family,
                "feature_id": feature_id,
                "positions_a": positions_a,
                "positions_b": positions_b,
            }
            rows.append(
                {
                    "evidence_id": _hash_id("LE", payload),
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "evidence_family": evidence_family,
                    "feature_id": feature_id,
                    "feature_value": value,
                    "passage_a_positions_json": _canonical_json(list(positions_a)),
                    "passage_b_positions_json": _canonical_json(list(positions_b)),
                    "corpus_frequency": corpus_frequency,
                    "document_frequency": document_frequency,
                    "passage_a_local_frequency": len(positions_a),
                    "passage_b_local_frequency": len(positions_b),
                    "association_score": 1.0 / max(1, corpus_frequency),
                    "pmi": None,
                    "log_likelihood": None,
                    "frequency_control": None,
                    "score_formula": "inverse_corpus_frequency_evidence_weight",
                    "detector_contributions_json": _canonical_json(
                        {
                            "jaccard_intersection": 1.0 if evidence_family == family else 0.0,
                            "rare_lemma_root": (1.0 / corpus_frequency if source_rare else 0.0),
                        }
                    ),
                    "independence_expected_count": (
                        document_frequency * document_frequency / max(1, document_count)
                    ),
                    "contains_primary_rare_item": source_rare,
                    "counts_as_independent_co_signal": False,
                    "english_derived": english,
                    "notes": (
                        "alternative_passage_ids="
                        + ",".join(alternatives)
                        + f";local_frequency_a={len(positions_a)}"
                        + f";local_frequency_b={len(positions_b)}"
                    ),
                    "_source_tokens_a": tuple(
                        item.token_id for item in occurrences_a if item.value == value
                    ),
                    "_source_tokens_b": tuple(
                        item.token_id for item in occurrences_b if item.value == value
                    ),
                }
            )
        rare_by_family[evidence_family] = tuple(rare_values)

    if english:
        append_base_rows("english_gloss", "english_gloss")
    else:
        for evidence_family, sequence_family in (
            ("lemma", "lemma"),
            ("root", "root"),
            ("normalized_surface", "surface"),
            ("part_of_speech", "part_of_speech"),
            ("morphology", "morphology"),
        ):
            append_base_rows(evidence_family, sequence_family)

    lemma_phrases: tuple[tuple[str, ...], ...] = ()
    root_phrases: tuple[tuple[str, ...], ...] = ()
    lemma_skips: tuple[tuple[str, str], ...] = ()
    root_skips: tuple[tuple[str, str], ...] = ()
    if english:
        occurrences_a = passage_a.english_gloss
        occurrences_b = passage_b.english_gloss
        phrases_a, skips_a = _phrases(
            passage_a.values("english_gloss"),
            ngram_sizes=context.config.phrases.lemma_ngram_sizes,
            maximum_gap=context.config.skipgrams.maximum_gap,
        )
        phrases_b, skips_b = _phrases(
            passage_b.values("english_gloss"),
            ngram_sizes=context.config.phrases.lemma_ngram_sizes,
            maximum_gap=context.config.skipgrams.maximum_gap,
        )
        governed_english_phrases = sorted(
            (phrases_a & phrases_b).intersection(phrase_associations.weights)
        )
        governed_english_skips = sorted(
            (skips_a & skips_b).intersection(phrase_associations.skipgram_weights)
        )
        for phrase in governed_english_phrases:
            value = "\u241f".join(phrase)
            positions_a = _phrase_positions(occurrences_a, phrase)
            positions_b = _phrase_positions(occurrences_b, phrase)
            phrase_cf = phrase_associations.corpus_frequency[phrase]
            phrase_df = phrase_associations.document_frequency[phrase]
            feature_id = _hash_id(
                "LF",
                {
                    "namespace": "en",
                    "family": "english_gloss_ngram",
                    "value": value,
                },
            )
            weight = phrase_associations.weights[phrase]
            rows.append(
                {
                    "evidence_id": _hash_id(
                        "LE",
                        {
                            "candidate_pair_id": candidate.candidate_pair_id,
                            "evidence_family": "english_gloss_ngram",
                            "feature_id": feature_id,
                            "positions_a": positions_a,
                            "positions_b": positions_b,
                        },
                    ),
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "evidence_family": "english_gloss_ngram",
                    "feature_id": feature_id,
                    "feature_value": value,
                    "passage_a_positions_json": _canonical_json(list(positions_a)),
                    "passage_b_positions_json": _canonical_json(list(positions_b)),
                    "corpus_frequency": phrase_cf,
                    "document_frequency": phrase_df,
                    "passage_a_local_frequency": len(positions_a),
                    "passage_b_local_frequency": len(positions_b),
                    "association_score": weight,
                    "pmi": phrase_associations.pmi[phrase],
                    "log_likelihood": phrase_associations.log_likelihood[phrase],
                    "frequency_control": 1.0 + math.log(phrase_cf),
                    "score_formula": (
                        "(max(0,pmi)+log1p(max(0,log_likelihood)))/(1+log(corpus_frequency))"
                    ),
                    "detector_contributions_json": _canonical_json({"phrase_association": weight}),
                    "independence_expected_count": phrase_df * phrase_df / max(1, document_count),
                    "contains_primary_rare_item": False,
                    "counts_as_independent_co_signal": False,
                    "english_derived": True,
                    "notes": "english_derived_contiguous_phrase",
                }
            )
        for skip in governed_english_skips:
            value = "\u241f*\u241f".join(skip)
            positions_a = _skipgram_positions(
                occurrences_a, skip, maximum_gap=context.config.skipgrams.maximum_gap
            )
            positions_b = _skipgram_positions(
                occurrences_b, skip, maximum_gap=context.config.skipgrams.maximum_gap
            )
            skip_cf = phrase_associations.skipgram_corpus_frequency[skip]
            skip_df = phrase_associations.skipgram_document_frequency[skip]
            feature_id = _hash_id(
                "LF",
                {
                    "namespace": "en",
                    "family": "english_gloss_skipgram",
                    "value": value,
                },
            )
            weight = phrase_associations.skipgram_weights[skip]
            rows.append(
                {
                    "evidence_id": _hash_id(
                        "LE",
                        {
                            "candidate_pair_id": candidate.candidate_pair_id,
                            "evidence_family": "english_gloss_skipgram",
                            "feature_id": feature_id,
                            "positions_a": positions_a,
                            "positions_b": positions_b,
                        },
                    ),
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "evidence_family": "english_gloss_skipgram",
                    "feature_id": feature_id,
                    "feature_value": value,
                    "passage_a_positions_json": _canonical_json(list(positions_a)),
                    "passage_b_positions_json": _canonical_json(list(positions_b)),
                    "corpus_frequency": skip_cf,
                    "document_frequency": skip_df,
                    "passage_a_local_frequency": len(positions_a),
                    "passage_b_local_frequency": len(positions_b),
                    "association_score": weight,
                    "pmi": None,
                    "log_likelihood": None,
                    "frequency_control": None,
                    "score_formula": "1/corpus_frequency",
                    "detector_contributions_json": _canonical_json({"phrase_association": weight}),
                    "independence_expected_count": skip_df * skip_df / max(1, document_count),
                    "contains_primary_rare_item": False,
                    "counts_as_independent_co_signal": False,
                    "english_derived": True,
                    "notes": "english_derived_skipgram",
                }
            )
        lemma_phrases = tuple(governed_english_phrases)
        lemma_skips = tuple(governed_english_skips)
    if not english:
        for source_family in ("lemma", "root"):
            occurrences_a = getattr(passage_a, source_family)
            occurrences_b = getattr(passage_b, source_family)
            phrases_a, skips_a = _phrases(
                passage_a.values(source_family),
                ngram_sizes=context.config.phrases.lemma_ngram_sizes,
                maximum_gap=context.config.skipgrams.maximum_gap,
            )
            phrases_b, skips_b = _phrases(
                passage_b.values(source_family),
                ngram_sizes=context.config.phrases.lemma_ngram_sizes,
                maximum_gap=context.config.skipgrams.maximum_gap,
            )
            governed_phrases: list[tuple[str, ...]] = []
            for phrase in sorted(phrases_a & phrases_b):
                value = "\u241f".join(phrase)
                key = (namespace, f"{source_family}_ngram", value)
                feature = context.feature_statistics.get(key)
                if feature is None:
                    continue
                feature_id, phrase_cf, phrase_df, _phrase_is_rare, phrase_is_formulaic = feature
                governed_phrases.append(phrase)
                if source_family == "lemma":
                    formulaic_count += int(phrase_is_formulaic)
                positions_a = _phrase_positions(occurrences_a, phrase)
                positions_b = _phrase_positions(occurrences_b, phrase)
                alternatives = [
                    passage_id
                    for passage_id in context.feature_passages.get(key, ())
                    if passage_id not in {passage_a.passage_id, passage_b.passage_id}
                ][:5]
                payload = {
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "evidence_family": key[1],
                    "feature_id": feature_id,
                    "positions_a": positions_a,
                    "positions_b": positions_b,
                }
                active_phrase = source_family == family and phrase in phrase_associations.weights
                phrase_score = (
                    phrase_associations.weights.get(phrase, 0.0) if active_phrase else 0.0
                )
                phrase_pmi = phrase_associations.pmi.get(phrase) if active_phrase else None
                phrase_likelihood = (
                    phrase_associations.log_likelihood.get(phrase) if active_phrase else None
                )
                frequency_control = 1.0 + math.log(phrase_cf) if active_phrase else None
                rows.append(
                    {
                        "evidence_id": _hash_id("LE", payload),
                        "candidate_pair_id": candidate.candidate_pair_id,
                        "evidence_family": key[1],
                        "feature_id": feature_id,
                        "feature_value": value,
                        "passage_a_positions_json": _canonical_json(list(positions_a)),
                        "passage_b_positions_json": _canonical_json(list(positions_b)),
                        "corpus_frequency": phrase_cf,
                        "document_frequency": phrase_df,
                        "passage_a_local_frequency": len(positions_a),
                        "passage_b_local_frequency": len(positions_b),
                        "association_score": phrase_score,
                        "pmi": phrase_pmi,
                        "log_likelihood": phrase_likelihood,
                        "frequency_control": frequency_control,
                        "score_formula": (
                            "(max(0,pmi)+log1p(max(0,log_likelihood)))/(1+log(corpus_frequency))"
                            if active_phrase
                            else "root_phrase_audit_not_active_detector"
                        ),
                        "detector_contributions_json": _canonical_json(
                            {"phrase_association": phrase_score}
                        ),
                        "independence_expected_count": (
                            phrase_df * phrase_df / max(1, document_count)
                        ),
                        "contains_primary_rare_item": any(
                            item in rare_by_family[source_family] for item in phrase
                        ),
                        "counts_as_independent_co_signal": False,
                        "english_derived": False,
                        "notes": (
                            "derived_contiguous_phrase"
                            f";formulaic={str(phrase_is_formulaic).lower()}"
                            ";alternative_passage_ids="
                            + ",".join(alternatives)
                            + f";local_frequency_a={len(positions_a)}"
                            + f";local_frequency_b={len(positions_b)}"
                        ),
                    }
                )
            governed_skips: list[tuple[str, str]] = []
            for skip in sorted(skips_a & skips_b):
                value = "\u241f*\u241f".join(skip)
                key = (namespace, f"{source_family}_skipgram", value)
                feature = context.feature_statistics.get(key)
                if feature is None:
                    continue
                feature_id, skip_cf, skip_df, _skip_is_rare, skip_is_formulaic = feature
                governed_skips.append(skip)
                positions_a = _skipgram_positions(
                    occurrences_a,
                    skip,
                    maximum_gap=context.config.skipgrams.maximum_gap,
                )
                positions_b = _skipgram_positions(
                    occurrences_b,
                    skip,
                    maximum_gap=context.config.skipgrams.maximum_gap,
                )
                alternatives = [
                    passage_id
                    for passage_id in context.feature_passages.get(key, ())
                    if passage_id not in {passage_a.passage_id, passage_b.passage_id}
                ][:5]
                payload = {
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "evidence_family": key[1],
                    "feature_id": feature_id,
                    "positions_a": positions_a,
                    "positions_b": positions_b,
                }
                rows.append(
                    {
                        "evidence_id": _hash_id("LE", payload),
                        "candidate_pair_id": candidate.candidate_pair_id,
                        "evidence_family": key[1],
                        "feature_id": feature_id,
                        "feature_value": value,
                        "passage_a_positions_json": _canonical_json(list(positions_a)),
                        "passage_b_positions_json": _canonical_json(list(positions_b)),
                        "corpus_frequency": skip_cf,
                        "document_frequency": skip_df,
                        "passage_a_local_frequency": len(positions_a),
                        "passage_b_local_frequency": len(positions_b),
                        "association_score": (
                            phrase_associations.skipgram_weights.get(skip, 0.0)
                            if source_family == family
                            else 0.0
                        ),
                        "pmi": None,
                        "log_likelihood": None,
                        "frequency_control": None,
                        "score_formula": (
                            "1/corpus_frequency"
                            if source_family == family
                            else "root_skipgram_audit_not_active_detector"
                        ),
                        "detector_contributions_json": _canonical_json(
                            {
                                "phrase_association": (
                                    phrase_associations.skipgram_weights.get(skip, 0.0)
                                    if source_family == family
                                    else 0.0
                                )
                            }
                        ),
                        "independence_expected_count": (skip_df * skip_df / max(1, document_count)),
                        "contains_primary_rare_item": any(
                            item in rare_by_family[source_family] for item in skip
                        ),
                        "counts_as_independent_co_signal": False,
                        "english_derived": False,
                        "notes": (
                            "derived_skipgram"
                            f";formulaic={str(skip_is_formulaic).lower()}"
                            ";alternative_passage_ids=" + ",".join(alternatives)
                        ),
                    }
                )
            if source_family == "lemma":
                lemma_phrases = tuple(governed_phrases)
                lemma_skips = tuple(governed_skips)
            else:
                root_phrases = tuple(governed_phrases)
                root_skips = tuple(governed_skips)

    shared = shared_by_family.get(family, ())
    shared_rare = rare_by_family.get("lemma", ())
    shared_rare_roots = rare_by_family.get("root", ())
    return rows, SharedSummary(
        shared=shared,
        shared_roots=shared_by_family.get("root", ()),
        shared_surfaces=shared_by_family.get("normalized_surface", ()),
        shared_rare=shared_rare,
        shared_rare_roots=shared_rare_roots,
        shared_phrases=lemma_phrases,
        shared_root_phrases=root_phrases,
        shared_skips=lemma_skips,
        shared_root_skips=root_skips,
        formulaic_count=formulaic_count,
    )


def _append_note(row: dict[str, object], note: str) -> None:
    current = str(row["notes"])
    row["notes"] = f"{current};{note}" if current else note


def _mark_independent_signal(row: dict[str, object], reason: str) -> None:
    row["counts_as_independent_co_signal"] = True
    _append_note(row, f"independent_co_signal={reason}")


def _positions_signature(row: Mapping[str, object]) -> tuple[str, str]:
    if "_source_tokens_a" in row and "_source_tokens_b" in row:
        return (
            _canonical_json(row["_source_tokens_a"]),
            _canonical_json(row["_source_tokens_b"]),
        )
    return str(row["passage_a_positions_json"]), str(row["passage_b_positions_json"])


def _rare_rule_result(
    shared: SharedSummary,
    shared_rows: list[dict[str, object]],
    passage_a: PassageLexicalSequence,
    passage_b: PassageLexicalSequence,
    scores: Mapping[str, float],
    *,
    context: CandidateEvidenceContext,
) -> RareRuleResult:
    rare_rows = sorted(
        (
            row
            for row in shared_rows
            if row["evidence_family"] in {"lemma", "root"}
            and bool(row["contains_primary_rare_item"])
        ),
        key=lambda row: (
            _positions_signature(row),
            str(row["evidence_family"]),
            str(row["feature_value"]),
        ),
    )
    expected_rare_count = len(shared.shared_rare) + len(shared.shared_rare_roots)
    if len(rare_rows) != expected_rare_count:
        raise CandidateMaterializationError(
            "rare feature summary does not reconcile to detailed evidence: "
            f"{len(rare_rows)} != {expected_rare_count}"
        )
    if not rare_rows:
        return RareRuleResult(independent_co_signal_count=0, passed=True)

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rare_rows:
        grouped[_positions_signature(row)].append(row)
    ordered_groups = sorted(
        grouped.values(),
        key=lambda rows: (
            _positions_signature(rows[0]),
            str(rows[0]["evidence_family"]),
            str(rows[0]["feature_value"]),
        ),
    )
    primary_group = ordered_groups[0]
    for row in primary_group:
        _append_note(row, "primary_rare_evidence=true")
    for row in primary_group[1:]:
        _append_note(row, "co_signal_rejected=lemma_root_same_token_positions")
    used_feature_ids = {str(row["feature_id"]) for row in primary_group}
    accepted_count = 0

    for group in ordered_groups[1:]:
        representative = group[0]
        _mark_independent_signal(representative, "second_distinct_rare_lemma_or_root")
        for row in group[1:]:
            _append_note(row, "co_signal_rejected=lemma_root_same_token_positions")
        used_feature_ids.update(str(row["feature_id"]) for row in group)
        accepted_count += 1

    namespace = _namespace(passage_a, english=False)
    primary_family = str(primary_group[0]["evidence_family"])
    primary_values = {str(row["feature_value"]) for row in primary_group}
    all_rare_values = {
        str(row["feature_value"]) for row in rare_rows if row["evidence_family"] == primary_family
    }

    phrase_candidates: list[tuple[dict[str, object], set[str]]] = []
    for row in shared_rows:
        if row["evidence_family"] != f"{primary_family}_ngram":
            continue
        components = str(row["feature_value"]).split("\u241f")
        if not primary_values.intersection(components):
            continue
        additional_ids: set[str] = set()
        for value in components:
            if value in all_rare_values:
                continue
            feature = context.feature_statistics.get((namespace, primary_family, value))
            if feature is not None and not feature[4]:
                additional_ids.add(feature[0])
        if additional_ids:
            phrase_candidates.append((row, additional_ids))
        else:
            _append_note(row, "co_signal_rejected=no_additional_eligible_lexical_material")
    for row, support_ids in sorted(
        phrase_candidates,
        key=lambda item: (str(item[0]["feature_value"]), str(item[0]["evidence_id"])),
    ):
        if support_ids.issubset(used_feature_ids):
            _append_note(row, "co_signal_rejected=correlated_restatement")
            continue
        _mark_independent_signal(row, "phrase_with_additional_lexical_material")
        used_feature_ids.update(support_ids)
        accepted_count += 1
        break

    sequence_a = passage_a.values(primary_family)
    sequence_b = passage_b.values(primary_family)
    shared_base_rows = [
        row
        for row in shared_rows
        if row["evidence_family"] == primary_family
        and str(row["feature_value"]) not in primary_values
        and not context.feature_statistics[(namespace, primary_family, str(row["feature_value"]))][
            4
        ]
    ]
    ordered_support = sorted(
        shared_base_rows,
        key=lambda row: (str(row["feature_value"]), str(row["feature_id"])),
    )
    new_ordered_support = [
        row for row in ordered_support if str(row["feature_id"]) not in used_feature_ids
    ]
    if (
        _bitset_lcs_length(sequence_a, sequence_b) >= 3
        and len({str(row["feature_value"]) for row in ordered_support}) >= 2
        and len({str(row["feature_id"]) for row in new_ordered_support}) >= 2
    ):
        representative = new_ordered_support[0]
        _mark_independent_signal(representative, "ordered_sequence_with_two_additional_features")
        used_feature_ids.update(str(row["feature_id"]) for row in new_ordered_support[:2])
        accepted_count += 1

    if scores.get("pos_morphology_support", 0.0) > 0.5:
        for family in ("part_of_speech", "morphology"):
            support_a = passage_a.values(family)
            support_b = passage_b.values(family)
            shorter = min(len(support_a), len(support_b))
            if shorter < 2 or _bitset_lcs_length(support_a, support_b) / shorter <= 0.5:
                continue
            support_rows = sorted(
                (row for row in shared_rows if row["evidence_family"] == family),
                key=lambda row: (str(row["feature_value"]), str(row["feature_id"])),
            )
            new_support = [
                row for row in support_rows if str(row["feature_id"]) not in used_feature_ids
            ]
            if new_support:
                _mark_independent_signal(new_support[0], "independent_pos_or_morphology_sequence")
                used_feature_ids.update(str(row["feature_id"]) for row in support_rows)
                accepted_count += 1
                break

    if scores.get("jaccard", 0.0) > 0.0 or scores.get("weighted_jaccard", 0.0) > 0.0:
        new_overlap_support = [
            row for row in ordered_support if str(row["feature_id"]) not in used_feature_ids
        ]
        if new_overlap_support:
            _mark_independent_signal(
                new_overlap_support[0], "non_restatement_detector_family:set_overlap"
            )
            used_feature_ids.add(str(new_overlap_support[0]["feature_id"]))
            accepted_count += 1

    if accepted_count == 0 and (
        scores.get("tfidf_cosine", 0.0) > 0.0 or scores.get("bm25", 0.0) > 0.0
    ):
        _append_note(primary_group[0], "co_signal_rejected=tfidf_bm25_same_item")
    return RareRuleResult(
        independent_co_signal_count=accepted_count,
        passed=accepted_count > 0,
    )


def _apply_penalties(
    raw_score: float,
    *,
    formulaic_penalty: float,
    local_context_penalty: float,
    short_passage_penalty: float,
) -> tuple[float, dict[str, float]]:
    """Apply registered fractional penalties sequentially with additive reconciliation."""

    current = raw_score
    contributions: dict[str, float] = {}
    for name, fraction in (
        ("formulaic", formulaic_penalty),
        ("local_context", local_context_penalty),
        ("short_passage", short_passage_penalty),
    ):
        deduction = -(current * fraction)
        contributions[name] = deduction
        current += deduction
    if not math.isclose(
        raw_score + math.fsum(contributions.values()), current, rel_tol=0.0, abs_tol=1e-15
    ):
        raise CandidateMaterializationError("penalty contributions do not reconcile")
    return current, contributions


def _rrf_without_ablation(
    candidate: CandidateAggregate,
    ablation_name: str,
    *,
    context: CandidateEvidenceContext,
) -> float:
    excluded = {
        "remove_tfidf": {"tfidf_cosine"},
        "remove_bm25": {"bm25"},
        "remove_rare_evidence": {"rare_lemma_root"},
        "remove_phrase_evidence": {"phrase_association"},
        "remove_ordered_sequence": {
            "longest_common_subsequence",
            "weighted_sequence_alignment",
        },
    }.get(ablation_name, set())
    if ablation_name == "remove_all_english_derived_features" and (
        candidate.corpus_pair == "hb_gnt_english_bridge"
    ):
        return 0.0
    directional_scores: list[float] = []
    for direction in candidate.directions.values():
        best_by_family: dict[str, tuple[int, str]] = {}
        for detector, rank in direction.ranks.items():
            if detector in excluded:
                continue
            family = DETECTOR_FAMILIES[detector]
            previous = best_by_family.get(family)
            if previous is None or (rank, detector) < previous:
                best_by_family[family] = (rank, detector)
        directional_scores.append(
            math.fsum(
                1.0 / (context.config.composite.rrf_k + rank) for rank, _ in best_by_family.values()
            )
        )
    return max(directional_scores, default=0.0)


def _formulaic_evidence_present(
    candidate: CandidateAggregate,
    context: CandidateEvidenceContext,
    phrase_associations: PhraseAssociationIndex,
) -> bool:
    passage_a = context.sequences[candidate.passage_a_id]
    passage_b = context.sequences[candidate.passage_b_id]
    family, english = _active_family(candidate)
    namespace = _namespace(passage_a, english=english)
    shared = set(passage_a.values(family)).intersection(passage_b.values(family))
    if any(
        context.feature_statistics[(namespace, family, value)][4]
        for value in shared
        if (namespace, family, value) in context.feature_statistics
    ):
        return True
    phrases_a, _ = _phrases(
        passage_a.values(family),
        ngram_sizes=context.config.phrases.lemma_ngram_sizes,
        maximum_gap=context.config.skipgrams.maximum_gap,
    )
    phrases_b, _ = _phrases(
        passage_b.values(family),
        ngram_sizes=context.config.phrases.lemma_ngram_sizes,
        maximum_gap=context.config.skipgrams.maximum_gap,
    )
    for phrase in (phrases_a & phrases_b).intersection(phrase_associations.weights):
        key = (namespace, f"{family}_ngram", "\u241f".join(phrase))
        feature = context.feature_statistics.get(key)
        if feature is not None and feature[4]:
            return True
    return False


def _candidate_penalty_state(
    candidate: CandidateAggregate,
    *,
    context: CandidateEvidenceContext,
    phrase_associations: PhraseAssociationIndex,
    book_ordinals: Mapping[str, int],
) -> CandidatePenaltyState:
    passage_a = context.sequences[candidate.passage_a_id]
    passage_b = context.sequences[candidate.passage_b_id]
    family, _ = _active_family(candidate)
    nearby = (
        passage_a.corpus == passage_b.corpus
        and passage_a.book == passage_b.book
        and passage_a.analysis_profile == passage_b.analysis_profile
        and passage_a.analysis_reading == passage_b.analysis_reading
        and passage_a.granularity == passage_b.granularity
        and abs(book_ordinals[passage_a.passage_id] - book_ordinals[passage_b.passage_id])
        <= context.config.penalties.nearby_verse_distance
    )
    short = (
        min(len(passage_a.values(family)), len(passage_b.values(family)))
        <= context.config.penalties.short_passage_token_count
    )
    formulaic = _formulaic_evidence_present(candidate, context, phrase_associations)
    formulaic_fraction = context.config.penalties.formulaic_penalty if formulaic else 0.0
    local_fraction = context.config.penalties.local_context_penalty if nearby else 0.0
    short_fraction = context.config.penalties.short_passage_penalty if short else 0.0
    adjusted, contributions = _apply_penalties(
        candidate.best_rrf_score,
        formulaic_penalty=formulaic_fraction,
        local_context_penalty=local_fraction,
        short_passage_penalty=short_fraction,
    )
    return CandidatePenaltyState(
        formulaic_fraction=formulaic_fraction,
        local_context_fraction=local_fraction,
        short_passage_fraction=short_fraction,
        adjusted_score=adjusted,
        contributions=contributions,
    )


def _candidate_ablation_values(
    candidate: CandidateAggregate,
    penalty: CandidatePenaltyState,
    *,
    context: CandidateEvidenceContext,
) -> dict[str, CandidateAblationValue]:
    output: dict[str, CandidateAblationValue] = {}
    for name in context.config.ablations.names:
        raw_after = _rrf_without_ablation(candidate, name, context=context)
        formulaic = 0.0 if name == "remove_formulaic_penalty" else penalty.formulaic_fraction
        local = 0.0 if name == "remove_local_context_penalty" else penalty.local_context_fraction
        adjusted, contributions = _apply_penalties(
            raw_after,
            formulaic_penalty=formulaic,
            local_context_penalty=local,
            short_passage_penalty=penalty.short_passage_fraction,
        )
        output[name] = CandidateAblationValue(
            score=adjusted,
            penalty_magnitude=-math.fsum(contributions.values()),
        )
    return output


def _candidate_rank_maps(
    candidates: Mapping[str, CandidateAggregate],
    penalty_states: Mapping[str, CandidatePenaltyState],
    ablation_values: Mapping[str, Mapping[str, CandidateAblationValue]],
) -> tuple[dict[str, int], dict[tuple[str, str], int | None]]:
    before: dict[str, int] = {}
    after: dict[tuple[str, str], int | None] = {}
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate_id, candidate in candidates.items():
        groups[candidate.corpus_pair].append(candidate_id)
    for members in groups.values():
        ordered_before = sorted(
            members,
            key=lambda item: (-penalty_states[item].adjusted_score, item),
        )
        before.update((candidate_id, rank) for rank, candidate_id in enumerate(ordered_before, 1))
        ablation_names = tuple(ablation_values[ordered_before[0]]) if ordered_before else ()
        for name in ablation_names:
            positive = [item for item in members if ablation_values[item][name].score > 0.0]
            ordered_after = sorted(
                positive,
                key=lambda item: (-ablation_values[item][name].score, item),
            )
            ranks = {candidate_id: rank for rank, candidate_id in enumerate(ordered_after, 1)}
            for candidate_id in members:
                after[(candidate_id, name)] = ranks.get(candidate_id)
    return before, after


def _sequence_edit_distance(first: Sequence[str], second: Sequence[str]) -> int:
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, 1):
        current = [row]
        for column, right in enumerate(second, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def _near_exact_duplicate(
    passage_a: PassageLexicalSequence, passage_b: PassageLexicalSequence
) -> bool:
    surface_a = passage_a.values("surface")
    surface_b = passage_b.values("surface")
    if (
        passage_a.corpus != passage_b.corpus
        or not surface_a
        or not surface_b
        or surface_a == surface_b
    ):
        return False
    maximum = max(len(surface_a), len(surface_b))
    similarity = 1.0 - (_sequence_edit_distance(surface_a, surface_b) / maximum)
    return similarity >= 0.95


def _detector_rows(
    candidate: CandidateAggregate,
    scores: Mapping[str, float],
    *,
    context: CandidateEvidenceContext,
    traces_by_direction: Mapping[str, Mapping[str, Mapping[str, object]]],
    adjusted_rrf_score: float,
    total_penalty_contribution: float,
    penalty_components: Mapping[str, float],
) -> list[dict[str, object]]:
    representation_id = context.representation_ids.get(candidate.corpus_pair)
    if representation_id is None:
        raise CandidateMaterializationError(
            f"missing representation for corpus pair {candidate.corpus_pair!r}"
        )
    rows: list[dict[str, object]] = []
    rrf_direction = max(
        candidate.directions.values(), key=lambda item: (item.rrf_score, item.direction)
    )
    selected_by_family: dict[str, str] = {}
    for detector, rank in sorted(rrf_direction.ranks.items()):
        if detector not in DETECTOR_FAMILIES:
            raise CandidateMaterializationError(f"unknown detector in RRF ranks: {detector!r}")
        if rank < 1:
            raise CandidateMaterializationError(
                f"nonpositive detector rank for {candidate.candidate_pair_id}: {detector}"
            )
        family = DETECTOR_FAMILIES[detector]
        previous = selected_by_family.get(family)
        if previous is None or (rank, detector) < (rrf_direction.ranks[previous], previous):
            selected_by_family[family] = detector
    contributing_detectors = set(selected_by_family.values())
    expected_rrf = math.fsum(
        1.0 / (context.config.composite.rrf_k + rrf_direction.ranks[detector])
        for detector in sorted(contributing_detectors)
    )
    if not math.isclose(expected_rrf, rrf_direction.rrf_score, rel_tol=0.0, abs_tol=1e-12):
        raise CandidateMaterializationError(
            f"RRF contributions do not reconcile for {candidate.candidate_pair_id}: "
            f"{expected_rrf} != {rrf_direction.rrf_score}"
        )
    if not math.isclose(
        candidate.best_rrf_score,
        rrf_direction.rrf_score,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise CandidateMaterializationError(
            f"best RRF score is stale for {candidate.candidate_pair_id}"
        )
    for detector in (*DETECTOR_FAMILIES, "rrf_composite"):
        best_direction = max(
            candidate.directions.values(),
            key=lambda item: (
                item.rrf_score if detector == "rrf_composite" else item.scores.get(detector, 0.0),
                item.direction,
            ),
        )
        forward = candidate.directions.get("a_to_b")
        reverse = candidate.directions.get("b_to_a")
        query_rank = forward.ranks.get(detector) if forward is not None else None
        reverse_rank = reverse.ranks.get(detector) if reverse is not None else None
        contribution = 0.0
        if detector in contributing_detectors:
            contribution = 1.0 / (context.config.composite.rrf_k + rrf_direction.ranks[detector])
        if detector == "rrf_composite":
            components: dict[str, object] = {
                "formula": "sum(best_reciprocal_rank_per_detector_family)+penalty_contributions",
                "rrf_k": context.config.composite.rrf_k,
                "selected_detector_by_family": selected_by_family,
                "detector_ranks": rrf_direction.ranks,
                "raw_rrf_score": scores[detector],
                "penalty_components": dict(penalty_components),
                "adjusted_rrf_score": adjusted_rrf_score,
            }
            adjusted_score = adjusted_rrf_score
            penalty_contribution = total_penalty_contribution
        else:
            components = dict(traces_by_direction[best_direction.direction][detector])
            adjusted_score = scores[detector]
            penalty_contribution = 0.0
        components_json = _canonical_json(components)
        rows.append(
            {
                "candidate_pair_id": candidate.candidate_pair_id,
                "detector": detector,
                "representation_id": representation_id,
                "score": scores[detector],
                "quantized_score": round(
                    scores[detector], context.config.statistics.score_quantization_decimals
                ),
                "direction": best_direction.direction,
                "query_rank": query_rank,
                "reverse_rank": reverse_rank,
                "normalization_method": (
                    "decomposed_reciprocal_rank_fusion_family_best"
                    if detector == "rrf_composite"
                    else "detector_native_governed_v1"
                ),
                "score_contribution": contribution,
                "penalty_contribution": penalty_contribution,
                "adjusted_score": adjusted_score,
                "score_components_json": components_json,
                "score_trace_digest": hashlib.sha256(components_json.encode("utf-8")).hexdigest(),
                "config_hash": context.configuration_hash,
            }
        )
    return rows


def _materialize_one(
    candidate: CandidateAggregate,
    *,
    context: CandidateEvidenceContext,
    q_value: float,
    hypothesis_family_size: int,
    phrase_associations: PhraseAssociationIndex,
    penalty_state: CandidatePenaltyState,
    ablation_values: Mapping[str, CandidateAblationValue],
    rank_before: int,
    rank_after: Mapping[str, int | None],
    book_ordinals: Mapping[str, int] | None = None,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object] | None,
]:
    try:
        passage_a = context.sequences[candidate.passage_a_id]
        passage_b = context.sequences[candidate.passage_b_id]
    except KeyError as exc:
        raise CandidateMaterializationError(
            f"candidate references unavailable passage: {exc.args[0]}"
        ) from exc
    _validate_candidate_corpora(candidate, passage_a, passage_b)
    shared_rows, shared = _shared_evidence_rows(
        candidate,
        passage_a,
        passage_b,
        context=context,
        phrase_associations=phrase_associations,
    )
    scores = _best_scores(candidate)
    traces_by_direction = {
        name: _detector_score_traces(
            candidate,
            direction,
            context=context,
            phrase_associations=phrase_associations,
        )
        for name, direction in candidate.directions.items()
    }
    family, english = _active_family(candidate)
    values_a = passage_a.values(family)
    values_b = passage_b.values(family)
    lcs_length = _bitset_lcs_length(values_a, values_b)
    normalized_lcs = (
        lcs_length / min(len(values_a), len(values_b)) if values_a and values_b else 0.0
    )
    population, success_states, draws, observed = _hypergeometric_inputs(candidate, context)
    hypergeometric = hypergeometric_upper_tail(population, success_states, draws, observed)
    expected = success_states * draws / population if population else 0.0
    calibration = context.calibration.get(
        candidate.corpus_pair,
        CalibrationSelection(1.0, math.inf, math.inf, False),
    )
    ordinals = book_ordinals or context.book_ordinals
    nearby = (
        passage_a.corpus == passage_b.corpus
        and passage_a.book == passage_b.book
        and passage_a.analysis_profile == passage_b.analysis_profile
        and passage_a.analysis_reading == passage_b.analysis_reading
        and passage_a.granularity == passage_b.granularity
        and abs(ordinals[passage_a.passage_id] - ordinals[passage_b.passage_id])
        <= context.config.penalties.nearby_verse_distance
    )
    direct_adjacency = nearby and (
        abs(ordinals[passage_a.passage_id] - ordinals[passage_b.passage_id]) == 1
    )
    overlap = _passages_overlap(passage_a, passage_b)
    short = min(len(values_a), len(values_b)) <= context.config.penalties.short_passage_token_count
    surface_a = passage_a.values("surface")
    surface_b = passage_b.values("surface")
    exact_duplicate = (
        passage_a.corpus == passage_b.corpus and bool(surface_a) and surface_a == surface_b
    )
    near_exact_duplicate = _near_exact_duplicate(passage_a, passage_b)
    formulaic_penalty = penalty_state.formulaic_fraction
    local_penalty = penalty_state.local_context_fraction
    short_penalty = penalty_state.short_passage_fraction
    expected_formulaic = (
        context.config.penalties.formulaic_penalty if shared.formulaic_count else 0.0
    )
    if (
        formulaic_penalty != expected_formulaic
        or local_penalty != (context.config.penalties.local_context_penalty if nearby else 0.0)
        or short_penalty != (context.config.penalties.short_passage_penalty if short else 0.0)
    ):
        raise CandidateMaterializationError(
            f"precomputed penalty state does not reconcile for {candidate.candidate_pair_id}"
        )
    rare_rule = _rare_rule_result(
        shared,
        shared_rows,
        passage_a,
        passage_b,
        scores,
        context=context,
    )
    best_rrf_direction = max(
        candidate.directions.values(), key=lambda item: (item.rrf_score, item.direction)
    )
    best_trace = traces_by_direction[best_rrf_direction.direction]
    lcs_trace = best_trace["longest_common_subsequence"]
    lcs_features = tuple(str(value) for value in cast(Sequence[object], lcs_trace["features"]))
    if lcs_features:
        lcs_payload = {
            "candidate_pair_id": candidate.candidate_pair_id,
            "evidence_family": "longest_common_subsequence_trace",
            "features": lcs_features,
            "positions_a": lcs_trace["positions_a"],
            "positions_b": lcs_trace["positions_b"],
        }
        shared_rows.append(
            {
                "evidence_id": _hash_id("LE", lcs_payload),
                "candidate_pair_id": candidate.candidate_pair_id,
                "evidence_family": "longest_common_subsequence_trace",
                "feature_id": _hash_id("LF", lcs_payload),
                "feature_value": "\u241f".join(lcs_features),
                "passage_a_positions_json": _canonical_json(lcs_trace["positions_a"]),
                "passage_b_positions_json": _canonical_json(lcs_trace["positions_b"]),
                "corpus_frequency": 0,
                "document_frequency": 0,
                "passage_a_local_frequency": len(lcs_features),
                "passage_b_local_frequency": len(lcs_features),
                "association_score": cast(float, lcs_trace["normalized_score"]),
                "pmi": None,
                "log_likelihood": None,
                "frequency_control": None,
                "score_formula": "lcs_length/min(sequence_lengths)",
                "detector_contributions_json": _canonical_json(
                    {"longest_common_subsequence": cast(float, lcs_trace["normalized_score"])}
                ),
                "independence_expected_count": 0.0,
                "contains_primary_rare_item": False,
                "counts_as_independent_co_signal": False,
                "english_derived": english,
                "notes": "deterministic_lcs_traceback",
            }
        )
    alignment_trace = best_trace["weighted_sequence_alignment"]
    alignment_features = tuple(
        str(value) for value in cast(Sequence[object], alignment_trace["matched_features"])
    )
    if alignment_features and bool(alignment_trace["evaluated_in_bounded_rerank"]):
        alignment_payload = {
            "candidate_pair_id": candidate.candidate_pair_id,
            "evidence_family": "weighted_sequence_alignment_trace",
            "features": alignment_features,
            "positions_a": alignment_trace["matched_positions_a"],
            "positions_b": alignment_trace["matched_positions_b"],
        }
        shared_rows.append(
            {
                "evidence_id": _hash_id("LE", alignment_payload),
                "candidate_pair_id": candidate.candidate_pair_id,
                "evidence_family": "weighted_sequence_alignment_trace",
                "feature_id": _hash_id("LF", alignment_payload),
                "feature_value": "\u241f".join(alignment_features),
                "passage_a_positions_json": _canonical_json(alignment_trace["matched_positions_a"]),
                "passage_b_positions_json": _canonical_json(alignment_trace["matched_positions_b"]),
                "corpus_frequency": 0,
                "document_frequency": 0,
                "passage_a_local_frequency": len(alignment_features),
                "passage_b_local_frequency": len(alignment_features),
                "association_score": cast(float, alignment_trace["normalized_score"]),
                "pmi": None,
                "log_likelihood": None,
                "frequency_control": None,
                "score_formula": "local_idf_weighted_alignment/maximum_self_alignment",
                "detector_contributions_json": _canonical_json(
                    {
                        "weighted_sequence_alignment": cast(
                            float, alignment_trace["normalized_score"]
                        )
                    }
                ),
                "independence_expected_count": 0.0,
                "contains_primary_rare_item": False,
                "counts_as_independent_co_signal": False,
                "english_derived": english,
                "notes": "traceback=" + _canonical_json(alignment_trace["steps"]),
            }
        )
    total_penalty_contribution = math.fsum(penalty_state.contributions.values())
    detector_rows = _detector_rows(
        candidate,
        scores,
        context=context,
        traces_by_direction=traces_by_direction,
        adjusted_rrf_score=penalty_state.adjusted_score,
        total_penalty_contribution=total_penalty_contribution,
        penalty_components=penalty_state.contributions,
    )
    for row in shared_rows:
        row.pop("_source_tokens_a", None)
        row.pop("_source_tokens_b", None)
    rare_rule_passed = rare_rule.passed
    known = _reconciled_known_pair(context, candidate.passage_a_id, candidate.passage_b_id)
    known_status = (
        "represented_in_openbible_snapshot"
        if known is not None
        else "not_represented_in_openbible_snapshot"
    )
    ablation_survives = not english
    score_passes = penalty_state.adjusted_score >= calibration.score_threshold
    base_policy_without_score = all(
        (
            calibration.both_null_families_present,
            calibration.estimated_empirical_fdr
            <= context.config.candidate_thresholds.maximum_empirical_fdr,
            rare_rule_passed,
            known is None,
            not english,
            not overlap,
            not nearby,
            not exact_duplicate,
            not near_exact_duplicate,
        )
    )
    review_eligible = base_policy_without_score and score_passes
    reasons: list[str] = []
    if not calibration.both_null_families_present:
        reasons.append("both_null_families_required")
    if (
        calibration.estimated_empirical_fdr
        > context.config.candidate_thresholds.maximum_empirical_fdr
    ):
        reasons.append("empirical_fdr_exceeds_frozen_limit")
    if not score_passes:
        reasons.append("below_frozen_rrf_threshold")
    if not rare_rule_passed:
        reasons.append("rare_evidence_lacks_independent_cosignal")
    if known is not None:
        reasons.append("represented_in_openbible_snapshot")
    if english:
        reasons.append("english_only_ablation_failure")
    if overlap:
        reasons.append("passage_or_constituent_overlap")
    if nearby:
        reasons.append("nearby_context")
    if exact_duplicate:
        reasons.append("exact_duplicate_positive_control")
    if near_exact_duplicate:
        reasons.append("near_exact_duplicate_positive_control")
    if not reasons:
        reasons.append("passes_frozen_unreviewed_queue_policy")
    representation_id = context.representation_ids[candidate.corpus_pair]
    hypothesis_family_payload = {
        "corpus_pair": candidate.corpus_pair,
        "representation_id": representation_id,
        "selection_scope": "persisted_candidate_union_only_not_global_all_pairs",
    }
    hypothesis_family_id = _hash_id("LHF", hypothesis_family_payload)
    gloss_count_a = len(passage_a.english_gloss)
    gloss_count_b = len(passage_b.english_gloss)
    gloss_coverage_a = (
        len({item.token_id for item in passage_a.english_gloss}) / passage_a.token_count
        if passage_a.token_count
        else 0.0
    )
    gloss_coverage_b = (
        len({item.token_id for item in passage_b.english_gloss}) / passage_b.token_count
        if passage_b.token_count
        else 0.0
    )
    gloss_overlap_count = len(
        set(passage_a.values("english_gloss")).intersection(passage_b.values("english_gloss"))
    )
    classification_before = (
        "review_eligible_unreviewed" if review_eligible else "ineligible_unreviewed"
    )
    penalty_before = -total_penalty_contribution
    ablation_rows: list[dict[str, object]] = []
    for ablation_name in context.config.ablations.names:
        ablated = ablation_values[ablation_name]
        ablated_rank = rank_after[ablation_name]
        review_after = base_policy_without_score and (ablated.score >= calibration.score_threshold)
        if ablation_name == "remove_all_english_derived_features" and english:
            classification_after = "no_cross_language_lexical_score_after_ablation"
        elif review_after:
            classification_after = "counterfactual_eligible_no_model_selection"
        else:
            classification_after = "counterfactual_ineligible_no_model_selection"
        changed = (
            not math.isclose(
                penalty_state.adjusted_score, ablated.score, rel_tol=0.0, abs_tol=1e-15
            )
            or rank_before != ablated_rank
            or not math.isclose(
                penalty_before, ablated.penalty_magnitude, rel_tol=0.0, abs_tol=1e-15
            )
        )
        ablation_payload = {
            "experiment_run_id": context.experiment_run_id,
            "ablation_name": ablation_name,
            "subject_type": "candidate_pair",
            "subject_id": candidate.candidate_pair_id,
            "candidate_pair_id": candidate.candidate_pair_id,
            "ranking_id": None,
            "corpus_pair": candidate.corpus_pair,
            "representation_id": representation_id,
            "detector": "rrf_composite",
            "direction": "canonical_unordered_pair",
            "query_passage_id": candidate.passage_a_id,
            "target_passage_id": candidate.passage_b_id,
            "query_gloss_feature_count": gloss_count_a,
            "target_gloss_feature_count": gloss_count_b,
            "query_token_count": passage_a.token_count,
            "target_token_count": passage_b.token_count,
            "query_gloss_coverage": gloss_coverage_a,
            "target_gloss_coverage": gloss_coverage_b,
            "gloss_overlap_count": gloss_overlap_count,
            "score_before": penalty_state.adjusted_score,
            "score_after": ablated.score,
            "rank_before": rank_before,
            "rank_after": ablated_rank,
            "penalty_before": penalty_before,
            "penalty_after": ablated.penalty_magnitude,
            "contains_english_derived_evidence": english,
            "non_english_evidence_remains": not english,
            "review_eligible_before": review_eligible,
            "review_eligible_after": review_after,
            "classification_before": classification_before,
            "classification_after": classification_after,
            "downgrade_required": (
                (review_eligible and not review_after)
                or (english and ablation_name == "remove_all_english_derived_features")
            ),
            "changed": changed,
            "config_hash": context.configuration_hash,
        }
        ablation_digest = ablation_result_digest(ablation_payload)
        ablation_rows.append(
            {
                "ablation_result_id": "LXA_" + ablation_digest,
                **ablation_payload,
                "evidence_digest": ablation_digest,
            }
        )
    detector_digest = detector_trace_digest(detector_rows)
    ablation_digest = ablation_family_digest(ablation_rows)
    shared_digest = shared_evidence_digest(shared_rows)
    evidence_row = {
        "candidate_pair_id": candidate.candidate_pair_id,
        "shared_lemma_count": len(shared.shared) if family == "lemma" else 0,
        "shared_root_count": len(shared.shared_roots),
        "shared_surface_count": len(shared.shared_surfaces),
        "shared_rare_lemma_count": len(shared.shared_rare) if family == "lemma" else 0,
        "shared_rare_root_count": len(shared.shared_rare_roots),
        "shared_phrase_count": len(shared.shared_phrases) + len(shared.shared_root_phrases),
        "shared_skipgram_count": len(shared.shared_skips) + len(shared.shared_root_skips),
        "lcs_length": lcs_length,
        "normalized_lcs": normalized_lcs,
        "weighted_alignment_score": scores["weighted_sequence_alignment"],
        "weighted_jaccard_score": scores["weighted_jaccard"],
        "tfidf_score": scores["tfidf_cosine"],
        "bm25_score": scores["bm25"],
        "rare_overlap_score": scores["rare_lemma_root"],
        "phrase_score": scores["phrase_association"],
        "ordered_sequence_score": max(
            scores["longest_common_subsequence"], scores["weighted_sequence_alignment"]
        ),
        "raw_rrf_score": scores["rrf_composite"],
        "rrf_score": penalty_state.adjusted_score,
        "expected_overlap_independence": expected,
        "hypergeometric_p_value": hypergeometric.upper_tail_p_value,
        "benjamini_hochberg_q_value": q_value,
        "hypergeometric_population_size": population,
        "hypergeometric_success_states": success_states,
        "hypergeometric_draws": draws,
        "hypergeometric_observed_overlap": observed,
        "hypothesis_family_id": hypothesis_family_id,
        "hypothesis_family_size": hypothesis_family_size,
        "hypothesis_selection_scope": str(hypothesis_family_payload["selection_scope"]),
        "null_model_empirical_rate": calibration.empirical_rate,
        "estimated_empirical_fdr": calibration.estimated_empirical_fdr,
        "selected_score_threshold": calibration.score_threshold,
        "both_null_families_present": calibration.both_null_families_present,
        "calibration_selection_scope": "frozen_corpus_pair_rrf_threshold",
        "independent_co_signal_count": rare_rule.independent_co_signal_count,
        "rare_rule_passed": rare_rule_passed,
        "formulaic_penalty": formulaic_penalty,
        "local_context_penalty": local_penalty,
        "short_passage_penalty": short_penalty,
        "total_penalty_contribution": total_penalty_contribution,
        "overlap_exclusion": overlap,
        "detector_trace_digest": detector_digest,
        "ablation_digest": ablation_digest,
        "evidence_digest": "",
    }
    evidence_row["evidence_digest"] = candidate_evidence_digest(
        evidence_row,
        shared_digest=shared_digest,
        detector_digest=detector_digest,
        ablation_digest=ablation_digest,
    )
    pair_row = {
        "candidate_pair_id": candidate.candidate_pair_id,
        "canonical_unordered_pair_id": candidate.canonical_unordered_pair_id,
        "experiment_run_id": context.experiment_run_id,
        "passage_a_id": candidate.passage_a_id,
        "passage_b_id": candidate.passage_b_id,
        "passage_a_reference": passage_a.start_reference,
        "passage_b_reference": passage_b.start_reference,
        "passage_a_book": passage_a.book,
        "passage_b_book": passage_b.book,
        "passage_a_reading": passage_a.analysis_reading,
        "passage_b_reading": passage_b.analysis_reading,
        "passage_a_token_count": passage_a.token_count,
        "passage_b_token_count": passage_b.token_count,
        "corpus_pair": candidate.corpus_pair,
        "analysis_profile": candidate.analysis_profile,
        "granularity": candidate.granularity,
        "directional_support_count": len(candidate.directions),
        "detector_support_count": sum(scores[detector] > 0.0 for detector in DETECTOR_FAMILIES),
        "known_link_status": known_status,
        "openbible_relationship_ids_json": _canonical_json(
            list(known.relationship_ids) if known else []
        ),
        "highest_openbible_vote": known.highest_vote if known else None,
        "benchmark_tier": 3 if known else None,
        "mapping_quality": known.mapping_quality if known else "not_applicable",
        "disputed_passage_flag": passage_a.disputed_passage_flag or passage_b.disputed_passage_flag,
        "reference_gap": passage_a.reference_gap or passage_b.reference_gap,
        "ketiv_structural_uncertainty": (
            passage_a.ketiv_structural_uncertainty or passage_b.ketiv_structural_uncertainty
        ),
        "direct_adjacency": direct_adjacency,
        "nearby_context": nearby,
        "same_book": passage_a.corpus == passage_b.corpus and passage_a.book == passage_b.book,
        "exact_duplicate": exact_duplicate,
        "near_exact_duplicate": near_exact_duplicate,
        "formulaic_evidence_flag": formulaic_penalty > 0.0,
        "genealogical_formula_pattern_flag": False,
        "legal_formula_pattern_flag": False,
        "formula_pattern_annotation_status": (
            "frequency_formulaic_only_semantic_subtype_unavailable"
        ),
        "proper_name_only_flag": False,
        "proper_name_annotation_status": "unavailable_no_source_entity_annotation",
        "contains_english_derived_evidence": english,
        "passage_a_gloss_feature_count": gloss_count_a,
        "passage_b_gloss_feature_count": gloss_count_b,
        "passage_a_gloss_coverage": gloss_coverage_a,
        "passage_b_gloss_coverage": gloss_coverage_b,
        "gloss_overlap_count": gloss_overlap_count,
        "score_with_english_features": penalty_state.adjusted_score if english else None,
        "score_after_removing_all_english_features": 0.0 if english else None,
        "rank_with_english_features": rank_before if english else None,
        "rank_after_removing_all_english_features": (
            rank_after["remove_all_english_derived_features"] if english else None
        ),
        "non_english_evidence_remains": not english,
        "english_ablation_survives": ablation_survives,
        "classification_after_english_ablation": (
            "no_cross_language_lexical_score_after_ablation"
            if english
            else "original_language_candidate_unchanged"
        ),
        "review_eligible": review_eligible,
        "eligibility_reason": ";".join(reasons),
    }
    queue = None
    if review_eligible:
        queue = {
            "candidate_pair_id": candidate.candidate_pair_id,
            "passage_a_reference": passage_a.start_reference,
            "passage_b_reference": passage_b.start_reference,
            "corpus_pair": candidate.corpus_pair,
            "raw_rrf_score": scores["rrf_composite"],
            "rrf_score": penalty_state.adjusted_score,
            "total_penalty_contribution": total_penalty_contribution,
            "detector_support_count": pair_row["detector_support_count"],
            "rare_rule_passed": rare_rule_passed,
            "estimated_empirical_fdr": calibration.estimated_empirical_fdr,
            "known_link_status": known_status,
            "contains_english_derived_evidence": english,
            "english_ablation_survives": ablation_survives,
            "disputed_passage_flag": pair_row["disputed_passage_flag"],
            "reference_gap": pair_row["reference_gap"],
            "ketiv_structural_uncertainty": pair_row["ketiv_structural_uncertainty"],
            "review_eligible": True,
        }
    return pair_row, detector_rows, evidence_row, shared_rows, ablation_rows, queue


def _materialize_candidate_rank_table(
    rank_connection: duckdb.DuckDBPyConnection,
    *,
    rank_expressions: str,
) -> None:
    """Compute the governed global rank windows once in a spillable DuckDB table."""
    rank_connection.execute(
        "CREATE TABLE candidate_ranks AS SELECT *,row_number() OVER "
        "(PARTITION BY corpus_pair ORDER BY score_before DESC,candidate_pair_id) "
        f"AS rank_before,{rank_expressions} FROM rank_inputs"
    )
    rank_connection.execute("DROP TABLE rank_inputs")


def iter_candidate_artifact_batches(
    candidates: Mapping[str, CandidateAggregate],
    *,
    context: CandidateEvidenceContext,
    q_values: Mapping[str, float],
    batch_size: int = 5_000,
    duckdb_memory_limit_bytes: int = 512 * MEBIBYTE,
    resource_check: CandidateResourceCheck | None = None,
    materialization_target_bytes: int = _CANDIDATE_OUTPUT_TARGET_BYTES,
) -> Iterator[CandidateArtifactBatch]:
    """Yield deterministic bounded evidence frames for all persisted candidates."""

    if batch_size < 1:
        raise CandidateMaterializationError("candidate batch size must be positive")
    if materialization_target_bytes < 1:
        raise CandidateMaterializationError("candidate materialization target must be positive")
    if resource_check is not None:
        resource_check(
            "candidate_materialization:ordered_ids",
            estimated_additional_bytes=max(16 * MEBIBYTE, len(candidates) * 256),
        )
    ordered = sorted(candidates)
    missing_q_values = sorted(set(ordered).difference(q_values))
    extra_q_values = sorted(set(q_values).difference(ordered))
    if missing_q_values or extra_q_values:
        raise CandidateMaterializationError(
            "candidate/q-value identity mismatch: "
            f"missing={missing_q_values[:5]}, extra={extra_q_values[:5]}"
        )
    book_ordinals = context.book_ordinals
    phrase_indexes = _phrase_association_indexes(context)
    family_sizes: Counter[tuple[str, str]] = Counter(
        (
            candidate.corpus_pair,
            context.representation_ids[candidate.corpus_pair],
        )
        for candidate in candidates.values()
    )
    ablation_names = tuple(context.config.ablations.names)
    if ablation_names != tuple(_ABLATION_NAMES):
        raise CandidateMaterializationError("candidate ablations differ from the frozen order")
    score_columns = ",".join(f'"{name}" DOUBLE' for name in ablation_names)
    insert_placeholders = ",".join("?" for _ in range(3 + len(ablation_names)))
    materialization_batch_index = 0

    def materialize_frames(
        pair_rows: list[dict[str, object]],
        score_rows: list[dict[str, object]],
        evidence_rows: list[dict[str, object]],
        shared_rows: list[dict[str, object]],
        ablation_rows: list[dict[str, object]],
        queue_rows: list[dict[str, object]],
        estimated_bytes: int,
    ) -> CandidateArtifactBatch:
        nonlocal materialization_batch_index
        if resource_check is not None:
            resource_check(
                f"candidate_materialization:frames:{materialization_batch_index}",
                estimated_additional_bytes=max(
                    64 * MEBIBYTE,
                    estimated_bytes * _CANDIDATE_FRAME_MULTIPLIER,
                ),
            )
        materialization_batch_index += 1
        return CandidateArtifactBatch(
            candidate_pairs=pl.DataFrame(pair_rows, schema=CANDIDATE_PAIRS_SCHEMA, orient="row"),
            detector_scores=pl.DataFrame(
                score_rows, schema=CANDIDATE_DETECTOR_SCORES_SCHEMA, orient="row"
            ),
            candidate_evidence=pl.DataFrame(
                evidence_rows, schema=CANDIDATE_EVIDENCE_SCHEMA, orient="row"
            ),
            shared_evidence=pl.DataFrame(shared_rows, schema=SHARED_EVIDENCE_SCHEMA, orient="row"),
            ablation_results=pl.DataFrame(
                ablation_rows, schema=ABLATION_RESULTS_SCHEMA, orient="row"
            ),
            queue_candidates=tuple(queue_rows),
        )

    with (
        TemporaryDirectory(prefix="echoes-candidate-ranks-") as temporary,
        duckdb.connect(str(Path(temporary) / "candidate-ranks.duckdb")) as rank_connection,
    ):
        configure_duckdb_connection(
            rank_connection,
            memory_limit_bytes=duckdb_memory_limit_bytes,
            temp_directory=Path(temporary) / "spill",
            thread_count=1,
        )
        rank_connection.execute(
            "CREATE TABLE rank_inputs(candidate_pair_id VARCHAR,corpus_pair VARCHAR,"
            f"score_before DOUBLE,{score_columns})"
        )
        rank_buffer: list[tuple[object, ...]] = []
        for candidate_id in ordered:
            candidate = candidates[candidate_id]
            penalty = _candidate_penalty_state(
                candidate,
                context=context,
                phrase_associations=phrase_indexes[candidate.corpus_pair],
                book_ordinals=book_ordinals,
            )
            ablated = _candidate_ablation_values(candidate, penalty, context=context)
            rank_buffer.append(
                (
                    candidate_id,
                    candidate.corpus_pair,
                    penalty.adjusted_score,
                    *(ablated[name].score for name in ablation_names),
                )
            )
            if len(rank_buffer) >= batch_size:
                rank_connection.executemany(
                    f"INSERT INTO rank_inputs VALUES ({insert_placeholders})", rank_buffer
                )
                rank_buffer.clear()
        if rank_buffer:
            rank_connection.executemany(
                f"INSERT INTO rank_inputs VALUES ({insert_placeholders})", rank_buffer
            )
        rank_expressions = ",".join(
            (
                f'CASE WHEN "{name}">0.0 THEN row_number() OVER '
                f'(PARTITION BY corpus_pair ORDER BY ("{name}">0.0) DESC,'
                f'"{name}" DESC,candidate_pair_id) END AS "rank_{name}"'
            )
            for name in ablation_names
        )
        if resource_check is not None:
            resource_check(
                "candidate_materialization:materialize_global_ranks",
                estimated_additional_bytes=64 * MEBIBYTE,
            )
        # Materialize the global windows once.  A view causes DuckDB to
        # recompute all nine corpus-pair rank windows for every bounded ID
        # lookup below; at production scale that repeated work eventually
        # exhausted the allocator even though each requested batch was small.
        # The table retains the identical SQL, ordering, and global candidate
        # population while allowing DuckDB to spill the one bounded
        # computation through the configured temporary directory.
        _materialize_candidate_rank_table(
            rank_connection,
            rank_expressions=rank_expressions,
        )
        for start in range(0, len(ordered), batch_size):
            batch_ids = ordered[start : start + batch_size]
            if resource_check is not None:
                resource_check(
                    f"candidate_materialization:rank_batch:{start // batch_size}",
                    estimated_additional_bytes=max(32 * MEBIBYTE, len(batch_ids) * 8192),
                )
            placeholders = ",".join("?" for _ in batch_ids)
            cursor = rank_connection.execute(
                f"SELECT * FROM candidate_ranks WHERE candidate_pair_id IN ({placeholders})",
                batch_ids,
            )
            rank_columns = [description[0] for description in cursor.description]
            ranks = {
                str(row[0]): dict(zip(rank_columns, row, strict=True)) for row in cursor.fetchall()
            }
            pair_rows: list[dict[str, object]] = []
            score_rows: list[dict[str, object]] = []
            evidence_rows: list[dict[str, object]] = []
            shared_rows: list[dict[str, object]] = []
            ablation_rows: list[dict[str, object]] = []
            queue_rows: list[dict[str, object]] = []
            estimated_materialization_bytes = 0
            for candidate_id in batch_ids:
                candidate = candidates[candidate_id]
                candidate_reservation = _candidate_output_reservation_bytes(candidate, context)
                if (
                    pair_rows
                    and estimated_materialization_bytes + candidate_reservation
                    > materialization_target_bytes
                ):
                    yield materialize_frames(
                        pair_rows,
                        score_rows,
                        evidence_rows,
                        shared_rows,
                        ablation_rows,
                        queue_rows,
                        estimated_materialization_bytes,
                    )
                    pair_rows = []
                    score_rows = []
                    evidence_rows = []
                    shared_rows = []
                    ablation_rows = []
                    queue_rows = []
                    estimated_materialization_bytes = 0
                if resource_check is not None:
                    resource_check(
                        f"candidate_materialization:candidate:{candidate_id}",
                        estimated_additional_bytes=(
                            candidate_reservation * _CANDIDATE_FRAME_MULTIPLIER
                        ),
                    )
                penalty = _candidate_penalty_state(
                    candidate,
                    context=context,
                    phrase_associations=phrase_indexes[candidate.corpus_pair],
                    book_ordinals=book_ordinals,
                )
                ablated = _candidate_ablation_values(candidate, penalty, context=context)
                rank_row = ranks[candidate_id]
                materialized = _materialize_one(
                    candidate,
                    context=context,
                    q_value=q_values[candidate_id],
                    hypothesis_family_size=family_sizes[
                        (
                            candidate.corpus_pair,
                            context.representation_ids[candidate.corpus_pair],
                        )
                    ],
                    phrase_associations=phrase_indexes[candidate.corpus_pair],
                    penalty_state=penalty,
                    ablation_values=ablated,
                    rank_before=int(str(rank_row["rank_before"])),
                    rank_after={
                        name: (
                            int(str(rank_row[f"rank_{name}"]))
                            if rank_row[f"rank_{name}"] is not None
                            else None
                        )
                        for name in ablation_names
                    },
                    book_ordinals=book_ordinals,
                )
                pair, scores, evidence, shared, ablations, queue = materialized
                pair_rows.append(pair)
                score_rows.extend(scores)
                evidence_rows.append(evidence)
                shared_rows.extend(shared)
                ablation_rows.extend(ablations)
                if queue is not None:
                    queue_rows.append(queue)
                actual_row_count = (
                    2 + len(scores) + len(shared) + len(ablations) + int(queue is not None)
                )
                estimated_materialization_bytes += max(
                    candidate_reservation,
                    actual_row_count * _CANDIDATE_OUTPUT_ROW_BYTES,
                )
            if pair_rows:
                yield materialize_frames(
                    pair_rows,
                    score_rows,
                    evidence_rows,
                    shared_rows,
                    ablation_rows,
                    queue_rows,
                    estimated_materialization_bytes,
                )


def build_review_queue(rows: Iterable[dict[str, object]]) -> pl.DataFrame:
    """Rank the frozen-policy queue without adding any human-review decision."""

    materialized = list(rows)
    candidate_ids = [str(row.get("candidate_pair_id", "")) for row in materialized]
    if any(not candidate_id for candidate_id in candidate_ids):
        raise CandidateMaterializationError("queue rows require candidate-pair IDs")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise CandidateMaterializationError("queue rows contain duplicate candidate-pair IDs")
    for row in materialized:
        score = float(str(row.get("rrf_score", "nan")))
        if not math.isfinite(score):
            raise CandidateMaterializationError("queue RRF scores must be finite")
        if row.get("review_eligible") is not True:
            raise CandidateMaterializationError("queue rows must be review-eligible")
        if row.get("known_link_status") != "not_represented_in_openbible_snapshot":
            raise CandidateMaterializationError(
                "OpenBible-represented or unresolved pairs cannot enter the queue"
            )
        if (
            row.get("contains_english_derived_evidence") is True
            and row.get("english_ablation_survives") is not True
        ):
            raise CandidateMaterializationError(
                "English-only ablation failures cannot enter the queue"
            )
    ordered = sorted(
        materialized,
        key=lambda row: (
            -float(str(row["rrf_score"])),
            str(row["candidate_pair_id"]),
        ),
    )
    ranked = [{"queue_rank": rank, **row} for rank, row in enumerate(ordered, start=1)]
    return pl.DataFrame(ranked, schema=CANDIDATE_REVIEW_QUEUE_SCHEMA, orient="row")
