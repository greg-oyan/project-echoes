"""Deterministic Greek Parquet output, DuckDB loading, and unified corpus views."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict

from echoes.corpus.greek_books import GREEK_BOOKS
from echoes.corpus.greek_models import GREEK_TOKEN_COLUMNS, GREEK_TOKEN_SCHEMA_VERSION
from echoes.corpus.storage import (
    CorpusStorageError,
    logical_frame_hash,
    refresh_cross_corpus_artifacts,
)
from echoes.ingest.macula_greek import GreekAdapterResult
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest

GREEK_PARQUET_FILES = {
    "tokens": "tokens.parquet",
    "books": "books.parquet",
    "source_records": "source_records.parquet",
    "issues": "ingestion_issues.parquet",
    "metadata": "corpus_metadata.parquet",
}
GREEK_TABLE_HASH_FILE = "table-hashes.json"
GREEK_SORT_COLUMNS = {
    "tokens": ["position_in_corpus"],
    "books": ["book_order"],
    "source_records": ["source_record_id"],
    "issues": ["severity", "code", "source_record_id"],
    "metadata": ["ingestion_run_id"],
}


class GreekCorpusSummary(BaseModel):
    """Required local analytical summary for the Greek corpus."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_version: str
    total_tokens: int
    total_books: int
    tokens_by_book: dict[str, int]
    missing_lemma_count: int
    missing_morphology_count: int
    missing_syntax_count: int
    missing_gloss_count: int
    missing_semantic_domain_count: int
    elided_count: int
    punctuation_bearing_count: int
    validation_issue_count: int
    ingestion_run_id: str


@dataclass(frozen=True, slots=True)
class ProcessedGreekCorpus:
    output_dir: Path
    run_id: str
    parquet_paths: dict[str, Path]
    file_hashes: dict[str, str]
    logical_hashes: dict[str, str]


def _frames(
    result: GreekAdapterResult,
    *,
    source: SourceManifest,
    normalization_config_hash: str,
    raw_file_hashes: dict[str, str],
) -> tuple[dict[str, pl.DataFrame], str]:
    tokens = result.tokens.clone().select(GREEK_TOKEN_COLUMNS)
    book_rows = []
    for book in GREEK_BOOKS:
        book_tokens = tokens.filter(pl.col("book") == book.code)
        if book_tokens.is_empty():
            continue
        book_rows.append(
            {
                "book": book.code,
                "book_name": book.name,
                "book_order": book.order,
                "source_book_number": book.source_number,
                "chapter_count": book_tokens["chapter"].n_unique(),
                "verse_count": book_tokens.select(["chapter", "verse"]).unique().height,
                "token_count": book_tokens.height,
            }
        )
    books = pl.DataFrame(
        book_rows,
        schema={
            "book": pl.String,
            "book_name": pl.String,
            "book_order": pl.Int16,
            "source_book_number": pl.Int16,
            "chapter_count": pl.Int16,
            "verse_count": pl.Int32,
            "token_count": pl.Int64,
        },
        orient="row",
    )
    source_records = result.source_records.clone()
    issue_schema = {
        "severity": pl.String,
        "code": pl.String,
        "message": pl.String,
        "source_record_id": pl.String,
        "token_id": pl.String,
        "book": pl.String,
        "chapter": pl.Int16,
        "verse": pl.Int16,
    }
    issue_rows = [issue.model_dump(mode="json") for issue in result.issues]
    issues = pl.DataFrame(issue_rows, schema=issue_schema, orient="row")

    run_digest = hashlib.sha256()
    run_digest.update((source.version_or_commit or "UNPINNED").encode("utf-8"))
    run_digest.update(normalization_config_hash.encode("ascii"))
    for path, file_hash in sorted(raw_file_hashes.items()):
        run_digest.update(path.encode("utf-8"))
        run_digest.update(file_hash.encode("ascii"))
    run_digest.update(str(GREEK_TOKEN_SCHEMA_VERSION).encode("ascii"))
    run_id = f"greek-{run_digest.hexdigest()[:20]}"
    metadata = pl.DataFrame(
        [
            {
                "ingestion_run_id": run_id,
                "source_id": source.source_id,
                "source_version": source.version_or_commit or "UNPINNED",
                "source_version_label": (
                    source.acquisition.version_label
                    if source.acquisition is not None
                    else "fixture"
                ),
                "schema_version": GREEK_TOKEN_SCHEMA_VERSION,
                "normalization_config_hash": normalization_config_hash,
                "raw_file_hashes_json": json.dumps(raw_file_hashes, sort_keys=True),
                "source_record_count": source_records.height,
                "token_count": tokens.height,
            }
        ],
        schema={
            "ingestion_run_id": pl.String,
            "source_id": pl.String,
            "source_version": pl.String,
            "source_version_label": pl.String,
            "schema_version": pl.Int16,
            "normalization_config_hash": pl.String,
            "raw_file_hashes_json": pl.String,
            "source_record_count": pl.Int64,
            "token_count": pl.Int64,
        },
        orient="row",
    )
    return {
        "tokens": tokens,
        "books": books,
        "source_records": source_records,
        "issues": issues,
        "metadata": metadata,
    }, run_id


