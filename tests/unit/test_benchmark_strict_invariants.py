"""Fixture-only tamper tests for strict Milestone 6 relational invariants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from echoes.benchmarks.mapping import (
    PassageReferenceIndex,
    PassageTarget,
    map_benchmark_endpoints,
)
from echoes.benchmarks.models import BenchmarkEndpointRow
from echoes.benchmarks.pipeline import (
    _exact_pair_group_id,
    _hash_partition,
    _split_assignment_id,
    benchmark_config_fingerprint,
)
from echoes.benchmarks.validation import (
    BenchmarkValidationIssue,
    _expected_contrastive_id,
    _mapping_database_validation,
    _negative_database_validation,
    _split_database_validation,
)
from echoes.settings import BenchmarkConfig, load_config


def _id(prefix: str, digit: str) -> str:
    return f"{prefix}_{digit * 64}"


def _create_table(
    connection: duckdb.DuckDBPyConnection, name: str, rows: list[dict[str, Any]]
) -> None:
    frame = pl.DataFrame(rows, strict=False)
    connection.register("_fixture_frame", frame)
    try:
        connection.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _fixture_frame')
    finally:
        connection.unregister("_fixture_frame")


def _target(
    passage_id: str,
    *,
    corpus: str,
    profile: str,
    reading: str,
    book: str,
    chapter: int,
    verse: int,
    disputed_ids: tuple[str, ...] = (),
    reference_gap: bool = False,
) -> PassageTarget:
    return PassageTarget(
        passage_id=passage_id,
        corpus=corpus,  # type: ignore[arg-type]
        analysis_profile=profile,  # type: ignore[arg-type]
        analysis_reading=reading,  # type: ignore[arg-type]
        book=book,
        chapter=chapter,
        verse=verse,
        reference=f"{book} {chapter}:{verse}",
        token_count=3,
        disputed_passage_flag=bool(disputed_ids),
        disputed_passage_ids=disputed_ids,
        reference_gap=reference_gap,
    )


def _paired_targets(
    stem: str,
    *,
    corpus: str,
    reading: str,
    book: str,
    chapter: int,
    verse: int,
    disputed_ids: tuple[str, ...] = (),
) -> list[PassageTarget]:
    return [
        _target(
            f"{stem}-{profile}",
            corpus=corpus,
            profile=profile,
            reading=reading,
            book=book,
            chapter=chapter,
            verse=verse,
            disputed_ids=disputed_ids,
        )
        for profile in ("edition_complete", "critical_core")
    ]


def _mapping_fixture(database: Path) -> None:
    targets: list[PassageTarget] = []
    for chapter, verse in ((1, 2), (1, 3), (2, 1)):
        targets.extend(
            _paired_targets(
                f"P-GEN-{chapter}-{verse}",
                corpus="hebrew",
                reading="qere",
                book="GEN",
                chapter=chapter,
                verse=verse,
                disputed_ids=("fixture-dispute",) if (chapter, verse) == (1, 3) else (),
            )
        )
    targets.append(
        _target(
            "P-MRK-16-20-edition",
            corpus="greek",
            profile="edition_complete",
            reading="source",
            book="MRK",
            chapter=16,
            verse=20,
            disputed_ids=("longer-ending",),
        )
    )
    for verse in (1, 3):
        targets.extend(
            _paired_targets(
                f"P-EXO-1-{verse}",
                corpus="hebrew",
                reading="qere",
                book="EXO",
                chapter=1,
                verse=verse,
            )
        )

    endpoints = [
        BenchmarkEndpointRow(
            endpoint_id=_id("BE", "1"),
            relationship_id=_id("BR", "1"),
            endpoint_side="a",
            source_reference="Gen.1.2-Gen.2.1",
            source_reference_scheme="openbible-fixture",
            parsed_book="GEN",
            parsed_start_chapter=1,
            parsed_start_verse=2,
            parsed_end_chapter=2,
            parsed_end_verse=1,
            is_range=True,
            parse_status="parsed",
        ),
        BenchmarkEndpointRow(
            endpoint_id=_id("BE", "2"),
            relationship_id=_id("BR", "2"),
            endpoint_side="a",
            source_reference="Mark.16.20",
            source_reference_scheme="openbible-fixture",
            parsed_book="MRK",
            parsed_start_chapter=16,
            parsed_start_verse=20,
            parsed_end_chapter=16,
            parsed_end_verse=20,
            is_range=False,
            parse_status="parsed",
        ),
        BenchmarkEndpointRow(
            endpoint_id=_id("BE", "3"),
            relationship_id=_id("BR", "3"),
            endpoint_side="a",
            source_reference="Exod.1.1-Exod.1.3",
            source_reference_scheme="openbible-fixture",
            parsed_book="EXO",
            parsed_start_chapter=1,
            parsed_start_verse=1,
            parsed_end_chapter=1,
            parsed_end_verse=3,
            is_range=True,
            parse_status="parsed",
        ),
        BenchmarkEndpointRow(
            endpoint_id=_id("BE", "4"),
            relationship_id=_id("BR", "4"),
            endpoint_side="a",
            source_reference="Acts.28.17-Rom.1.1",
            source_reference_scheme="openbible-fixture",
            parsed_book=None,
            parsed_start_chapter=None,
            parsed_start_verse=None,
            parsed_end_chapter=None,
            parsed_end_verse=None,
            is_range=True,
            parse_status="cross_book_range",
        ),
    ]
    mappings = map_benchmark_endpoints(endpoints, PassageReferenceIndex(targets)).mappings

    passage_rows = [
        {
            "passage_id": target.passage_id,
            "start_reference": target.reference,
            "corpus": target.corpus,
            "analysis_profile": target.analysis_profile,
            "analysis_reading": target.analysis_reading,
            "granularity": "verse",
            "disputed_passage_flag": target.disputed_passage_flag,
            "disputed_passage_ids_json": json.dumps(
                target.disputed_passage_ids, separators=(",", ":")
            ),
            "reference_gap": target.reference_gap,
        }
        for target in targets
    ]
    mapping_rows = [row.model_dump(mode="python") for row in mappings]
    target_rows: list[dict[str, Any]] = []
    for mapping in mappings:
        for position, passage_id in enumerate(json.loads(mapping.target_passage_ids_json), start=1):
            target_rows.append(
                {
                    "mapping_id": mapping.mapping_id,
                    "endpoint_id": mapping.endpoint_id,
                    "position": position,
                    "target_passage_id": passage_id,
                }
            )
    with duckdb.connect(str(database)) as connection:
        _create_table(
            connection,
            "benchmark_endpoints",
            [row.model_dump(mode="python") for row in endpoints],
        )
        _create_table(connection, "benchmark_endpoint_mappings", mapping_rows)
        _create_table(connection, "benchmark_mapping_target_passages", target_rows)
        _create_table(connection, "passages", passage_rows)


def _mapping_codes(database: Path) -> set[str]:
    issues: list[BenchmarkValidationIssue] = []
    _mapping_database_validation(database, issues)
    return {issue.code for issue in issues}


def test_mapping_strict_fixture_recomputes_complete_cross_chapter_and_risk_flags(
    tmp_path: Path,
) -> None:
    database = tmp_path / "mapping.duckdb"
    _mapping_fixture(database)

    assert _mapping_codes(database) == set()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            "UPDATE benchmark_endpoint_mappings SET disputed_passage_flag=false, "
            "disputed_passage_ids_json='[]' WHERE endpoint_id='BE_" + "2" * 64 + "' "
            "AND target_analysis_profile='critical_core'",
            "mapping_disputed_flag_mismatch",
        ),
        (
            "UPDATE benchmark_endpoint_mappings SET reference_gap=false "
            "WHERE endpoint_id='BE_" + "3" * 64 + "'",
            "mapping_reference_gap_mismatch",
        ),
        (
            "UPDATE benchmark_endpoint_mappings SET mapping_status='unresolved_missing_target' "
            "WHERE endpoint_id='BE_" + "2" * 64 + "' "
            "AND target_analysis_profile='critical_core'",
            "mapping_status_recomputation_mismatch",
        ),
        (
            "UPDATE benchmark_endpoint_mappings SET mapping_status='mapped_provisional' "
            "WHERE endpoint_id='BE_" + "3" * 64 + "'",
            "mapping_status_recomputation_mismatch",
        ),
        (
            "UPDATE benchmark_endpoint_mappings SET target_corpus='hebrew', "
            "target_analysis_reading='qere' WHERE endpoint_id='BE_" + "4" * 64 + "'",
            "mapping_target_corpus_inference_mismatch",
        ),
    ],
)
def test_mapping_strict_tamper_is_detected(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    database = tmp_path / "mapping.duckdb"
    _mapping_fixture(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(mutation)

    assert expected_code in _mapping_codes(database)


def _split_negative_fixture(
    database: Path,
) -> tuple[BenchmarkConfig, dict[str, object], dict[str, tuple[str, str]]]:
    loaded = load_config(Path("config/benchmark.yaml"))
    assert isinstance(loaded, BenchmarkConfig)
    config = loaded
    config_hash = benchmark_config_fingerprint(config)
    benchmark_version = "known-links-fixture-v1"
    metadata: dict[str, object] = {
        "benchmark_version": benchmark_version,
        "configuration_hash": config_hash,
    }
    relationship_id = _id("BR", "a")
    endpoint_a = _id("BE", "a")
    endpoint_b = _id("BE", "b")
    unordered_pair = _id("BUP", "a")
    exact_group = _exact_pair_group_id(unordered_pair)
    relationships = [{"relationship_id": relationship_id, "tier": 3}]
    endpoints = [
        {
            "endpoint_id": endpoint_a,
            "relationship_id": relationship_id,
            "endpoint_side": "a",
            "source_reference": "Gen.1.1",
            "parsed_book": "GEN",
        },
        {
            "endpoint_id": endpoint_b,
            "relationship_id": relationship_id,
            "endpoint_side": "b",
            "source_reference": "Matt.1.1",
            "parsed_book": "MAT",
        },
    ]
    mappings = [
        {
            "mapping_id": _id("BM", "a"),
            "endpoint_id": endpoint_a,
            "target_analysis_profile": "edition_complete",
            "mapping_status": "mapped_provisional",
        },
        {
            "mapping_id": _id("BM", "b"),
            "endpoint_id": endpoint_b,
            "target_analysis_profile": "edition_complete",
            "mapping_status": "mapped_provisional",
        },
    ]

    passage_specs = [
        ("P-GEN-POS", "hebrew", "GEN", 5),
        ("P-MAT-POS", "greek", "MAT", 5),
        ("P-GEN-LEN", "hebrew", "GEN", 5),
        ("P-MAT-LEN", "greek", "MAT", 7),
        ("P-GEN-SB1", "hebrew", "GEN", 4),
        ("P-GEN-SB2", "hebrew", "GEN", 6),
        ("P-GEN-BP", "hebrew", "GEN", 5),
        ("P-MAT-BP", "greek", "MAT", 5),
        ("P-GEN-GENRE", "hebrew", "GEN", 5),
        ("P-NUM-GENRE", "hebrew", "NUM", 5),
        ("P-GEN-NEAR1", "hebrew", "GEN", 5),
        ("P-GEN-NEAR2", "hebrew", "GEN", 5),
    ]
    positions: dict[str, int] = {"hebrew": 1, "greek": 1}
    passage_rows: list[dict[str, Any]] = []
    passage_facts: dict[str, tuple[str, str, int]] = {}
    for passage_id, corpus, book, token_count in passage_specs:
        start = positions[corpus]
        end = start + token_count - 1
        positions[corpus] = end + 2
        passage_rows.append(
            {
                "passage_id": passage_id,
                "corpus": corpus,
                "analysis_profile": "edition_complete",
                "analysis_reading": "qere" if corpus == "hebrew" else "source",
                "granularity": "verse",
                "book": book,
                "token_count": token_count,
                "start_stream_position_in_corpus": start,
                "end_stream_position_in_corpus": end,
            }
        )
        passage_facts[passage_id] = (corpus, book, token_count)

    target_rows = [
        {
            "mapping_id": _id("BM", "a"),
            "endpoint_id": endpoint_a,
            "position": 1,
            "target_passage_id": "P-GEN-POS",
        },
        {
            "mapping_id": _id("BM", "b"),
            "endpoint_id": endpoint_b,
            "position": 1,
            "target_passage_id": "P-MAT-POS",
        },
    ]
    leakage = [
        {
            "leakage_group_id": exact_group,
            "relationship_id": relationship_id,
            "group_type": "exact_unordered_pair",
        }
    ]

    endpoint_books = ("GEN", "MAT")
    endpoint_references = ("Gen.1.1", "Matt.1.1")
    split_rows: list[dict[str, Any]] = []
    for item in config.splits:
        reason: str | None = None
        if item.strategy == "held_out_book":
            values = [_hash_partition(item.seed, book, item.proportions) for book in endpoint_books]
            partition = (
                "test"
                if "test" in values
                else ("development" if "development" in values else "train")
            )
        elif item.strategy == "held_out_book_pair":
            partition = _hash_partition(item.seed, "GEN|MAT", item.proportions)
        elif item.strategy == "held_out_source_passage":
            values = {
                _hash_partition(item.seed, value, item.proportions) for value in endpoint_references
            }
            if len(values) == 1:
                partition = values.pop()
            else:
                partition = "excluded"
                reason = "endpoint_partition_conflict"
        elif item.strategy == "held_out_genre":
            values = [
                _hash_partition(item.seed, config.book_genres[book], item.proportions)
                for book in endpoint_books
            ]
            partition = (
                "test"
                if "test" in values
                else ("development" if "development" in values else "train")
            )
        else:
            partition = "excluded"
            reason = "relationship_family_unavailable"
        split_rows.append(
            {
                "split_assignment_id": _split_assignment_id(
                    benchmark_version=benchmark_version,
                    config_hash=config_hash,
                    relationship_id=relationship_id,
                    strategy=item.name,
                ),
                "benchmark_version": benchmark_version,
                "relationship_id": relationship_id,
                "split_strategy": item.name,
                "partition": partition,
                "leakage_group_id": exact_group,
                "seed": item.seed,
                "eligibility_status": "excluded" if reason else "eligible",
                "exclusion_reason": reason,
                "config_hash": config_hash,
            }
        )

    pairs = {
        "length_matched_random_unlinked": ("P-GEN-LEN", "P-MAT-LEN"),
        "same_book_unlinked": ("P-GEN-SB1", "P-GEN-SB2"),
        "same_book_pair_unlinked": ("P-GEN-BP", "P-MAT-BP"),
        "same_broad_genre_unlinked": ("P-GEN-GENRE", "P-NUM-GENRE"),
        "nearby_context_unlinked": ("P-GEN-NEAR1", "P-GEN-NEAR2"),
    }
    held_out = next(item for item in config.splits if item.strategy == "held_out_book")
    negative_rows: list[dict[str, Any]] = []
    for item in config.presumed_negatives:
        first, second = sorted(pairs[item.strategy])
        corpus_a, book_a, length_a = passage_facts[first]
        corpus_b, book_b, length_b = passage_facts[second]
        genre_a = config.book_genres[book_a]
        genre_b = config.book_genres[book_b]
        partition = _hash_partition(held_out.seed, book_a, held_out.proportions)
        negative_rows.append(
            {
                "contrastive_id": _expected_contrastive_id(
                    benchmark_version=benchmark_version,
                    generation_config_hash=config_hash,
                    negative_strategy=item.strategy,
                    passage_a_id=first,
                    passage_b_id=second,
                    seed=item.seed,
                    split_strategy="held_out_book",
                ),
                "benchmark_version": benchmark_version,
                "passage_a_id": first,
                "passage_b_id": second,
                "corpus_pair": "|".join(sorted((corpus_a, corpus_b))),
                "negative_strategy": item.strategy,
                "presumed_negative": True,
                "positive_graph_checked": True,
                "reverse_pair_checked": True,
                "passage_overlap_checked": True,
                "leakage_checked": True,
                "length_difference": abs(length_a - length_b),
                "book_pair": "|".join(sorted((book_a, book_b))),
                "genre_pair": "|".join(sorted((genre_a, genre_b))),
                "split_strategy": "held_out_book",
                "partition": partition,
                "seed": item.seed,
                "generation_config_hash": config_hash,
                "notes": "Presumed negative only; fixture relationship is not proven absent.",
            }
        )

    with duckdb.connect(str(database)) as connection:
        _create_table(connection, "benchmark_relationships", relationships)
        _create_table(connection, "benchmark_endpoints", endpoints)
        _create_table(connection, "benchmark_endpoint_mappings", mappings)
        _create_table(connection, "benchmark_mapping_target_passages", target_rows)
        _create_table(connection, "benchmark_leakage_groups", leakage)
        _create_table(connection, "benchmark_split_assignments", split_rows)
        _create_table(connection, "benchmark_presumed_negatives", negative_rows)
        _create_table(connection, "passages", passage_rows)
    return config, metadata, pairs


def _split_codes(database: Path, config: BenchmarkConfig, metadata: dict[str, object]) -> set[str]:
    issues: list[BenchmarkValidationIssue] = []
    with duckdb.connect(str(database), read_only=True) as connection:
        _split_database_validation(connection, config=config, metadata=metadata, issues=issues)
    return {issue.code for issue in issues}


def _negative_codes(
    database: Path, config: BenchmarkConfig, metadata: dict[str, object]
) -> set[str]:
    issues: list[BenchmarkValidationIssue] = []
    with duckdb.connect(str(database), read_only=True) as connection:
        _negative_database_validation(connection, config=config, metadata=metadata, issues=issues)
    return {issue.code for issue in issues}


def test_split_and_negative_strict_fixtures_pass(tmp_path: Path) -> None:
    database = tmp_path / "strict.duckdb"
    config, metadata, _ = _split_negative_fixture(database)

    assert _split_codes(database, config, metadata) == set()
    assert _negative_codes(database, config, metadata) == set()


@pytest.mark.parametrize(
    "strategy",
    ["held_out_book", "held_out_book_pair", "held_out_source_passage", "held_out_genre"],
)
def test_split_partition_tamper_fails_actual_held_out_rule(tmp_path: Path, strategy: str) -> None:
    database = tmp_path / "strict.duckdb"
    config, metadata, _ = _split_negative_fixture(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE benchmark_split_assignments SET partition="
            "CASE WHEN partition='train' THEN 'test' ELSE 'train' END "
            "WHERE split_strategy=?",
            [strategy],
        )

    assert "split_partition_behavior_mismatch" in _split_codes(database, config, metadata)


def test_split_foreign_key_and_completeness_tamper_fail(tmp_path: Path) -> None:
    database = tmp_path / "strict.duckdb"
    config, metadata, _ = _split_negative_fixture(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE benchmark_split_assignments SET relationship_id='BR_missing' "
            "WHERE split_strategy='held_out_book'"
        )

    codes = _split_codes(database, config, metadata)
    assert "split_foreign_key_failure" in codes
    assert "split_completeness_mismatch" in codes


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            "UPDATE passages SET start_stream_position_in_corpus=100, "
            "end_stream_position_in_corpus=105 "
            "WHERE passage_id IN ('P-GEN-SB1','P-GEN-SB2')",
            "presumed_negative_passage_overlap",
        ),
        (
            "UPDATE benchmark_presumed_negatives SET partition='test' "
            "WHERE negative_strategy='same_book_unlinked'",
            "presumed_negative_partition_mismatch",
        ),
        (
            "UPDATE benchmark_presumed_negatives SET seed=999 "
            "WHERE negative_strategy='same_book_unlinked'",
            "presumed_negative_provenance_mismatch",
        ),
        (
            "DELETE FROM benchmark_presumed_negatives WHERE negative_strategy='same_book_unlinked'",
            "presumed_negative_ratio_mismatch",
        ),
        (
            "UPDATE benchmark_presumed_negatives SET passage_a_id='P-GEN-POS', "
            "passage_b_id='P-MAT-POS' "
            "WHERE negative_strategy='same_book_pair_unlinked'",
            "presumed_negative_positive_collision",
        ),
    ],
)
def test_presumed_negative_tamper_is_detected(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    database = tmp_path / "strict.duckdb"
    config, metadata, _ = _split_negative_fixture(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(mutation)

    assert expected_code in _negative_codes(database, config, metadata)
