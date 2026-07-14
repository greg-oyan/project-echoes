# ruff: noqa: E402
"""End-to-end deterministic Milestone 7 transparent lexical pipeline."""

from __future__ import annotations

import gc
import hashlib
import json
import math
import platform
import shutil
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from echoes.lexical.resources import (
    MEBIBYTE,
    LexicalResourceError,
    ProcessResourceGuard,
    configure_duckdb_connection,
    enforce_thread_controls,
    initialize_thread_controls,
)

# Numeric thread pools read these variables at import time.  The governed M7
# configuration is single-threaded; the runtime check below rejects any drift.
initialize_thread_controls(1)

import duckdb
import polars as pl

from echoes.corpus.storage import logical_frame_hash
from echoes.lexical.anchors import AnchorVerification, verify_upstream_anchors
from echoes.lexical.candidates import (
    CandidateEvidenceContext,
    build_feature_evidence_indexes,
    build_review_queue,
    candidate_q_values,
    iter_candidate_artifact_batches,
    load_known_pair_index,
)
from echoes.lexical.config import (
    AnalysisProfile,
    CorpusPair,
    FeatureFamily,
    Granularity,
    LexicalConfig,
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    validate_preregistration_against_config,
)
from echoes.lexical.experiment import (
    LexicalExperimentError,
    Tier3EvaluationScope,
    combine_lexical_experiment_artifacts,
    governed_detectors_by_corpus_pair,
    run_null_calibration_experiment,
    run_tier3_evaluation_experiment,
)
from echoes.lexical.features import (
    build_feature_vocabulary,
    build_passage_feature_statistics,
    combine_feature_vocabularies,
)
from echoes.lexical.identity import (
    FeatureIdentityPayload,
    LanguageNamespace,
    RepresentationIdentityPayload,
    build_feature_identity,
    build_representation_identity,
)
from echoes.lexical.models import (
    CANDIDATE_REVIEW_QUEUE_SCHEMA,
    FEATURE_VOCABULARY_SCHEMA,
    LEXICAL_INDEX_METADATA_SCHEMA,
    LEXICAL_ISSUES_SCHEMA,
    LEXICAL_METADATA_SCHEMA,
    SENSITIVITY_RESULTS_SCHEMA,
)
from echoes.lexical.retrieval import CandidateAggregate, iter_retrieval_batches
from echoes.lexical.sequences import (
    PassageLexicalSequence,
    iter_passage_sequences,
    sequence_digest,
)
from echoes.lexical.sparse import SparseLexicalIndex, build_sparse_index, persist_sparse_index
from echoes.lexical.storage import (
    LexicalArtifactWriter,
    ProcessedLexical,
    load_lexical_duckdb,
)
from echoes.lexical.validation import sparse_index_physical_hash
from echoes.settings import BenchmarkConfig, load_config

DEFAULT_DATABASE_PATH = Path("data/processed/project_echoes.duckdb")
DEFAULT_PASSAGE_ROOT = Path("data/processed/passages/schema-v1")
DEFAULT_BENCHMARK_ROOT = Path("data/processed/benchmarks/schema-v1")
DEFAULT_OSHB_ROOT = Path("data/processed/oshb-morphhb/master-3d15126")
DEFAULT_TIER1_PATH = Path("data/benchmarks/tier1_quotations.csv")
DEFAULT_LEXICAL_ROOT = Path("data/processed/lexical/schema-v1")

_DUCKDB_PREFERRED_MEMORY_BYTES = 512 * MEBIBYTE
_PROVENANCE_DUCKDB_PREFERRED_MEMORY_BYTES = 1536 * MEBIBYTE
_DUCKDB_PYTHON_RESERVE_BYTES = 512 * MEBIBYTE
_SEQUENCE_LOAD_RESERVATION_BYTES = 512 * MEBIBYTE
_FEATURE_VOCABULARY_RESERVATION_BYTES = 768 * MEBIBYTE
_PASSAGE_STATISTICS_RESERVATION_BYTES = 512 * MEBIBYTE
_CANDIDATE_EVIDENCE_RESERVATION_BYTES = 768 * MEBIBYTE
_REVIEW_QUEUE_READ_BATCH_SIZE = 10_000


class LexicalPipelineError(RuntimeError):
    """Raised when the governed Milestone 7 pipeline cannot finish safely."""


class _ResourceCheck(Protocol):
    def __call__(self, stage: str, *, estimated_additional_bytes: int = 0) -> None: ...


@dataclass(frozen=True, slots=True)
class LexicalPipelineResult:
    """Report-ready result from one complete atomic lexical run."""

    experiment_run_id: str
    experiment_version: str
    configuration_hash: str
    preregistration_hash: str
    anchors: AnchorVerification
    processed: ProcessedLexical
    database_path: Path
    stage_runtime_seconds: dict[str, float]
    feature_counts: dict[str, int]
    index_summaries: dict[str, dict[str, object]]
    ranking_count: int
    candidate_count: int
    review_eligible_count: int
    queue_count: int
    null_iteration_count: int
    evaluation_count: int
    acceptance_status: str
    approximate_peak_memory_bytes: int


@dataclass(frozen=True, slots=True)
class _IndexDefinition:
    key: str
    sequences: Sequence[PassageLexicalSequence]
    family: str
    namespace: str
    corpus_scope: tuple[str, ...]
    reading: str
    analysis_profile: str
    granularity: str
    retain_for_retrieval: bool = True


@dataclass(frozen=True, slots=True)
class _RetrievalScopeResult:
    candidates: dict[str, CandidateAggregate]
    ranking_count: int
    next_ranking_part: int
    next_ablation_part: int


