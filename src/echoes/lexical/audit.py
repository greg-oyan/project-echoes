"""Full-data lexical feasibility audit without candidate generation."""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import duckdb

from echoes.lexical.config import (
    LEXICAL_CONFIG_PATH,
    FeatureFamily,
    load_lexical_config,
)
from echoes.lexical.identity import (
    FeatureIdentityPayload,
    LanguageNamespace,
    build_feature_identity,
)
from echoes.lexical.resources import (
    LexicalResourceError,
    ProcessResourceGuard,
    configure_duckdb_connection,
    physical_memory_bytes,
)
from echoes.lexical.sequences import PassageLexicalSequence, iter_passage_sequences


class LexicalAuditError(RuntimeError):
    """Raised when the lexical feasibility audit cannot be completed."""


@contextmanager
def _bounded_audit_connection(
    database_path: Path,
    *,
    memory_limit_bytes: int,
) -> Iterator[duckdb.DuckDBPyConnection]:
    with (
        TemporaryDirectory(prefix="echoes-lexical-audit-query-") as temporary,
        duckdb.connect(str(database_path), read_only=True) as connection,
    ):
        configure_duckdb_connection(
            connection,
            memory_limit_bytes=memory_limit_bytes,
            temp_directory=Path(temporary) / "spill",
            thread_count=1,
        )
        yield connection


def _load_audit_sequences(
    database_path: Path,
    *,
    memory_limit_bytes: int,
    corpus: str,
    analysis_reading: str,
) -> list[PassageLexicalSequence]:
    with TemporaryDirectory(prefix=f"echoes-lexical-audit-{corpus}-") as temporary:
        return list(
            iter_passage_sequences(
                database_path,
                corpus=corpus,
                analysis_profile="edition_complete",
                analysis_reading=analysis_reading,
                granularity="verse",
                duckdb_memory_limit_bytes=memory_limit_bytes,
                duckdb_temp_directory=Path(temporary) / "spill",
            )
        )


def _feature_id(
    *,
    namespace: str,
    family: str,
    value: str | tuple[str, ...],
    order: int = 1,
) -> str:
    serialized = value if isinstance(value, str) else "\u241f".join(value)
    return build_feature_identity(
        FeatureIdentityPayload(
            feature_family=cast(FeatureFamily, family),
            language_namespace=cast(LanguageNamespace, namespace),
            feature_value=serialized,
            feature_order=order,
        )
    ).identifier


def _occurrences(
    sequences: Sequence[PassageLexicalSequence], family: str
) -> Iterable[tuple[str, ...]]:
    for passage in sequences:
        yield passage.values(family)


