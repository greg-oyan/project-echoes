"""Command-line interface for Project Echoes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from echoes import __version__
from echoes.acquire import (
    AcquisitionError,
    acquire_source,
    audit_manifest_hashes,
    verify_acquisition,
)
from echoes.corpus.hebrew import (
    HebrewPipelineError,
    ingest_hebrew_corpus,
    validate_existing_hebrew_corpus,
)
from echoes.corpus.storage import CorpusStorageError, corpus_summary
from echoes.corpus.validation import CorpusValidationError
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
from echoes.settings import ConfigLoadError, RuntimeSettings, validate_config_directory

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


@app.command("validate-corpus")
def validate_corpus_command(
    corpus: Annotated[str, typer.Option("--corpus", help="Corpus identifier.")] = "hebrew",
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
    if corpus != "hebrew":
        typer.echo(f"Unsupported corpus: {corpus}", err=True)
        raise typer.Exit(code=1)
    try:
        report = validate_existing_hebrew_corpus(
            manifest_path=manifest_path,
            config_dir=config_dir,
            data_root=data_root,
            output_dir=output_dir,
            database_path=database,
        )
    except (
        ConfigLoadError,
        CorpusValidationError,
        HebrewPipelineError,
        SourceManifestError,
    ) as exc:
        typer.echo(f"Corpus validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(report)
    else:
        typer.echo(
            f"Validated Hebrew corpus: tokens={report.total_tokens}, "
            f"books={report.book_count}, chapters={report.chapter_count}, "
            f"verses={report.verse_count}."
        )
        typer.echo(f"Findings: errors={report.error_count}, warnings={report.warning_count}.")
    if not report.passed:
        raise typer.Exit(code=1)


@app.command("corpus-summary")
def corpus_summary_command(
    corpus: Annotated[str, typer.Option("--corpus", help="Corpus identifier.")] = "hebrew",
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