def write_processed_greek_corpus(
    result: GreekAdapterResult,
    *,
    source: SourceManifest,
    normalization_config_hash: str,
    raw_file_hashes: dict[str, str],
    output_dir: Path,
    force: bool = False,
) -> ProcessedGreekCorpus:
    """Write stable Parquet files through an atomic version-directory replacement."""
    if output_dir.exists() and not force:
        raise CorpusStorageError(
            f"refusing to overwrite processed corpus at {output_dir}; pass --force explicitly"
        )
    frames, run_id = _frames(
        result,
        source=source,
        normalization_config_hash=normalization_config_hash,
        raw_file_hashes=raw_file_hashes,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.writing-{uuid4().hex}"
    backup = output_dir.parent / f".{output_dir.name}.backup-{uuid4().hex}"
    try:
        staging.mkdir()
        for name, frame in frames.items():
            frame.write_parquet(
                staging / GREEK_PARQUET_FILES[name],
                compression="zstd",
                compression_level=6,
                statistics=True,
            )
        parquet_paths = {name: staging / filename for name, filename in GREEK_PARQUET_FILES.items()}
        file_hashes = {path.name: sha256_file(path) for path in sorted(parquet_paths.values())}
        logical_hashes = {
            name: logical_frame_hash(frame, sort_by=GREEK_SORT_COLUMNS[name])
            for name, frame in frames.items()
        }
        hash_document = {
            "schema_version": 1,
            "ingestion_run_id": run_id,
            "parquet_sha256": file_hashes,
            "logical_table_sha256": logical_hashes,
        }
        (staging / GREEK_TABLE_HASH_FILE).write_text(
            json.dumps(hash_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if output_dir.exists():
            output_dir.replace(backup)
        try:
            staging.replace(output_dir)
        except OSError:
            if backup.exists() and not output_dir.exists():
                backup.replace(output_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not output_dir.exists():
            backup.replace(output_dir)
        raise
    return ProcessedGreekCorpus(
        output_dir=output_dir,
        run_id=run_id,
        parquet_paths={
            name: output_dir / filename for name, filename in GREEK_PARQUET_FILES.items()
        },
        file_hashes=file_hashes,
        logical_hashes=logical_hashes,
    )


def load_greek_duckdb(processed: ProcessedGreekCorpus, database_path: Path) -> None:
    """Transactionally replace only the intended Greek analytical tables and views."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                table_sources = {
                    "greek_tokens": processed.parquet_paths["tokens"],
                    "greek_books": processed.parquet_paths["books"],
                    "greek_source_records": processed.parquet_paths["source_records"],
                    "greek_ingestion_issues": processed.parquet_paths["issues"],
                    "greek_corpus_metadata": processed.parquet_paths["metadata"],
                }
                for table, path in table_sources.items():
                    quoted_path = str(path.resolve()).replace("'", "''")
                    connection.execute(
                        f"CREATE OR REPLACE TABLE {table} AS "
                        f"SELECT * FROM read_parquet('{quoted_path}')"
                    )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS greek_token_id_idx ON greek_tokens(token_id)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS greek_source_record_idx "
                    "ON greek_tokens(source_record_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS greek_reference_idx "
                    "ON greek_tokens(book_order, chapter, verse, position_in_verse)"
                )
                refresh_cross_corpus_artifacts(connection)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except (duckdb.Error, OSError) as exc:
        raise CorpusStorageError(f"could not load DuckDB database {database_path}: {exc}") from exc


def greek_corpus_summary(database_path: Path) -> GreekCorpusSummary:
    """Query the required Greek analytical counts from the local DuckDB database."""
    if not database_path.is_file():
        raise CorpusStorageError(f"DuckDB database does not exist: {database_path}")
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            metadata = connection.execute(
                "SELECT source_id, source_version, ingestion_run_id FROM greek_corpus_metadata"
            ).fetchone()
            if metadata is None:
                raise CorpusStorageError("Greek corpus metadata table is empty")
            counts = connection.execute(
                """
                SELECT
                    count(*) AS total_tokens,
                    count(DISTINCT book) AS total_books,
                    count(*) FILTER (WHERE lemma IS NULL OR lemma = '') AS missing_lemma,
                    count(*) FILTER (
                        WHERE morphology_json IS NULL OR morphology_json = ''
                    ) AS missing_morphology,
                    count(*) FILTER (
                        WHERE clause_id IS NULL AND phrase_id IS NULL
                    ) AS missing_syntax,
                    count(*) FILTER (
                        WHERE english_gloss IS NULL OR english_gloss = ''
                    ) AS missing_gloss,
                    count(*) FILTER (
                        WHERE semantic_domain IS NULL OR semantic_domain = ''
                    ) AS missing_semantic_domain,
                    count(*) FILTER (WHERE is_elided) AS elided,
                    count(*) FILTER (
                        WHERE leading_punctuation <> '' OR trailing_punctuation <> ''
                    ) AS punctuation_bearing
                FROM greek_tokens
                """
            ).fetchone()
            if counts is None:
                raise CorpusStorageError("Greek token table is unavailable")
            tokens_by_book = {
                str(book): int(count)
                for book, count in connection.execute(
                    "SELECT book, count(*) FROM greek_tokens "
                    "GROUP BY book, book_order ORDER BY book_order"
                ).fetchall()
            }
            issue_row = connection.execute("SELECT count(*) FROM greek_ingestion_issues").fetchone()
            if issue_row is None:
                raise CorpusStorageError("Greek ingestion issue table is unavailable")
            issue_count = int(issue_row[0])
    except duckdb.Error as exc:
        raise CorpusStorageError(f"could not query Greek corpus summary: {exc}") from exc
    return GreekCorpusSummary(
        source_id=str(metadata[0]),
        source_version=str(metadata[1]),
        total_tokens=int(counts[0]),
        total_books=int(counts[1]),
        tokens_by_book=tokens_by_book,
        missing_lemma_count=int(counts[2]),
        missing_morphology_count=int(counts[3]),
        missing_syntax_count=int(counts[4]),
        missing_gloss_count=int(counts[5]),
        missing_semantic_domain_count=int(counts[6]),
        elided_count=int(counts[7]),
        punctuation_bearing_count=int(counts[8]),
        validation_issue_count=issue_count,
        ingestion_run_id=str(metadata[2]),
    )