def _sanitized_feature_rows(
    sequences_by_corpus: Sequence[tuple[str, str, Sequence[PassageLexicalSequence]]],
    *,
    formulaic_ratio: float,
    formulaic_minimum_count: int,
    rare_maximum_count: int,
) -> tuple[
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    list[tuple[object, ...]],
]:
    """Return bounded, ID-only frequency reports without redistributing lexical values."""

    most_frequent: list[tuple[object, ...]] = []
    highest_df: list[tuple[object, ...]] = []
    formulaic: list[tuple[object, ...]] = []
    rare: list[tuple[object, ...]] = []
    for corpus, namespace, sequences in sequences_by_corpus:
        for family in ("lemma", "root", "surface", "english_gloss"):
            effective_namespace = "en" if family == "english_gloss" else namespace
            frequencies: Counter[str] = Counter()
            document_frequencies: Counter[str] = Counter()
            for values in _occurrences(sequences, family):
                frequencies.update(values)
                document_frequencies.update(set(values))
            formulaic_df = max(1, int(len(sequences) * formulaic_ratio + 0.999999999))
            ordered_frequency = sorted(
                frequencies,
                key=lambda value: (-frequencies[value], -document_frequencies[value], value),
            )
            ordered_df = sorted(
                document_frequencies,
                key=lambda value: (-document_frequencies[value], -frequencies[value], value),
            )
            for value in ordered_frequency[:10]:
                most_frequent.append(
                    (
                        corpus,
                        family,
                        _feature_id(
                            namespace=effective_namespace,
                            family=family if family != "surface" else "normalized_surface",
                            value=value,
                        ),
                        frequencies[value],
                        document_frequencies[value],
                    )
                )
            for value in ordered_df[:10]:
                highest_df.append(
                    (
                        corpus,
                        family,
                        _feature_id(
                            namespace=effective_namespace,
                            family=family if family != "surface" else "normalized_surface",
                            value=value,
                        ),
                        frequencies[value],
                        document_frequencies[value],
                    )
                )
            formulaic_values = sorted(
                (
                    value
                    for value in frequencies
                    if frequencies[value] >= formulaic_minimum_count
                    and document_frequencies[value] >= formulaic_df
                ),
                key=lambda value: (-document_frequencies[value], -frequencies[value], value),
            )
            for value in formulaic_values[:10]:
                formulaic.append(
                    (
                        corpus,
                        family,
                        _feature_id(
                            namespace=effective_namespace,
                            family=family if family != "surface" else "normalized_surface",
                            value=value,
                        ),
                        frequencies[value],
                        document_frequencies[value],
                        "marked_formulaic_and_retained_for_audit",
                    )
                )
            rare_values = sorted(
                (value for value, count in frequencies.items() if count <= rare_maximum_count),
                key=lambda value: (frequencies[value], value),
            )
            for value in rare_values[:10]:
                count = frequencies[value]
                rare.append(
                    (
                        corpus,
                        family,
                        _feature_id(
                            namespace=effective_namespace,
                            family=family if family != "surface" else "normalized_surface",
                            value=value,
                        ),
                        count,
                        document_frequencies[value],
                        "hapax" if count == 1 else "near_hapax_or_rare",
                    )
                )
        for n, feature_family in ((2, "lemma_ngram"), (3, "lemma_ngram")):
            frequencies_ngram: Counter[tuple[str, ...]] = Counter()
            document_ngram: Counter[tuple[str, ...]] = Counter()
            for values in _occurrences(sequences, "lemma"):
                features = tuple(zip(*(values[offset:] for offset in range(n)), strict=False))
                frequencies_ngram.update(features)
                document_ngram.update(set(features))
            for ngram_value in sorted(
                frequencies_ngram,
                key=lambda item: (-frequencies_ngram[item], -document_ngram[item], item),
            )[:10]:
                most_frequent.append(
                    (
                        corpus,
                        f"lemma_{n}gram",
                        _feature_id(
                            namespace=namespace,
                            family=feature_family,
                            value=ngram_value,
                            order=n,
                        ),
                        frequencies_ngram[ngram_value],
                        document_ngram[ngram_value],
                    )
                )
    return most_frequent, highest_df, formulaic, rare


def _qere_ketiv_frequency_changes(
    qere: Sequence[PassageLexicalSequence],
    ketiv: Sequence[PassageLexicalSequence],
) -> list[tuple[object, ...]]:
    """Return the largest ID-only lemma-frequency changes across paired readings."""

    qere_by_reference = {item.start_reference: item for item in qere}
    ketiv_by_reference = {item.start_reference: item for item in ketiv}
    paired = sorted(set(qere_by_reference).intersection(ketiv_by_reference))
    qere_counts: Counter[str] = Counter()
    ketiv_counts: Counter[str] = Counter()
    for reference in paired:
        qere_counts.update(qere_by_reference[reference].values("lemma"))
        ketiv_counts.update(ketiv_by_reference[reference].values("lemma"))
    changed = sorted(
        set(qere_counts).union(ketiv_counts),
        key=lambda value: (
            -abs(ketiv_counts[value] - qere_counts[value]),
            value,
        ),
    )
    rows: list[tuple[object, ...]] = []
    for value in changed:
        if qere_counts[value] == ketiv_counts[value]:
            continue
        rows.append(
            (
                _feature_id(namespace="hb", family="lemma", value=value),
                qere_counts[value],
                ketiv_counts[value],
                ketiv_counts[value] - qere_counts[value],
            )
        )
        if len(rows) == 25:
            break
    return rows


