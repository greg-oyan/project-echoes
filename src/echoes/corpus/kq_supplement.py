"""Ketiv/Qere supplement storage, derived streams, and validation (ADR 0009).

The supplement lives beside the primary tables: ketiv tokens, the locus
registry, and conflict rows are written to their own versioned Parquet
directory and DuckDB tables.  The primary MACULA tables are never modified;
their identity and content digests are recorded at build time and re-checked
at validation time.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl

from echoes.align.book_codes import macula_book_for_oshb
from echoes.align.supplementary import (
    STRUCTURAL_ALIGNMENT_COLUMNS,
    StructuralAlignmentError,
    build_kq_structural_alignments,
    build_kq_supplementary_annotations,
    validate_supplementary_annotations,
)
from echoes.corpus.analysis import (
    ANALYSIS_TOKEN_COLUMNS,
    ANALYSIS_TOKEN_POLARS_SCHEMA,
    AnalysisReading,
    derive_analysis_stream,
)
from echoes.corpus.models import CanonicalToken, IngestionIssue, ValidationSeverity
from echoes.corpus.storage import CorpusStorageError, logical_frame_hash
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.corpus.validation import (
    CorpusValidationReport,
    corpus_analytical_digest,
    corpus_content_digest,
    corpus_identity_digest,
)
from echoes.ingest.oshb_ketiv_qere import (
    KQSupplementResult,
    KQSupplementSummary,
    build_kq_supplement,
)
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest, load_source_catalog

KQ_SUPPLEMENT_SCHEMA_VERSION = 2
OSHB_SOURCE_ID = "oshb-morphhb"
KQ_PARQUET_FILES = {
    "ketiv_tokens": "kq_ketiv_tokens.parquet",
    "locus_registry": "kq_locus_registry.parquet",
    "structural_alignments": "kq_structural_alignments.parquet",
    "conflicts": "kq_conflicts.parquet",
    "supplementary_annotations": "kq_supplementary_annotations.parquet",
    "issues": "kq_ingestion_issues.parquet",
    "metadata": "kq_metadata.parquet",
}
KQ_TABLE_HASH_FILE = "table-hashes.json"
KQ_SORT_COLUMNS = {
    "ketiv_tokens": ["position_in_corpus"],
    "locus_registry": ["locus_id"],
    "structural_alignments": ["ketiv_token_id"],
    "conflicts": ["locus_id", "field_name"],
    "supplementary_annotations": ["annotation_id"],
    "issues": ["severity", "code", "book", "chapter", "verse"],
    "metadata": ["ingestion_run_id"],
}

SUPPLEMENTED_ANALYSIS_TOKEN_POLARS_SCHEMA = {
    **ANALYSIS_TOKEN_POLARS_SCHEMA,
    "analysis_sentence_id": pl.String,
    "analysis_clause_id": pl.String,
    "analysis_phrase_id": pl.String,
    "structural_status": pl.String,
}
SUPPLEMENTED_ANALYSIS_TOKEN_COLUMNS: tuple[str, ...] = tuple(
    SUPPLEMENTED_ANALYSIS_TOKEN_POLARS_SCHEMA
)


@dataclass(frozen=True, slots=True)
class ProcessedKQSupplement:
    output_dir: Path
    run_id: str
    parquet_paths: dict[str, Path]
    file_hashes: dict[str, str]
    logical_hashes: dict[str, str]


def _word_slot_expression() -> pl.Expr:
    return pl.col("source_word_id").str.extract(r"!(\d+)$", 1).cast(pl.Int32).alias("_word_slot")


def derive_supplemented_analysis_stream(
    primary_tokens: pl.DataFrame,
    ketiv_tokens: pl.DataFrame,
    locus_registry: pl.DataFrame,
    structural_alignments: pl.DataFrame,
    *,
    analysis_reading: AnalysisReading,
) -> pl.DataFrame:
    """Derive the configured reading stream across primary plus supplement.

    ``qere``: its legacy-column projection is byte-identical to the
    primary-only derived stream; additive columns expose the source-native
    structural memberships.

    ``ketiv``: at every *paired* locus the referenced MACULA qere tokens are
    replaced by the OSHB ketiv tokens; lone ketiv readings (ketiv-only loci)
    join the stream; everything else keeps the existing reading.  Positions
    are recomputed continuously over (book, chapter, verse, source word slot,
    position in word), which reproduces corpus order for primary tokens.
    """
    if analysis_reading not in {"qere", "ketiv"}:
        raise ValueError("analysis_reading must be 'qere' or 'ketiv'")
    if analysis_reading == "qere":
        base = derive_analysis_stream(primary_tokens, analysis_reading="qere")
        return (
            base.join(
                primary_tokens.select(
                    "token_id",
                    pl.col("sentence_id").alias("analysis_sentence_id"),
                    pl.col("clause_id").alias("analysis_clause_id"),
                    pl.col("phrase_id").alias("analysis_phrase_id"),
                ),
                on="token_id",
                how="left",
                validate="1:1",
            )
            .with_columns(pl.lit("source_native").alias("structural_status"))
            .cast(pl.Schema(SUPPLEMENTED_ANALYSIS_TOKEN_POLARS_SCHEMA))
            .select(SUPPLEMENTED_ANALYSIS_TOKEN_COLUMNS)
        )

    paired = locus_registry.filter(pl.col("kind") == "paired")
    replaced_qere_ids = {
        token_id
        for ids_json in paired["macula_qere_token_ids_json"].to_list()
        for token_id in json.loads(ids_json)
    }
    # Respect primary-internal paired variant groups exactly as the base
    # derivation does (full-corpus MACULA supplies none; fixtures may).
    base = derive_analysis_stream(primary_tokens, analysis_reading="ketiv")
    base_ids = set(base["token_id"].to_list())
    selected_primary = primary_tokens.filter(
        pl.col("token_id").is_in(base_ids) & ~pl.col("token_id").is_in(replaced_qere_ids)
    )
    mapped_ketiv = ketiv_tokens.join(
        structural_alignments.select(
            "ketiv_token_id",
            "analysis_sentence_id",
            "analysis_clause_id",
            "analysis_phrase_id",
            "resolution_status",
        ).rename(
            {
                "ketiv_token_id": "token_id",
                "resolution_status": "structural_status",
            }
        ),
        on="token_id",
        how="left",
        validate="1:1",
    )
    if mapped_ketiv.filter(pl.col("structural_status").is_null()).height:
        raise ValueError("every Ketiv token requires one explicit structural mapping row")
    merged = pl.concat(
        [
            selected_primary.select(
                "token_id",
                "source_edition_reference",
                "variant_group_id",
                "variant_type",
                "book_order",
                "chapter",
                "verse",
                "source_word_id",
                "position_in_word",
                pl.col("sentence_id").alias("analysis_sentence_id"),
                pl.col("clause_id").alias("analysis_clause_id"),
                pl.col("phrase_id").alias("analysis_phrase_id"),
                pl.lit("source_native").alias("structural_status"),
                "book",
            ),
            mapped_ketiv.select(
                "token_id",
                "source_edition_reference",
                "variant_group_id",
                "variant_type",
                "book_order",
                "chapter",
                "verse",
                "source_word_id",
                "position_in_word",
                "analysis_sentence_id",
                "analysis_clause_id",
                "analysis_phrase_id",
                "structural_status",
                "book",
            ),
        ],
        how="vertical",
        rechunk=True,
    )
    ordered = merged.with_columns(_word_slot_expression()).sort(
        "book_order", "chapter", "verse", "_word_slot", "position_in_word", "token_id"
    )
    stream = ordered.with_columns(
        pl.col("token_id")
        .cum_count()
        .over("book", "chapter", "verse")
        .cast(pl.Int32)
        .alias("analysis_position_in_verse"),
        pl.when(pl.col("analysis_clause_id").is_not_null())
        .then(pl.col("token_id").cum_count().over("analysis_clause_id"))
        .otherwise(None)
        .cast(pl.Int32)
        .alias("analysis_position_in_clause"),
        pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("analysis_position_in_corpus"),
    ).select(
        pl.lit(1, dtype=pl.Int16).alias("schema_version"),
        pl.lit("ketiv").alias("analysis_reading"),
        "token_id",
        "source_edition_reference",
        "variant_group_id",
        "variant_type",
        "analysis_position_in_verse",
        "analysis_position_in_clause",
        "analysis_position_in_corpus",
        "analysis_sentence_id",
        "analysis_clause_id",
        "analysis_phrase_id",
        "structural_status",
    )
    return stream.cast(pl.Schema(SUPPLEMENTED_ANALYSIS_TOKEN_POLARS_SCHEMA)).select(
        SUPPLEMENTED_ANALYSIS_TOKEN_COLUMNS
    )


def write_kq_supplement(
    result: KQSupplementResult,
    *,
    source: SourceManifest,
    normalization_config_hash: str,
    raw_file_hashes: dict[str, str],
    primary_identity_digest: str,
    primary_content_digest: str,
    primary_analytical_digest: str,
    output_dir: Path,
    force: bool = False,
) -> ProcessedKQSupplement:
    """Write supplement Parquet tables through an atomic directory replacement."""
    if output_dir.exists() and not force:
        raise CorpusStorageError(
            f"refusing to overwrite processed supplement at {output_dir}; pass --force explicitly"
        )
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
    issues = pl.DataFrame(
        [issue.model_dump(mode="json") for issue in result.issues],
        schema=issue_schema,
        orient="row",
    )
    run_digest = hashlib.sha256()
    run_digest.update((source.version_or_commit or "UNPINNED").encode("utf-8"))
    run_digest.update(normalization_config_hash.encode("ascii"))
    for path_name, file_hash in sorted(raw_file_hashes.items()):
        run_digest.update(path_name.encode("utf-8"))
        run_digest.update(file_hash.encode("ascii"))
    run_digest.update(primary_identity_digest.encode("ascii"))
    run_digest.update(primary_analytical_digest.encode("ascii"))
    run_digest.update(str(KQ_SUPPLEMENT_SCHEMA_VERSION).encode("ascii"))
    run_id = f"oshb-kq-{run_digest.hexdigest()[:20]}"
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
                "schema_version": KQ_SUPPLEMENT_SCHEMA_VERSION,
                "normalization_config_hash": normalization_config_hash,
                "raw_file_hashes_json": json.dumps(raw_file_hashes, sort_keys=True),
                "primary_identity_digest": primary_identity_digest,
                "primary_content_digest": primary_content_digest,
                "primary_analytical_digest": primary_analytical_digest,
                "locus_count": result.locus_registry.height,
                "ketiv_token_count": result.ketiv_tokens.height,
                "structural_alignment_count": result.structural_alignments.height,
                "conflict_count": result.conflicts.height,
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
            "primary_identity_digest": pl.String,
            "primary_content_digest": pl.String,
            "primary_analytical_digest": pl.String,
            "locus_count": pl.Int64,
            "ketiv_token_count": pl.Int64,
            "structural_alignment_count": pl.Int64,
            "conflict_count": pl.Int64,
        },
        orient="row",
    )
    frames = {
        "ketiv_tokens": result.ketiv_tokens,
        "locus_registry": result.locus_registry,
        "structural_alignments": result.structural_alignments,
        "conflicts": result.conflicts,
        "supplementary_annotations": build_kq_supplementary_annotations(result.locus_registry),
        "issues": issues,
        "metadata": metadata,
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.writing-{uuid4().hex}"
    backup = output_dir.parent / f".{output_dir.name}.backup-{uuid4().hex}"
    try:
        staging.mkdir()
        for name, frame in frames.items():
            frame.write_parquet(
                staging / KQ_PARQUET_FILES[name],
                compression="zstd",
                compression_level=6,
                statistics=True,
            )
        parquet_paths = {name: staging / filename for name, filename in KQ_PARQUET_FILES.items()}
        file_hashes = {path.name: sha256_file(path) for path in sorted(parquet_paths.values())}
        logical_hashes = {
            name: logical_frame_hash(frame, sort_by=KQ_SORT_COLUMNS[name])
            for name, frame in frames.items()
        }
        hash_document = {
            "schema_version": KQ_SUPPLEMENT_SCHEMA_VERSION,
            "ingestion_run_id": run_id,
            "parquet_sha256": file_hashes,
            "logical_table_sha256": logical_hashes,
        }
        (staging / KQ_TABLE_HASH_FILE).write_text(
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
    return ProcessedKQSupplement(
        output_dir=output_dir,
        run_id=run_id,
        parquet_paths={name: output_dir / filename for name, filename in KQ_PARQUET_FILES.items()},
        file_hashes=file_hashes,
        logical_hashes=logical_hashes,
    )


def load_kq_duckdb(processed: ProcessedKQSupplement, database_path: Path) -> None:
    """Transactionally replace only the supplement tables and pairing view."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                table_sources = {
                    "hebrew_kq_ketiv_tokens": processed.parquet_paths["ketiv_tokens"],
                    "hebrew_kq_locus_registry": processed.parquet_paths["locus_registry"],
                    "hebrew_kq_structural_alignments": processed.parquet_paths[
                        "structural_alignments"
                    ],
                    "hebrew_kq_conflicts": processed.parquet_paths["conflicts"],
                    "hebrew_kq_supplementary_annotations": processed.parquet_paths[
                        "supplementary_annotations"
                    ],
                    "hebrew_kq_ingestion_issues": processed.parquet_paths["issues"],
                    "hebrew_kq_metadata": processed.parquet_paths["metadata"],
                }
                for table, path in table_sources.items():
                    quoted_path = str(path.resolve()).replace("'", "''")
                    connection.execute(
                        f"CREATE OR REPLACE TABLE {table} AS "
                        f"SELECT * FROM read_parquet('{quoted_path}')"
                    )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS hebrew_kq_token_id_idx "
                    "ON hebrew_kq_ketiv_tokens(token_id)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS hebrew_kq_structural_token_id_idx "
                    "ON hebrew_kq_structural_alignments(ketiv_token_id)"
                )
                existing = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
                if "hebrew_tokens" in existing:
                    connection.execute(
                        "CREATE OR REPLACE VIEW hebrew_kq_variant_groups AS "
                        "SELECT registry.locus_id, registry.variant_group_id, "
                        "registry.kind, registry.book, registry.chapter, registry.verse, "
                        "registry.surface_match_tier, registry.alignment_method, "
                        "registry.alignment_confidence, registry.conflict, "
                        "ketiv.token_id AS ketiv_token_id, "
                        "ketiv.surface_form AS ketiv_surface_form, "
                        "qere.token_id AS qere_token_id, "
                        "qere.surface_form AS qere_surface_form "
                        "FROM hebrew_kq_locus_registry AS registry "
                        "LEFT JOIN hebrew_kq_ketiv_tokens AS ketiv "
                        "ON list_contains(from_json(registry.ketiv_token_ids_json, "
                        "'[\"VARCHAR\"]'), ketiv.token_id) "
                        "LEFT JOIN hebrew_tokens AS qere "
                        "ON list_contains(from_json(registry.macula_qere_token_ids_json, "
                        "'[\"VARCHAR\"]'), qere.token_id)"
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except (duckdb.Error, OSError) as exc:
        raise CorpusStorageError(f"could not load DuckDB database {database_path}: {exc}") from exc


def validate_kq_supplement(
    output_dir: Path,
    primary_tokens: pl.DataFrame,
    *,
    other_corpus_token_ids: set[str] | None = None,
    expected_primary_identity_digest: str | None = None,
    expected_primary_content_digest: str | None = None,
    expected_primary_analytical_digest: str | None = None,
) -> CorpusValidationReport:
    """Validate supplement integrity without touching the primary tables."""
    frames: dict[str, pl.DataFrame] = {}
    for name, filename in KQ_PARQUET_FILES.items():
        path = output_dir / filename
        if not path.is_file():
            raise CorpusStorageError(f"required supplement table does not exist: {path}")
        frames[name] = pl.read_parquet(path)
    ketiv = frames["ketiv_tokens"]
    registry = frames["locus_registry"]
    structural_alignments = frames["structural_alignments"]
    conflicts = frames["conflicts"]
    metadata = frames["metadata"]
    issues = [IngestionIssue.model_validate(row) for row in frames["issues"].to_dicts()]

    def add_issue(code: str, message: str) -> None:
        issues.append(IngestionIssue(severity=ValidationSeverity.ERROR, code=code, message=message))

    document = json.loads((output_dir / KQ_TABLE_HASH_FILE).read_text(encoding="utf-8"))
    file_hashes = {
        filename: sha256_file(output_dir / filename) for filename in KQ_PARQUET_FILES.values()
    }
    for filename, digest in file_hashes.items():
        if document.get("parquet_sha256", {}).get(filename) != digest:
            add_issue("parquet-hash-mismatch", f"{filename} differs from its recorded SHA-256")
    logical_hashes = {
        name: logical_frame_hash(frame, sort_by=KQ_SORT_COLUMNS[name])
        for name, frame in frames.items()
    }
    for name, digest in logical_hashes.items():
        if document.get("logical_table_sha256", {}).get(name) != digest:
            add_issue("logical-hash-mismatch", f"{name} differs from its recorded logical hash")

    # Primary tables must be untouched.
    identity = corpus_identity_digest(primary_tokens)
    content = corpus_content_digest(primary_tokens)
    analytical = corpus_analytical_digest(primary_tokens)
    if (
        expected_primary_identity_digest is not None
        and identity != expected_primary_identity_digest
    ):
        add_issue("primary-identity-changed", "primary identity digest changed")
    if expected_primary_content_digest is not None and content != expected_primary_content_digest:
        add_issue("primary-content-changed", "primary content digest changed")
    if (
        expected_primary_analytical_digest is not None
        and analytical != expected_primary_analytical_digest
    ):
        add_issue("primary-analytical-changed", "primary analytical digest changed")
    if metadata.height == 1:
        if str(metadata.item(0, "primary_identity_digest")) != identity:
            add_issue(
                "primary-identity-drift",
                "primary identity digest differs from the build-time record",
            )
        if str(metadata.item(0, "primary_content_digest")) != content:
            add_issue(
                "primary-content-drift",
                "primary content digest differs from the build-time record",
            )
        if str(metadata.item(0, "primary_analytical_digest")) != analytical:
            add_issue(
                "primary-analytical-drift",
                "primary analytical digest differs from the build-time record",
            )
        if int(metadata.item(0, "structural_alignment_count")) != structural_alignments.height:
            add_issue(
                "structural-alignment-count-drift",
                "structural alignment count differs from the build-time record",
            )
    else:
        add_issue("metadata-cardinality", f"expected one metadata row, found {metadata.height}")

    # Every ketiv row revalidates against canonical schema v2.
    for row in ketiv.to_dicts():
        try:
            CanonicalToken.model_validate(row)
        except Exception as exc:  # collected as a validation finding, not raised
            add_issue("ketiv-schema-invalid", f"{row.get('token_id')}: {exc}")
            break

    # Token-ID uniqueness and cross-corpus collision-freedom.
    if ketiv["token_id"].n_unique() != ketiv.height:
        add_issue("duplicate-ketiv-token-id", "ketiv token IDs are not unique")
    primary_ids = set(primary_tokens["token_id"].to_list())
    ketiv_ids = set(ketiv["token_id"].to_list())
    if ketiv_ids & primary_ids:
        add_issue("ketiv-primary-collision", "ketiv token IDs collide with primary tokens")
    if other_corpus_token_ids and ketiv_ids & other_corpus_token_ids:
        add_issue("ketiv-cross-corpus-collision", "ketiv token IDs collide across corpora")

    # Registry consistency, gap verification, and qere references.
    verse_slots: dict[tuple[str, int, int], set[int]] = {}
    for book, chapter, verse, word_id in primary_tokens.select(
        "book", "chapter", "verse", "source_word_id"
    ).iter_rows():
        verse_slots.setdefault((str(book), int(chapter), int(verse)), set()).add(
            int(str(word_id).rsplit("!", maxsplit=1)[-1])
        )
    registry_ketiv_ids: set[str] = set()
    gap_violations = 0
    missing_qere_refs = 0
    source_identity_violations = 0
    source_reference_violations = 0
    ketiv_by_id = {str(row["token_id"]): row for row in ketiv.iter_rows(named=True)}
    for row in registry.iter_rows(named=True):
        ketiv_token_ids = json.loads(str(row["ketiv_token_ids_json"]))
        registry_ketiv_ids.update(ketiv_token_ids)
        source_book = str(row["source_book_identifier"])
        canonical_book = str(row["canonical_book"])
        try:
            expected_canonical_book = macula_book_for_oshb(source_book)
        except ValueError:
            source_reference_violations += 1
        else:
            if canonical_book != expected_canonical_book or str(row["book"]) != canonical_book:
                source_reference_violations += 1
        expected_reference = f"{source_book} {row['chapter']}:{row['verse']}"
        for token_id in ketiv_token_ids:
            token = ketiv_by_id.get(str(token_id))
            if token is None:
                continue
            expected_word_id = f"{expected_reference}!{token['position_in_verse']}"
            if (
                str(token["source_edition_reference"]) != expected_reference
                or str(token["source_word_id"]) != expected_word_id
                or str(token["book"]) != canonical_book
            ):
                source_reference_violations += 1
            expected_token_id = generate_source_edition_token_id(
                book_identifier=source_book,
                chapter=int(row["chapter"]),
                verse=int(row["verse"]),
                source_token_position=int(token["position_in_verse"]),
                source_record_id=str(token["source_record_id"]),
                disambiguate_with_source_record=True,
            )
            if str(token["token_id"]) != expected_token_id:
                source_identity_violations += 1
        slots = json.loads(str(row["ketiv_word_slots_json"]))
        present = verse_slots.get((str(row["book"]), int(row["chapter"]), int(row["verse"])), set())
        if any(int(slot) in present for slot in slots):
            gap_violations += 1
        for token_id in json.loads(str(row["macula_qere_token_ids_json"])):
            if token_id not in primary_ids:
                missing_qere_refs += 1
        confidence = float(row["alignment_confidence"])
        if not 0.0 <= confidence <= 1.0:
            add_issue("confidence-out-of-range", f"{row['locus_id']}: {confidence}")
        if str(row["surface_match_tier"]) in {"consonantal", "mismatch"} and not bool(
            row["conflict"]
        ):
            add_issue("unrecorded-conflict", f"{row['locus_id']} disagrees without a conflict row")
    if registry_ketiv_ids != ketiv_ids:
        add_issue("registry-token-mismatch", "registry ketiv IDs differ from the token table")
    if gap_violations:
        add_issue("ketiv-slot-occupied", f"{gap_violations} loci key into occupied MACULA slots")
    if missing_qere_refs:
        add_issue("missing-qere-reference", f"{missing_qere_refs} qere references are unresolved")
    if source_identity_violations:
        add_issue(
            "non-source-native-ketiv-token-id",
            f"{source_identity_violations} Ketiv IDs differ from OSHB source identity",
        )
    if source_reference_violations:
        add_issue(
            "source-canonical-reference-mismatch",
            f"{source_reference_violations} source/canonical book references are inconsistent",
        )
    conflict_loci = set(conflicts["locus_id"].to_list())
    flagged_loci = set(registry.filter(pl.col("conflict"))["locus_id"].to_list())
    if conflict_loci != flagged_loci:
        add_issue("conflict-table-mismatch", "conflict rows do not match flagged registry loci")

    # Supplementary annotations obey the beside-not-over contract.
    annotations = frames["supplementary_annotations"]
    for finding in validate_supplementary_annotations(primary_tokens, annotations):
        add_issue("supplementary-annotation-invalid", finding)
    expected_annotations = build_kq_supplementary_annotations(registry)
    if not annotations.equals(expected_annotations):
        add_issue(
            "supplementary-annotation-drift",
            "stored annotation rows differ from the registry-derived rows",
        )

    # Structural IDs are an explicit analytical mapping, never source-native
    # OSHB annotation. Recompute every row from the untouched primary table.
    if tuple(structural_alignments.columns) != STRUCTURAL_ALIGNMENT_COLUMNS:
        add_issue(
            "structural-alignment-schema",
            "structural alignment columns differ from the governed schema",
        )
    if structural_alignments["ketiv_token_id"].n_unique() != structural_alignments.height:
        add_issue("duplicate-structural-alignment", "Ketiv structural rows are not unique")
    if set(structural_alignments["ketiv_token_id"].to_list()) != ketiv_ids:
        add_issue(
            "structural-alignment-token-mismatch",
            "structural alignment token IDs differ from the Ketiv token table",
        )
    try:
        expected_structural_alignments = build_kq_structural_alignments(
            primary_tokens,
            ketiv,
            registry,
        )
    except StructuralAlignmentError as exc:
        add_issue("structural-alignment-recompute-failed", str(exc))
    else:
        if not structural_alignments.equals(expected_structural_alignments):
            add_issue(
                "structural-alignment-drift",
                "stored structural rows differ from deterministic primary-token consensus",
            )
    valid_statuses = {"resolved", "partially_resolved", "unresolved"}
    if not set(structural_alignments["resolution_status"].to_list()) <= valid_statuses:
        add_issue("structural-alignment-status", "unknown structural alignment status")
    if structural_alignments.filter(
        (pl.col("analysis_clause_id").is_null()) & (pl.col("resolution_status") == "resolved")
    ).height:
        add_issue(
            "silent-unresolved-clause",
            "a resolved structural row has no analysis clause identifier",
        )

    # Derived streams: qere byte-identical; ketiv continuous with substitutions.
    qere_stream = derive_supplemented_analysis_stream(
        primary_tokens,
        ketiv,
        registry,
        structural_alignments,
        analysis_reading="qere",
    )
    base_stream = derive_analysis_stream(primary_tokens, analysis_reading="qere")
    if not qere_stream.select(ANALYSIS_TOKEN_COLUMNS).equals(base_stream):
        add_issue("qere-stream-changed", "supplemented qere stream differs from the base stream")
    ketiv_stream = derive_supplemented_analysis_stream(
        primary_tokens,
        ketiv,
        registry,
        structural_alignments,
        analysis_reading="ketiv",
    )
    positions = ketiv_stream["analysis_position_in_corpus"].to_list()
    if positions != list(range(1, len(positions) + 1)):
        add_issue("ketiv-stream-noncontinuous", "ketiv stream positions are not continuous")
    stream_ids = set(ketiv_stream["token_id"].to_list())
    paired = registry.filter(pl.col("kind") == "paired")
    for row in paired.iter_rows(named=True):
        for token_id in json.loads(str(row["macula_qere_token_ids_json"])):
            if token_id in stream_ids:
                add_issue(
                    "ketiv-stream-substitution",
                    f"{row['locus_id']}: replaced qere token remains in the ketiv stream",
                )
                break
        for token_id in json.loads(str(row["ketiv_token_ids_json"])):
            if token_id not in stream_ids:
                add_issue(
                    "ketiv-stream-substitution",
                    f"{row['locus_id']}: ketiv token missing from the ketiv stream",
                )
                break

    errors = sum(issue.severity is ValidationSeverity.ERROR for issue in issues)
    metadata_row = metadata.row(0, named=True)
    coverage: dict[str, object] = {
        "loci": registry.height,
        "paired_loci": registry.filter(pl.col("kind") == "paired").height,
        "ketiv_only_loci": registry.filter(pl.col("kind") == "ketiv_only").height,
        "qere_only_loci": registry.filter(pl.col("kind") == "qere_only").height,
        "conflicts": conflicts.height,
        "structural_resolved_tokens": structural_alignments.filter(
            pl.col("resolution_status") == "resolved"
        ).height,
        "structural_partially_resolved_tokens": structural_alignments.filter(
            pl.col("resolution_status") == "partially_resolved"
        ).height,
        "structural_unresolved_tokens": structural_alignments.filter(
            pl.col("resolution_status") == "unresolved"
        ).height,
        "structural_sentence_coverage": (
            structural_alignments["analysis_sentence_id"].is_not_null().sum()
            / structural_alignments.height
            if structural_alignments.height
            else 0.0
        ),
        "structural_clause_coverage": (
            structural_alignments["analysis_clause_id"].is_not_null().sum()
            / structural_alignments.height
            if structural_alignments.height
            else 0.0
        ),
        "structural_phrase_coverage": (
            structural_alignments["analysis_phrase_id"].is_not_null().sum()
            / structural_alignments.height
            if structural_alignments.height
            else 0.0
        ),
        "loci_by_book": dict(registry.group_by("book").len(name="count").sort("book").iter_rows()),
    }
    return CorpusValidationReport(
        corpus="hebrew-kq-supplement",
        passed=errors == 0,
        ingestion_run_id=str(metadata_row["ingestion_run_id"]),
        source_id=str(metadata_row["source_id"]),
        source_version=str(metadata_row["source_version"]),
        schema_version=int(metadata_row["schema_version"]),
        normalization_config_hash=str(metadata_row["normalization_config_hash"]),
        total_tokens=ketiv.height,
        total_source_records=ketiv.height,
        book_count=registry["book"].n_unique(),
        chapter_count=registry.select("book", "chapter").unique().height,
        verse_count=registry.select("book", "chapter", "verse").unique().height,
        completeness={"total_tokens": ketiv.height},
        coverage=coverage,
        parquet_sha256=file_hashes,
        logical_table_sha256=logical_hashes,
        issues=issues,
    )


class KQPipelineError(RuntimeError):
    """Raised when supplement pipeline configuration or governance is inconsistent."""


@dataclass(frozen=True, slots=True)
class KQPipelineResult:
    source: SourceManifest
    summary: KQSupplementSummary
    processed: ProcessedKQSupplement
    validation: CorpusValidationReport


def ingest_kq_supplement(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    config_dir: Path = Path("config"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
    force: bool = False,
) -> KQPipelineResult:
    """Verify the OSHB acquisition, build the K/Q supplement, store, and validate."""
    from echoes.acquire import verify_acquisition
    from echoes.settings import NormalizationConfig, load_config

    catalog = load_source_catalog(manifest_path)
    oshb = catalog.find(OSHB_SOURCE_ID)
    if oshb is None:
        raise KQPipelineError("source manifest does not define oshb-morphhb")
    hebrew = catalog.find("macula-hebrew")
    if hebrew is None or hebrew.acquisition is None:
        raise KQPipelineError("source manifest does not define an acquired macula-hebrew")
    normalization = load_config(config_dir / "normalization.yaml")
    if not isinstance(normalization, NormalizationConfig):
        raise KQPipelineError("normalization.yaml loaded with an unexpected schema")
    oshb_root, receipt = verify_acquisition(oshb, data_root=data_root)

    primary_dir = data_root / "processed" / hebrew.source_id / hebrew.acquisition.version_label
    primary_path = primary_dir / "tokens.parquet"
    if not primary_path.is_file():
        raise KQPipelineError(f"primary Hebrew token table does not exist: {primary_path}")
    primary_tokens = pl.read_parquet(primary_path)

    greek_ids: set[str] = set()
    greek = catalog.find("macula-greek")
    if greek is not None and greek.acquisition is not None:
        greek_path = (
            data_root
            / "processed"
            / greek.source_id
            / greek.acquisition.version_label
            / "tokens.parquet"
        )
        if greek_path.is_file():
            greek_ids = set(pl.read_parquet(greek_path, columns=["token_id"])["token_id"].to_list())

    result = build_kq_supplement(
        oshb_root,
        primary_tokens,
        source=oshb,
        normalization=normalization.hebrew,
    )
    if oshb.acquisition is None:
        raise KQPipelineError("oshb-morphhb has no acquisition version label")
    resolved_output = output_dir or (
        data_root / "processed" / oshb.source_id / oshb.acquisition.version_label
    )
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    processed = write_kq_supplement(
        result,
        source=oshb,
        normalization_config_hash=sha256_file(config_dir / "normalization.yaml"),
        raw_file_hashes={item.relative_path: item.sha256 for item in receipt.files},
        primary_identity_digest=corpus_identity_digest(primary_tokens),
        primary_content_digest=corpus_content_digest(primary_tokens),
        primary_analytical_digest=corpus_analytical_digest(primary_tokens),
        output_dir=resolved_output,
        force=force,
    )
    load_kq_duckdb(processed, resolved_database)
    validation = validate_kq_supplement(
        resolved_output,
        primary_tokens,
        other_corpus_token_ids=greek_ids,
    )
    return KQPipelineResult(
        source=oshb,
        summary=result.summary,
        processed=processed,
        validation=validation,
    )