@contextmanager
def _bounded_duckdb_connection(
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    database_path: Path | None = None,
    read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open one connection with explicit single-thread, memory, and spill limits."""

    if temp_directory.exists():
        raise LexicalPipelineError(f"DuckDB spill directory already exists: {temp_directory}")
    try:
        if database_path is None:
            connection = duckdb.connect()
        else:
            connection = duckdb.connect(str(database_path), read_only=read_only)
        try:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=memory_limit_bytes,
                temp_directory=temp_directory,
                thread_count=1,
            )
            yield connection
        finally:
            connection.close()
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


@contextmanager
def _managed_temp_directory(path: Path) -> Iterator[Path]:
    """Create one fail-closed pipeline spill directory and always remove it."""

    if path.exists():
        raise LexicalPipelineError(f"pipeline spill directory already exists: {path}")
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sparse_index_reservation_bytes(definition: _IndexDefinition) -> int:
    """Conservatively reserve transient Python/CSR construction memory."""

    occurrence_count = sum(
        len(passage.values(definition.family)) for passage in definition.sequences
    )
    estimated = occurrence_count * 384 + len(definition.sequences) * 4096
    return max(256 * MEBIBYTE, estimated)


def _retrieval_reservation_bytes(config: LexicalConfig) -> int:
    """Reserve a bounded query block plus detector/rerank working state."""

    hits_per_query = (
        config.retrieval.candidate_union_k
        + config.retrieval.persisted_top_k
        + config.retrieval.persisted_candidate_pool_k
        + config.retrieval.expensive_sequence_rerank_k
    )
    estimated = config.resource_limits.block_passage_count * hits_per_query * 128
    return max(256 * MEBIBYTE, estimated)


def build_experiment_run_id(
    *,
    configuration_hash: str,
    preregistration_hash: str,
    anchors: AnchorVerification,
) -> str:
    """Derive the run ID only from frozen methodology and anchored inputs."""

    digest = _sha256_json(
        {
            "schema": 1,
            "configuration_hash": configuration_hash,
            "preregistration_hash": preregistration_hash,
            "corpus_identity": anchors.corpus_identity_digests,
            "corpus_content": anchors.corpus_content_digests,
            "corpus_analytical": anchors.corpus_analytical_digests,
            "oshb": anchors.oshb_logical_hashes,
            "passages": anchors.passage_logical_hashes,
            "benchmark": anchors.benchmark_logical_hashes,
            "tier1": anchors.tier1_sha256,
        }
    )
    return f"lexical-v1-{digest[:20]}"


def _time_stage(
    timings: dict[str, float],
    name: str,
    operation: object,
) -> object:
    start = time.perf_counter()
    if not callable(operation):
        raise TypeError("stage operation must be callable")
    result = operation()
    timings[name] = time.perf_counter() - start
    return result


def _book_genres() -> dict[str, str]:
    loaded = load_config(Path("config/benchmark.yaml"))
    if not isinstance(loaded, BenchmarkConfig):
        raise LexicalPipelineError("config/benchmark.yaml did not load as BenchmarkConfig")
    return dict(loaded.book_genres)


def _load_split_provenance(
    database_path: Path,
    sequences: Sequence[PassageLexicalSequence],
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    resource_check: _ResourceCheck | None = None,
) -> dict[str, str]:
    """Load compact, actual Tier-3 split/leakage facts for ranked passages once."""

    passage_ids = sorted({item.passage_id for item in sequences})
    if not passage_ids:
        return {}
    if resource_check is not None:
        resource_check(
            "benchmark_split_provenance:before",
            estimated_additional_bytes=(duckdb_memory_limit_bytes + 768 * MEBIBYTE),
        )
    query = """
        WITH mapped AS (
          SELECT json_extract_string(j.value, '$') AS passage_id,
                 r.relationship_id,
                 m.mapping_status
          FROM benchmark_endpoint_mappings m
          JOIN benchmark_endpoints e USING (endpoint_id)
          JOIN benchmark_relationships r USING (relationship_id),
          LATERAL json_each(m.target_passage_ids_json) j
          WHERE r.tier=3
            AND m.target_granularity='verse'
            AND json_extract_string(j.value, '$') = ANY(?)
        )
        SELECT mapped.passage_id,
               s.benchmark_version,
               s.split_strategy,
               s.partition,
               s.eligibility_status,
               coalesce(s.exclusion_reason, '') AS exclusion_reason,
               mapped.mapping_status,
               count(DISTINCT mapped.relationship_id) AS relationship_count,
               count(DISTINCT s.leakage_group_id) AS leakage_group_count,
               list_sort(
                 list(DISTINCT s.leakage_group_id)
                   FILTER (WHERE s.leakage_group_id IS NOT NULL)
               ) AS leakage_group_ids,
               bool_and(s.leakage_group_id IS NOT NULL) AS leakage_membership_complete
        FROM mapped
        JOIN benchmark_split_assignments s USING (relationship_id)
        GROUP BY mapped.passage_id, s.benchmark_version, s.split_strategy,
                 s.partition, s.eligibility_status, exclusion_reason,
                 mapped.mapping_status
        ORDER BY mapped.passage_id, s.split_strategy, s.partition,
                 s.eligibility_status, mapped.mapping_status
    """
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            cursor = connection.execute(query, [passage_ids])
            while rows := cursor.fetchmany(50_000):
                for (
                    passage_id,
                    benchmark_version,
                    split_strategy,
                    partition,
                    eligibility_status,
                    exclusion_reason,
                    mapping_status,
                    relationship_count,
                    leakage_group_count,
                    leakage_group_ids,
                    leakage_membership_complete,
                ) in rows:
                    grouped[str(passage_id)].append(
                        {
                            "benchmark_version": str(benchmark_version),
                            "split_strategy": str(split_strategy),
                            "partition": str(partition),
                            "eligibility_status": str(eligibility_status),
                            "exclusion_reason": str(exclusion_reason),
                            "mapping_status": str(mapping_status),
                            "relationship_count": int(relationship_count),
                            "leakage_group_count": int(leakage_group_count),
                            "leakage_group_ids": sorted(
                                str(group_id) for group_id in (leakage_group_ids or [])
                            ),
                            "leakage_membership_complete": bool(leakage_membership_complete),
                        }
                    )
    except (duckdb.Error, OSError) as exc:
        raise LexicalPipelineError(
            f"could not load anchored benchmark split provenance: {exc}"
        ) from exc
    output: dict[str, str] = {}
    for passage_id, assignments in sorted(grouped.items()):
        # DuckDB's grouped result can contain rows tied on the human-facing
        # ORDER BY fields.  The digest commits to every field, so impose a total
        # canonical order in Python before hashing or deriving summaries.
        assignments = sorted(assignments, key=_canonical_json)
        has_eligible = any(
            item["eligibility_status"] == "eligible"
            and item["partition"] != "excluded"
            and item["leakage_membership_complete"] is True
            for item in assignments
        )
        eligible_partitions: dict[str, list[str]] = {}
        for strategy in sorted({str(item["split_strategy"]) for item in assignments}):
            eligible_partitions[strategy] = sorted(
                {
                    str(item["partition"])
                    for item in assignments
                    if item["split_strategy"] == strategy
                    and item["eligibility_status"] == "eligible"
                    and item["partition"] != "excluded"
                }
            )
        leakage_group_ids = sorted(
            {
                str(group_id)
                for item in assignments
                for group_id in cast(list[str], item["leakage_group_ids"])
            }
        )
        output[passage_id] = _canonical_json(
            {
                "assignment_digest": _sha256_json(assignments),
                "benchmark_versions": sorted(
                    {str(item["benchmark_version"]) for item in assignments}
                ),
                "eligible_partitions": eligible_partitions,
                "leakage_membership_complete": all(
                    item["leakage_membership_complete"] is True for item in assignments
                ),
                # Directional rankings repeat this payload tens of millions of times.
                # Retain a count and canonical digest instead of the potentially large
                # identifier list.  ``assignment_digest`` still commits to every grouped
                # assignment fact returned above, and strict validation reproduces both
                # digests from the anchored benchmark database, so the compact summary is
                # traceable without duplicating every leakage-group identifier per rank.
                "leakage_group_count": len(leakage_group_ids),
                "leakage_group_ids_digest": _sha256_json(leakage_group_ids),
                "mapping_statuses": sorted({str(item["mapping_status"]) for item in assignments}),
                "status": (
                    "eligible_benchmark_assignment_present"
                    if has_eligible
                    else "no_eligible_benchmark_assignment"
                ),
            }
        )
    if resource_check is not None:
        resource_check("benchmark_split_provenance:after")
    return output


def _oshb_affected_verse_references(
    database_path: Path,
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
) -> dict[str, int]:
    """Return stable verse references and locus multiplicities from the anchored registry."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            rows = connection.execute(
                "SELECT canonical_book || ' ' || chapter::VARCHAR || ':' || verse::VARCHAR, "
                "count(*) FROM hebrew_kq_locus_registry GROUP BY 1 ORDER BY 1"
            ).fetchall()
    except (duckdb.Error, OSError) as exc:
        raise LexicalPipelineError(f"could not load OSHB affected verse references: {exc}") from exc
    references = {str(reference): int(count) for reference, count in rows}
    if not references or any(count < 1 for count in references.values()):
        raise LexicalPipelineError("OSHB affected-verse registry is empty or invalid")
    return references