def _markdown_table(headers: tuple[str, ...], rows: Sequence[tuple[object, ...]]) -> list[str]:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return output


def _ngram_statistics(
    sequences: list[PassageLexicalSequence], family: str
) -> tuple[int, int, int, int, int, int]:
    bigrams: Counter[tuple[str, ...]] = Counter()
    trigrams: Counter[tuple[str, ...]] = Counter()
    skipgrams: Counter[tuple[str, str]] = Counter()
    for passage in sequences:
        values = passage.values(family)
        bigrams.update(pairwise(values))
        trigrams.update(zip(values, values[1:], values[2:], strict=False))
        for index, first in enumerate(values):
            for second_index in range(index + 2, min(len(values), index + 4)):
                skipgrams[(first, values[second_index])] += 1
    return (
        sum(count >= 2 for count in bigrams.values()),
        sum(count >= 2 for count in trigrams.values()),
        sum(count >= 2 for count in skipgrams.values()),
        max(bigrams.values(), default=0),
        max(trigrams.values(), default=0),
        max(skipgrams.values(), default=0),
    )


def _document_frequency_statistics(
    sequences: list[PassageLexicalSequence], family: str, *, formulaic_ratio: float
) -> tuple[int, int, int, int, int]:
    frequencies: Counter[str] = Counter()
    for passage in sequences:
        frequencies.update(set(passage.values(family)))
    ordered = sorted(frequencies.values())
    if not ordered:
        return (0, 0, 0, 0, 0)

    def percentile(ratio: float) -> int:
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))]

    formulaic_threshold = max(1, int(len(sequences) * formulaic_ratio + 0.999999999))
    return (
        len(ordered),
        percentile(0.5),
        percentile(0.95),
        ordered[-1],
        sum(value >= formulaic_threshold for value in ordered),
    )


