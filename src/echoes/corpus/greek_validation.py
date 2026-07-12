"""Automated Greek corpus validation and unified cross-corpus checks."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from echoes.corpus.greek_books import GREEK_BOOKS
from echoes.corpus.greek_models import GREEK_TOKEN_COLUMNS
from echoes.corpus.greek_storage import (
    GREEK_PARQUET_FILES,
    GREEK_SORT_COLUMNS,
    GREEK_TABLE_HASH_FILE,
)
from echoes.corpus.models import IngestionIssue, ValidationSeverity
from echoes.corpus.storage import logical_frame_hash
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.corpus.validation import CorpusValidationError, CorpusValidationReport
from echoes.manifest import sha256_file
from echoes.normalize.greek import is_greek_elided, normalize_greek_token
from echoes.settings import GreekNormalization


def _issue(
    issues: list[IngestionIssue],
    severity: ValidationSeverity,
    code: str,
    message: str,
) -> None:
    issues.append(IngestionIssue(severity=severity, code=code, message=message))


def _load_frames(output_dir: Path) -> dict[str, pl.DataFrame]:
    frames: dict[str, pl.DataFrame] = {}
    for name, filename in GREEK_PARQUET_FILES.items():
        path = output_dir / filename
        if not path.is_file():
            raise CorpusValidationError(f"required processed table does not exist: {path}")
        try:
            frames[name] = pl.read_parquet(path)
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise CorpusValidationError(f"could not read processed table {path}: {exc}") from exc
    return frames


def _check_hashes(
    output_dir: Path,
    frames: dict[str, pl.DataFrame],
    issues: list[IngestionIssue],
) -> tuple[dict[str, str], dict[str, str]]:
    path = output_dir / GREEK_TABLE_HASH_FILE
    if not path.is_file():
        raise CorpusValidationError(f"processed table-hash document does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusValidationError(f"invalid processed table-hash document {path}: {exc}") from exc
    recorded_files = document.get("parquet_sha256")
    recorded_logical = document.get("logical_table_sha256")
    if not isinstance(recorded_files, dict) or not isinstance(recorded_logical, dict):
        raise CorpusValidationError("table-hash document is missing hash mappings")
    file_hashes = {
        filename: sha256_file(output_dir / filename) for filename in GREEK_PARQUET_FILES.values()
    }
    for filename, digest in file_hashes.items():
        if recorded_files.get(filename) != digest:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "parquet-hash-mismatch",
                f"{filename} differs from its recorded SHA-256",
            )
    logical_hashes = {
        name: logical_frame_hash(frame, sort_by=GREEK_SORT_COLUMNS[name])
        for name, frame in frames.items()
    }
    for name, digest in logical_hashes.items():
        if recorded_logical.get(name) != digest:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "logical-hash-mismatch",
                f"{name} differs from its recorded logical table hash",
            )
    return file_hashes, logical_hashes


def _validate_identity(
    tokens: pl.DataFrame,
    source_records: pl.DataFrame,
    metadata: pl.DataFrame,
    issues: list[IngestionIssue],
) -> None:
    if tokens["token_id"].n_unique() != tokens.height:
        _issue(issues, ValidationSeverity.ERROR, "duplicate-token-id", "token IDs are not unique")
    if tokens["source_record_id"].n_unique() != tokens.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "duplicate-source-mapping",
            "canonical tokens do not map one-to-one to source record IDs",
        )
    if source_records["source_record_id"].n_unique() != source_records.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "duplicate-source-record",
            "source record table contains duplicate identifiers",
        )
    token_source_ids = set(tokens["source_record_id"].to_list())
    record_source_ids = set(source_records["source_record_id"].to_list())
    missing = token_source_ids - record_source_ids
    dropped = record_source_ids - token_source_ids
    if missing:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "missing-source-provenance",
            f"{len(missing)} tokens do not trace to a source record",
        )
    if dropped:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "dropped-source-records",
            f"{len(dropped)} source records have no canonical token",
        )
    if metadata.height != 1:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "metadata-cardinality",
            f"expected one corpus metadata row, found {metadata.height}",
        )
        return
    source_id = str(metadata.item(0, "source_id"))
    source_version = str(metadata.item(0, "source_version"))
    if tokens["source_id"].n_unique() != 1 or tokens.item(0, "source_id") != source_id:
        _issue(issues, ValidationSeverity.ERROR, "source-id-mismatch", "source IDs differ")
    if (
        tokens["source_version"].n_unique() != 1
        or tokens.item(0, "source_version") != source_version
    ):
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "source-version-mismatch",
            "source versions differ across corpus records",
        )
    identity_mismatches = 0
    reference_mismatches = 0
    for row in tokens.select(
        "token_id",
        "book",
        "chapter",
        "verse",
        "source_word_id",
        "source_edition_reference",
    ).iter_rows(named=True):
        word_id = str(row["source_word_id"])
        expected_id = generate_source_edition_token_id(
            book_identifier=str(row["book"]),
            chapter=int(row["chapter"]),
            verse=int(row["verse"]),
            source_token_position=int(word_id.rsplit("!", maxsplit=1)[-1]),
            corpus_prefix="GNT",
        )
        if row["token_id"] != expected_id:
            identity_mismatches += 1
        expected_reference = f"{row['book']} {row['chapter']}:{row['verse']}"
        if row["source_edition_reference"] != expected_reference:
            reference_mismatches += 1
    if identity_mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "non-source-edition-token-id",
            f"{identity_mismatches} token IDs differ from their source-edition identities",
        )
    if reference_mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "source-edition-reference-mismatch",
            f"{reference_mismatches} preserved source-edition verse references differ",
        )


def _validate_structure(
    tokens: pl.DataFrame,
    issues: list[IngestionIssue],
    *,
    expected_missing_verses: set[str],
    expected_out_of_sequence_verses: set[str],
) -> None:
    if set(tokens.columns) != set(GREEK_TOKEN_COLUMNS):
        missing = sorted(set(GREEK_TOKEN_COLUMNS) - set(tokens.columns))
        unexpected = sorted(set(tokens.columns) - set(GREEK_TOKEN_COLUMNS))
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "canonical-schema-columns",
            f"token columns differ from schema; missing={missing}, unexpected={unexpected}",
        )
    expected_books = {book.code: book for book in GREEK_BOOKS}
    for row in tokens.select("book", "book_order", "chapter").unique().iter_rows(named=True):
        book = expected_books.get(str(row["book"]))
        if book is None:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "invalid-book",
                f"unknown book code {row['book']}",
            )
            continue
        if int(row["book_order"]) != book.order:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "invalid-book-order",
                f"{book.code} has book order {row['book_order']}, expected {book.order}",
            )
        chapter = int(row["chapter"])
        if chapter < 1 or chapter > book.chapter_count:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "invalid-chapter",
                f"{book.code} chapter {chapter} is outside 1-{book.chapter_count}",
            )
    if set(tokens["language"].unique().to_list()) != {"greek"}:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "invalid-language",
            "tokens contain an unsupported language value",
        )
    if tokens["position_in_corpus"].n_unique() != tokens.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "duplicate-corpus-position",
            "corpus positions are not unique",
        )
    if tokens.height and (
        tokens["position_in_corpus"].min() != 1
        or tokens["position_in_corpus"].max() != tokens.height
    ):
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "noncontinuous-corpus-position",
            "corpus positions are not continuous from 1 through token count",
        )
    verse_groups = tokens.group_by("book", "chapter", "verse").agg(
        pl.len().alias("count"),
        pl.col("position_in_verse").min().alias("minimum"),
        pl.col("position_in_verse").max().alias("maximum"),
        pl.col("position_in_verse").n_unique().alias("unique_count"),
    )
    invalid_verse_positions = verse_groups.filter(
        (pl.col("minimum") != 1)
        | (pl.col("maximum") != pl.col("count"))
        | (pl.col("unique_count") != pl.col("count"))
    )
    if invalid_verse_positions.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "noncontinuous-verse-position",
            f"{invalid_verse_positions.height} verses have noncontinuous token positions",
        )

    # Edition-level verse coverage: every verse from 1 through the last
    # sequential verse must exist unless the pinned edition omits it, and
    # every declared out-of-sequence verse (for example the shorter ending of
    # Mark at MRK 16:99) must be present exactly as declared.
    observed: dict[tuple[str, int], set[int]] = {}
    for book_code, chapter, verse in tokens.select("book", "chapter", "verse").unique().iter_rows():
        observed.setdefault((str(book_code), int(chapter)), set()).add(int(verse))
    special_by_chapter: dict[tuple[str, int], set[int]] = {}
    for reference in expected_out_of_sequence_verses:
        book_code, rest = reference.split(" ", maxsplit=1)
        chapter_text, verse_text = rest.split(":")
        special_by_chapter.setdefault((book_code, int(chapter_text)), set()).add(int(verse_text))
    unexpected_gaps: list[str] = []
    missing_expected_gaps: list[str] = sorted(
        reference
        for reference in expected_missing_verses
        if int(reference.split(":")[1])
        in observed.get(
            (reference.split(" ")[0], int(reference.split(" ")[1].split(":")[0])), set()
        )
    )
    missing_specials: list[str] = []
    for (book_code, chapter), verses in sorted(observed.items()):
        specials = special_by_chapter.get((book_code, chapter), set())
        for special in sorted(specials):
            if special not in verses:
                missing_specials.append(f"{book_code} {chapter}:{special}")
        sequential = verses - specials
        top = max(sequential) if sequential else 0
        for verse in range(1, top + 1):
            if verse in verses:
                continue
            reference = f"{book_code} {chapter}:{verse}"
            if reference not in expected_missing_verses:
                unexpected_gaps.append(reference)
    if unexpected_gaps:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "verse-coverage-gap",
            f"unexpected missing verses: {unexpected_gaps[:10]}",
        )
    if missing_expected_gaps:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unexpected-verse-present",
            f"verses declared edition-omitted are present: {missing_expected_gaps[:10]}",
        )
    if missing_specials:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "missing-out-of-sequence-verse",
            f"declared out-of-sequence verses are absent: {missing_specials[:10]}",
        )


def _validate_normalization(
    tokens: pl.DataFrame,
    normalization: GreekNormalization,
    issues: list[IngestionIssue],
) -> None:
    mismatches = 0
    reconstruction_failures = 0
    elision_mismatches = 0
    for row in tokens.select(
        "surface_form",
        "normalized_form",
        "folded_form",
        "leading_punctuation",
        "trailing_punctuation",
        "is_elided",
        "is_punctuation",
    ).iter_rows(named=True):
        surface = str(row["surface_form"])
        expected = normalize_greek_token(surface, normalization)
        if (
            expected.normalized_form != row["normalized_form"]
            or expected.folded_form != row["folded_form"]
            or expected.leading_punctuation != row["leading_punctuation"]
            or expected.trailing_punctuation != row["trailing_punctuation"]
        ):
            mismatches += 1
        if not bool(row["is_punctuation"]):
            reconstructed = (
                str(row["leading_punctuation"])
                + str(row["normalized_form"])
                + str(row["trailing_punctuation"])
            )
            if reconstructed != surface:
                reconstruction_failures += 1
        if is_greek_elided(surface) != bool(row["is_elided"]):
            elision_mismatches += 1
    if mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "nondeterministic-normalization",
            f"{mismatches} tokens differ from configured deterministic normalization",
        )
    if reconstruction_failures:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "punctuation-separation-loss",
            f"{reconstruction_failures} tokens fail lossless punctuation reconstruction",
        )
    if elision_mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "elision-policy-mismatch",
            f"{elision_mismatches} elision flags differ from configuration",
        )


def _completeness(tokens: pl.DataFrame, issues: list[IngestionIssue]) -> dict[str, float | int]:
    total = tokens.height
    fields = {
        "lemma": "lemma",
        "morphology": "morphology_json",
        "syntax": "clause_id",
        "semantic_domain": "semantic_domain",
        "word_sense": "word_sense",
        "gloss": "english_gloss",
    }
    completeness: dict[str, float | int] = {"total_tokens": total}
    for label, column in fields.items():
        missing = tokens.filter(pl.col(column).is_null() | (pl.col(column) == "")).height
        completeness[f"missing_{label}"] = missing
        completeness[f"{label}_coverage_percent"] = (
            round(((total - missing) / total) * 100, 6) if total else 0.0
        )
        _issue(
            issues,
            ValidationSeverity.INFORMATIONAL,
            f"{label}-completeness",
            f"{label}: {total - missing}/{total} tokens populated",
        )
    return completeness


def _validate_duckdb(
    database_path: Path,
    output_dir: Path,
    frames: dict[str, pl.DataFrame],
    issues: list[IngestionIssue],
) -> None:
    if not database_path.is_file():
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "missing-duckdb",
            f"DuckDB database does not exist: {database_path}",
        )
        return
    table_map = {
        "tokens": "greek_tokens",
        "books": "greek_books",
        "source_records": "greek_source_records",
        "issues": "greek_ingestion_issues",
        "metadata": "greek_corpus_metadata",
    }
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            existing = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
            missing_tables = sorted(set(table_map.values()) - existing)
            if missing_tables:
                _issue(
                    issues,
                    ValidationSeverity.ERROR,
                    "missing-duckdb-tables",
                    f"DuckDB is missing tables: {missing_tables}",
                )
                return
            for name, table in table_map.items():
                columns = frames[name].columns
                quoted_columns = ", ".join(
                    f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
                )
                parquet_path = str((output_dir / GREEK_PARQUET_FILES[name]).resolve()).replace(
                    "'", "''"
                )
                database_fingerprint = connection.execute(
                    f"SELECT count(*), bit_xor(row_hash), sum(row_hash) FROM "
                    f"(SELECT hash({quoted_columns}) AS row_hash FROM {table})"
                ).fetchone()
                parquet_fingerprint = connection.execute(
                    f"SELECT count(*), bit_xor(row_hash), sum(row_hash) FROM "
                    f"(SELECT hash({quoted_columns}) AS row_hash "
                    f"FROM read_parquet('{parquet_path}'))"
                ).fetchone()
                if database_fingerprint is None or parquet_fingerprint is None:
                    _issue(
                        issues,
                        ValidationSeverity.ERROR,
                        "duckdb-fingerprint-failure",
                        f"could not fingerprint {table}",
                    )
                    continue
                if int(database_fingerprint[0]) != frames[name].height:
                    _issue(
                        issues,
                        ValidationSeverity.ERROR,
                        "duckdb-row-count-mismatch",
                        f"{table} has {database_fingerprint[0]} rows; "
                        f"expected {frames[name].height}",
                    )
                if database_fingerprint != parquet_fingerprint:
                    _issue(
                        issues,
                        ValidationSeverity.ERROR,
                        "duckdb-logical-hash-mismatch",
                        f"{table} differs logically from its Parquet source",
                    )
            _validate_unified_view(connection, frames["tokens"].height, issues)
    except duckdb.Error as exc:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "duckdb-query-failure",
            f"could not validate DuckDB: {exc}",
        )


def _validate_unified_view(
    connection: duckdb.DuckDBPyConnection,
    greek_token_count: int,
    issues: list[IngestionIssue],
) -> None:
    existing = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    if "hebrew_tokens" not in existing:
        _issue(
            issues,
            ValidationSeverity.INFORMATIONAL,
            "unified-view-single-corpus",
            "hebrew_tokens is absent; unified view checks were skipped",
        )
        return
    if "unified_tokens" not in existing:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "missing-unified-view",
            "both corpora are loaded but the unified_tokens view is absent",
        )
        return
    row = connection.execute(
        "SELECT count(*), count(DISTINCT token_id), "
        "count(*) FILTER (WHERE corpus = 'hebrew'), "
        "count(*) FILTER (WHERE corpus = 'greek'), "
        "count(DISTINCT source_id) "
        "FROM unified_tokens"
    ).fetchone()
    if row is None:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unified-view-query-failure",
            "could not query the unified token view",
        )
        return
    total, distinct_ids, hebrew_count, greek_count, distinct_sources = (int(v) for v in row)
    hebrew_total_row = connection.execute("SELECT count(*) FROM hebrew_tokens").fetchone()
    hebrew_total = int(hebrew_total_row[0]) if hebrew_total_row else 0
    if total != hebrew_total + greek_token_count:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unified-count-mismatch",
            f"unified view has {total} rows; expected {hebrew_total + greek_token_count}",
        )
    if distinct_ids != total:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unified-token-id-collision",
            "token IDs collide across corpora in the unified view",
        )
    if hebrew_count != hebrew_total or greek_count != greek_token_count:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unified-corpus-attribution",
            "unified view corpus attribution does not match the corpus tables",
        )
    if distinct_sources < 2:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "unified-provenance-collapse",
            "unified view does not retain distinct source provenance values",
        )


def validate_greek_corpus(
    output_dir: Path,
    *,
    database_path: Path,
    normalization: GreekNormalization,
    expected_books: int,
    expected_chapters: int,
    expected_tokens: int | None,
    expected_missing_verses: list[str] | None = None,
    expected_out_of_sequence_verses: list[str] | None = None,
) -> CorpusValidationReport:
    """Run the complete Greek identity, structure, normalization, and storage gate."""
    frames = _load_frames(output_dir)
    tokens = frames["tokens"]
    source_records = frames["source_records"]
    metadata = frames["metadata"]
    issues = [IngestionIssue.model_validate(row) for row in frames["issues"].to_dicts()]
    file_hashes, logical_hashes = _check_hashes(output_dir, frames, issues)
    _validate_identity(tokens, source_records, metadata, issues)
    _validate_structure(
        tokens,
        issues,
        expected_missing_verses=set(expected_missing_verses or []),
        expected_out_of_sequence_verses=set(expected_out_of_sequence_verses or []),
    )
    _validate_normalization(tokens, normalization, issues)
    completeness = _completeness(tokens, issues)

    book_count = tokens["book"].n_unique()
    chapter_count = tokens.select("book", "chapter").unique().height
    verse_count = tokens.select("book", "chapter", "verse").unique().height
    if book_count != expected_books:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "book-coverage",
            f"found {book_count} books; expected {expected_books}",
        )
    if chapter_count != expected_chapters:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "chapter-coverage",
            f"found {chapter_count} chapters; expected {expected_chapters}",
        )
    if expected_tokens is not None and tokens.height != expected_tokens:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "token-count",
            f"found {tokens.height} tokens; expected {expected_tokens}",
        )
    _validate_duckdb(database_path, output_dir, frames, issues)

    metadata_row = metadata.row(0, named=True)
    errors = sum(issue.severity is ValidationSeverity.ERROR for issue in issues)
    coverage: dict[str, object] = {
        "books": book_count,
        "chapters": chapter_count,
        "verses": verse_count,
        "tokens_by_book": dict(
            tokens.group_by("book", "book_order")
            .len(name="count")
            .sort("book_order")
            .select("book", "count")
            .iter_rows()
        ),
        "elided_tokens": tokens.filter(pl.col("is_elided")).height,
        "punctuation_bearing_tokens": tokens.filter(
            (pl.col("leading_punctuation") != "") | (pl.col("trailing_punctuation") != "")
        ).height,
    }
    return CorpusValidationReport(
        corpus="greek",
        passed=errors == 0,
        ingestion_run_id=str(metadata_row["ingestion_run_id"]),
        source_id=str(metadata_row["source_id"]),
        source_version=str(metadata_row["source_version"]),
        schema_version=int(metadata_row["schema_version"]),
        normalization_config_hash=str(metadata_row["normalization_config_hash"]),
        total_tokens=tokens.height,
        total_source_records=source_records.height,
        book_count=book_count,
        chapter_count=chapter_count,
        verse_count=verse_count,
        completeness=completeness,
        coverage=coverage,
        parquet_sha256=file_hashes,
        logical_table_sha256=logical_hashes,
        issues=issues,
    )
