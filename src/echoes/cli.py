"""Command-line interface for Project Echoes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from echoes import __version__
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
) -> None:
    """Validate source records and report governance-state counts."""
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