def _sequence_reference_frame(
    sequences: Sequence[PassageLexicalSequence],
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for passage in sorted(sequences, key=lambda item: item.passage_id):
        if passage.granularity != "verse" or passage.start_reference != passage.end_reference:
            raise LexicalPipelineError(
                "sensitivity comparison requires single-reference verse passages"
            )
        rows.append(
            {
                "passage_id": passage.passage_id,
                "corpus": passage.corpus,
                "reference": passage.start_reference,
                "lemma_digest": sequence_digest(passage.values("lemma")),
                "english_digest": sequence_digest(passage.values("english_gloss")),
            }
        )
    frame = pl.DataFrame(
        rows,
        schema={
            "passage_id": pl.String,
            "corpus": pl.String,
            "reference": pl.String,
            "lemma_digest": pl.String,
            "english_digest": pl.String,
        },
        orient="row",
    )
    if frame.get_column("passage_id").n_unique() != frame.height:
        raise LexicalPipelineError("sensitivity sequence passage IDs are not unique")
    if frame.select("corpus", "reference").unique().height != frame.height:
        raise LexicalPipelineError(
            "sensitivity sequence references are not unique within a corpus scope"
        )
    return frame


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _iter_sensitivity_result_frames(
    *,
    ranking_root: Path,
    baseline_scope: str,
    comparison_scope: str,
    sensitivity_type: str,
    corpus_pairs: Sequence[str],
    baseline_profile: str,
    comparison_profile: str,
    baseline_reading: str,
    comparison_reading: str,
    baseline_sequences: Sequence[PassageLexicalSequence],
    comparison_sequences: Sequence[PassageLexicalSequence],
    baseline_representation_ids: Mapping[str, str],
    comparison_representation_ids: Mapping[str, str],
    affected_references: Mapping[str, int],
    experiment_run_id: str,
    configuration_hash: str,
    preregistration_hash: str,
    resource_guard: ProcessResourceGuard,
    spill_directory: Path,
) -> Iterator[pl.DataFrame]:
    """Externally join profile/reading top-K rankings on stable verse references."""

    if set(corpus_pairs) != set(baseline_representation_ids) or set(corpus_pairs) != set(
        comparison_representation_ids
    ):
        raise LexicalPipelineError(
            f"{sensitivity_type} representation maps do not match governed corpus pairs"
        )
    try:
        reference_frame_reservation = max(
            128 * MEBIBYTE,
            (len(baseline_sequences) + len(comparison_sequences)) * 4096
            + len(affected_references) * 256,
        )
        resource_guard.check(
            f"sensitivity:{sensitivity_type}:reference_frames:before",
            estimated_additional_bytes=reference_frame_reservation,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    baseline_passages = _sequence_reference_frame(baseline_sequences)
    comparison_passages = _sequence_reference_frame(comparison_sequences)
    representations = pl.DataFrame(
        [
            {
                "corpus_pair": pair,
                "baseline_representation_id": baseline_representation_ids[pair],
                "comparison_representation_id": comparison_representation_ids[pair],
            }
            for pair in corpus_pairs
        ],
        schema={
            "corpus_pair": pl.String,
            "baseline_representation_id": pl.String,
            "comparison_representation_id": pl.String,
        },
        orient="row",
    )
    affected = pl.DataFrame(
        [
            {"reference": reference, "locus_count": count}
            for reference, count in sorted(affected_references.items())
        ],
        schema={"reference": pl.String, "locus_count": pl.Int64},
        orient="row",
    )
    ranking_glob = (ranking_root / "part-*.parquet").as_posix().replace("'", "''")
    pair_sql = ",".join(_sql_string(pair) for pair in corpus_pairs)
    affected_filter = (
        "AND q.reference IN (SELECT reference FROM affected_references)"
        if affected_references
        else ""
    )
    try:
        duckdb_limit = resource_guard.bounded_duckdb_memory_bytes(
            f"sensitivity:{sensitivity_type}:join:before",
            preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    query = f"""
        WITH rankings AS (
          SELECT * FROM read_parquet('{ranking_glob}', union_by_name=true)
          WHERE corpus_pair IN ({pair_sql})
        ),
        baseline AS (
          SELECT r.*, q.corpus AS query_corpus, q.reference AS query_reference,
                 t.corpus AS target_corpus, t.reference AS target_reference,
                 sha256(
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN q.english_digest ELSE q.lemma_digest END || ':' ||
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN t.english_digest ELSE t.lemma_digest END
                 ) AS pair_sequence_digest
          FROM rankings r
          JOIN baseline_passages q ON q.passage_id=r.query_passage_id
          JOIN baseline_passages t ON t.passage_id=r.target_passage_id
          JOIN representation_pairs p USING (corpus_pair)
          WHERE r.experiment_scope={_sql_string(baseline_scope)}
            AND r.analysis_profile={_sql_string(baseline_profile)}
            AND r.representation_id=p.baseline_representation_id
            {affected_filter}
        ),
        comparison AS (
          SELECT r.*, q.corpus AS query_corpus, q.reference AS query_reference,
                 t.corpus AS target_corpus, t.reference AS target_reference,
                 sha256(
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN q.english_digest ELSE q.lemma_digest END || ':' ||
                   CASE WHEN r.corpus_pair='hb_gnt_english_bridge'
                        THEN t.english_digest ELSE t.lemma_digest END
                 ) AS pair_sequence_digest
          FROM rankings r
          JOIN comparison_passages q ON q.passage_id=r.query_passage_id
          JOIN comparison_passages t ON t.passage_id=r.target_passage_id
          JOIN representation_pairs p USING (corpus_pair)
          WHERE r.experiment_scope={_sql_string(comparison_scope)}
            AND r.analysis_profile={_sql_string(comparison_profile)}
            AND r.representation_id=p.comparison_representation_id
            {affected_filter}
        ),
        paired AS (
          SELECT coalesce(b.corpus_pair,c.corpus_pair) AS corpus_pair,
                 coalesce(b.detector,c.detector) AS detector,
                 coalesce(b.query_corpus,c.query_corpus) AS query_corpus,
                 coalesce(b.target_corpus,c.target_corpus) AS target_corpus,
                 coalesce(b.query_reference,c.query_reference) AS query_reference,
                 coalesce(b.target_reference,c.target_reference) AS target_reference,
                 b.query_passage_id AS baseline_query_passage_id,
                 c.query_passage_id AS comparison_query_passage_id,
                 b.target_passage_id AS baseline_target_passage_id,
                 c.target_passage_id AS comparison_target_passage_id,
                 b.raw_score AS baseline_score,
                 c.raw_score AS comparison_score,
                 b.rank AS baseline_rank,
                 c.rank AS comparison_rank,
                 b.pair_sequence_digest AS ranked_baseline_digest,
                 c.pair_sequence_digest AS ranked_comparison_digest
          FROM baseline b FULL OUTER JOIN comparison c
            ON b.corpus_pair=c.corpus_pair
           AND b.detector=c.detector
           AND b.query_corpus=c.query_corpus
           AND b.target_corpus=c.target_corpus
           AND b.query_reference=c.query_reference
           AND b.target_reference=c.target_reference
        ),
        resolved AS (
          SELECT paired.*, p.baseline_representation_id,
                 p.comparison_representation_id,
                 bq.passage_id AS resolved_baseline_query_id,
                 bt.passage_id AS resolved_baseline_target_id,
                 cq.passage_id AS resolved_comparison_query_id,
                 ct.passage_id AS resolved_comparison_target_id,
                 coalesce(
                   ranked_baseline_digest,
                   sha256(
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN bq.english_digest ELSE bq.lemma_digest END || ':' ||
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN bt.english_digest ELSE bt.lemma_digest END
                   ),
                   sha256('')
                 ) AS baseline_sequence_digest,
                 coalesce(
                   ranked_comparison_digest,
                   sha256(
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN cq.english_digest ELSE cq.lemma_digest END || ':' ||
                     CASE WHEN paired.corpus_pair='hb_gnt_english_bridge'
                          THEN ct.english_digest ELSE ct.lemma_digest END
                   ),
                   sha256('')
                 ) AS comparison_sequence_digest,
                 coalesce(a.locus_count,0)::BIGINT AS affected_locus_count
          FROM paired
          JOIN representation_pairs p USING (corpus_pair)
          LEFT JOIN baseline_passages bq
            ON bq.corpus=paired.query_corpus AND bq.reference=paired.query_reference
          LEFT JOIN baseline_passages bt
            ON bt.corpus=paired.target_corpus AND bt.reference=paired.target_reference
          LEFT JOIN comparison_passages cq
            ON cq.corpus=paired.query_corpus AND cq.reference=paired.query_reference
          LEFT JOIN comparison_passages ct
            ON ct.corpus=paired.target_corpus AND ct.reference=paired.target_reference
          LEFT JOIN affected_references a ON a.reference=paired.query_reference
        ),
        measured AS (
          SELECT *,
                 count(baseline_rank) OVER comparison_window AS baseline_k,
                 count(comparison_rank) OVER comparison_window AS comparison_k,
                 count(*) FILTER (
                   WHERE baseline_rank IS NOT NULL AND comparison_rank IS NOT NULL
                 ) OVER comparison_window AS shared_k
          FROM resolved
          WINDOW comparison_window AS (
            PARTITION BY corpus_pair, detector, query_corpus, target_corpus, query_reference
          )
        )
        SELECT 'LXS_' || sha256(concat_ws(chr(31),
                 {_sql_string(sensitivity_type)}, corpus_pair, detector,
                 query_corpus || '_to_' || target_corpus,
                 query_reference, target_reference)) AS sensitivity_id,
               {_sql_string(experiment_run_id)} AS experiment_run_id,
               {_sql_string(sensitivity_type)} AS sensitivity_type,
               corpus_pair,
               detector,
               query_corpus || '_to_' || target_corpus AS direction,
               {_sql_string(baseline_profile)} AS baseline_profile,
               {_sql_string(comparison_profile)} AS comparison_profile,
               CASE WHEN corpus_pair='gnt_gnt' THEN 'source'
                    ELSE {_sql_string(baseline_reading)} END AS baseline_reading,
               CASE WHEN corpus_pair='gnt_gnt' THEN 'source'
                    ELSE {_sql_string(comparison_reading)} END AS comparison_reading,
               query_reference,
               target_reference,
               coalesce(baseline_query_passage_id,resolved_baseline_query_id)
                 AS baseline_query_passage_id,
               coalesce(comparison_query_passage_id,resolved_comparison_query_id)
                 AS comparison_query_passage_id,
               coalesce(baseline_target_passage_id,resolved_baseline_target_id)
                 AS baseline_target_passage_id,
               coalesce(comparison_target_passage_id,resolved_comparison_target_id)
                 AS comparison_target_passage_id,
               baseline_representation_id,
               comparison_representation_id,
               baseline_score,
               comparison_score,
               CASE WHEN baseline_score IS NOT NULL AND comparison_score IS NOT NULL
                    THEN comparison_score-baseline_score END AS score_delta,
               baseline_rank,
               comparison_rank,
               CASE WHEN baseline_rank IS NOT NULL AND comparison_rank IS NOT NULL
                    THEN comparison_rank-baseline_rank END::BIGINT AS rank_delta,
               CASE WHEN greatest(baseline_k,comparison_k)>0
                    THEN shared_k::DOUBLE/greatest(baseline_k,comparison_k) END
                 AS top_k_overlap,
               affected_locus_count,
               CASE
                 WHEN resolved_baseline_query_id IS NULL THEN 'query_missing_from_baseline_scope'
                 WHEN resolved_baseline_target_id IS NULL THEN 'target_missing_from_baseline_scope'
                 WHEN resolved_comparison_query_id IS NULL
                   THEN 'query_missing_from_comparison_scope'
                 WHEN resolved_comparison_target_id IS NULL
                   THEN 'target_missing_from_comparison_scope'
               END AS excluded_reason,
               baseline_sequence_digest,
               comparison_sequence_digest,
               {_sql_string(configuration_hash)} AS config_hash,
               {_sql_string(preregistration_hash)} AS preregistration_hash
        FROM measured
        ORDER BY sensitivity_type, corpus_pair, detector, direction, sensitivity_id
    """
    try:
        with _bounded_duckdb_connection(
            memory_limit_bytes=duckdb_limit,
            temp_directory=spill_directory,
        ) as connection:
            connection.register("baseline_passages", baseline_passages.to_arrow())
            connection.register("comparison_passages", comparison_passages.to_arrow())
            connection.register("representation_pairs", representations.to_arrow())
            connection.register("affected_references", affected.to_arrow())
            reader = connection.execute(query).to_arrow_reader(50_000)
            for part, batch in enumerate(reader):
                frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).cast(
                    SENSITIVITY_RESULTS_SCHEMA, strict=True
                )
                resource_guard.check(f"sensitivity:{sensitivity_type}:part-{part}")
                yield frame
    except (duckdb.Error, OSError, pl.exceptions.PolarsError, LexicalResourceError) as exc:
        raise LexicalPipelineError(
            f"could not materialize {sensitivity_type} comparison: {exc}"
        ) from exc


def _derived_values(values: Sequence[str], family: FeatureFamily) -> tuple[str, ...]:
    if family in {"lemma_ngram", "root_ngram"}:
        output: list[str] = []
        for size in (2, 3):
            output.extend(
                "\u241f".join(item)
                for item in zip(*(values[i:] for i in range(size)), strict=False)
            )
        return tuple(output)
    if family in {"lemma_skipgram", "root_skipgram"}:
        return tuple(
            f"{values[first]}\u241f*\u241f{values[second]}"
            for first in range(len(values))
            for second in range(first + 2, min(len(values), first + 4))
        )
    raise LexicalPipelineError(f"unsupported derived family: {family}")


def _derived_vocabulary(
    sequences: Sequence[PassageLexicalSequence],
    *,
    family: FeatureFamily,
    namespace: LanguageNamespace,
    config: LexicalConfig,
    book_genres: Mapping[str, str],
) -> pl.DataFrame:
    source_family = "lemma" if family.startswith("lemma") else "root"
    corpus_frequency: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    books: dict[str, set[str]] = defaultdict(set)
    genres: dict[str, set[str]] = defaultdict(set)
    for passage in sequences:
        derived = _derived_values(passage.values(source_family), family)
        corpus_frequency.update(derived)
        for value in set(derived):
            document_frequency[value] += 1
            books[value].add(passage.book)
            genres[value].add(book_genres.get(passage.book, "unassigned"))
    minimum = config.phrases.minimum_corpus_count
    document_count = len(sequences)
    rows: list[dict[str, object]] = []
    for value in sorted(key for key, count in corpus_frequency.items() if count >= minimum):
        order = 2 if family.endswith("skipgram") else value.count("\u241f") + 1
        identity = build_feature_identity(
            FeatureIdentityPayload(
                feature_family=family,
                language_namespace=namespace,
                feature_value=value,
                feature_order=order,
            )
        )
        df = document_frequency[value]
        ratio = df / document_count if document_count else 0.0
        rows.append(
            {
                "feature_id": identity.identifier,
                "lexical_schema_version": 1,
                "feature_family": family,
                "language_namespace": namespace,
                "feature_value": value,
                "feature_order": order,
                "corpus_frequency": corpus_frequency[value],
                "document_frequency": df,
                "inverse_document_frequency": (math.log((1.0 + document_count) / (1.0 + df)) + 1.0),
                "book_frequency": len(books[value]),
                "genre_frequency": len(genres[value]),
                "is_rare": (
                    corpus_frequency[value] <= config.rare_evidence.maximum_corpus_frequency
                ),
                "is_high_frequency": (
                    ratio >= config.feature_frequency_thresholds.high_document_frequency_ratio
                ),
                "is_formulaic": (
                    ratio >= config.feature_frequency_thresholds.formulaic_document_frequency_ratio
                    and corpus_frequency[value]
                    >= config.feature_frequency_thresholds.formulaic_minimum_corpus_count
                ),
                "contains_english_derived_content": False,
                "normalization_method": "source_sequence_derived_no_cross_boundary-v1",
                "notes": "minimum_corpus_count=2; positions reproduce from source sequence",
            }
        )
    return pl.DataFrame(rows, schema=FEATURE_VOCABULARY_SCHEMA, orient="row")


def build_all_feature_vocabulary(
    hebrew: Sequence[PassageLexicalSequence],
    greek: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
    book_genres: Mapping[str, str],
) -> pl.DataFrame:
    """Build every governed source, structural, phrase, and English feature family."""

    frames: list[pl.DataFrame] = []
    for sequences, namespace in ((hebrew, "hb"), (greek, "gk")):
        for family in (
            "lemma",
            "root",
            "normalized_surface",
            "part_of_speech",
            "morphology",
        ):
            frames.append(
                build_feature_vocabulary(
                    sequences,
                    family=family,
                    namespace=cast(LanguageNamespace, namespace),
                    rare_maximum_corpus_frequency=(config.rare_evidence.maximum_corpus_frequency),
                    high_frequency_document_ratio=(
                        config.feature_frequency_thresholds.high_document_frequency_ratio
                    ),
                    formulaic_document_ratio=(
                        config.feature_frequency_thresholds.formulaic_document_frequency_ratio
                    ),
                    formulaic_minimum_corpus_count=(
                        config.feature_frequency_thresholds.formulaic_minimum_corpus_count
                    ),
                    book_genres=dict(book_genres),
                )
            )
        for family in (
            "lemma_ngram",
            "root_ngram",
            "lemma_skipgram",
            "root_skipgram",
        ):
            frames.append(
                _derived_vocabulary(
                    sequences,
                    family=cast(FeatureFamily, family),
                    namespace=cast(LanguageNamespace, namespace),
                    config=config,
                    book_genres=book_genres,
                )
            )
    frames.append(
        build_feature_vocabulary(
            [*hebrew, *greek],
            family="english_gloss",
            namespace="en",
            rare_maximum_corpus_frequency=config.rare_evidence.maximum_corpus_frequency,
            high_frequency_document_ratio=(
                config.feature_frequency_thresholds.high_document_frequency_ratio
            ),
            formulaic_document_ratio=(
                config.feature_frequency_thresholds.formulaic_document_frequency_ratio
            ),
            formulaic_minimum_corpus_count=(
                config.feature_frequency_thresholds.formulaic_minimum_corpus_count
            ),
            book_genres=dict(book_genres),
        )
    )
    return combine_feature_vocabularies(frames)


def _representation_id(
    *,
    config: LexicalConfig,
    family: FeatureFamily,
    corpus_scope: tuple[str, ...],
    reading: str,
    analysis_profile: str,
    granularity: str,
    configuration_hash: str,
) -> str:
    eligibility_hash = _sha256_json(config.token_eligibility.model_dump(mode="json"))
    normalization_hash = hashlib.sha256(Path("config/normalization.yaml").read_bytes()).hexdigest()
    return build_representation_identity(
        RepresentationIdentityPayload(
            representation_kind=(
                "english_derived" if family == "english_gloss" else "original_language"
            ),
            corpus_scope=cast(tuple[object, ...], corpus_scope),  # type: ignore[arg-type]
            analysis_profile=cast(AnalysisProfile, analysis_profile),
            analysis_reading=reading,
            granularity=cast(Granularity, granularity),
            feature_families=(family,),
            token_eligibility_policy_sha256=eligibility_hash,
            frequency_scope=f"language_and_representation:{configuration_hash}",
            normalization_config_sha256=normalization_hash,
        )
    ).identifier


def _primary_index_definitions(
    hebrew: Sequence[PassageLexicalSequence],
    greek: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    profile = config.primary_scope.analysis_profile
    granularity = config.primary_scope.granularity
    qere = config.primary_scope.hebrew_reading
    source = config.primary_scope.greek_reading
    return (
        _IndexDefinition("hb_hb", hebrew, "lemma", "hb", ("hebrew",), qere, profile, granularity),
        _IndexDefinition("gnt_gnt", greek, "lemma", "gk", ("greek",), source, profile, granularity),
        _IndexDefinition(
            "hb_gnt_english_bridge",
            [*hebrew, *greek],
            "english_gloss",
            "en",
            ("hebrew", "greek"),
            f"{qere}+{source}",
            profile,
            granularity,
        ),
        _IndexDefinition(
            "hb_root", hebrew, "root", "hb", ("hebrew",), qere, profile, granularity, False
        ),
        _IndexDefinition(
            "gnt_root", greek, "root", "gk", ("greek",), source, profile, granularity, False
        ),
        _IndexDefinition(
            "hb_surface",
            hebrew,
            "surface",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_surface",
            greek,
            "surface",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "hb_pos",
            hebrew,
            "part_of_speech",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_pos",
            greek,
            "part_of_speech",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "hb_morph",
            hebrew,
            "morphology",
            "hb",
            ("hebrew",),
            qere,
            profile,
            granularity,
            False,
        ),
        _IndexDefinition(
            "gnt_morph",
            greek,
            "morphology",
            "gk",
            ("greek",),
            source,
            profile,
            granularity,
            False,
        ),
    )


def _critical_index_definitions(
    *,
    critical_hebrew: Sequence[PassageLexicalSequence],
    critical_greek: Sequence[PassageLexicalSequence],
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    critical = config.sensitivity_scopes.critical_core_greek
    return (
        _IndexDefinition(
            "critical_gnt_gnt",
            critical_greek,
            "lemma",
            "gk",
            ("greek",),
            critical.greek_reading,
            critical.analysis_profile,
            critical.granularity,
        ),
        _IndexDefinition(
            "critical_hb_gnt_english_bridge",
            [*critical_hebrew, *critical_greek],
            "english_gloss",
            "en",
            ("hebrew", "greek"),
            f"{critical.hebrew_reading}+{critical.greek_reading}",
            critical.analysis_profile,
            critical.granularity,
        ),
    )


def _ketiv_index_definitions(
    ketiv_hebrew: Sequence[PassageLexicalSequence],
    *,
    config: LexicalConfig,
) -> tuple[_IndexDefinition, ...]:
    reading = config.sensitivity_scopes.hebrew_qere_ketiv
    return (
        _IndexDefinition(
            "ketiv_hb_hb",
            ketiv_hebrew,
            "lemma",
            "hb",
            ("hebrew",),
            reading.comparison_reading,
            reading.analysis_profile,
            reading.granularity,
        ),
    )


def _build_indexes(
    *,
    writer: LexicalArtifactWriter,
    definitions: Sequence[_IndexDefinition],
    config: LexicalConfig,
    configuration_hash: str,
    experiment_run_id: str,
    resource_check: _ResourceCheck | None = None,
) -> tuple[dict[str, SparseLexicalIndex], pl.DataFrame, dict[str, dict[str, object]]]:
    indexes: dict[str, SparseLexicalIndex] = {}
    metadata_rows: list[dict[str, object]] = []
    summaries: dict[str, dict[str, object]] = {}
    family_identity: dict[str, FeatureFamily] = {
        "lemma": "lemma",
        "root": "root",
        "surface": "normalized_surface",
        "part_of_speech": "part_of_speech",
        "morphology": "morphology",
        "english_gloss": "english_gloss",
    }
    for definition in definitions:
        identity_family = family_identity[definition.family]
        if resource_check is not None:
            resource_check(
                f"sparse_index:{definition.key}:before",
                estimated_additional_bytes=_sparse_index_reservation_bytes(definition),
            )
        representation_id = _representation_id(
            config=config,
            family=identity_family,
            corpus_scope=definition.corpus_scope,
            reading=definition.reading,
            analysis_profile=definition.analysis_profile,
            granularity=definition.granularity,
            configuration_hash=configuration_hash,
        )
        index = build_sparse_index(
            definition.sequences,
            representation_id=representation_id,
            family=definition.family,
            namespace=definition.namespace,
            sublinear_tf=config.tfidf.sublinear_tf,
            smooth_idf=config.tfidf.smooth_idf,
            l2_normalize=config.tfidf.norm == "l2",
        )
        files = persist_sparse_index(index, writer.staging_dir / "indexes" / representation_id)
        physical_hash = sparse_index_physical_hash(files.root)
        index_id = "LXI_" + _sha256_json(
            {"run": experiment_run_id, "representation": representation_id}
        )
        metadata_rows.append(
            {
                "index_id": index_id,
                "experiment_run_id": experiment_run_id,
                "representation_id": representation_id,
                "corpus_scope": "+".join(definition.corpus_scope),
                "profile": definition.analysis_profile,
                "reading": definition.reading,
                "granularity": definition.granularity,
                "feature_family": identity_family,
                "matrix_shape_json": _canonical_json(list(index.counts.shape)),
                "nonzero_count": index.counts.nnz,
                "vocabulary_size": len(index.vocabulary),
                "document_count": len(index.passage_ids),
                "index_config_hash": configuration_hash,
                "logical_matrix_hash": index.logical_hash,
                "physical_file_hash": physical_hash,
                "dtype": "float64",
                "storage_format": "canonical-npy-csr-v1",
                "notes": (
                    "production root annotations unavailable; empty governed interface"
                    if definition.family == "root" and not index.vocabulary
                    else "deterministic CSR; no dense passage-by-feature matrix persisted"
                ),
            }
        )
        summaries[definition.key] = {
            "index_id": index_id,
            "representation_id": representation_id,
            "shape": list(index.counts.shape),
            "nonzero_count": int(index.counts.nnz),
            "logical_hash": index.logical_hash,
            "physical_hash": physical_hash,
        }
        if definition.retain_for_retrieval:
            indexes[definition.key] = index
        if resource_check is not None:
            resource_check(f"sparse_index:{definition.key}:after")
    return (
        indexes,
        pl.DataFrame(metadata_rows, schema=LEXICAL_INDEX_METADATA_SCHEMA, orient="row"),
        summaries,
    )


def _merge_updates(
    merged: dict[str, CandidateAggregate], updates: Iterable[CandidateAggregate]
) -> None:
    for update in updates:
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
        for direction in update.directions.values():
            current.add_direction(direction)


def _run_retrieval(
    *,
    writer: LexicalArtifactWriter,
    indexes: Mapping[str, SparseLexicalIndex],
    sequences_by_pair: Mapping[str, Sequence[PassageLexicalSequence]],
    experiment_run_id: str,
    configuration_hash: str,
    config: LexicalConfig,
    experiment_scope: str,
    corpus_pairs: Sequence[str],
    split_provenance_by_passage_id: Mapping[str, str],
    query_reference_filter: frozenset[str] | None = None,
    collect_candidates: bool = True,
    ranking_part_start: int = 0,
    ablation_part_start: int = 0,
    resource_check: _ResourceCheck | None = None,
) -> _RetrievalScopeResult:
    candidates: dict[str, CandidateAggregate] = {}
    ranking_count = 0
    ranking_part = ranking_part_start
    ablation_part = ablation_part_start
    for corpus_pair in corpus_pairs:
        index = indexes[corpus_pair]
        sequences = sorted(sequences_by_pair[corpus_pair], key=lambda item: item.passage_id)
        corpus_indices: dict[str, list[int]] = defaultdict(list)
        for position, passage in enumerate(sequences):
            corpus_indices[passage.corpus].append(position)
        directions: tuple[tuple[Sequence[int], Sequence[int]], ...]
        if corpus_pair == "hb_gnt_english_bridge":
            directions = (
                (corpus_indices["hebrew"], corpus_indices["greek"]),
                (corpus_indices["greek"], corpus_indices["hebrew"]),
            )
        else:
            all_indices = tuple(range(len(sequences)))
            selected_query_indices = (
                tuple(
                    index
                    for index, passage in enumerate(sequences)
                    if passage.start_reference in query_reference_filter
                    and passage.end_reference in query_reference_filter
                )
                if query_reference_filter is not None
                else all_indices
            )
            directions = ((selected_query_indices, all_indices),)
        if any(
            not query_indices or not target_indices for query_indices, target_indices in directions
        ):
            raise LexicalPipelineError(
                f"retrieval scope {experiment_scope}/{corpus_pair} has an empty query or target set"
            )
        maximum_df = max(
            1,
            math.floor(
                len(sequences)
                * config.feature_frequency_thresholds.proposal_maximum_document_frequency_ratio
            ),
        )
        for direction_query_indices, direction_target_indices in directions:
            if resource_check is not None:
                resource_check(
                    f"retrieval:{experiment_scope}:{corpus_pair}:direction:before",
                    estimated_additional_bytes=_retrieval_reservation_bytes(config),
                )
            for batch in iter_retrieval_batches(
                index,
                sequences,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                experiment_scope=experiment_scope,
                corpus_pair=cast(CorpusPair, corpus_pair),
                query_indices=direction_query_indices,
                target_indices=direction_target_indices,
                candidate_union_k=config.retrieval.candidate_union_k,
                persisted_top_k=config.retrieval.persisted_top_k,
                persisted_candidate_pool_k=config.retrieval.persisted_candidate_pool_k,
                expensive_sequence_rerank_k=config.retrieval.expensive_sequence_rerank_k,
                block_size=config.resource_limits.block_passage_count,
                maximum_proposal_document_frequency=maximum_df,
                score_quantization_decimals=config.statistics.score_quantization_decimals,
                bm25_k1=config.bm25.k1,
                bm25_b=config.bm25.b,
                rare_threshold=config.rare_evidence.maximum_corpus_frequency,
                rrf_k=config.composite.rrf_k,
                gap_penalty=config.sequence.gap_penalty,
                mismatch_score=config.sequence.mismatch_penalty,
                nearby_context_distance=config.penalties.nearby_verse_distance,
                phrase_ngram_sizes=config.phrases.lemma_ngram_sizes,
                phrase_minimum_corpus_count=config.phrases.minimum_corpus_count,
                phrase_pmi_cap=config.phrases.pmi_cap,
                skipgram_max_gap=config.skipgrams.maximum_gap,
                skipgram_minimum_corpus_count=config.skipgrams.minimum_corpus_count,
                split_provenance_by_passage_id={
                    passage_id: split_provenance_by_passage_id[passage_id]
                    for passage_id in index.passage_ids
                    if passage_id in split_provenance_by_passage_id
                },
                resource_check=resource_check,
            ):
                writer.write_frame("directional_rankings", batch.rankings, part=ranking_part)
                ranking_part += 1
                ranking_count += batch.rankings.height
                if batch.ablation_results.height:
                    writer.write_frame(
                        "ablation_results",
                        batch.ablation_results,
                        part=ablation_part,
                    )
                    ablation_part += 1
                if collect_candidates:
                    if resource_check is not None:
                        resource_check(
                            f"retrieval:{experiment_scope}:{corpus_pair}:candidate-merge",
                            estimated_additional_bytes=max(
                                16 * MEBIBYTE, len(batch.candidates) * 4096
                            ),
                        )
                    _merge_updates(candidates, batch.candidates)
                if resource_check is not None:
                    resource_check(
                        f"retrieval:{experiment_scope}:{corpus_pair}:part-{ranking_part - 1}"
                    )
                del batch
    return _RetrievalScopeResult(
        candidates=candidates,
        ranking_count=ranking_count,
        next_ranking_part=ranking_part,
        next_ablation_part=ablation_part,
    )


def _iter_ranked_review_queue_frames(
    spool_directory: Path,
    *,
    expected_count: int,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    resource_check: _ResourceCheck | None = None,
) -> Iterator[pl.DataFrame]:
    """Globally rank disk-spooled eligible rows without retaining the queue in Python."""

    if expected_count < 0:
        raise LexicalPipelineError("review-queue expected count cannot be negative")
    if expected_count == 0:
        yield pl.DataFrame(schema=CANDIDATE_REVIEW_QUEUE_SCHEMA)
        return
    paths = sorted(spool_directory.glob("part-*.parquet"))
    if not paths:
        raise LexicalPipelineError("review-queue spool is empty despite eligible candidates")
    glob = (spool_directory / "part-*.parquet").as_posix().replace("'", "''")
    payload_columns = tuple(CANDIDATE_REVIEW_QUEUE_SCHEMA.names()[1:])
    selected_columns = ",".join(f'"{column}"' for column in payload_columns)
    if resource_check is not None:
        resource_check(
            "candidate_review_queue:sort:before",
            estimated_additional_bytes=duckdb_memory_limit_bytes + 64 * MEBIBYTE,
        )
    try:
        with _bounded_duckdb_connection(
            memory_limit_bytes=duckdb_memory_limit_bytes,
            temp_directory=duckdb_temp_directory,
        ) as connection:
            facts = connection.execute(
                "SELECT count(*),count(DISTINCT candidate_pair_id),"
                "count_if(NOT review_eligible),"
                "count_if(known_link_status <> "
                "'not_represented_in_openbible_snapshot'),"
                "count_if(contains_english_derived_evidence AND "
                "NOT english_ablation_survives) "
                f"FROM read_parquet('{glob}', union_by_name=true)"
            ).fetchone()
            if facts is None or tuple(int(value) for value in facts) != (
                expected_count,
                expected_count,
                0,
                0,
                0,
            ):
                raise LexicalPipelineError(
                    f"review-queue spool failed identity or eligibility checks: {facts}"
                )
            cursor = connection.execute(
                "SELECT CAST(row_number() OVER (ORDER BY rrf_score DESC,"
                "candidate_pair_id) AS BIGINT) AS queue_rank,"
                f"{selected_columns} FROM read_parquet('{glob}', union_by_name=true) "
                "ORDER BY queue_rank"
            )
            observed = 0
            for batch_number, batch in enumerate(
                cursor.to_arrow_reader(_REVIEW_QUEUE_READ_BATCH_SIZE), start=1
            ):
                if resource_check is not None:
                    resource_check(
                        f"candidate_review_queue:sort:batch-{batch_number}",
                        estimated_additional_bytes=64 * MEBIBYTE,
                    )
                frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).select(
                    CANDIDATE_REVIEW_QUEUE_SCHEMA.names()
                )
                frame = frame.cast(CANDIDATE_REVIEW_QUEUE_SCHEMA)
                observed += frame.height
                yield frame
            if observed != expected_count:
                raise LexicalPipelineError(
                    "review-queue sorted row count differs from its spool: "
                    f"expected={expected_count}, observed={observed}"
                )
    except (duckdb.Error, OSError, pl.exceptions.PolarsError, LexicalResourceError) as exc:
        raise LexicalPipelineError(f"could not rank the review-queue spool: {exc}") from exc


def _issue_frame(
    experiment_run_id: str,
    *,
    scientific_gate_status: str,
    uncalibrated_corpus_pairs: Sequence[str],
    sensitivity_counts: Mapping[str, int],
) -> pl.DataFrame:
    facts: list[tuple[str, str]] = [
        (
            "root_coverage_unavailable",
            "Production Hebrew and Greek lexical-root coverage is zero; root interfaces are "
            "fixture-tested and no roots were fabricated.",
        ),
        (
            "null_scope_candidate_union_sample",
            "Null calibration is scoped to the frozen deterministic candidate-union sample; "
            "no global all-pairs FDR claim is made.",
        ),
        (
            "tier1_empty",
            "Tier 1 remains exactly zero rows; no high-confidence quotation recovery claim "
            "was tested.",
        ),
        (
            "bounded_nonprimary_scope",
            "Critical-core and Qere/Ketiv sensitivity rankings were evaluated without "
            "repeating primary null simulations; non-verse granularities remain bounded "
            "smoke-test interfaces only.",
        ),
        (
            "sensitivity_results_materialized",
            "Required reproducible comparison rows were materialized: "
            + ", ".join(f"{name}={count}" for name, count in sorted(sensitivity_counts.items()))
            + ".",
        ),
    ]
    if scientific_gate_status != "passed":
        facts.append(
            (
                "scientific_gate_not_complete",
                "The frozen Tier 3 scientific recovery gate did not pass; the result is "
                "preserved and Milestone 7 remains scientifically incomplete.",
            )
        )
    if uncalibrated_corpus_pairs:
        facts.append(
            (
                "null_threshold_not_selected",
                "No preregistered RRF threshold met both-family empirical-FDR policy for: "
                + ", ".join(sorted(uncalibrated_corpus_pairs))
                + ". Thresholds were not weakened.",
            )
        )
    rows = [
        {
            "issue_id": f"LI_{_sha256_json({'code': code, 'run': experiment_run_id})}",
            "severity": "informational",
            "code": code,
            "message": message,
            "artifact": "lexical_metadata",
            "record_id": experiment_run_id,
            "experiment_run_id": experiment_run_id,
            "details_json": "{}",
        }
        for code, message in facts
    ]
    return pl.DataFrame(rows, schema=LEXICAL_ISSUES_SCHEMA, orient="row")


def run_lexical_pipeline(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_dir: Path = DEFAULT_LEXICAL_ROOT,
    force: bool = False,
) -> LexicalPipelineResult:
    """Run every frozen verse-level M7 stage and atomically replace lexical artifacts."""

    timings: dict[str, float] = {}
    start = time.perf_counter()
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    validate_preregistration_against_config(preregistration, config)
    thread_controls = enforce_thread_controls(config.resource_limits.thread_count)
    observed_polars_threads = pl.thread_pool_size()
    if observed_polars_threads > config.resource_limits.thread_count:
        raise LexicalPipelineError(
            "Polars initialized before the governed thread control: "
            f"observed={observed_polars_threads}, maximum={config.resource_limits.thread_count}"
        )
    try:
        resource_guard = ProcessResourceGuard(config.resource_limits.maximum_memory_bytes)
    except LexicalResourceError as exc:
        raise LexicalPipelineError(f"could not initialize resource guard: {exc}") from exc

    def resource_check(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        try:
            resource_guard.check(
                stage,
                estimated_additional_bytes=estimated_additional_bytes,
            )
        except LexicalResourceError as exc:
            raise LexicalPipelineError(str(exc)) from exc

    resource_check("pipeline:start")
    configuration_hash = lexical_config_sha256(config)
    preregistration_hash = lexical_preregistration_sha256(preregistration)
    try:
        database_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
            "pipeline_database:duckdb-budget",
            preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    anchor_spill_directory = output_dir.parent / f".{output_dir.name}.anchor-spill"
    with _managed_temp_directory(anchor_spill_directory):
        anchors = cast(
            AnchorVerification,
            _time_stage(
                timings,
                "verify_anchors",
                lambda: verify_upstream_anchors(
                    database_path=database_path,
                    passage_root=DEFAULT_PASSAGE_ROOT,
                    benchmark_root=DEFAULT_BENCHMARK_ROOT,
                    tier1_path=DEFAULT_TIER1_PATH,
                    oshb_root=DEFAULT_OSHB_ROOT,
                    duckdb_memory_limit_bytes=database_duckdb_memory,
                    duckdb_temp_directory=anchor_spill_directory / "duckdb",
                ),
            ),
        )
    resource_check("verify_anchors:after")
    experiment_run_id = build_experiment_run_id(
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        anchors=anchors,
    )
    database_spill_directory = (
        output_dir.parent / f".{output_dir.name}.{experiment_run_id}.duckdb-spill"
    )

    with (
        _managed_temp_directory(database_spill_directory),
        LexicalArtifactWriter(
            output_dir,
            force=force,
            duckdb_memory_limit_bytes=database_duckdb_memory,
            required_free_bytes=(
                config.resource_limits.minimum_free_disk_bytes
                if config.resource_limits.check_disk_before_build
                else 0
            ),
        ) as writer,
    ):
        primary = config.primary_scope
        critical_scope = config.sensitivity_scopes.critical_core_greek
        reading_scope = config.sensitivity_scopes.hebrew_qere_ketiv

        def load_sequences(
            *, corpus: str, profile: str, reading: str, stage: str
        ) -> list[PassageLexicalSequence]:
            resource_check(
                f"{stage}:before",
                estimated_additional_bytes=(
                    _SEQUENCE_LOAD_RESERVATION_BYTES + database_duckdb_memory
                ),
            )
            loaded = cast(
                list[PassageLexicalSequence],
                _time_stage(
                    timings,
                    stage,
                    lambda: list(
                        iter_passage_sequences(
                            database_path,
                            corpus=corpus,
                            analysis_profile=profile,
                            analysis_reading=reading,
                            granularity="verse",
                            duckdb_memory_limit_bytes=database_duckdb_memory,
                            duckdb_temp_directory=database_spill_directory / "sequences",
                        )
                    ),
                ),
            )
            if not loaded:
                raise LexicalPipelineError(f"{stage} produced no governed verse sequences")
            resource_check(f"{stage}:after")
            return loaded

        hebrew = load_sequences(
            corpus="hebrew",
            profile=primary.analysis_profile,
            reading=primary.hebrew_reading,
            stage="load_primary_hebrew_sequences",
        )
        greek = load_sequences(
            corpus="greek",
            profile=primary.analysis_profile,
            reading=primary.greek_reading,
            stage="load_primary_greek_sequences",
        )
        critical_hebrew = load_sequences(
            corpus="hebrew",
            profile=critical_scope.analysis_profile,
            reading=critical_scope.hebrew_reading,
            stage="load_critical_hebrew_sequences",
        )
        critical_greek = load_sequences(
            corpus="greek",
            profile=critical_scope.analysis_profile,
            reading=critical_scope.greek_reading,
            stage="load_critical_greek_sequences",
        )
        ketiv_hebrew = load_sequences(
            corpus="hebrew",
            profile=reading_scope.analysis_profile,
            reading=reading_scope.comparison_reading,
            stage="load_ketiv_hebrew_sequences",
        )
        all_sequences = [*hebrew, *greek]
        critical_all_sequences = [*critical_hebrew, *critical_greek]
        book_genres = _book_genres()
        resource_check(
            "feature_vocabulary:before",
            estimated_additional_bytes=_FEATURE_VOCABULARY_RESERVATION_BYTES,
        )
        vocabulary = cast(
            pl.DataFrame,
            _time_stage(
                timings,
                "feature_vocabulary",
                lambda: build_all_feature_vocabulary(
                    hebrew, greek, config=config, book_genres=book_genres
                ),
            ),
        )
        resource_check("feature_vocabulary:after")
        passage_statistics_start = time.perf_counter()
        resource_check(
            "passage_feature_statistics:before",
            estimated_additional_bytes=_PASSAGE_STATISTICS_RESERVATION_BYTES,
        )
        passage_statistics = build_passage_feature_statistics(all_sequences, vocabulary)
        timings["passage_feature_statistics"] = time.perf_counter() - passage_statistics_start
        resource_check("passage_feature_statistics:after")
        feature_counts = {
            f"{namespace}:{family}": int(group.height)
            for (namespace, family), group in vocabulary.group_by(
                "language_namespace", "feature_family", maintain_order=False
            )
        }
        writer.write_frame("feature_vocabulary", vocabulary)
        writer.write_frame("passage_feature_statistics", passage_statistics)
        del passage_statistics
        gc.collect()
        resource_check("passage_feature_statistics:released")

        provenance_start = time.perf_counter()
        try:
            provenance_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
                "benchmark_split_provenance:duckdb-budget",
                preferred_bytes=_PROVENANCE_DUCKDB_PREFERRED_MEMORY_BYTES,
                reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
            )
        except LexicalResourceError as exc:
            raise LexicalPipelineError(str(exc)) from exc
        split_provenance = _load_split_provenance(
            database_path,
            [*all_sequences, *critical_all_sequences, *ketiv_hebrew],
            duckdb_memory_limit_bytes=provenance_duckdb_memory,
            duckdb_temp_directory=database_spill_directory,
            resource_check=resource_check,
        )
        affected_references = _oshb_affected_verse_references(
            database_path,
            duckdb_memory_limit_bytes=provenance_duckdb_memory,
            duckdb_temp_directory=database_spill_directory,
        )
        qere_references = {item.start_reference for item in hebrew}
        ketiv_references = {item.start_reference for item in ketiv_hebrew}
        missing_affected = sorted(
            set(affected_references).difference(qere_references.intersection(ketiv_references))
        )
        if missing_affected:
            raise LexicalPipelineError(
                "OSHB sensitivity references do not resolve in both Qere and Ketiv verse "
                f"streams: {missing_affected[:10]}"
            )
        timings["split_provenance_and_sensitivity_scope"] = time.perf_counter() - provenance_start

        primary_sequences_by_pair = {
            "hb_hb": hebrew,
            "gnt_gnt": greek,
            "hb_gnt_english_bridge": all_sequences,
        }
        index_seconds = 0.0
        retrieval_seconds = 0.0

        index_start = time.perf_counter()
        primary_indexes, primary_index_metadata, index_summaries = _build_indexes(
            writer=writer,
            definitions=_primary_index_definitions(hebrew, greek, config=config),
            config=config,
            configuration_hash=configuration_hash,
            experiment_run_id=experiment_run_id,
            resource_check=resource_check,
        )
        index_seconds += time.perf_counter() - index_start
        writer.write_frame("lexical_index_metadata", primary_index_metadata, part=0)
        primary_representation_ids = {
            pair: primary_indexes[pair].representation_id
            for pair in ("hb_hb", "gnt_gnt", "hb_gnt_english_bridge")
        }
        retrieval_start = time.perf_counter()
        primary_retrieval = _run_retrieval(
            writer=writer,
            indexes=primary_indexes,
            sequences_by_pair=primary_sequences_by_pair,
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            config=config,
            experiment_scope="primary",
            corpus_pairs=("hb_hb", "gnt_gnt", "hb_gnt_english_bridge"),
            split_provenance_by_passage_id=split_provenance,
            resource_check=resource_check,
        )
        retrieval_seconds += time.perf_counter() - retrieval_start
        candidates = primary_retrieval.candidates
        primary_ranking_count = primary_retrieval.ranking_count
        next_ranking_part = primary_retrieval.next_ranking_part
        next_ablation_part = primary_retrieval.next_ablation_part
        del primary_indexes, primary_index_metadata, primary_retrieval
        gc.collect()
        resource_check("primary_sparse_indexes:released")

        critical_sequences_by_pair = {
            "gnt_gnt": critical_greek,
            "hb_gnt_english_bridge": critical_all_sequences,
        }
        index_start = time.perf_counter()
        critical_indexes, critical_index_metadata, critical_summaries = _build_indexes(
            writer=writer,
            definitions=_critical_index_definitions(
                critical_hebrew=critical_hebrew,
                critical_greek=critical_greek,
                config=config,
            ),
            config=config,
            configuration_hash=configuration_hash,
            experiment_run_id=experiment_run_id,
            resource_check=resource_check,
        )
        index_seconds += time.perf_counter() - index_start
        index_summaries.update(critical_summaries)
        writer.write_frame("lexical_index_metadata", critical_index_metadata, part=1)
        critical_index_by_pair = {
            "gnt_gnt": critical_indexes["critical_gnt_gnt"],
            "hb_gnt_english_bridge": critical_indexes["critical_hb_gnt_english_bridge"],
        }
        critical_representation_ids = {
            pair: index.representation_id for pair, index in critical_index_by_pair.items()
        }
        retrieval_start = time.perf_counter()
        critical_retrieval = _run_retrieval(
            writer=writer,
            indexes=critical_index_by_pair,
            sequences_by_pair=critical_sequences_by_pair,
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            config=config,
            experiment_scope="critical_core_greek_sensitivity",
            corpus_pairs=critical_scope.corpus_pairs,
            split_provenance_by_passage_id=split_provenance,
            collect_candidates=False,
            ranking_part_start=next_ranking_part,
            ablation_part_start=next_ablation_part,
            resource_check=resource_check,
        )
        retrieval_seconds += time.perf_counter() - retrieval_start
        critical_ranking_count = critical_retrieval.ranking_count
        next_ranking_part = critical_retrieval.next_ranking_part
        next_ablation_part = critical_retrieval.next_ablation_part
        del critical_indexes, critical_index_by_pair, critical_index_metadata
        del critical_summaries, critical_retrieval
        gc.collect()
        resource_check("critical_sparse_indexes:released")

        index_start = time.perf_counter()
        ketiv_indexes, ketiv_index_metadata, ketiv_summaries = _build_indexes(
            writer=writer,
            definitions=_ketiv_index_definitions(ketiv_hebrew, config=config),
            config=config,
            configuration_hash=configuration_hash,
            experiment_run_id=experiment_run_id,
            resource_check=resource_check,
        )
        index_seconds += time.perf_counter() - index_start
        index_summaries.update(ketiv_summaries)
        writer.write_frame("lexical_index_metadata", ketiv_index_metadata, part=2)
        ketiv_representation_id = ketiv_indexes["ketiv_hb_hb"].representation_id
        retrieval_start = time.perf_counter()
        ketiv_retrieval = _run_retrieval(
            writer=writer,
            indexes={"hb_hb": ketiv_indexes["ketiv_hb_hb"]},
            sequences_by_pair={"hb_hb": ketiv_hebrew},
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            config=config,
            experiment_scope="hebrew_qere_ketiv_sensitivity",
            corpus_pairs=("hb_hb",),
            split_provenance_by_passage_id=split_provenance,
            query_reference_filter=frozenset(affected_references),
            collect_candidates=False,
            ranking_part_start=next_ranking_part,
            ablation_part_start=next_ablation_part,
            resource_check=resource_check,
        )
        retrieval_seconds += time.perf_counter() - retrieval_start
        ketiv_ranking_count = ketiv_retrieval.ranking_count
        next_ablation_part = ketiv_retrieval.next_ablation_part
        del ketiv_indexes, ketiv_index_metadata, ketiv_summaries, ketiv_retrieval
        del split_provenance
        gc.collect()
        resource_check("ketiv_sparse_indexes_and_split_provenance:released")

        ranking_count = primary_ranking_count + critical_ranking_count + ketiv_ranking_count
        timings["sparse_indexes"] = index_seconds
        timings["retrieval_and_reranking"] = retrieval_seconds

        sensitivity_start = time.perf_counter()
        sensitivity_part = 0
        sensitivity_counts = {
            "critical_core_profile": 0,
            "hebrew_qere_ketiv": 0,
        }
        ranking_root = writer.staging_dir / "directional_rankings"
        for frame in _iter_sensitivity_result_frames(
            ranking_root=ranking_root,
            baseline_scope="primary",
            comparison_scope="critical_core_greek_sensitivity",
            sensitivity_type="critical_core_profile",
            corpus_pairs=critical_scope.corpus_pairs,
            baseline_profile=primary.analysis_profile,
            comparison_profile=critical_scope.analysis_profile,
            baseline_reading=f"{primary.hebrew_reading}+{primary.greek_reading}",
            comparison_reading=(f"{critical_scope.hebrew_reading}+{critical_scope.greek_reading}"),
            baseline_sequences=all_sequences,
            comparison_sequences=critical_all_sequences,
            baseline_representation_ids={
                pair: primary_representation_ids[pair] for pair in critical_scope.corpus_pairs
            },
            comparison_representation_ids=critical_representation_ids,
            affected_references={},
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            resource_guard=resource_guard,
            spill_directory=writer.staging_dir / ".critical-sensitivity-spill",
        ):
            writer.write_frame("sensitivity_results", frame, part=sensitivity_part)
            sensitivity_part += 1
            sensitivity_counts["critical_core_profile"] += frame.height
        for frame in _iter_sensitivity_result_frames(
            ranking_root=ranking_root,
            baseline_scope="primary",
            comparison_scope="hebrew_qere_ketiv_sensitivity",
            sensitivity_type="hebrew_qere_ketiv",
            corpus_pairs=("hb_hb",),
            baseline_profile=primary.analysis_profile,
            comparison_profile=reading_scope.analysis_profile,
            baseline_reading=reading_scope.baseline_reading,
            comparison_reading=reading_scope.comparison_reading,
            baseline_sequences=hebrew,
            comparison_sequences=ketiv_hebrew,
            baseline_representation_ids={"hb_hb": primary_representation_ids["hb_hb"]},
            comparison_representation_ids={"hb_hb": ketiv_representation_id},
            affected_references=affected_references,
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            preregistration_hash=preregistration_hash,
            resource_guard=resource_guard,
            spill_directory=writer.staging_dir / ".qere-ketiv-sensitivity-spill",
        ):
            writer.write_frame("sensitivity_results", frame, part=sensitivity_part)
            sensitivity_part += 1
            sensitivity_counts["hebrew_qere_ketiv"] += frame.height
        if any(count < 1 for count in sensitivity_counts.values()):
            raise LexicalPipelineError(
                f"required sensitivity comparison produced no rows: {sensitivity_counts}"
            )
        timings["sensitivity_comparisons"] = time.perf_counter() - sensitivity_start

        del ketiv_hebrew, qere_references, ketiv_references, affected_references
        gc.collect()
        resource_check("pre_tier3_ketiv_working_set:released")

        experiment_start = time.perf_counter()
        try:
            detectors_by_pair = governed_detectors_by_corpus_pair(
                ranking_root,
                experiment_run_id=experiment_run_id,
                representation_ids=primary_representation_ids,
            )
            tier3_start = time.perf_counter()
            evaluation_artifacts = run_tier3_evaluation_experiment(
                ranking_root,
                sequences_by_corpus_pair=primary_sequences_by_pair,
                representation_ids=primary_representation_ids,
                config=config,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                benchmark_database_path=database_path,
                book_genres=book_genres,
                additional_evaluation_scopes=(
                    Tier3EvaluationScope(
                        analysis_profile=cast(AnalysisProfile, critical_scope.analysis_profile),
                        experiment_scope="critical_core_greek_sensitivity",
                        directional_rankings=ranking_root,
                        sequences_by_corpus_pair=critical_sequences_by_pair,
                        representation_ids=critical_representation_ids,
                    ),
                ),
                resource_check=resource_check,
                duckdb_memory_limit_bytes=database_duckdb_memory,
                duckdb_temp_directory=database_spill_directory / "experiment",
            )
            timings["tier3_evaluation"] = time.perf_counter() - tier3_start
            del critical_hebrew, critical_greek, critical_all_sequences
            del critical_sequences_by_pair, critical_representation_ids
            gc.collect()
            resource_check("post_tier3_sensitivity_sequences:released")

            null_start = time.perf_counter()
            calibration_artifacts = run_null_calibration_experiment(
                candidates,
                sequences_by_corpus_pair=primary_sequences_by_pair,
                representation_ids=primary_representation_ids,
                config=config,
                experiment_run_id=experiment_run_id,
                configuration_hash=configuration_hash,
                preregistration_hash=preregistration_hash,
                book_genres=book_genres,
                detectors_by_corpus_pair=detectors_by_pair,
                resource_check=resource_check,
            )
            timings["null_calibration"] = time.perf_counter() - null_start
            experiment = combine_lexical_experiment_artifacts(
                calibration_artifacts,
                evaluation_artifacts,
            )
            del calibration_artifacts, evaluation_artifacts
        except LexicalExperimentError as exc:
            raise LexicalPipelineError(f"lexical calibration/evaluation failed: {exc}") from exc
        timings["null_calibration_and_tier3_evaluation"] = time.perf_counter() - experiment_start
        null_frame = experiment.null_replicate_summaries
        calibration_frame = experiment.threshold_calibration
        evaluation_frame = experiment.evaluation_results
        calibration = dict(experiment.selected_calibration)
        scientific_gate_status = experiment.scientific_gate_status
        null_iteration_count = int(null_frame.get_column("null_run_id").n_unique())
        evaluation_count = evaluation_frame.height
        writer.write_frame("null_replicate_summaries", null_frame)
        writer.write_frame("threshold_calibration", calibration_frame)
        writer.write_frame("evaluation_results", evaluation_frame)
        resource_check("experiment_artifacts:written")

        del experiment, null_frame, calibration_frame, evaluation_frame
        hebrew.clear()
        greek.clear()
        book_genres.clear()
        del primary_sequences_by_pair
        gc.collect()
        resource_check("post_tier3_evaluation_working_sets:released")

        evidence_start = time.perf_counter()
        resource_check(
            "candidate_evidence_indexes:before",
            estimated_additional_bytes=_CANDIDATE_EVIDENCE_RESERVATION_BYTES,
        )
        feature_statistics, feature_passages = build_feature_evidence_indexes(
            all_sequences, vocabulary
        )
        feature_vocabulary_logical_hash = logical_frame_hash(vocabulary, sort_by=["feature_id"])
        del vocabulary
        gc.collect()
        resource_check("candidate_evidence_indexes:after")
        try:
            candidate_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
                "candidate_materialization:duckdb-budget",
                preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
                reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
            )
        except LexicalResourceError as exc:
            raise LexicalPipelineError(str(exc)) from exc
        known_pairs = load_known_pair_index(
            database_path,
            duckdb_memory_limit_bytes=candidate_duckdb_memory,
            duckdb_temp_directory=database_spill_directory,
            resource_check=resource_check,
        )
        context = CandidateEvidenceContext(
            experiment_run_id=experiment_run_id,
            configuration_hash=configuration_hash,
            sequences={item.passage_id: item for item in all_sequences},
            feature_statistics=feature_statistics,
            feature_passages=feature_passages,
            representation_ids=primary_representation_ids,
            known_pairs=known_pairs,
            calibration=calibration,
            config=config,
        )
        resource_check(
            "candidate_q_values:before",
            estimated_additional_bytes=max(64 * MEBIBYTE, len(candidates) * 256),
        )
        q_values = candidate_q_values(candidates, context)
        resource_check("candidate_q_values:after")
        queue_spool_directory = writer.staging_dir / ".candidate-review-queue-spool"
        queue_spool_directory.mkdir()
        queue_input_count = 0
        candidate_parts = 0
        ablation_part = next_ablation_part
        candidate_count = len(candidates)
        candidate_batches = iter_candidate_artifact_batches(
            candidates,
            context=context,
            q_values=q_values,
            duckdb_memory_limit_bytes=candidate_duckdb_memory,
            resource_check=resource_check,
        )
        for part, batch in enumerate(candidate_batches):
            writer.write_frame("candidate_pairs", batch.candidate_pairs, part=part)
            writer.write_frame("candidate_detector_scores", batch.detector_scores, part=part)
            writer.write_frame("candidate_evidence", batch.candidate_evidence, part=part)
            writer.write_frame("shared_evidence", batch.shared_evidence, part=part)
            if batch.ablation_results.height:
                writer.write_frame("ablation_results", batch.ablation_results, part=ablation_part)
                ablation_part += 1
            if batch.queue_candidates:
                queue_input = build_review_queue(batch.queue_candidates).drop("queue_rank")
                writer.check_free_disk(f"candidate_queue_spool:part-{part}:before")
                queue_input.write_parquet(
                    queue_spool_directory / f"part-{part:05d}.parquet",
                    compression="zstd",
                    compression_level=6,
                    statistics=True,
                )
                writer.check_free_disk(f"candidate_queue_spool:part-{part}:after")
                queue_input_count += queue_input.height
            candidate_parts += 1
            resource_check(f"candidate_artifacts:part-{part}")
            del batch
        if candidate_parts == 0:
            raise LexicalPipelineError("primary retrieval produced no persisted candidates")
        del candidate_batches, candidates, context, q_values, known_pairs
        del feature_statistics, feature_passages
        all_sequences.clear()
        gc.collect()
        resource_check("candidate_aggregate_working_sets:released")
        queue_count = 0
        for queue_part, queue_frame in enumerate(
            _iter_ranked_review_queue_frames(
                queue_spool_directory,
                expected_count=queue_input_count,
                duckdb_memory_limit_bytes=candidate_duckdb_memory,
                duckdb_temp_directory=writer.staging_dir / ".candidate-review-queue-sort-spill",
                resource_check=resource_check,
            )
        ):
            writer.write_frame("candidate_review_queue", queue_frame, part=queue_part)
            queue_count += queue_frame.height
        if queue_count != queue_input_count:
            raise LexicalPipelineError(
                "review-queue count differs after bounded global ranking: "
                f"spooled={queue_input_count}, ranked={queue_count}"
            )
        review_eligible_count = queue_input_count
        shutil.rmtree(queue_spool_directory)
        gc.collect()
        resource_check("candidate_review_queue:released")
        uncalibrated_pairs: list[str] = []
        for pair in primary_representation_ids:
            selection = calibration.get(pair)
            if selection is None or not (
                selection.both_null_families_present
                and math.isfinite(selection.score_threshold)
                and math.isfinite(selection.estimated_empirical_fdr)
                and selection.estimated_empirical_fdr
                <= config.candidate_thresholds.maximum_empirical_fdr
            ):
                uncalibrated_pairs.append(pair)
        writer.write_frame(
            "lexical_issues",
            _issue_frame(
                experiment_run_id,
                scientific_gate_status=scientific_gate_status,
                uncalibrated_corpus_pairs=uncalibrated_pairs,
                sensitivity_counts=sensitivity_counts,
            ),
        )
        timings["candidate_evidence_and_queue"] = time.perf_counter() - evidence_start

        resource_check(
            "finalize:before_hashes",
            estimated_additional_bytes=database_duckdb_memory,
        )
        content_hash_start = time.perf_counter()
        logical_hashes, physical_hashes = writer.content_hashes()
        staging_footprint = sum(
            path.stat().st_size for path in writer.staging_dir.rglob("*") if path.is_file()
        )
        timings["content_hashes_and_footprint"] = time.perf_counter() - content_hash_start
        acceptance_status = (
            "scientifically_complete"
            if scientific_gate_status == "passed" and not uncalibrated_pairs
            else "scientifically_incomplete"
        )
        resource_check("finalize:metadata")
        timings["pre_finalize_total"] = time.perf_counter() - start
        metadata = pl.DataFrame(
            [
                {
                    "experiment_run_id": experiment_run_id,
                    "experiment_version": config.experiment_version,
                    "lexical_schema_version": 1,
                    "candidate_pair_schema_version": 1,
                    "configuration_hash": configuration_hash,
                    "preregistration_hash": preregistration_hash,
                    "input_corpus_hashes_json": _canonical_json(
                        {
                            "identity": anchors.corpus_identity_digests,
                            "content": anchors.corpus_content_digests,
                            "analytical": anchors.corpus_analytical_digests,
                            "oshb": anchors.oshb_logical_hashes,
                        }
                    ),
                    "passage_hashes_json": _canonical_json(anchors.passage_logical_hashes),
                    "benchmark_hashes_json": _canonical_json(anchors.benchmark_logical_hashes),
                    "feature_vocabulary_hashes_json": _canonical_json(
                        {"all": feature_vocabulary_logical_hash}
                    ),
                    "sparse_index_hashes_json": _canonical_json(
                        {
                            str(value["index_id"]): value["logical_hash"]
                            for value in index_summaries.values()
                        }
                    ),
                    "table_logical_hashes_json": _canonical_json(logical_hashes),
                    "table_physical_hashes_json": _canonical_json(physical_hashes),
                    "ranking_count": ranking_count,
                    "candidate_count": candidate_count,
                    "null_iteration_count": null_iteration_count,
                    "evaluation_count": evaluation_count,
                    "runtime_seconds": time.perf_counter() - start,
                    "stage_runtime_seconds_json": _canonical_json(dict(sorted(timings.items()))),
                    "peak_memory_bytes": resource_guard.peak_rss_bytes,
                    "storage_footprint_bytes": staging_footprint,
                    "numerical_environment_json": _canonical_json(
                        {
                            "python": platform.python_version(),
                            "platform": platform.system(),
                            "polars": pl.__version__,
                            "rss_probe": "os_native_current_working_set",
                        }
                    ),
                    "thread_controls_json": _canonical_json(
                        {**thread_controls, "POLARS_OBSERVED_THREADS": observed_polars_threads}
                    ),
                    "acceptance_status": acceptance_status,
                    "notes": (
                        "Tier 3 weak-supervision only; primary nulls are edition-complete "
                        "verse/Qere/source only; critical-core and Qere/Ketiv are explicit "
                        "non-null sensitivity scopes; English bridge separate; Milestone 8 "
                        "review not begun"
                    ),
                }
            ],
            schema=LEXICAL_METADATA_SCHEMA,
            orient="row",
        )
        processed = writer.finalize(metadata)

    try:
        final_duckdb_memory = resource_guard.bounded_duckdb_memory_bytes(
            "duckdb_load:budget",
            preferred_bytes=_DUCKDB_PREFERRED_MEMORY_BYTES,
            reserve_for_python_bytes=_DUCKDB_PYTHON_RESERVE_BYTES,
        )
    except LexicalResourceError as exc:
        raise LexicalPipelineError(str(exc)) from exc
    final_spill_directory = (
        output_dir.parent / f".{output_dir.name}.{experiment_run_id}.duckdb-load-spill"
    )
    if final_spill_directory.exists():
        raise LexicalPipelineError(
            f"DuckDB load spill directory already exists: {final_spill_directory}"
        )
    try:
        load_lexical_duckdb(
            processed,
            database_path,
            duckdb_memory_limit_bytes=final_duckdb_memory,
            duckdb_temp_directory=final_spill_directory,
        )
    finally:
        shutil.rmtree(final_spill_directory, ignore_errors=True)
    resource_check("duckdb_load:after")
    timings["total"] = time.perf_counter() - start
    gc.collect()
    return LexicalPipelineResult(
        experiment_run_id=experiment_run_id,
        experiment_version=config.experiment_version,
        configuration_hash=configuration_hash,
        preregistration_hash=preregistration_hash,
        anchors=anchors,
        processed=processed,
        database_path=database_path,
        stage_runtime_seconds=timings,
        feature_counts=feature_counts,
        index_summaries=index_summaries,
        ranking_count=ranking_count,
        candidate_count=candidate_count,
        review_eligible_count=review_eligible_count,
        queue_count=queue_count,
        null_iteration_count=null_iteration_count,
        evaluation_count=evaluation_count,
        acceptance_status=acceptance_status,
        approximate_peak_memory_bytes=resource_guard.peak_rss_bytes,
    )
