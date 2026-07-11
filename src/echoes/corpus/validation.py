"""Automated Hebrew corpus validation and deterministic-output comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Self

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.corpus.analysis import AnalysisReading, derive_analysis_stream
from echoes.corpus.books import BOOKS
from echoes.corpus.models import (
    CANONICAL_TOKEN_COLUMNS,
    IngestionIssue,
    ValidationSeverity,
)
from echoes.corpus.storage import (
    PARQUET_FILES,
    TABLE_HASH_FILE,
    ProcessedCorpus,
    logical_frame_hash,
)
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.manifest import sha256_file
from echoes.normalize.hebrew import is_punctuation, normalize_hebrew_token
from echoes.settings import HebrewNormalization


class CorpusValidationError(RuntimeError):
    """Raised when validation cannot inspect the requested corpus artifacts."""


class CorpusValidationReport(BaseModel):
    """Structured corpus gate result with errors, warnings, and measured absence."""

    model_config = ConfigDict(extra="forbid")

    corpus: str = "hebrew"
    passed: bool
    ingestion_run_id: str
    source_id: str
    source_version: str
    schema_version: int
    normalization_config_hash: str
    total_tokens: int
    total_source_records: int
    book_count: int
    chapter_count: int
    verse_count: int
    completeness: dict[str, float | int]
    coverage: dict[str, object]
    parquet_sha256: dict[str, str]
    logical_table_sha256: dict[str, str]
    issues: list[IngestionIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def pass_state_matches_issues(self) -> Self:
        has_errors = any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)
        if self.passed == has_errors:
            raise ValueError("passed must be true exactly when no validation errors exist")
        return self

    @property
    def error_count(self) -> int:
        return sum(issue.severity is ValidationSeverity.ERROR for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity is ValidationSeverity.WARNING for issue in self.issues)


def _issue(
    issues: list[IngestionIssue],
    severity: ValidationSeverity,
    code: str,
    message: str,
) -> None:
    issues.append(IngestionIssue(severity=severity, code=code, message=message))


def _load_frames(output_dir: Path) -> dict[str, pl.DataFrame]:
    frames: dict[str, pl.DataFrame] = {}
    for name, filename in PARQUET_FILES.items():
        path = output_dir / filename
        if not path.is_file():
            raise CorpusValidationError(f"required processed table does not exist: {path}")
        try:
            frames[name] = pl.read_parquet(path)
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise CorpusValidationError(f"could not read processed table {path}: {exc}") from exc
    return frames


def _load_hash_document(output_dir: Path) -> dict[str, object]:
    path = output_dir / TABLE_HASH_FILE
    if not path.is_file():
        raise CorpusValidationError(f"processed table-hash document does not exist: {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusValidationError(f"invalid processed table-hash document {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise CorpusValidationError(f"table-hash document root must be an object: {path}")
    return loaded


def _check_hashes(
    output_dir: Path,
    frames: dict[str, pl.DataFrame],
    issues: list[IngestionIssue],
) -> tuple[dict[str, str], dict[str, str]]:
    document = _load_hash_document(output_dir)
    recorded_files = document.get("parquet_sha256")
    recorded_logical = document.get("logical_table_sha256")
    if not isinstance(recorded_files, dict) or not isinstance(recorded_logical, dict):
        raise CorpusValidationError("table-hash document is missing hash mappings")
    file_hashes = {
        filename: sha256_file(output_dir / filename) for filename in PARQUET_FILES.values()
    }
    for filename, digest in file_hashes.items():
        if recorded_files.get(filename) != digest:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "parquet-hash-mismatch",
                f"{filename} differs from its recorded SHA-256",
            )
    sort_columns = {
        "tokens": ["position_in_corpus"],
        "analysis_tokens": ["analysis_position_in_corpus"],
        "books": ["book_order"],
        "source_records": ["source_record_id"],
        "issues": ["severity", "code", "source_record_id"],
        "metadata": ["ingestion_run_id"],
    }
    logical_hashes = {
        name: logical_frame_hash(frame, sort_by=sort_columns[name])
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
    word_counts = dict(
        tokens.group_by("source_word_id").len().select("source_word_id", "len").iter_rows()
    )
    identity_mismatches = 0
    reference_mismatches = 0
    for row in tokens.select(
        "token_id",
        "book",
        "chapter",
        "verse",
        "position_in_word",
        "source_word_id",
        "source_record_id",
        "source_edition_reference",
        "variant_type",
    ).iter_rows(named=True):
        word_id = str(row["source_word_id"])
        expected_id = generate_source_edition_token_id(
            book_identifier=str(row["book"]),
            chapter=int(row["chapter"]),
            verse=int(row["verse"]),
            source_token_position=int(word_id.rsplit("!", maxsplit=1)[-1]),
            source_subtoken_position=(
                int(row["position_in_word"]) if int(word_counts[word_id]) > 1 else None
            ),
            source_record_id=str(row["source_record_id"]),
            disambiguate_with_source_record=row["variant_type"] is not None,
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
    require_full_coverage: bool,
) -> None:
    if set(tokens.columns) != set(CANONICAL_TOKEN_COLUMNS):
        missing = sorted(set(CANONICAL_TOKEN_COLUMNS) - set(tokens.columns))
        unexpected = sorted(set(tokens.columns) - set(CANONICAL_TOKEN_COLUMNS))
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "canonical-schema-columns",
            f"token columns differ from schema; missing={missing}, unexpected={unexpected}",
        )
    expected_books = {book.code: book for book in BOOKS}
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
    if set(tokens["language"].unique().to_list()) - {"hebrew", "aramaic"}:
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
    if require_full_coverage:
        chapter_verses = tokens.group_by("book", "chapter").agg(
            pl.col("verse").min().alias("minimum"),
            pl.col("verse").max().alias("maximum"),
            pl.col("verse").n_unique().alias("unique_count"),
        )
        gaps = chapter_verses.filter(
            (pl.col("minimum") != 1) | (pl.col("maximum") != pl.col("unique_count"))
        )
        if gaps.height:
            _issue(
                issues,
                ValidationSeverity.ERROR,
                "verse-coverage-gap",
                f"{gaps.height} chapters have missing or unexpected verse references",
            )


def _validate_normalization(
    tokens: pl.DataFrame,
    normalization: HebrewNormalization,
    issues: list[IngestionIssue],
) -> None:
    empty_surface = tokens.filter(
        ~pl.col("is_zero_width")
        & (pl.col("surface_form").is_null() | (pl.col("surface_form") == ""))
    )
    empty_normalized = tokens.filter(
        ~pl.col("is_zero_width")
        & (pl.col("normalized_form").is_null() | (pl.col("normalized_form") == ""))
    )
    if empty_surface.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "empty-surface-form",
            f"{empty_surface.height} tokens lost their original surface form",
        )
    if empty_normalized.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "empty-normalized-form",
            f"{empty_normalized.height} tokens have empty normalized forms",
        )
    mismatches = 0
    punctuation_mismatches = 0
    for surface, normalized, unpointed, punctuation, zero_width in tokens.select(
        "surface_form",
        "normalized_form",
        "unpointed_form",
        "is_punctuation",
        "is_zero_width",
    ).iter_rows():
        if zero_width:
            if surface or normalized or unpointed:
                mismatches += 1
            continue
        expected = normalize_hebrew_token(str(surface), normalization)
        if expected.normalized_form != normalized or expected.unpointed_form != unpointed:
            mismatches += 1
        if is_punctuation(str(surface)) != punctuation:
            punctuation_mismatches += 1
    if mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "nondeterministic-normalization",
            f"{mismatches} tokens differ from configured deterministic normalization",
        )
    if punctuation_mismatches:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "punctuation-policy-mismatch",
            f"{punctuation_mismatches} punctuation flags differ from configuration",
        )
    invalid_variant_rows = tokens.filter(
        (
            pl.col("is_variant")
            & (
                pl.col("variant_type").is_null()
                | ~pl.col("variant_type").is_in(["ketiv", "qere"])
                | pl.col("variant_group_id").is_null()
                | (
                    (pl.col("variant_type") == "ketiv")
                    & (
                        pl.col("ketiv_form").is_null()
                        | (pl.col("ketiv_form") != pl.col("surface_form"))
                        | pl.col("qere_form").is_not_null()
                    )
                )
                | (
                    (pl.col("variant_type") == "qere")
                    & (
                        pl.col("qere_form").is_null()
                        | (pl.col("qere_form") != pl.col("surface_form"))
                        | pl.col("ketiv_form").is_not_null()
                    )
                )
            )
        )
        | (
            ~pl.col("is_variant")
            & (
                pl.col("variant_type").is_not_null()
                | pl.col("variant_group_id").is_not_null()
                | pl.col("ketiv_form").is_not_null()
                | pl.col("qere_form").is_not_null()
                | ~pl.col("is_default_reading")
            )
        )
    )
    if invalid_variant_rows.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "variant-form-loss",
            f"{invalid_variant_rows.height} tokens have inconsistent variant preservation",
        )
    variant_groups = (
        tokens.filter(pl.col("variant_group_id").is_not_null())
        .group_by("variant_group_id")
        .agg(
            pl.col("variant_type").eq("ketiv").sum().alias("ketiv_count"),
            pl.col("variant_type").eq("qere").sum().alias("qere_count"),
            pl.col("is_default_reading").sum().alias("default_count"),
            pl.col("is_default_reading")
            .filter(pl.col("variant_type") == "qere")
            .any()
            .alias("qere_is_default"),
        )
    )
    invalid_groups = variant_groups.filter(
        (pl.col("ketiv_count") > 1)
        | (pl.col("qere_count") > 1)
        | (pl.col("default_count") != 1)
        | ((pl.col("ketiv_count") == 1) & (pl.col("qere_count") == 1) & ~pl.col("qere_is_default"))
    )
    if invalid_groups.height:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "invalid-variant-group",
            f"{invalid_groups.height} Ketiv/Qere groups are ambiguous or lack one default",
        )


def _validate_analysis_stream(
    tokens: pl.DataFrame,
    analysis_tokens: pl.DataFrame,
    metadata: pl.DataFrame,
    analysis_reading: AnalysisReading,
    issues: list[IngestionIssue],
) -> None:
    expected = derive_analysis_stream(tokens, analysis_reading=analysis_reading)
    actual = analysis_tokens.sort("analysis_position_in_corpus")
    if actual.columns != expected.columns or actual.dtypes != expected.dtypes:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "analysis-stream-schema",
            "derived analysis stream columns or types differ from the governed schema",
        )
    elif not actual.equals(expected):
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "analysis-stream-mismatch",
            f"derived analysis stream does not match configured {analysis_reading} selection",
        )
    if metadata.height == 1 and metadata.item(0, "analysis_reading") != analysis_reading:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "analysis-reading-metadata-mismatch",
            "corpus metadata does not record the configured analysis reading",
        )


def _completeness(tokens: pl.DataFrame, issues: list[IngestionIssue]) -> dict[str, float | int]:
    total = tokens.height
    fields = {
        "lemma": "lemma",
        "morphology": "morphology_json",
        "syntax": "clause_id",
        "semantic_domain": "semantic_domain",
        "participant": "participant_id",
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
        "tokens": "hebrew_tokens",
        "analysis_tokens": "hebrew_analysis_tokens",
        "books": "hebrew_books",
        "source_records": "hebrew_source_records",
        "issues": "hebrew_ingestion_issues",
        "metadata": "hebrew_corpus_metadata",
    }
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            existing = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
            required = set(table_map.values()) | {
                "corpus_schema_versions",
                "hebrew_analysis_stream",
            }
            missing_tables = sorted(required - existing)
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
                parquet_path = str((output_dir / PARQUET_FILES[name]).resolve()).replace("'", "''")
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
    except duckdb.Error as exc:
        _issue(
            issues,
            ValidationSeverity.ERROR,
            "duckdb-query-failure",
            f"could not validate DuckDB: {exc}",
        )


def validate_hebrew_corpus(
    output_dir: Path,
    *,
    database_path: Path,
    normalization: HebrewNormalization,
    analysis_reading: AnalysisReading = "qere",
    expected_books: int,
    expected_chapters: int,
    expected_tokens: int | None,
    require_full_coverage: bool = True,
) -> CorpusValidationReport:
    """Run the complete identity, structure, normalization, coverage, and storage gate."""
    frames = _load_frames(output_dir)
    tokens = frames["tokens"]
    source_records = frames["source_records"]
    metadata = frames["metadata"]
    issues = [IngestionIssue.model_validate(row) for row in frames["issues"].to_dicts()]
    file_hashes, logical_hashes = _check_hashes(output_dir, frames, issues)
    _validate_identity(tokens, source_records, metadata, issues)
    _validate_structure(tokens, issues, require_full_coverage=require_full_coverage)
    _validate_normalization(tokens, normalization, issues)
    _validate_analysis_stream(
        tokens,
        frames["analysis_tokens"],
        metadata,
        analysis_reading,
        issues,
    )
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
        "hebrew_tokens": tokens.filter(pl.col("language") == "hebrew").height,
        "aramaic_tokens": tokens.filter(pl.col("language") == "aramaic").height,
    }
    return CorpusValidationReport(
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


def compare_processed_corpora(first: ProcessedCorpus, second: ProcessedCorpus) -> list[str]:
    """Return deterministic-output differences between two independent runs."""
    differences: list[str] = []
    if first.run_id != second.run_id:
        differences.append("ingestion run IDs differ")
    if first.file_hashes != second.file_hashes:
        differences.append("Parquet file hashes differ")
    if first.logical_hashes != second.logical_hashes:
        differences.append("logical table hashes differ")
    return differences
