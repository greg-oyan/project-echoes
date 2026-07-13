"""Command-line interface for Project Echoes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, cast

import duckdb
import typer
from pydantic import BaseModel, ValidationError

from echoes import __version__
from echoes.acquire import (
    AcquisitionError,
    acquire_source,
    audit_manifest_hashes,
    verify_acquisition,
)
from echoes.corpus.greek import (
    GreekPipelineError,
    ingest_greek_corpus,
    validate_existing_greek_corpus,
)
from echoes.corpus.greek_storage import greek_corpus_summary
from echoes.corpus.hebrew import (
    HebrewPipelineError,
    ingest_hebrew_corpus,
    validate_existing_hebrew_corpus,
)
from echoes.corpus.kq_supplement import KQPipelineError, ingest_kq_supplement
from echoes.corpus.storage import CorpusStorageError, corpus_summary
from echoes.corpus.validation import CorpusValidationError
from echoes.ingest.macula_greek import GreekIngestionError
from echoes.ingest.macula_hebrew import HebrewIngestionError
from echoes.manifest import build_run_manifest, write_run_manifest
from echoes.manifests.sources import (
    SourceManifestError,
    SourceRole,
    SourceStatus,
    load_source_catalog,
    serialize_source,
    summarize_sources,
)
from echoes.segment.generation import PassageGenerationError
from echoes.segment.pipeline import (
    PassagePipelineError,
    SegmentationSelection,
    default_passage_output,
    segment_passages,
)
from echoes.segment.storage import (
    PassageStorageError,
    read_passage,
    read_passage_membership,
)
from echoes.segment.streams import SegmentationInputError, load_segmentation_inputs
from echoes.segment.validation import validate_passage_artifacts
from echoes.settings import (
    ConfigLoadError,
    RuntimeSettings,
    SegmentationConfig,
    load_config,
    validate_config_directory,
)

app = typer.Typer(
    name="echoes",
    help="Reproducible computational biblical-studies research tools.",
    no_args_is_help=True,
    add_completion=False,
)


def _echo_json(value: BaseModel) -> None:
    """Emit portable JSON even when the Windows console uses a legacy code page."""
    typer.echo(json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=True))


ConfigDir = Annotated[
    Path,
    typer.Option(
        "--config-dir",
        help="Directory containing Project Echoes YAML configuration.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]
SourceManifestPath = Annotated[
    Path,
    typer.Option(
        "--manifest-path",
        help="Source-manifest YAML file or directory.",
        file_okay=True,
        dir_okay=True,
        resolve_path=True,
    ),
]
DataRoot = Annotated[
    Path,
    typer.Option(
        "--data-root",
        help="Project data root containing Git-ignored raw and processed directories.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]


def _counts(values: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in values.items())


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row, strict=True)]
    rendered = ["  ".join(value.ljust(width) for value, width in zip(headers, widths, strict=True))]
    rendered.append("  ".join("-" * width for width in widths))
    rendered.extend(
        "  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True))
        for row in rows
    )
    return "\n".join(rendered)


def _load_segmentation_config(config_dir: Path) -> SegmentationConfig:
    loaded = load_config(config_dir / "segmentation.yaml")
    if not isinstance(loaded, SegmentationConfig):  # pragma: no cover - schema registry guard
        raise ConfigLoadError("segmentation.yaml did not load as SegmentationConfig")
    return loaded


def _passage_exclusions(database: Path, passage_id: str) -> list[dict[str, object]]:
    """Return explicit exclusions related to one passage without JSON SQL assumptions."""

    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            cursor = connection.execute(
                "SELECT exclusion_id, token_id, locus_id, source_reference, reason_code, "
                "resolution_status, related_passage_ids_json, notes "
                "FROM segmentation_exclusions ORDER BY stream_position_in_corpus, exclusion_id"
            )
            rows = cursor.fetchall()
            columns = [str(description[0]) for description in cursor.description]
    except (duckdb.Error, OSError) as exc:
        raise PassageStorageError(
            f"could not read exclusions for passage {passage_id}: {exc}"
        ) from exc

    related: list[dict[str, object]] = []
    for row in rows:
        values = dict(zip(columns, row, strict=True))
        try:
            passage_ids = json.loads(cast(str, values["related_passage_ids_json"]))
        except (json.JSONDecodeError, TypeError) as exc:
            raise PassageStorageError(
                "segmentation exclusion contains invalid passage IDs"
            ) from exc
        if passage_id in passage_ids:
            values.pop("related_passage_ids_json")
            related.append(values)
    return related


def _passage_selection(
    *,
    all_streams: bool,
    corpus: str | None,
    profile: str | None,
    reading: str | None,
    granularity: str | None,
    book: str | None,
) -> SegmentationSelection:
    try:
        selection = SegmentationSelection.model_validate(
            {
                "all_streams": all_streams,
                "corpus": corpus,
                "analysis_profile": profile,
                "analysis_reading": reading,
                "granularity": granularity,
                "book": book,
            }
        )
        selection.selected_streams()
    except ValidationError as exc:
        raise PassagePipelineError(str(exc)) from exc
    return selection


@app.command()
def version() -> None:
    """Print the installed Project Echoes version."""
    typer.echo(__version__)


@app.command("validate-config")
def validate_config_command(config_dir: ConfigDir = Path("config")) -> None:
    """Validate every registered YAML configuration file."""
    try:
        validated = validate_config_directory(config_dir)
    except ConfigLoadError as exc:
        typer.echo(f"Configuration validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Validated {len(validated)} configuration files in {config_dir}.")


@app.command("validate-sources")
def validate_sources_command(
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    data_root: DataRoot = Path("data"),
    audit_canonical_hashes: Annotated[
        bool,
        typer.Option(
            "--audit-canonical-hashes",
            help="Explicitly request the canonical-hash audit that is always enforced.",
        ),
    ] = False,
) -> None:
    """Validate source records, governance state, and locally present canonical hashes."""
    try:
        catalog = load_source_catalog(manifest_path)
    except SourceManifestError as exc:
        typer.echo(f"Source manifest validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    summary = summarize_sources(catalog)
    typer.echo(f"Validated {summary.total} source records from {manifest_path}.")
    typer.echo(f"Roles: {_counts(summary.by_role)}")
    typer.echo(f"Statuses: {_counts(summary.by_status)}")
    typer.echo(f"Redistribution: {_counts(summary.by_redistribution)}")
    typer.echo(
        "Licensing: "
        f"complete={summary.licensing_complete}, incomplete={summary.licensing_incomplete}"
    )
    if audit_canonical_hashes:
        typer.echo("Explicit canonical-hash audit requested.")
    audited = 0
    hash_findings: list[str] = []
    for source in catalog.sources:
        findings = audit_manifest_hashes(source, data_root=data_root)
        if findings is None:
            continue
        audited += 1
        hash_findings.extend(findings)
    typer.echo(f"Canonical-hash audit: {audited} locally present source(s) recomputed.")
    if hash_findings:
        for finding in hash_findings:
            typer.echo(f"Canonical-hash mismatch: {finding}", err=True)
        raise typer.Exit(code=1)


@app.command("list-sources")
def list_sources_command(
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    role: Annotated[
        SourceRole | None,
        typer.Option("--role", help="Show only sources with this research role."),
    ] = None,
    status: Annotated[
        SourceStatus | None,
        typer.Option("--status", help="Show only sources with this lifecycle status."),
    ] = None,
) -> None:
    """List source-governance records with optional role and status filters."""
    try:
        catalog = load_source_catalog(manifest_path)
    except SourceManifestError as exc:
        typer.echo(f"Could not list sources: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    sources = [
        source
        for source in catalog.sources
        if (role is None or source.role is role) and (status is None or source.status is status)
    ]
    rows = [
        (
            source.source_id,
            source.source_name,
            source.corpus,
            source.role.value,
            source.status.value,
            source.license_review_status.value,
            source.redistribution_status.value,
        )
        for source in sorted(sources, key=lambda item: item.source_id)
    ]
    headers = (
        "SOURCE ID",
        "NAME",
        "CORPUS",
        "ROLE",
        "STATUS",
        "LICENSE REVIEW",
        "REDISTRIBUTION",
    )
    typer.echo(_table(headers, rows))
    typer.echo(f"{len(rows)} source(s).")


@app.command("show-source")
def show_source_command(
    source_id: Annotated[str, typer.Argument(help="Stable source identifier.")],
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
) -> None:
    """Display the complete normalized manifest for one source."""
    try:
        catalog = load_source_catalog(manifest_path)
    except SourceManifestError as exc:
        typer.echo(f"Could not show source: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    source = catalog.find(source_id)
    if source is None:
        typer.echo(f"Source not found: {source_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(serialize_source(source), nl=False)


@app.command("acquire-source")
def acquire_source_command(
    source_id: Annotated[str, typer.Argument(help="Approved source identifier.")],
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    data_root: DataRoot = Path("data"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Explicitly replace an existing acquisition after validation.",
        ),
    ] = False,
) -> None:
    """Acquire only manifest-declared files after the source-approval gate passes."""
    try:
        source = load_source_catalog(manifest_path).find(source_id)
        if source is None:
            raise AcquisitionError(f"source not found: {source_id}")
        directory, receipt = acquire_source(
            source,
            data_root=data_root,
            force=force,
            command=f"echoes acquire-source {source_id}",
        )
    except (SourceManifestError, AcquisitionError) as exc:
        typer.echo(f"Source acquisition failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Acquired {source_id} {receipt.version_label} at {directory} "
        f"({len(receipt.files)} verified files)."
    )


@app.command("verify-acquisition")
def verify_acquisition_command(
    source_id: Annotated[str, typer.Argument(help="Approved source identifier.")],
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    data_root: DataRoot = Path("data"),
) -> None:
    """Verify local acquisition files and hashes without network access."""
    try:
        source = load_source_catalog(manifest_path).find(source_id)
        if source is None:
            raise AcquisitionError(f"source not found: {source_id}")
        directory, receipt = verify_acquisition(source, data_root=data_root)
    except (SourceManifestError, AcquisitionError) as exc:
        typer.echo(f"Acquisition verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Verified {source_id} {receipt.version_label} at {directory}: "
        f"{len(receipt.files)} files match their SHA-256 receipts."
    )


@app.command("ingest-hebrew")
def ingest_hebrew_command(
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Optional versioned processed output directory."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option("--database", help="Optional local DuckDB database path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Explicitly replace this source version's processed outputs."),
    ] = False,
) -> None:
    """Ingest the verified MACULA Hebrew acquisition and run the full corpus gate."""
    try:
        result = ingest_hebrew_corpus(
            manifest_path=manifest_path,
            config_dir=config_dir,
            data_root=data_root,
            output_dir=output_dir,
            database_path=database,
            force=force,
        )
    except (
        AcquisitionError,
        ConfigLoadError,
        CorpusStorageError,
        CorpusValidationError,
        HebrewIngestionError,
        HebrewPipelineError,
        SourceManifestError,
        OSError,
    ) as exc:
        typer.echo(f"Hebrew ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Ingested {result.summary.total_tokens} tokens from "
        f"{result.adapter_summary.source_records} source records."
    )
    typer.echo(f"Processed output: {result.processed.output_dir}")
    typer.echo(
        f"Validation: errors={result.validation.error_count}, "
        f"warnings={result.validation.warning_count}"
    )
    if not result.validation.passed:
        raise typer.Exit(code=1)


@app.command("ingest-greek")
def ingest_greek_command(
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Optional versioned processed output directory."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option("--database", help="Optional local DuckDB database path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Explicitly replace this source version's processed outputs."),
    ] = False,
) -> None:
    """Ingest the verified MACULA Greek acquisition and run the full corpus gate."""
    try:
        result = ingest_greek_corpus(
            manifest_path=manifest_path,
            config_dir=config_dir,
            data_root=data_root,
            output_dir=output_dir,
            database_path=database,
            force=force,
        )
    except (
        AcquisitionError,
        ConfigLoadError,
        CorpusStorageError,
        CorpusValidationError,
        GreekIngestionError,
        GreekPipelineError,
        SourceManifestError,
        OSError,
    ) as exc:
        typer.echo(f"Greek ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Ingested {result.summary.total_tokens} tokens from "
        f"{result.adapter_summary.source_records} source records."
    )
    typer.echo(f"Processed output: {result.processed.output_dir}")
    typer.echo(
        f"Validation: errors={result.validation.error_count}, "
        f"warnings={result.validation.warning_count}"
    )
    if not result.validation.passed:
        raise typer.Exit(code=1)


@app.command("ingest-oshb-kq")
def ingest_oshb_kq_command(
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Optional versioned processed output directory."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option("--database", help="Optional local DuckDB database path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Explicitly replace this supplement's processed outputs."),
    ] = False,
) -> None:
    """Build the OSHB Ketiv/Qere supplement beside the untouched primary tables."""
    try:
        result = ingest_kq_supplement(
            manifest_path=manifest_path,
            config_dir=config_dir,
            data_root=data_root,
            output_dir=output_dir,
            database_path=database,
            force=force,
        )
    except (
        AcquisitionError,
        ConfigLoadError,
        CorpusStorageError,
        KQPipelineError,
        SourceManifestError,
        OSError,
    ) as exc:
        typer.echo(f"K/Q supplement ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    summary = result.summary
    typer.echo(
        f"Built {summary.loci} K/Q loci: paired={summary.paired_loci}, "
        f"ketiv_only={summary.ketiv_only_loci}, qere_only={summary.qere_only_loci}, "
        f"ketiv tokens={summary.ketiv_tokens}, conflicts={summary.conflicts}."
    )
    typer.echo(
        f"Surface agreement: exact={summary.exact_surface_matches}, "
        f"consonantal={summary.consonantal_surface_matches}, "
        f"mismatch={summary.surface_mismatches}."
    )
    typer.echo(f"Processed output: {result.processed.output_dir}")
    typer.echo(
        f"Validation: errors={result.validation.error_count}, "
        f"warnings={result.validation.warning_count}"
    )
    if not result.validation.passed:
        raise typer.Exit(code=1)


@app.command("validate-corpus")
def validate_corpus_command(
    corpus: Annotated[
        str,
        typer.Option("--corpus", help="Corpus identifier: hebrew, greek, or unified."),
    ] = "hebrew",
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Optional processed corpus directory."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option("--database", help="Optional local DuckDB database path."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the structured validation report as JSON."),
    ] = False,
) -> None:
    """Validate an existing processed corpus without acquiring or rewriting data."""
    if corpus not in {"hebrew", "greek", "unified"}:
        typer.echo(f"Unsupported corpus: {corpus}", err=True)
        raise typer.Exit(code=1)
    reports = []
    try:
        if corpus in {"hebrew", "unified"}:
            reports.append(
                validate_existing_hebrew_corpus(
                    manifest_path=manifest_path,
                    config_dir=config_dir,
                    data_root=data_root,
                    output_dir=output_dir if corpus == "hebrew" else None,
                    database_path=database,
                )
            )
        if corpus in {"greek", "unified"}:
            reports.append(
                validate_existing_greek_corpus(
                    manifest_path=manifest_path,
                    config_dir=config_dir,
                    data_root=data_root,
                    output_dir=output_dir if corpus == "greek" else None,
                    database_path=database,
                )
            )
    except (
        ConfigLoadError,
        CorpusValidationError,
        GreekPipelineError,
        HebrewPipelineError,
        SourceManifestError,
    ) as exc:
        typer.echo(f"Corpus validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    failed = False
    for report in reports:
        if json_output:
            _echo_json(report)
        else:
            typer.echo(
                f"Validated {report.corpus} corpus: tokens={report.total_tokens}, "
                f"books={report.book_count}, chapters={report.chapter_count}, "
                f"verses={report.verse_count}."
            )
            typer.echo(f"Findings: errors={report.error_count}, warnings={report.warning_count}.")
        failed = failed or not report.passed
    if failed:
        raise typer.Exit(code=1)


@app.command("corpus-summary")
def corpus_summary_command(
    corpus: Annotated[
        str,
        typer.Option("--corpus", help="Corpus identifier: hebrew or greek."),
    ] = "hebrew",
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path.", resolve_path=True),
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the summary as JSON."),
    ] = False,
) -> None:
    """Report corpus coverage, language, annotation, and issue counts."""
    if corpus == "greek":
        try:
            greek_summary = greek_corpus_summary(database)
        except CorpusStorageError as exc:
            typer.echo(f"Corpus summary failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if json_output:
            _echo_json(greek_summary)
            return
        typer.echo(
            f"Greek corpus {greek_summary.source_version}: {greek_summary.total_tokens} tokens, "
            f"{greek_summary.total_books} books."
        )
        typer.echo(
            "Missing annotations: "
            f"lemma={greek_summary.missing_lemma_count}, "
            f"morphology={greek_summary.missing_morphology_count}, "
            f"syntax={greek_summary.missing_syntax_count}, "
            f"gloss={greek_summary.missing_gloss_count}, "
            f"semantic_domain={greek_summary.missing_semantic_domain_count}."
        )
        typer.echo(
            f"Elided={greek_summary.elided_count}, "
            f"punctuation-bearing={greek_summary.punctuation_bearing_count}, "
            f"issues={greek_summary.validation_issue_count}."
        )
        return
    if corpus != "hebrew":
        typer.echo(f"Unsupported corpus: {corpus}", err=True)
        raise typer.Exit(code=1)
    try:
        summary = corpus_summary(database)
    except CorpusStorageError as exc:
        typer.echo(f"Corpus summary failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(summary)
        return
    typer.echo(
        f"Hebrew corpus {summary.source_version}: {summary.total_tokens} tokens, "
        f"{summary.total_books} books."
    )
    typer.echo(f"Languages: hebrew={summary.hebrew_tokens}, aramaic={summary.aramaic_tokens}.")
    typer.echo(
        "Missing annotations: "
        f"lemma={summary.missing_lemma_count}, "
        f"morphology={summary.missing_morphology_count}, "
        f"syntax={summary.missing_syntax_count}."
    )
    typer.echo(
        f"Variants={summary.variant_count}, ketiv/qere={summary.ketiv_qere_count}, "
        f"punctuation={summary.punctuation_count}, issues={summary.validation_issue_count}."
    )


@app.command("segment-passages")
def segment_passages_command(
    all_streams: Annotated[
        bool,
        typer.Option("--all", help="Generate every governed corpus/profile/reading stream."),
    ] = False,
    corpus: Annotated[
        str | None,
        typer.Option("--corpus", help="Exact corpus selector: hebrew or greek."),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Exact profile selector."),
    ] = None,
    reading: Annotated[
        str | None,
        typer.Option("--reading", help="Exact reading selector: qere, ketiv, or source."),
    ] = None,
    granularity: Annotated[
        str | None,
        typer.Option("--granularity", help="Optionally generate one governed granularity."),
    ] = None,
    book: Annotated[
        str | None,
        typer.Option("--book", help="Optionally generate one canonical three-character book."),
    ] = None,
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Generated schema-v1 passage output directory."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace only the selected generated passage artifacts."),
    ] = False,
) -> None:
    """Generate deterministic passage artifacts after all immutable-input gates."""

    try:
        selection = _passage_selection(
            all_streams=all_streams,
            corpus=corpus,
            profile=profile,
            reading=reading,
            granularity=granularity,
            book=book,
        )
        config = _load_segmentation_config(config_dir)
        result = segment_passages(
            config=config,
            selection=selection,
            manifest_path=manifest_path,
            data_root=data_root,
            output_dir=output_dir,
            database_path=database,
            force=force,
        )
    except (
        ConfigLoadError,
        PassageGenerationError,
        PassagePipelineError,
        PassageStorageError,
        SegmentationInputError,
        SourceManifestError,
        OSError,
    ) as exc:
        typer.echo(f"Passage generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Generated passage run {result.context.run_id}.")
    typer.echo(f"Artifacts: {result.output_dir}")
    typer.echo(f"DuckDB: {result.database_path}")
    typer.echo(f"Rows: {_counts(result.table_counts)}")
    typer.echo(
        f"Runtime: {result.runtime_seconds:.3f}s; output size: {result.output_size_bytes} bytes."
    )


@app.command("validate-passages")
def validate_passages_command(
    all_passages: Annotated[
        bool,
        typer.Option("--all", help="Validate all generated passage artifacts and input anchors."),
    ] = False,
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    config_dir: ConfigDir = Path("config"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Generated schema-v1 passage output directory."),
    ] = None,
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = Path("data/processed/project_echoes.duckdb"),
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat validation warnings as failures."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the complete structured validation report."),
    ] = False,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Optionally write the structured validation report."),
    ] = None,
) -> None:
    """Validate complete persisted passage artifacts and immutable corpus anchors."""

    if not all_passages:
        typer.echo("Passage validation failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        config = _load_segmentation_config(config_dir)
        inputs = load_segmentation_inputs(manifest_path=manifest_path, data_root=data_root)
        resolved_output = output_dir or default_passage_output(config)
        validation = validate_passage_artifacts(
            resolved_output,
            database_path=database,
            config=config,
            inputs=inputs,
            strict=strict,
        )
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(validation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (
        ConfigLoadError,
        PassagePipelineError,
        PassageStorageError,
        SegmentationInputError,
        SourceManifestError,
        OSError,
    ) as exc:
        typer.echo(f"Passage validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(validation)
    else:
        typer.echo(
            f"Validated passage run {validation.segmentation_run_id or 'unknown'}: "
            f"errors={validation.error_count}, warnings={validation.warning_count}, "
            f"informational={validation.informational_count}."
        )
        typer.echo(f"Rows: {_counts(validation.table_counts)}")
        for issue in validation.issues:
            if issue.severity != "informational":
                location = f" [{issue.table}]" if issue.table else ""
                typer.echo(
                    f"{issue.severity.upper()} {issue.code}{location}: {issue.message}",
                    err=issue.severity == "error",
                )
    if not validation.passed:
        raise typer.Exit(code=validation.exit_code)


@app.command("passage-summary")
def passage_summary_command(
    all_streams: Annotated[
        bool,
        typer.Option("--all", help="Summarize every generated passage stream."),
    ] = False,
    corpus: Annotated[str | None, typer.Option("--corpus", help="Exact corpus selector.")] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Exact analysis-profile selector.")
    ] = None,
    reading: Annotated[
        str | None, typer.Option("--reading", help="Exact analysis-reading selector.")
    ] = None,
    granularity: Annotated[
        str | None, typer.Option("--granularity", help="Optional granularity filter.")
    ] = None,
    book: Annotated[
        str | None, typer.Option("--book", help="Optional canonical book filter.")
    ] = None,
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the passage summary as JSON."),
    ] = False,
) -> None:
    """Summarize generated passages by stream and granularity."""

    try:
        selection = _passage_selection(
            all_streams=all_streams,
            corpus=corpus,
            profile=profile,
            reading=reading,
            granularity=granularity,
            book=book,
        )
        clauses: list[str] = []
        parameters: list[str] = []
        if not selection.all_streams:
            for column, value in (
                ("corpus", selection.corpus),
                ("analysis_profile", selection.analysis_profile),
                ("analysis_reading", selection.analysis_reading),
                ("granularity", selection.granularity),
                ("book", selection.book),
            ):
                if value is not None:
                    clauses.append(f"{column} = ?")
                    parameters.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with duckdb.connect(str(database), read_only=True) as connection:
            rows = connection.execute(
                "SELECT corpus, analysis_profile, analysis_reading, granularity, "
                "count(*) AS passage_count, sum(token_count) AS membership_count, "
                "count(*) FILTER (WHERE disputed_passage_flag) AS disputed_count, "
                "count(*) FILTER (WHERE reference_gap) AS reference_gap_count, "
                "count(*) FILTER (WHERE ketiv_structural_uncertainty) AS uncertainty_count "
                f"FROM passages{where} GROUP BY ALL ORDER BY 1, 2, 3, 4",
                parameters,
            ).fetchall()
    except (PassagePipelineError, duckdb.Error, OSError) as exc:
        typer.echo(f"Passage summary failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not rows:
        typer.echo("Passage summary failed: no passages match the selection.", err=True)
        raise typer.Exit(code=1)
    headers = (
        "CORPUS",
        "PROFILE",
        "READING",
        "GRANULARITY",
        "PASSAGES",
        "MEMBERSHIPS",
        "DISPUTED",
        "GAPS",
        "KETIV UNCERTAIN",
    )
    rendered = [[str(value) for value in row] for row in rows]
    if json_output:
        json_fields = (
            "corpus",
            "analysis_profile",
            "analysis_reading",
            "granularity",
            "passage_count",
            "membership_count",
            "disputed_count",
            "reference_gap_count",
            "ketiv_uncertainty_count",
        )
        typer.echo(
            json.dumps(
                [dict(zip(json_fields, row, strict=True)) for row in rows],
                indent=2,
                ensure_ascii=True,
            )
        )
    else:
        typer.echo(_table(headers, rendered))
        typer.echo(f"{len(rows)} stream/granularity row(s).")


@app.command("show-passage")
def show_passage_command(
    passage_id: Annotated[str, typer.Argument(help="Stable passage identifier.")],
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit complete passage metadata as JSON."),
    ] = False,
) -> None:
    """Display passage metadata, reconstruction, uncertainty, and exclusions."""

    try:
        passage = read_passage(database, passage_id)
        if passage is None:
            typer.echo(f"Passage not found: {passage_id}", err=True)
            raise typer.Exit(code=1)
        exclusions = _passage_exclusions(database, passage_id)
    except PassageStorageError as exc:
        typer.echo(f"Could not show passage: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        payload = passage.model_dump(mode="json")
        payload["exclusions"] = exclusions
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))
        return
    constituent_ids = json.loads(passage.constituent_verse_passage_ids_json)
    typer.echo(f"Passage: {passage.passage_id}")
    typer.echo(
        f"Stream: {passage.corpus}/{passage.analysis_profile}/{passage.analysis_reading}/"
        f"{passage.granularity}"
    )
    typer.echo(f"References: {passage.start_reference} through {passage.end_reference}")
    typer.echo(f"Tokens: {passage.token_count}")
    typer.echo(f"Surface: {passage.surface_text}")
    typer.echo(f"Normalized: {passage.normalized_text}")
    if passage.unpointed_text is not None:
        typer.echo(f"Unpointed: {passage.unpointed_text}")
    if passage.folded_text is not None:
        typer.echo(f"Folded: {passage.folded_text}")
    typer.echo(f"Disputed: {passage.disputed_passage_flag}")
    typer.echo(f"Reference gap: {passage.reference_gap}")
    typer.echo(f"Ketiv structural uncertainty: {passage.ketiv_structural_uncertainty}")
    typer.echo(f"Constituent verse IDs: {json.dumps(constituent_ids, ensure_ascii=True)}")
    typer.echo(f"Explicit exclusions: {len(exclusions)}")
    for exclusion in exclusions:
        typer.echo(
            f"- {exclusion['reason_code']} at {exclusion['source_reference']} "
            f"(token {exclusion['token_id']}, {exclusion['resolution_status']})"
        )


@app.command("reconstruct-passage")
def reconstruct_passage_command(
    passage_id: Annotated[str, typer.Argument(help="Stable passage identifier.")],
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit all stored reconstruction forms as JSON."),
    ] = False,
) -> None:
    """Display the deterministic language-aware reconstruction for one passage."""

    try:
        passage = read_passage(database, passage_id)
    except PassageStorageError as exc:
        typer.echo(f"Could not reconstruct passage: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if passage is None:
        typer.echo(f"Passage not found: {passage_id}", err=True)
        raise typer.Exit(code=1)
    forms = {
        "passage_id": passage.passage_id,
        "surface_text": passage.surface_text,
        "normalized_text": passage.normalized_text,
        "unpointed_text": passage.unpointed_text,
        "folded_text": passage.folded_text,
    }
    if json_output:
        typer.echo(json.dumps(forms, indent=2, ensure_ascii=True))
        return
    typer.echo(f"Passage: {passage.passage_id}")
    typer.echo(f"Surface: {passage.surface_text}")
    typer.echo(f"Normalized: {passage.normalized_text}")
    if passage.unpointed_text is not None:
        typer.echo(f"Unpointed: {passage.unpointed_text}")
    if passage.folded_text is not None:
        typer.echo(f"Folded: {passage.folded_text}")


@app.command("passage-membership")
def passage_membership_command(
    passage_id: Annotated[str, typer.Argument(help="Stable passage identifier.")],
    database: Annotated[
        Path,
        typer.Option("--database", help="Local DuckDB database path."),
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit exact ordered membership as JSON."),
    ] = False,
) -> None:
    """Display authoritative ordered token membership for one passage."""

    try:
        members = read_passage_membership(database, passage_id)
    except PassageStorageError as exc:
        typer.echo(f"Could not read passage membership: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not members:
        typer.echo(f"Passage not found: {passage_id}", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(
            json.dumps(
                [member.model_dump(mode="json") for member in members],
                indent=2,
                ensure_ascii=True,
            )
        )
        return
    headers = (
        "POSITION",
        "TOKEN ID",
        "REFERENCE",
        "SOURCE POS",
        "STREAM POS",
        "BASIS",
        "RESOLUTION",
    )
    rows = [
        (
            str(member.position_in_passage),
            member.token_id,
            member.source_reference,
            str(member.source_position_in_corpus),
            str(member.stream_position_in_corpus),
            member.membership_basis,
            member.structural_resolution_status,
        )
        for member in members
    ]
    typer.echo(_table(headers, rows))
    typer.echo(f"{len(rows)} token(s).")


@app.command("create-run-manifest")
def create_run_manifest(
    experiment_name: Annotated[
        str,
        typer.Option("--experiment-name", help="Human-readable experiment name."),
    ] = "milestone-0-foundation",
    config_dir: ConfigDir = Path("config"),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional output path for the JSON manifest."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow replacement of an explicitly selected path."),
    ] = False,
) -> None:
    """Generate an empty, provenance-bearing experiment run manifest."""
    project_root = Path.cwd()
    try:
        manifest = build_run_manifest(
            experiment_name,
            project_root=project_root,
            config_dir=config_dir,
        )
        output_path = output
        if output_path is None:
            output_path = (
                RuntimeSettings.from_environment().output_dir
                / "experiments"
                / manifest.run_id
                / "run-manifest.json"
            )
        write_run_manifest(manifest, output_path, overwrite=force)
    except (ConfigLoadError, FileExistsError, OSError, TypeError) as exc:
        typer.echo(f"Run manifest generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Created run manifest: {output_path}")


if __name__ == "__main__":  # pragma: no cover
    app()