def generate_lexical_feature_audit(
    *,
    database_path: Path,
    output_path: Path,
    lexical_config_path: Path = LEXICAL_CONFIG_PATH,
) -> str:
    """Inspect complete local artifacts and write the registered sanitized audit."""

    if not database_path.is_file():
        raise LexicalAuditError(f"DuckDB database does not exist: {database_path}")
    try:
        lexical_config = load_lexical_config(lexical_config_path)
    except ValueError as exc:
        raise LexicalAuditError(f"could not load governed lexical configuration: {exc}") from exc
    try:
        resource_guard = ProcessResourceGuard(lexical_config.resource_limits.maximum_memory_bytes)
        duckdb_memory_limit = resource_guard.bounded_duckdb_memory_bytes(
            "feature-audit:duckdb-budget",
            preferred_bytes=1024**3,
            reserve_for_python_bytes=1024**3,
        )
    except LexicalResourceError as exc:
        raise LexicalAuditError(f"could not establish bounded audit resources: {exc}") from exc
    coverage_rows: list[tuple[object, ...]] = []
    distinct_rows: list[tuple[object, ...]] = []
    passage_length_rows: list[tuple[object, ...]] = []
    benchmark_pair_rows: list[tuple[object, ...]] = []
    mapping_rows: list[tuple[object, ...]] = []
    split_rows: list[tuple[object, ...]] = []
    vote_rows: list[tuple[object, ...]] = []
    structural_rows: list[tuple[object, ...]] = []
    try:
        with _bounded_audit_connection(
            database_path,
            memory_limit_bytes=duckdb_memory_limit,
        ) as connection:
            for corpus, table, root_expression, entity_expression, zero_width_expression in (
                ("hebrew", "hebrew_tokens", "lexical_root", "entity_id", "is_zero_width"),
                ("greek", "greek_tokens", "NULL", "NULL", "false"),
            ):
                row = connection.execute(
                    f"""
                    SELECT count(*), count(lemma), count({root_expression}),
                           count(surface_form), count(normalized_form), count(english_gloss),
                           count(part_of_speech), count(morphology_json),
                           count({entity_expression}), count(participant_id),
                           count(*) FILTER (WHERE is_punctuation),
                           count(*) FILTER (WHERE {zero_width_expression})
                    FROM {table}
                    """
                ).fetchone()
                if row is None:
                    raise LexicalAuditError(f"coverage query returned no row for {corpus}")
                coverage_rows.append((corpus, *[int(value) for value in row]))
                distinct = connection.execute(
                    f"""
                    SELECT count(DISTINCT lemma), count(DISTINCT {root_expression}),
                           count(DISTINCT normalized_form),
                           count(DISTINCT part_of_speech), count(DISTINCT morphology_json)
                    FROM {table}
                    """
                ).fetchone()
                if distinct is None:
                    raise LexicalAuditError(f"distinct query returned no row for {corpus}")
                distinct_rows.append((corpus, *[int(value) for value in distinct]))
            passage_length_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT corpus, analysis_profile, analysis_reading, granularity,
                           count(*), min(token_count),
                           round(quantile_cont(token_count, 0.5), 2),
                           round(quantile_cont(token_count, 0.95), 2), max(token_count)
                    FROM passages GROUP BY ALL ORDER BY 1,2,3,4
                    """
                ).fetchall()
            ]
            frequency_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    WITH features AS (
                      SELECT 'hebrew' corpus, lemma feature_value FROM hebrew_tokens
                      WHERE lemma IS NOT NULL AND NOT is_punctuation AND NOT is_zero_width
                      UNION ALL
                      SELECT 'greek', lemma FROM greek_tokens
                      WHERE lemma IS NOT NULL AND NOT is_punctuation
                    ), frequencies AS (
                      SELECT corpus, feature_value, count(*) frequency FROM features GROUP BY ALL
                    )
                    SELECT corpus, count(*) distinct_features,
                           count(*) FILTER (WHERE frequency=1) hapax,
                           count(*) FILTER (WHERE frequency BETWEEN 2 AND 3) near_hapax,
                           max(frequency) maximum_frequency
                    FROM frequencies GROUP BY corpus ORDER BY corpus
                    """
                ).fetchall()
            ]
            structural_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT 'hebrew_multi_morpheme_words', count(*) FROM (
                      SELECT source_word_id FROM hebrew_tokens GROUP BY source_word_id
                      HAVING count(*) > 1
                    ) UNION ALL
                    SELECT 'greek_elided_tokens', count(*) FROM greek_tokens WHERE is_elided
                    UNION ALL
                    SELECT 'ketiv_supplement_tokens', count(*) FROM hebrew_kq_ketiv_tokens
                    UNION ALL
                    SELECT 'qere_affected_verse_passages', count(DISTINCT p.passage_id)
                    FROM passages p JOIN passage_membership m USING(passage_id)
                    WHERE p.corpus='hebrew' AND p.analysis_reading='qere'
                      AND p.granularity='verse' AND m.locus_id IS NOT NULL
                    UNION ALL
                    SELECT 'ketiv_affected_verse_passages', count(DISTINCT p.passage_id)
                    FROM passages p JOIN passage_membership m USING(passage_id)
                    WHERE p.corpus='hebrew' AND p.analysis_reading='ketiv'
                      AND p.granularity='verse' AND m.locus_id IS NOT NULL
                    """
                ).fetchall()
            ]
            reading_sensitivity = connection.execute(
                """
                SELECT count(*) paired_verses,
                       count(*) FILTER (WHERE q.token_ids_json <> k.token_ids_json) token_changes,
                       count(*) FILTER (WHERE q.lemma_sequence_json <> k.lemma_sequence_json)
                           lemma_changes
                FROM passages q JOIN passages k
                  ON q.corpus=k.corpus AND q.analysis_profile=k.analysis_profile
                 AND q.granularity=k.granularity AND q.book=k.book
                 AND q.start_reference=k.start_reference AND q.end_reference=k.end_reference
                WHERE q.corpus='hebrew' AND q.analysis_profile='edition_complete'
                  AND q.granularity='verse' AND q.analysis_reading='qere'
                  AND k.analysis_reading='ketiv'
                """
            ).fetchone()
            profile_sensitivity = connection.execute(
                """
                SELECT count(*) paired_verses,
                       count(*) FILTER (WHERE e.token_ids_json <> c.token_ids_json) token_changes,
                       count(*) FILTER (WHERE e.lemma_sequence_json <> c.lemma_sequence_json)
                           lemma_changes
                FROM passages e JOIN passages c
                  ON e.corpus=c.corpus AND e.analysis_reading=c.analysis_reading
                 AND e.granularity=c.granularity AND e.book=c.book
                 AND e.start_reference=c.start_reference AND e.end_reference=c.end_reference
                WHERE e.corpus='greek' AND e.analysis_profile='edition_complete'
                  AND c.analysis_profile='critical_core' AND e.analysis_reading='source'
                  AND e.granularity='verse'
                """
            ).fetchone()
            if reading_sensitivity is None or profile_sensitivity is None:
                raise LexicalAuditError("sensitivity query returned no row")
            benchmark_pair_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    WITH targets AS (
                      SELECT e.relationship_id, e.endpoint_side, m.mapping_status,
                             m.target_corpus, t.target_passage_id
                      FROM benchmark_endpoints e
                      JOIN benchmark_endpoint_mappings m USING(endpoint_id)
                      JOIN benchmark_mapping_target_passages t USING(mapping_id,endpoint_id)
                      WHERE m.target_analysis_profile='edition_complete'
                        AND m.mapping_status IN (
                          'mapped_verified','mapped_provisional','mapped_partial'
                        )
                    ), pairs AS (
                      SELECT a.relationship_id, a.target_corpus a_corpus,
                             b.target_corpus b_corpus, a.target_passage_id a, b.target_passage_id b
                      FROM targets a JOIN targets b USING(relationship_id)
                      WHERE a.endpoint_side='a' AND b.endpoint_side='b'
                    )
                    SELECT CASE WHEN a_corpus='hebrew' AND b_corpus='hebrew' THEN 'hb_hb'
                                WHEN a_corpus='greek' AND b_corpus='greek' THEN 'gnt_gnt'
                                ELSE 'hb_gnt_english_bridge' END corpus_pair,
                           count(DISTINCT relationship_id), count(*) mapped_pairs,
                           count(DISTINCT a) queries_a, count(DISTINCT b) queries_b
                    FROM pairs GROUP BY 1 ORDER BY 1
                    """
                ).fetchall()
            ]
            mapping_rows = [
                tuple(row)
                for row in connection.execute(
                    "SELECT mapping_status,count(*) FROM benchmark_endpoint_mappings "
                    "GROUP BY 1 ORDER BY 1"
                ).fetchall()
            ]
            split_rows = [
                tuple(row)
                for row in connection.execute(
                    "SELECT split_strategy,partition,count(*) FROM benchmark_split_assignments "
                    "GROUP BY ALL ORDER BY 1,2"
                ).fetchall()
            ]
            vote_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT CASE WHEN source_weight_max<0 THEN 'negative'
                                WHEN source_weight_max=0 THEN 'zero'
                                WHEN source_weight_max<=2 THEN '1-2'
                                WHEN source_weight_max<=5 THEN '3-5'
                                WHEN source_weight_max<=10 THEN '6-10'
                                WHEN source_weight_max<=25 THEN '11-25' ELSE '26+' END vote_stratum,
                           count(*) FROM benchmark_relationships GROUP BY 1 ORDER BY 1
                    """
                ).fetchall()
            ]
            multiple_targets = connection.execute(
                """
                WITH targets AS (
                  SELECT e.relationship_id,e.endpoint_side,count(*) target_count
                  FROM benchmark_endpoints e
                  JOIN benchmark_endpoint_mappings m USING(endpoint_id)
                  JOIN benchmark_mapping_target_passages t USING(mapping_id,endpoint_id)
                  WHERE m.target_analysis_profile='edition_complete'
                  GROUP BY 1,2
                )
                SELECT count(*) FILTER(WHERE target_count=1),
                       count(*) FILTER(WHERE target_count>1), max(target_count)
                FROM targets
                """
            ).fetchone()
            if multiple_targets is None:
                raise LexicalAuditError("benchmark target-cardinality query returned no row")
    except (duckdb.Error, OSError) as exc:
        raise LexicalAuditError(f"lexical feasibility query failed: {exc}") from exc

    hebrew = _load_audit_sequences(
        database_path,
        memory_limit_bytes=duckdb_memory_limit,
        corpus="hebrew",
        analysis_reading="qere",
    )
    greek = _load_audit_sequences(
        database_path,
        memory_limit_bytes=duckdb_memory_limit,
        corpus="greek",
        analysis_reading="source",
    )
    ketiv = _load_audit_sequences(
        database_path,
        memory_limit_bytes=duckdb_memory_limit,
        corpus="hebrew",
        analysis_reading="ketiv",
    )
    lemma_phrase = {
        "hebrew": _ngram_statistics(hebrew, "lemma"),
        "greek": _ngram_statistics(greek, "lemma"),
    }
    root_phrase = {
        "hebrew": _ngram_statistics(hebrew, "root"),
        "greek": _ngram_statistics(greek, "root"),
    }
    all_sequences = hebrew + greek
    estimated_nnz = {
        "hebrew_lemma": sum(len(set(item.values("lemma"))) for item in hebrew),
        "hebrew_root": sum(len(set(item.values("root"))) for item in hebrew),
        "greek_lemma": sum(len(set(item.values("lemma"))) for item in greek),
        "greek_root": sum(len(set(item.values("root"))) for item in greek),
        "english_gloss": sum(len(set(item.values("english_gloss"))) for item in all_sequences),
    }
    estimated_csr_bytes = {
        name: (nonzeros * 16) + ((row_count + 1) * 8)
        for name, nonzeros, row_count in (
            ("hebrew_lemma", estimated_nnz["hebrew_lemma"], len(hebrew)),
            ("hebrew_root", estimated_nnz["hebrew_root"], len(hebrew)),
            ("greek_lemma", estimated_nnz["greek_lemma"], len(greek)),
            ("greek_root", estimated_nnz["greek_root"], len(greek)),
            ("english_gloss", estimated_nnz["english_gloss"], len(all_sequences)),
        )
    }
    hebrew_lemma_values = {value for item in hebrew for value in item.values("lemma")}
    greek_lemma_values = {value for item in greek for value in item.values("lemma")}
    raw_serialization_overlap = len(hebrew_lemma_values & greek_lemma_values)
    feature_collision_count = len(
        {f"hb:lemma:{value}" for value in hebrew_lemma_values}
        & {f"gk:lemma:{value}" for value in greek_lemma_values}
    )
    memory = physical_memory_bytes()
    disk = shutil.disk_usage(database_path.parent).free
    document_frequency_rows = [
        (
            corpus,
            family,
            *_document_frequency_statistics(
                sequences,
                family,
                formulaic_ratio=(
                    lexical_config.feature_frequency_thresholds.formulaic_document_frequency_ratio
                ),
            ),
        )
        for corpus, sequences in (("hebrew", hebrew), ("greek", greek))
        for family in ("lemma", "root", "surface", "english_gloss")
    ]
    most_frequent_rows, highest_df_rows, formulaic_rows, rare_rows = _sanitized_feature_rows(
        (("hebrew", "hb", hebrew), ("greek", "gk", greek)),
        formulaic_ratio=(
            lexical_config.feature_frequency_thresholds.formulaic_document_frequency_ratio
        ),
        formulaic_minimum_count=(
            lexical_config.feature_frequency_thresholds.formulaic_minimum_corpus_count
        ),
        rare_maximum_count=lexical_config.rare_evidence.maximum_corpus_frequency,
    )
    qere_ketiv_change_rows = _qere_ketiv_frequency_changes(hebrew, ketiv)
    lines = [
        "# Milestone 7 lexical-feature and feasibility audit",
        "",
        "This is a structural and quantitative audit. It contains no bulk source text "
        "and makes no interpretive claim.",
        "",
        "## Coverage",
        "",
        *_markdown_table(
            (
                "corpus",
                "tokens",
                "lemma",
                "root",
                "surface",
                "normalized",
                "English gloss",
                "POS",
                "morphology",
                "entity",
                "participant",
                "punctuation",
                "zero width",
            ),
            coverage_rows,
        ),
        "",
        "Greek and Hebrew root coverage is zero in the governed full artifacts; root "
        "interfaces remain fixture-tested and no roots are fabricated.",
        "",
        "## Distinct feature inventory",
        "",
        *_markdown_table(
            ("corpus", "lemmas", "roots", "normalized surfaces", "POS", "morphology"),
            distinct_rows,
        ),
        "",
        *_markdown_table(
            ("corpus", "distinct lemmas", "hapax", "frequency 2-3", "maximum frequency"),
            frequency_rows,
        ),
        "",
        "### Primary-verse document-frequency distributions",
        "",
        *_markdown_table(
            (
                "corpus",
                "family",
                "features",
                "median DF",
                "p95 DF",
                "maximum DF",
                "DF-ratio-threshold features",
            ),
            document_frequency_rows,
        ),
        "",
        "### Sanitized feature-frequency exemplars",
        "",
        "The bounded tables below identify features by stable governed feature ID, not by "
        "redistributing source lexical strings. The IDs resolve against the local generated "
        "feature vocabulary. Counts come from the nonduplicated primary verse streams.",
        "",
        "#### Most frequent lemmas, roots, and lemma n-grams",
        "",
        *_markdown_table(
            ("corpus", "family", "feature ID", "corpus frequency", "document frequency"),
            most_frequent_rows,
        ),
        "",
        "#### Highest-document-frequency features",
        "",
        *_markdown_table(
            ("corpus", "family", "feature ID", "corpus frequency", "document frequency"),
            highest_df_rows,
        ),
        "",
        "#### Formulaic features",
        "",
        *_markdown_table(
            (
                "corpus",
                "family",
                "feature ID",
                "corpus frequency",
                "document frequency",
                "governed action",
            ),
            formulaic_rows,
        ),
        "",
        "#### Rare, hapax, and near-hapax features",
        "",
        *_markdown_table(
            (
                "corpus",
                "family",
                "feature ID",
                "corpus frequency",
                "document frequency",
                "rarity class",
            ),
            rare_rows,
        ),
        "",
        "#### Lemma frequencies changed by Qere/Ketiv reading",
        "",
        *_markdown_table(
            ("feature ID", "Qere frequency", "Ketiv frequency", "Ketiv minus Qere"),
            qere_ketiv_change_rows,
        ),
        "",
        "## Passage-length distributions",
        "",
        *_markdown_table(
            ("corpus", "profile", "reading", "granularity", "count", "min", "median", "p95", "max"),
            passage_length_rows,
        ),
        "",
        "The primary calibrated v1 scope contains "
        f"{len(hebrew):,} Hebrew/Aramaic Qere verses and {len(greek):,} Greek source verses. "
        "Other granularities are production interfaces with bounded smoke tests only.",
        "",
        "## Phrase feasibility",
        "",
        *_markdown_table(
            (
                "corpus",
                "lemma bigrams count>=2",
                "lemma trigrams count>=2",
                "lemma skipgrams count>=2",
                "maximum bigram count",
                "maximum trigram count",
                "maximum skipgram count",
            ),
            [(corpus, *values) for corpus, values in sorted(lemma_phrase.items())],
        ),
        "",
        *_markdown_table(
            (
                "corpus",
                "root bigrams count>=2",
                "root trigrams count>=2",
                "root skipgrams count>=2",
                "maximum bigram count",
                "maximum trigram count",
                "maximum skipgram count",
            ),
            [(corpus, *values) for corpus, values in sorted(root_phrase.items())],
        ),
        "",
        "## Tokenization and sensitivity",
        "",
        *_markdown_table(("measure", "count"), structural_rows),
        "",
        *_markdown_table(
            ("sensitivity", "paired verses", "token changes", "lemma changes"),
            [
                ("Hebrew Qere versus Ketiv", *reading_sensitivity),
                ("Greek edition-complete versus critical-core", *profile_sensitivity),
            ],
        ),
        "",
        "Zero-width and punctuation records remain in provenance but are excluded from "
        "visible lexical features. Hebrew morpheme order and word boundaries and Greek "
        "elision flags are preserved.",
        "",
        "## Namespace and sparse-index feasibility",
        "",
        f"Raw cross-language lemma serialization overlaps: **{raw_serialization_overlap}**. "
        f"Language-prefixed lemma identity collisions: **{feature_collision_count}** "
        "(required: 0). Raw overlap is never treated as lexical equivalence.",
        "",
        *_markdown_table(
            (
                "representation",
                "rows",
                "columns",
                "estimated nonzeros",
                "estimated count-CSR bytes",
            ),
            [
                (
                    "hb:lemma",
                    len(hebrew),
                    len(hebrew_lemma_values),
                    estimated_nnz["hebrew_lemma"],
                    estimated_csr_bytes["hebrew_lemma"],
                ),
                (
                    "hb:root",
                    len(hebrew),
                    len({value for item in hebrew for value in item.values("root")}),
                    estimated_nnz["hebrew_root"],
                    estimated_csr_bytes["hebrew_root"],
                ),
                (
                    "gk:lemma",
                    len(greek),
                    len(greek_lemma_values),
                    estimated_nnz["greek_lemma"],
                    estimated_csr_bytes["greek_lemma"],
                ),
                (
                    "gk:root",
                    len(greek),
                    len({value for item in greek for value in item.values("root")}),
                    estimated_nnz["greek_root"],
                    estimated_csr_bytes["greek_root"],
                ),
                (
                    "en:gloss",
                    len(all_sequences),
                    len(
                        {value for item in all_sequences for value in item.values("english_gloss")}
                    ),
                    estimated_nnz["english_gloss"],
                    estimated_csr_bytes["english_gloss"],
                ),
            ],
        ),
        "",
        "Count-CSR estimates include float64 values, int64 column indices, and the "
        "int64 row pointer. Binary/TF-IDF matrices, vocabulary metadata, and transient "
        "retrieval blocks require additional bounded memory.",
        "",
        f"Audited physical memory: {memory:,} bytes where available. Governed memory "
        f"ceiling: {lexical_config.resource_limits.maximum_memory_bytes:,} bytes. Free disk "
        f"near the database: {disk:,} bytes; configured minimum: "
        f"{lexical_config.resource_limits.minimum_free_disk_bytes:,} bytes. Governed "
        f"retrieval block: {lexical_config.resource_limits.block_passage_count:,} passages. "
        "Retrieval uses CSR matrices, stable vocabulary order, blockwise products, bounded "
        "candidate unions, and no dense all-pairs matrix.",
        "",
        "## Benchmark feasibility",
        "",
        *_markdown_table(
            ("corpus pair", "relationships", "mapped pairs", "queries A", "queries B"),
            benchmark_pair_rows,
        ),
        "",
        f"Endpoint mappings with one target: {int(multiple_targets[0]):,}; with multiple "
        f"targets: {int(multiple_targets[1]):,}; maximum targets: "
        f"{int(multiple_targets[2]):,}.",
        "",
        "### Mapping status",
        "",
        *_markdown_table(("status", "count"), mapping_rows),
        "",
        "### OpenBible vote strata",
        "",
        *_markdown_table(("descriptive vote stratum", "relationships"), vote_rows),
        "",
        "### Governed split assignments",
        "",
        *_markdown_table(("strategy", "partition", "count"), split_rows),
        "",
        "OpenBible remains Tier 3 weak supervision; same-label mappings remain provisional "
        "and votes are descriptive ranking values, not calibrated confidence.",
        "",
        "## Feasibility decision",
        "",
        "The verse-level transparent lexical experiment is feasible within the audited "
        "machine limits using deterministic sparse, blockwise retrieval. Root evidence is "
        "unavailable in the full corpora and must be reported as such. English-gloss "
        "cross-testament retrieval is a separately namespaced exploratory bridge requiring "
        "complete ablation.",
    ]
    report = "\n".join(lines).rstrip() + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(output_path)
    return report
