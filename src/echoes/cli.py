# ruff: noqa: E402
"""Command-line interface for Project Echoes."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, cast

from echoes.lexical.resources import initialize_thread_controls

# Establish deterministic numeric defaults before DuckDB/Polars/Numpy can
# initialize worker pools through any of the project imports below.
initialize_thread_controls(1)

import duckdb
import polars as pl
import typer
from pydantic import BaseModel, ValidationError

from echoes import __version__
from echoes.acquire import (
    AcquisitionError,
    acquire_source,
    audit_manifest_hashes,
    verify_acquisition,
)
from echoes.benchmarks.pipeline import BenchmarkBuildError, build_benchmark
from echoes.benchmarks.positive_controls import (
    PositiveControlError,
    validate_positive_controls,
)
from echoes.benchmarks.storage import BenchmarkStorageError, table_row_counts
from echoes.benchmarks.tier1 import Tier1ValidationError, validate_tier1_quotations
from echoes.benchmarks.validation import (
    BenchmarkValidationError,
    BenchmarkValidationReport,
    validate_benchmark_artifacts,
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
from echoes.lexical.audit import LexicalAuditError, generate_lexical_feature_audit
from echoes.lexical.config import (
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    validate_preregistration_against_config,
)
from echoes.lexical.models import LEXICAL_ARTIFACT_COLUMNS, LexicalArtifactName
from echoes.lexical.pipeline import (
    DEFAULT_LEXICAL_ROOT,
    LexicalPipelineError,
    LexicalPipelineResult,
    run_lexical_pipeline,
)
from echoes.lexical.storage import (
    LexicalStorageError,
    processed_from_directory,
    read_artifact_frame,
    read_current_lexical_promotion_witness,
    read_hash_manifest,
    recover_interrupted_lexical_promotion,
)
from echoes.lexical.validation import (
    LexicalValidationError,
    LexicalValidationReport,
    compare_lexical_ablation,
    lexical_summary,
    show_lexical_candidate,
    show_lexical_evidence,
    validate_lexical_artifacts,
)
from echoes.manifest import (
    build_run_manifest,
    finalize_recovered_execution_success,
    format_reproduction_command,
    load_execution_manifest,
    reproduction_command_path_mismatches,
    reproduction_environment_mismatches,
    resolve_execution_manifest,
    sha256_file,
    validate_execution_manifest_outputs,
    write_run_manifest,
)
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
    rebind_passage_duckdb_views,
    verify_passage_view_rebind_receipt,
)
from echoes.segment.streams import SegmentationInputError, load_segmentation_inputs
from echoes.segment.validation import validate_passage_artifacts
from echoes.settings import (
    BenchmarkConfig,
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

DEFAULT_EXECUTION_MANIFEST_ROOT = Path("data/processed/lexical/execution-manifests")


def _echo_json(value: BaseModel | Mapping[str, object]) -> None:
    """Emit portable JSON even when the Windows console uses a legacy code page."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


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


def _load_benchmark_config(config_path: Path) -> BenchmarkConfig:
    loaded = load_config(config_path)
    if not isinstance(loaded, BenchmarkConfig):  # pragma: no cover - schema registry guard
        raise ConfigLoadError(f"{config_path} did not load as BenchmarkConfig")
    return loaded


def _query_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: Sequence[object] = (),
) -> list[dict[str, object]]:
    cursor = connection.execute(sql, list(parameters))
    columns = [str(description[0]) for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _benchmark_summary_payload(database: Path) -> dict[str, object]:
    counts = table_row_counts(database)
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            metadata_rows = _query_dicts(
                connection,
                "SELECT benchmark_run_id, benchmark_version, relationship_count, "
                "endpoint_count, mapping_count FROM benchmark_metadata",
            )
            if len(metadata_rows) != 1:
                raise BenchmarkStorageError("benchmark_metadata must contain exactly one row")
            tiers = _query_dicts(
                connection,
                "SELECT tier, source_id, count(*) AS relationship_count "
                "FROM benchmark_relationships GROUP BY tier, source_id ORDER BY tier, source_id",
            )
            mappings = _query_dicts(
                connection,
                "SELECT target_analysis_profile, mapping_status, count(*) AS mapping_count "
                "FROM benchmark_endpoint_mappings GROUP BY target_analysis_profile, "
                "mapping_status ORDER BY target_analysis_profile, mapping_status",
            )
            splits = _query_dicts(
                connection,
                "SELECT split_strategy, partition, count(*) AS assignment_count "
                "FROM benchmark_split_assignments GROUP BY split_strategy, partition "
                "ORDER BY split_strategy, partition",
            )
            negatives = _query_dicts(
                connection,
                "SELECT negative_strategy, count(*) AS presumed_negative_count "
                "FROM benchmark_presumed_negatives GROUP BY negative_strategy "
                "ORDER BY negative_strategy",
            )
    except (duckdb.Error, OSError) as exc:
        raise BenchmarkStorageError(f"could not summarize benchmark tables: {exc}") from exc
    return {
        "metadata": metadata_rows[0],
        "table_counts": counts,
        "relationships_by_tier_and_source": tiers,
        "mappings_by_profile_and_status": mappings,
        "splits_by_strategy_and_partition": splits,
        "presumed_negatives_by_strategy": negatives,
    }


def _relationship_details(database: Path, relationship_id: str) -> dict[str, object] | None:
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            relationships = _query_dicts(
                connection,
                "SELECT * FROM benchmark_relationships WHERE relationship_id = ?",
                [relationship_id],
            )
            if not relationships:
                return None
            source_records = _query_dicts(
                connection,
                "SELECT l.link_role, s.* FROM benchmark_relationship_source_records l "
                "JOIN benchmark_source_records s USING (source_record_id) "
                "WHERE l.relationship_id = ? ORDER BY s.source_file, s.source_line_number",
                [relationship_id],
            )
            endpoints = _query_dicts(
                connection,
                "SELECT * FROM benchmark_endpoints WHERE relationship_id = ? "
                "ORDER BY endpoint_side",
                [relationship_id],
            )
            mappings = _query_dicts(
                connection,
                "SELECT m.* FROM benchmark_endpoint_mappings m "
                "JOIN benchmark_endpoints e USING (endpoint_id) "
                "WHERE e.relationship_id = ? "
                "ORDER BY e.endpoint_side, m.target_analysis_profile",
                [relationship_id],
            )
            leakage = _query_dicts(
                connection,
                "SELECT * FROM benchmark_leakage_groups WHERE relationship_id = ? "
                "ORDER BY group_type, leakage_group_id",
                [relationship_id],
            )
            splits = _query_dicts(
                connection,
                "SELECT * FROM benchmark_split_assignments WHERE relationship_id = ? "
                "ORDER BY split_strategy",
                [relationship_id],
            )
            negatives = _query_dicts(
                connection,
                "SELECT DISTINCT n.* FROM benchmark_presumed_negatives n "
                "JOIN benchmark_mapping_target_passages t "
                "ON t.target_passage_id IN (n.passage_a_id, n.passage_b_id) "
                "JOIN benchmark_endpoint_mappings m ON m.mapping_id = t.mapping_id "
                "JOIN benchmark_endpoints e ON e.endpoint_id = m.endpoint_id "
                "WHERE e.relationship_id = ? ORDER BY n.negative_strategy, n.contrastive_id",
                [relationship_id],
            )
    except (duckdb.Error, OSError) as exc:
        raise BenchmarkStorageError(
            f"could not read benchmark relationship {relationship_id}: {exc}"
        ) from exc
    return {
        "relationship": relationships[0],
        "source_records": source_records,
        "endpoints": endpoints,
        "endpoint_mappings": mappings,
        "leakage_groups": leakage,
        "split_assignments": splits,
        "related_presumed_negatives": negatives,
    }


def _mapping_details(database: Path, relationship_id: str) -> dict[str, object] | None:
    details = _relationship_details(database, relationship_id)
    if details is None:
        return None
    relationship = cast(dict[str, object], details["relationship"])
    return {
        "relationship_id": relationship_id,
        "source_reference_a": relationship["source_reference_a"],
        "source_reference_b": relationship["source_reference_b"],
        "endpoints": details["endpoints"],
        "endpoint_mappings": details["endpoint_mappings"],
    }


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


@app.command("rebind-passage-views")
def rebind_passage_views_command(
    database: Annotated[
        Path,
        typer.Option("--database", help="Transferred DuckDB database path."),
    ],
    passage_root: Annotated[
        Path,
        typer.Option(
            "--passage-root",
            help="Transferred schema-v1 passage Parquet root.",
        ),
    ],
    expected_database_sha256: Annotated[
        str,
        typer.Option(
            "--expected-database-sha256",
            help="SHA-256 verified for the transferred database before mutation.",
        ),
    ],
    receipt_path: Annotated[
        Path,
        typer.Option("--receipt", help="New atomic rebind receipt path."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the complete rebind receipt as JSON."),
    ] = False,
) -> None:
    """Rebind transferred passage views after checking the original DB hash."""

    if receipt_path.exists():
        typer.echo(
            f"Passage view rebind failed: refusing to overwrite rebind receipt: {receipt_path}",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        receipt = rebind_passage_duckdb_views(
            database,
            passage_root,
            expected_database_sha256=expected_database_sha256,
            receipt_path=receipt_path,
        )
    except (PassageStorageError, OSError) as exc:
        typer.echo(f"Passage view rebind failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(receipt)
    else:
        typer.echo(f"Rebound {len(receipt.view_globs)} passage views.")
        typer.echo(f"DuckDB: {receipt.database_path}")
        typer.echo(f"Passage root: {receipt.passage_root}")
        typer.echo(f"Receipt: {receipt_path}")
        typer.echo(f"Post-rebind SHA-256: {receipt.after_database_sha256}")


@app.command("verify-passage-view-rebind")
def verify_passage_view_rebind_command(
    database: Annotated[
        Path,
        typer.Option("--database", help="Rebound DuckDB database path."),
    ],
    passage_root: Annotated[
        Path,
        typer.Option("--passage-root", help="Bound schema-v1 passage Parquet root."),
    ],
    expected_before_database_sha256: Annotated[
        str,
        typer.Option(
            "--expected-before-database-sha256",
            help="Original transferred database SHA-256 recorded by the receipt.",
        ),
    ],
    receipt_path: Annotated[
        Path,
        typer.Option("--receipt", help="Rebind receipt path."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the verified rebind receipt as JSON."),
    ] = False,
) -> None:
    """Verify the current post-rebind DB hash, paths, version, and tiny reads."""

    try:
        receipt = verify_passage_view_rebind_receipt(
            database,
            passage_root,
            receipt_path,
            expected_before_database_sha256=expected_before_database_sha256,
        )
    except (PassageStorageError, OSError) as exc:
        typer.echo(f"Passage view rebind verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(receipt)
    else:
        typer.echo(f"Verified passage view rebind receipt: {receipt_path}")
        typer.echo(f"DuckDB version: {receipt.duckdb_version}")
        typer.echo(f"Post-rebind SHA-256: {receipt.after_database_sha256}")


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


@app.command("ingest-benchmark")
def ingest_benchmark_command(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            help="Governed benchmark source; only openbible-cross-references is enabled.",
        ),
    ] = "openbible-cross-references",
    config_path: Annotated[
        Path, typer.Option("--config", help="Typed benchmark configuration path.")
    ] = Path("config/benchmark.yaml"),
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    tier1_path: Annotated[
        Path, typer.Option("--tier1", help="Tracked header-only Tier 1 CSV path.")
    ] = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Generated benchmark output root."),
    ] = Path("data/processed/benchmarks"),
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace generated artifacts only; governance gates are never bypassed.",
        ),
    ] = False,
) -> None:
    """Build all governed known-link artifacts from the pinned OpenBible snapshot."""

    if source.lower() not in {"openbible-cross-references", "openbible"}:
        typer.echo(
            "Benchmark ingestion failed: only openbible-cross-references is enabled.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        result = build_benchmark(
            config_path=config_path,
            manifest_path=manifest_path,
            tier1_path=tier1_path,
            data_root=data_root,
            output_root=output_dir,
            database_path=database,
            force=force,
        )
    except (
        AcquisitionError,
        BenchmarkBuildError,
        BenchmarkStorageError,
        ConfigLoadError,
        SourceManifestError,
        Tier1ValidationError,
        duckdb.Error,
        OSError,
    ) as exc:
        typer.echo(f"Benchmark ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Generated benchmark run {result.benchmark_run_id} ({result.benchmark_version}).")
    typer.echo(f"Rows: {_counts(result.storage.table_counts)}")
    typer.echo(f"Mappings: {_counts(result.mapping_status_counts)}")
    typer.echo(f"Splits: {_counts(result.split_counts)}")
    typer.echo(f"Presumed negatives: {_counts(result.negative_counts)}")
    typer.echo(f"DuckDB: {result.database_path}")


@app.command("validate-benchmarks")
def validate_benchmarks_command(
    all_benchmarks: Annotated[
        bool, typer.Option("--all", help="Validate all ten benchmark artifacts.")
    ] = False,
    config_path: Annotated[
        Path, typer.Option("--config", help="Typed benchmark configuration path.")
    ] = Path("config/benchmark.yaml"),
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    tier1_path: Annotated[
        Path, typer.Option("--tier1", help="Tracked header-only Tier 1 CSV path.")
    ] = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated benchmark output root.")
    ] = Path("data/processed/benchmarks"),
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat benchmark warnings as failures.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete validation report as JSON.")
    ] = False,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Optionally write the validation report as JSON."),
    ] = None,
) -> None:
    """Validate source, tier, identity, mapping, leakage, split, and input invariants."""

    if not all_benchmarks:
        typer.echo("Benchmark validation failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        validation = validate_benchmark_artifacts(
            config_path=config_path,
            manifest_path=manifest_path,
            tier1_path=tier1_path,
            data_root=data_root,
            output_root=output_dir,
            database_path=database,
            strict=strict,
        )
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(validation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (
        AcquisitionError,
        BenchmarkBuildError,
        BenchmarkValidationError,
        BenchmarkStorageError,
        ConfigLoadError,
        SourceManifestError,
        Tier1ValidationError,
        duckdb.Error,
        OSError,
    ) as exc:
        typer.echo(f"Benchmark validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(validation)
    else:
        typer.echo(
            f"Validated benchmark run {validation.benchmark_run_id or 'unknown'}: "
            f"errors={validation.error_count}, warnings={validation.warning_count}, "
            f"informational={validation.informational_count}."
        )
        typer.echo(f"Rows: {_counts(validation.table_counts)}")
        for issue in validation.issues:
            if issue.severity != "informational":
                location = f" [{issue.artifact}]" if issue.artifact else ""
                typer.echo(
                    f"{issue.severity.upper()} {issue.code}{location}: {issue.message}",
                    err=issue.severity == "error",
                )
    if not validation.passed:
        raise typer.Exit(code=validation.exit_code)


@app.command("validate-tier1-quotations")
def validate_tier1_quotations_command(
    config_path: Annotated[
        Path, typer.Option("--config", help="Typed benchmark configuration path.")
    ] = Path("config/benchmark.yaml"),
    tier1_path: Annotated[
        Path, typer.Option("--tier1", help="Tracked header-only Tier 1 CSV path.")
    ] = Path("data/benchmarks/tier1_quotations.csv"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the Tier 1 validation result as JSON.")
    ] = False,
) -> None:
    """Require the exact governed Tier 1 header and exactly zero data rows."""

    try:
        config = _load_benchmark_config(config_path)
        result = validate_tier1_quotations(
            tier1_path,
            expected_sha256=config.sources.tier1.header_sha256,
        )
    except (ConfigLoadError, Tier1ValidationError, OSError) as exc:
        typer.echo(f"Tier 1 quotation validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(result)
    else:
        typer.echo(
            f"Validated Tier 1 quotation placeholder: rows={result.row_count}, "
            f"sha256={result.sha256}."
        )


@app.command("validate-positive-controls")
def validate_positive_controls_command(
    config_path: Annotated[
        Path, typer.Option("--config", help="Standalone positive-control config path.")
    ] = Path("data/benchmarks/positive_controls.yaml"),
    data_path: Annotated[
        Path | None,
        typer.Option("--data", help="Optional CSV override; its governed hash must still match."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the positive-control receipt as JSON.")
    ] = False,
) -> None:
    """Validate the separate reference-only final-discovery positive controls."""

    try:
        dataset = validate_positive_controls(config_path, data_path=data_path)
    except (PositiveControlError, OSError) as exc:
        typer.echo(f"Positive-control validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(dataset.validation)
    else:
        counts = dataset.validation.partition_counts
        typer.echo(
            f"Validated {dataset.validation.benchmark_id}: rows={dataset.validation.row_count}, "
            f"families={dataset.validation.relationship_family_count}, "
            f"splits=train:{counts['train']}/development:{counts['development']}/"
            f"test:{counts['test']}."
        )


@app.command("run-final-discovery")
def run_final_discovery_command(
    fixture: Annotated[
        bool,
        typer.Option("--fixture", help="Run the bounded local no-network campaign fixture."),
    ] = False,
    production: Annotated[
        bool,
        typer.Option("--production", help="Run the authorized exact production campaign."),
    ] = False,
    work_directory: Annotated[
        Path,
        typer.Option(
            "--work-dir",
            help="Persistent work/checkpoint directory outside the source tree for production.",
        ),
    ] = Path("outputs/experiments/final-discovery-v1-fixture"),
    prepared_passages: Annotated[
        Path | None,
        typer.Option("--prepared-passages", help="Authenticated prepared-passage JSONL."),
    ] = None,
    knownness_path: Annotated[
        Path | None,
        typer.Option(
            "--knownness-path",
            help="Authenticated knownness JSONL; its .receipt.json sidecar is required.",
        ),
    ] = None,
    offline_model_root: Annotated[
        Path | None,
        typer.Option("--offline-model-root", help="Exact pinned offline E5 model directory."),
    ] = None,
    m7_bucket: Annotated[
        str | None, typer.Option("--m7-bucket", help="Frozen canonical M7 B2 bucket.")
    ] = None,
    m7_prefix: Annotated[
        str | None, typer.Option("--m7-prefix", help="Frozen canonical M7 B2 prefix.")
    ] = None,
    output_bucket: Annotated[
        str | None, typer.Option("--output-bucket", help="Owner-selected B2 output bucket.")
    ] = None,
    output_prefix: Annotated[
        str | None,
        typer.Option("--output-prefix", help="New empty immutable B2 campaign prefix."),
    ] = None,
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Frozen final-discovery preregistration YAML."),
    ] = Path("config/experiments/final-discovery-v1.yaml"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the authenticated run boundary as JSON.")
    ] = False,
) -> None:
    """Run the one-command bounded fixture or owner-authorized campaign."""

    from echoes.final_discovery.command import (
        FinalDiscoveryCommandError,
        build_production_campaign_request,
        current_source_identity,
    )
    from echoes.final_discovery.config import (
        FinalDiscoveryConfigError,
        load_final_discovery_config,
    )
    from echoes.final_discovery.pipeline import (
        FinalDiscoveryCampaignError,
        build_bounded_fixture_campaign_request,
        run_final_discovery_campaign,
    )

    if fixture == production:
        typer.echo(
            "Final-discovery run failed: select exactly one of --fixture or --production.", err=True
        )
        raise typer.Exit(code=2)
    project_root = Path.cwd().resolve()
    try:
        if fixture:
            forbidden = {
                "--prepared-passages": prepared_passages,
                "--knownness-path": knownness_path,
                "--offline-model-root": offline_model_root,
                "--m7-bucket": m7_bucket,
                "--m7-prefix": m7_prefix,
                "--output-bucket": output_bucket,
                "--output-prefix": output_prefix,
            }
            supplied = sorted(name for name, value in forbidden.items() if value is not None)
            if supplied:
                raise FinalDiscoveryCommandError(
                    f"fixture mode rejects production options: {', '.join(supplied)}"
                )
            config_file = config_path if config_path.is_absolute() else project_root / config_path
            config = load_final_discovery_config(config_file)
            code_commit, code_sha256 = current_source_identity(project_root)
            request = build_bounded_fixture_campaign_request(
                work_directory,
                config=config,
                code_sha256=code_sha256,
                code_commit=code_commit,
            )
        else:
            required = {
                "--prepared-passages": prepared_passages,
                "--knownness-path": knownness_path,
                "--offline-model-root": offline_model_root,
                "--m7-bucket": m7_bucket,
                "--m7-prefix": m7_prefix,
                "--output-bucket": output_bucket,
                "--output-prefix": output_prefix,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise FinalDiscoveryCommandError(f"production mode requires: {', '.join(missing)}")
            assert prepared_passages is not None
            assert knownness_path is not None
            assert offline_model_root is not None
            assert m7_bucket is not None
            assert m7_prefix is not None
            assert output_bucket is not None
            assert output_prefix is not None
            request = build_production_campaign_request(
                project_root=project_root,
                work_directory=work_directory,
                prepared_passages_path=prepared_passages,
                knownness_path=knownness_path,
                offline_model_root=offline_model_root,
                m7_bucket=m7_bucket,
                m7_prefix=m7_prefix,
                output_bucket=output_bucket,
                output_prefix=output_prefix,
                config_path=config_path,
            )
        result = run_final_discovery_campaign(request)
    except (
        FinalDiscoveryCommandError,
        FinalDiscoveryConfigError,
        FinalDiscoveryCampaignError,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:
        typer.echo(f"Final-discovery run failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = {
        "experiment_id": result.experiment_id,
        "execution_mode": result.execution_mode,
        "authenticated_stage_count": len(result.stage_results),
        "durable_checkpoint_count": len(result.durable_checkpoint_receipts),
        "evidence_count": result.evidence_count,
        "candidate_count": result.candidate_count,
        "tier_a_count": result.tier_a_count,
        "tier_b_count": result.tier_b_count,
        "package_sha256": result.package_sha256,
        "package_path": str(result.package_path),
        "validation_report_path": str(result.validation_report_path),
        "transfer_verification_path": str(result.transfer_verification_path),
        "campaign_seal_path": str(result.campaign_seal_path),
        "finalization_receipt_path": str(result.finalization_receipt_path),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        typer.echo(
            "Completed final-discovery boundary: "
            f"mode={result.execution_mode}, stages={len(result.stage_results)}, "
            f"candidates={result.candidate_count}, tier_a={result.tier_a_count}, "
            f"tier_b={result.tier_b_count}, package_sha256={result.package_sha256}."
        )


@app.command("validate-final-discovery")
def validate_final_discovery_command(
    all_stages: Annotated[
        bool,
        typer.Option("--all", help="Require and authenticate all eleven campaign stages."),
    ] = False,
    work_directory: Annotated[
        Path,
        typer.Option("--work-dir", help="Persistent final-discovery work directory."),
    ] = Path("outputs/experiments/final-discovery-v1-fixture"),
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Frozen final-discovery preregistration YAML."),
    ] = Path("config/experiments/final-discovery-v1.yaml"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete validation report as JSON.")
    ] = False,
) -> None:
    """Independently recompute the completed campaign's scientific contract."""

    from echoes.final_discovery.command import (
        FinalDiscoveryCommandError,
        validate_completed_campaign,
    )

    if not all_stages:
        typer.echo("Final-discovery validation failed: --all is required.", err=True)
        raise typer.Exit(code=2)
    project_root = Path.cwd().resolve()
    config_file = config_path if config_path.is_absolute() else project_root / config_path
    try:
        report = validate_completed_campaign(
            work_directory=work_directory,
            config_path=config_file,
        )
    except (FinalDiscoveryCommandError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Final-discovery validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(report)
    else:
        typer.echo(
            "Validated final-discovery campaign: "
            f"passed={report.passed}, stages={report.authenticated_stage_count}, "
            f"evidence={report.evidence_count}, candidates={report.candidate_count}, "
            f"findings={report.error_count}."
        )
    if not report.passed:
        raise typer.Exit(code=1)


@app.command("verify-final-discovery-finalization")
def verify_final_discovery_finalization_command(
    work_directory: Annotated[
        Path,
        typer.Option("--work-dir", help="Persistent production campaign work directory."),
    ] = Path("/srv/project-echoes/final-discovery/work"),
    output_bucket: Annotated[
        str,
        typer.Option("--output-bucket", help="Backblaze bucket containing final output."),
    ] = "",
    output_prefix: Annotated[
        str,
        typer.Option("--output-prefix", help="Registered base prefix for this campaign."),
    ] = "",
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete cleanup receipt as JSON.")
    ] = False,
) -> None:
    """Boundedly reauthenticate the remote Stage 11 deletion gate once."""

    from echoes.final_discovery.command import (
        FinalDiscoveryCommandError,
        verify_production_finalization_for_cleanup,
    )

    if not output_bucket or not output_prefix:
        typer.echo(
            "Finalization verification failed: --output-bucket and --output-prefix are required.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        receipt = verify_production_finalization_for_cleanup(
            work_directory=work_directory,
            output_bucket=output_bucket,
            output_prefix=output_prefix,
        )
    except (FinalDiscoveryCommandError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Finalization verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(receipt)
    else:
        remote = receipt["remote_verification"]
        typer.echo(
            "Reauthenticated final-discovery finalization: "
            f"completion={receipt['completion_manifest_sha256']}, "
            f"objects={remote['object_count']}, "
            f"checkpoint_attempts={receipt['successful_checkpoint_attempt_count']}."
        )


@app.command("validate-final-discovery-model-runtime")
def validate_final_discovery_model_runtime_command(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Frozen final-discovery preregistration YAML."),
    ] = Path("config/experiments/final-discovery-v1.yaml"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit exact installed versions as JSON.")
    ] = False,
) -> None:
    """Fail if the offline embedding runtime differs from its registered pins."""

    from echoes.final_discovery.config import FinalDiscoveryConfigError, load_final_discovery_config
    from echoes.final_discovery.semantic import SemanticError, verify_model_runtime_dependencies

    try:
        config = load_final_discovery_config(config_path)
        report = verify_model_runtime_dependencies(config.embedding_model)
    except (FinalDiscoveryConfigError, SemanticError, OSError, ValueError) as exc:
        typer.echo(f"Final-discovery model runtime validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = report.model_dump(mode="json")
    if json_output:
        _echo_json(payload)
    else:
        typer.echo(
            "Validated final-discovery model runtime: "
            f"python={report.python_version}, dependencies={len(report.dependency_versions)}."
        )


@app.command("inspect-final-discovery-output")
def inspect_final_discovery_output_command(
    work_directory: Annotated[
        Path,
        typer.Option("--work-dir", help="Persistent production campaign work directory."),
    ] = Path("/srv/project-echoes/final-discovery/work"),
    output_bucket: Annotated[
        str,
        typer.Option("--output-bucket", help="Backblaze bucket containing final output."),
    ] = "",
    output_prefix: Annotated[
        str,
        typer.Option("--output-prefix", help="Registered base prefix for this campaign."),
    ] = "",
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Frozen final-discovery preregistration YAML."),
    ] = Path("config/experiments/final-discovery-v1.yaml"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the namespace receipt as JSON.")
    ] = False,
) -> None:
    """Inspect output state once before the managed production worker starts."""

    from echoes.final_discovery.command import (
        FinalDiscoveryCommandError,
        inspect_production_output_namespace,
    )
    from echoes.final_discovery.config import FinalDiscoveryConfigError

    if not output_bucket or not output_prefix:
        typer.echo(
            "Output inspection failed: --output-bucket and --output-prefix are required.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        receipt = inspect_production_output_namespace(
            work_directory=work_directory,
            output_bucket=output_bucket,
            output_prefix=output_prefix,
            config_path=config_path,
        )
    except (
        FinalDiscoveryCommandError,
        FinalDiscoveryConfigError,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:
        typer.echo(f"Output inspection failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _echo_json(receipt)
    else:
        typer.echo(
            "Inspected final-discovery output namespace: "
            f"state={receipt['state']}, objects={receipt['object_count']}."
        )


def _verify_generated_benchmark_stage(
    *,
    stage_table: str,
    config_path: Path,
    manifest_path: Path,
    tier1_path: Path,
    data_root: Path,
    output_dir: Path,
    database: Path,
) -> tuple[BenchmarkValidationReport, dict[str, int]]:
    validation = validate_benchmark_artifacts(
        config_path=config_path,
        manifest_path=manifest_path,
        tier1_path=tier1_path,
        data_root=data_root,
        output_root=output_dir,
        database_path=database,
        strict=True,
    )
    if not validation.passed:
        raise BenchmarkValidationError("the materialized benchmark does not pass strict validation")
    counts = table_row_counts(database)
    if stage_table not in counts:
        raise BenchmarkStorageError(f"materialized benchmark is missing {stage_table}")
    return validation, counts


@app.command("generate-benchmark-splits")
def generate_benchmark_splits_command(
    all_strategies: Annotated[
        bool, typer.Option("--all", help="Verify every configured split strategy.")
    ] = False,
    config_path: Annotated[
        Path, typer.Option("--config", help="Typed benchmark configuration path.")
    ] = Path("config/benchmark.yaml"),
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    tier1_path: Annotated[
        Path, typer.Option("--tier1", help="Tracked header-only Tier 1 CSV path.")
    ] = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated benchmark output root.")
    ] = Path("data/processed/benchmarks"),
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Acknowledge generated outputs; never bypass validation gates.",
        ),
    ] = False,
) -> None:
    """Verify deterministic split artifacts materialized by full benchmark ingestion."""

    if not all_strategies:
        typer.echo("Split generation verification failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        validation, counts = _verify_generated_benchmark_stage(
            stage_table="benchmark_split_assignments",
            config_path=config_path,
            manifest_path=manifest_path,
            tier1_path=tier1_path,
            data_root=data_root,
            output_dir=output_dir,
            database=database,
        )
    except (
        AcquisitionError,
        BenchmarkBuildError,
        BenchmarkValidationError,
        BenchmarkStorageError,
        ConfigLoadError,
        SourceManifestError,
        Tier1ValidationError,
        duckdb.Error,
        OSError,
    ) as exc:
        typer.echo(f"Split generation verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    force_note = " --force acknowledged after all gates." if force else ""
    typer.echo(
        f"Verified benchmark splits for {validation.benchmark_run_id}: "
        f"rows={counts['benchmark_split_assignments']}.{force_note}"
    )


@app.command("generate-presumed-negatives")
def generate_presumed_negatives_command(
    all_strategies: Annotated[
        bool, typer.Option("--all", help="Verify every configured negative strategy.")
    ] = False,
    config_path: Annotated[
        Path, typer.Option("--config", help="Typed benchmark configuration path.")
    ] = Path("config/benchmark.yaml"),
    manifest_path: SourceManifestPath = Path("data/manifests/sources.yaml"),
    tier1_path: Annotated[
        Path, typer.Option("--tier1", help="Tracked header-only Tier 1 CSV path.")
    ] = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: DataRoot = Path("data"),
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated benchmark output root.")
    ] = Path("data/processed/benchmarks"),
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Acknowledge generated outputs; never bypass validation gates.",
        ),
    ] = False,
) -> None:
    """Verify presumed-negative artifacts materialized by full benchmark ingestion."""

    if not all_strategies:
        typer.echo("Presumed-negative verification failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        validation, counts = _verify_generated_benchmark_stage(
            stage_table="benchmark_presumed_negatives",
            config_path=config_path,
            manifest_path=manifest_path,
            tier1_path=tier1_path,
            data_root=data_root,
            output_dir=output_dir,
            database=database,
        )
    except (
        AcquisitionError,
        BenchmarkBuildError,
        BenchmarkValidationError,
        BenchmarkStorageError,
        ConfigLoadError,
        SourceManifestError,
        Tier1ValidationError,
        duckdb.Error,
        OSError,
    ) as exc:
        typer.echo(f"Presumed-negative verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    force_note = " --force acknowledged after all gates." if force else ""
    typer.echo(
        f"Verified presumed negatives for {validation.benchmark_run_id}: "
        f"rows={counts['benchmark_presumed_negatives']}.{force_note}"
    )


@app.command("benchmark-summary")
def benchmark_summary_command(
    all_benchmarks: Annotated[
        bool, typer.Option("--all", help="Summarize all benchmark artifacts.")
    ] = False,
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete summary as JSON.")
    ] = False,
) -> None:
    """Summarize materialized benchmark tiers, mappings, splits, and negatives."""

    if not all_benchmarks:
        typer.echo("Benchmark summary failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        payload = _benchmark_summary_payload(database)
    except BenchmarkStorageError as exc:
        typer.echo(f"Benchmark summary failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))
        return
    metadata = cast(dict[str, object], payload["metadata"])
    counts = cast(dict[str, int], payload["table_counts"])
    typer.echo(f"Benchmark run {metadata['benchmark_run_id']} ({metadata['benchmark_version']}).")
    typer.echo(f"Rows: {_counts(counts)}")
    tier_groups = cast(list[object], payload["relationships_by_tier_and_source"])
    typer.echo(f"Tier/source groups: {len(tier_groups)}")
    typer.echo(
        f"Mapping groups: {len(cast(list[object], payload['mappings_by_profile_and_status']))}"
    )
    typer.echo(
        f"Split groups: {len(cast(list[object], payload['splits_by_strategy_and_partition']))}"
    )
    typer.echo(
        "Presumed-negative strategies: "
        f"{len(cast(list[object], payload['presumed_negatives_by_strategy']))}"
    )


@app.command("show-relationship")
def show_relationship_command(
    relationship_id: Annotated[str, typer.Argument(help="Stable relationship identifier.")],
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit all relationship evidence as JSON.")
    ] = False,
) -> None:
    """Display source provenance, mappings, leakage, splits, and contrasts."""

    try:
        details = _relationship_details(database, relationship_id)
    except BenchmarkStorageError as exc:
        typer.echo(f"Could not show benchmark relationship: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if details is None:
        typer.echo(f"Benchmark relationship not found: {relationship_id}", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(details, indent=2, ensure_ascii=True))
        return
    relationship = cast(dict[str, object], details["relationship"])
    typer.echo(f"Relationship: {relationship_id}")
    typer.echo(
        f"Source references: {relationship['source_reference_a']} -> "
        f"{relationship['source_reference_b']} ({relationship['relationship_direction']})"
    )
    typer.echo(
        f"Tier: {relationship['tier']}; class: {relationship['relationship_class']}; "
        f"source weight sum/max: {relationship['source_weight_sum']}/"
        f"{relationship['source_weight_max']}"
    )
    typer.echo(
        "Eligibility: weak_supervision="
        f"{relationship['weak_supervision_eligible']}, knownness="
        f"{relationship['knownness_filter_eligible']}, primary_evaluation="
        f"{relationship['primary_evaluation_eligible']}, tier1="
        f"{relationship['tier1_eligible']}"
    )
    typer.echo(f"Provenance: {relationship['provenance_json']}")
    source_records = cast(list[dict[str, object]], details["source_records"])
    typer.echo(f"Source records: {len(source_records)}")
    for source_record in source_records:
        typer.echo(
            f"- {source_record['source_record_id']} at {source_record['source_file']}:"
            f"{source_record['source_line_number']} weight={source_record['source_weight']} "
            f"status={source_record['parse_status']} raw_sha256="
            f"{source_record['raw_record_sha256']}"
        )
    mappings = cast(list[dict[str, object]], details["endpoint_mappings"])
    typer.echo(f"Endpoint mappings: {len(mappings)}")
    for mapping in mappings:
        typer.echo(
            f"- {mapping['target_analysis_profile']}/{mapping['target_corpus']}: "
            f"status={mapping['mapping_status']}, confidence={mapping['mapping_confidence']}, "
            f"gap={mapping['reference_gap']}, disputed={mapping['disputed_passage_flag']}, "
            f"passages={mapping['target_passage_ids_json']}"
        )
    leakage_groups = cast(list[dict[str, object]], details["leakage_groups"])
    typer.echo(f"Leakage groups: {len(leakage_groups)}")
    for group in leakage_groups:
        typer.echo(f"- {group['group_type']}: {group['group_key']}")
    split_assignments = cast(list[dict[str, object]], details["split_assignments"])
    typer.echo(f"Split assignments: {len(split_assignments)}")
    for assignment in split_assignments:
        typer.echo(
            f"- {assignment['split_strategy']}: {assignment['partition']} "
            f"({assignment['eligibility_status']})"
        )
    negatives = cast(list[dict[str, object]], details["related_presumed_negatives"])
    typer.echo(f"Related presumed negatives: {len(negatives)}")
    for negative in negatives:
        typer.echo(
            f"- {negative['negative_strategy']} {negative['partition']}: "
            f"{negative['passage_a_id']} / {negative['passage_b_id']}"
        )


@app.command("show-benchmark-mapping")
def show_benchmark_mapping_command(
    relationship_id: Annotated[str, typer.Argument(help="Stable relationship identifier.")],
    database: Annotated[
        Path, typer.Option("--database", help="Local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit complete endpoint mapping evidence as JSON.")
    ] = False,
) -> None:
    """Display mapping confidence, uncertainty, gaps, and disputed-text status."""

    try:
        details = _mapping_details(database, relationship_id)
    except BenchmarkStorageError as exc:
        typer.echo(f"Could not show benchmark mapping: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if details is None:
        typer.echo(f"Benchmark relationship not found: {relationship_id}", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(details, indent=2, ensure_ascii=True))
        return
    typer.echo(f"Relationship: {relationship_id}")
    typer.echo(
        f"Source references: {details['source_reference_a']} -> {details['source_reference_b']}"
    )
    mappings = cast(list[dict[str, object]], details["endpoint_mappings"])
    for mapping in mappings:
        typer.echo(
            f"- {mapping['target_analysis_profile']}/{mapping['target_corpus']}: "
            f"status={mapping['mapping_status']}, confidence={mapping['mapping_confidence']}, "
            f"method={mapping['mapping_method']}, gap={mapping['reference_gap']}, "
            f"disputed={mapping['disputed_passage_flag']}, "
            f"passages={mapping['target_passage_ids_json']}, "
            f"ambiguity={mapping['ambiguity_reason']}"
        )


def _lexical_pipeline_payload(result: LexicalPipelineResult) -> dict[str, object]:
    return {
        "experiment_run_id": result.experiment_run_id,
        "experiment_version": result.experiment_version,
        "configuration_hash": result.configuration_hash,
        "preregistration_hash": result.preregistration_hash,
        "table_counts": result.processed.table_counts,
        "table_logical_hashes": result.processed.table_logical_hashes,
        "feature_counts": result.feature_counts,
        "index_summaries": result.index_summaries,
        "ranking_count": result.ranking_count,
        "candidate_count": result.candidate_count,
        "review_eligible_count": result.review_eligible_count,
        "queue_count": result.queue_count,
        "null_iteration_count": result.null_iteration_count,
        "evaluation_count": result.evaluation_count,
        "acceptance_status": result.acceptance_status,
        "stage_runtime_seconds": result.stage_runtime_seconds,
        "approximate_peak_memory_bytes": result.approximate_peak_memory_bytes,
    }


@app.command("audit-lexical-features")
def audit_lexical_features_command(
    database: Annotated[
        Path, typer.Option("--database", help="Anchored local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    output: Annotated[
        Path, typer.Option("--output", help="Sanitized tracked audit report path.")
    ] = Path("outputs/reports/m7-lexical-feature-audit.md"),
) -> None:
    """Audit full lexical coverage and feasibility without generating candidates."""

    try:
        report = generate_lexical_feature_audit(database_path=database, output_path=output)
    except (LexicalAuditError, OSError) as exc:
        typer.echo(f"Lexical feature audit failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Lexical feature audit passed: {output} ({len(report)} characters).")


@app.command("run-lexical-pipeline")
def run_lexical_pipeline_command(
    primary: Annotated[
        bool, typer.Option("--primary", help="Run the frozen verse-level primary scope.")
    ] = False,
    database: Annotated[
        Path, typer.Option("--database", help="Anchored local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[
        bool, typer.Option("--force", help="Atomically replace generated lexical artifacts.")
    ] = False,
    resume_staging_dir: Annotated[
        Path | None,
        typer.Option(
            "--resume-staging-dir",
            help="Adopt one validated interrupted lexical staging directory.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete run summary as JSON.")
    ] = False,
) -> None:
    """Run the complete preregistered lexical pipeline behind one atomic boundary."""

    if not primary:
        typer.echo("Lexical pipeline failed: select --primary.", err=True)
        raise typer.Exit(code=1)
    try:
        result = run_lexical_pipeline(
            database_path=database,
            output_dir=output_dir,
            force=force,
            resume_staging_dir=resume_staging_dir,
        )
    except (LexicalPipelineError, LexicalStorageError, OSError, ValueError) as exc:
        typer.echo(f"Lexical pipeline failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = _lexical_pipeline_payload(result)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))
        return
    typer.echo(
        f"Lexical pipeline completed: {result.experiment_run_id}; "
        f"rankings={result.ranking_count}, candidates={result.candidate_count}, "
        f"queue={result.queue_count}, status={result.acceptance_status}."
    )


@app.command("recover-lexical-promotion")
def recover_lexical_promotion_command(
    database: Annotated[
        Path, typer.Option("--database", help="Governed DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Governed lexical schema-v1 directory."),
    ] = DEFAULT_LEXICAL_ROOT,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the recovery state as JSON."),
    ] = False,
) -> None:
    """Resolve a crash journal across lexical promotion and DuckDB exposure."""

    try:
        state = recover_interrupted_lexical_promotion(output_dir, database)
    except (LexicalStorageError, OSError) as exc:
        typer.echo(f"Lexical promotion recovery failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = {
        "state": state,
        "canonical_output_present": output_dir.is_dir() and not output_dir.is_symlink(),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        typer.echo(f"Lexical promotion recovery: {state}.")


@app.command("finalize-lexical-promotion-recovery")
def finalize_lexical_promotion_recovery_command(
    validation_report: Annotated[
        Path,
        typer.Option(
            "--validation-report",
            help="Successful strict lexical-validation JSON for the committed output.",
        ),
    ],
    service_result: Annotated[
        str,
        typer.Option(
            "--service-result",
            help="Authenticated systemd Result value for the completed worker.",
        ),
    ],
    database: Annotated[
        Path, typer.Option("--database", help="Governed DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Governed lexical schema-v1 directory."),
    ] = DEFAULT_LEXICAL_ROOT,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the finalized provenance receipt as JSON."),
    ] = False,
) -> None:
    """Finalize post-COMMIT provenance after strict recovery validation."""

    try:
        state = recover_interrupted_lexical_promotion(output_dir, database)
        if state != "canonical_committed":
            raise LexicalStorageError(
                f"recovery finalization requires a journaled committed exposure; observed {state}"
            )
        if not validation_report.is_file() or validation_report.is_symlink():
            raise LexicalStorageError(
                f"strict recovery validation report is missing or unsafe: {validation_report}"
            )
        validation = LexicalValidationReport.model_validate_json(
            validation_report.read_text(encoding="utf-8")
        )
        if (
            not validation.passed
            or not validation.strict
            or Path(validation.output_dir).resolve() != output_dir.resolve()
        ):
            raise LexicalStorageError(
                "recovery validation must be strict, passing, and bound to canonical output"
            )
        journal = read_current_lexical_promotion_witness(output_dir, database)
        manifest = load_execution_manifest(journal.execution_manifest_path)
        if (
            manifest.execution_id != journal.execution_id
            or validation.experiment_run_id != manifest.run_id
            or validation.table_logical_hashes != manifest.output_table_hashes
            or validation.table_physical_hashes != manifest.output_table_physical_hashes
        ):
            raise LexicalStorageError(
                "strict validation, promotion journal, and execution manifest identities differ"
            )
        prior_status = manifest.execution_status
        validation_sha256 = sha256_file(validation_report)
        finalized = finalize_recovered_execution_success(
            journal.execution_manifest_path,
            validation_report_sha256=validation_sha256,
            service_result=service_result,
        )
        sealed_state = recover_interrupted_lexical_promotion(
            output_dir,
            database,
            archive_committed=True,
        )
        if sealed_state != "canonical_committed":
            raise LexicalStorageError(f"could not seal committed lexical promotion: {sealed_state}")
    except (
        LexicalStorageError,
        OSError,
        UnicodeError,
        ValueError,
        ValidationError,
    ) as exc:
        typer.echo(f"Lexical promotion recovery finalization failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = {
        "state": sealed_state,
        "execution_id": finalized.execution_id,
        "prior_execution_status": prior_status,
        "execution_status": finalized.execution_status,
        "validation_report": str(validation_report.resolve()),
        "validation_report_sha256": validation_sha256,
        "service_result": service_result,
        "active_journal_present": False,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        typer.echo(
            "Lexical promotion recovery finalized: "
            f"{finalized.execution_id} ({prior_status} -> {finalized.execution_status})."
        )


@app.command("build-lexical-index")
def build_lexical_index_command(
    all_indexes: Annotated[
        bool, typer.Option("--all", help="Build all governed lexical representations.")
    ] = False,
    database: Annotated[
        Path, typer.Option("--database", help="Anchored local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[
        bool, typer.Option("--force", help="Atomically replace generated lexical artifacts.")
    ] = False,
) -> None:
    """Build indexes through the complete atomic workflow and report their count."""

    if not all_indexes:
        typer.echo("Lexical index build failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        result = run_lexical_pipeline(
            database_path=database,
            output_dir=output_dir,
            force=force,
        )
    except (LexicalPipelineError, LexicalStorageError, OSError, ValueError) as exc:
        typer.echo(f"Lexical index build failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Built {len(result.index_summaries)} governed sparse indexes for "
        f"{result.experiment_run_id}; the complete atomic artifact set is materialized."
    )


def _verify_lexical_stage(
    *,
    output_dir: Path,
    artifact: str,
    label: str,
    force: bool,
    allow_empty: bool = False,
) -> None:
    try:
        processed = processed_from_directory(output_dir)
        counts = processed.table_counts
        manifest = read_hash_manifest(output_dir)
        name = cast(LexicalArtifactName, artifact)
        file_hashes = cast(dict[str, object], manifest["file_sha256"])
        artifact_files = {
            relative: str(digest)
            for relative, digest in file_hashes.items()
            if relative.startswith(f"{artifact}/")
        }
        if not artifact_files:
            raise LexicalStorageError(f"{artifact} has no governed Parquet leaves")
        for relative, expected_digest in artifact_files.items():
            path = output_dir / Path(relative)
            if not path.is_file() or sha256_file(path) != expected_digest:
                raise LexicalStorageError(f"{artifact} physical hash mismatch: {relative}")
        paths = sorted((output_dir / artifact).glob("part-*.parquet"))
        scan = pl.scan_parquet(paths)
        actual_columns = tuple(scan.collect_schema().names())
        expected_columns = LEXICAL_ARTIFACT_COLUMNS[name]
        if actual_columns != expected_columns:
            raise LexicalStorageError(
                f"{artifact} schema differs; expected={expected_columns}, actual={actual_columns}"
            )
        actual_count = int(
            scan.select(pl.len().alias("row_count")).collect(engine="streaming").item()
        )
        metadata = read_artifact_frame(output_dir, "lexical_metadata")
        if metadata.height != 1:
            raise LexicalStorageError("lexical metadata must contain exactly one row")
        if actual_count != counts.get(artifact):
            raise LexicalStorageError(
                f"{artifact} manifest count differs from its typed Parquet rows"
            )
        config = load_lexical_config()
        preregistration = load_lexical_preregistration()
        validate_preregistration_against_config(preregistration, config)
        if metadata.item(0, "configuration_hash") != lexical_config_sha256(config):
            raise LexicalStorageError("lexical metadata configuration hash is stale")
        if metadata.item(0, "preregistration_hash") != lexical_preregistration_sha256(
            preregistration
        ):
            raise LexicalStorageError("lexical metadata preregistration hash is stale")
        stage_runtimes = json.loads(str(metadata.item(0, "stage_runtime_seconds_json")))
        if (
            not isinstance(stage_runtimes, dict)
            or not stage_runtimes
            or any(
                not isinstance(value, (int, float)) or value < 0
                for value in stage_runtimes.values()
            )
        ):
            raise LexicalStorageError("lexical metadata stage runtimes are invalid")
        declared_counts = {
            "directional_rankings": int(metadata.item(0, "ranking_count")),
            "candidate_pairs": int(metadata.item(0, "candidate_count")),
            "evaluation_results": int(metadata.item(0, "evaluation_count")),
        }
        for declared_artifact, declared_count in declared_counts.items():
            if counts.get(declared_artifact) != declared_count:
                raise LexicalStorageError(
                    f"metadata {declared_artifact} count differs from the hash manifest"
                )

        if artifact == "directional_rankings":
            expected_detectors = {*config.enabled_detectors, "rrf_composite"}
            expected_pairs = {"hb_hb", "gnt_gnt", "hb_gnt_english_bridge"}
            cells = {
                (str(pair), str(detector))
                for pair, detector in scan.filter(
                    (pl.col("experiment_scope") == "primary")
                    & (pl.col("analysis_profile") == "edition_complete")
                )
                .select("corpus_pair", "detector")
                .unique()
                .collect(engine="streaming")
                .iter_rows()
            }
            missing_cells = sorted(
                (pair, detector)
                for pair in expected_pairs
                for detector in expected_detectors
                if (pair, detector) not in cells
            )
            if missing_cells:
                raise LexicalStorageError(
                    f"primary directional rankings omit governed cells: {missing_cells[:10]}"
                )
            sensitivity_scopes = set(
                scan.select("experiment_scope")
                .unique()
                .collect(engine="streaming")
                .get_column("experiment_scope")
            )
            required_scopes = {
                "critical_core_greek_sensitivity",
                "hebrew_qere_ketiv_sensitivity",
            }
            if not required_scopes.issubset(sensitivity_scopes):
                raise LexicalStorageError("directional rankings omit required sensitivity scopes")
            if counts.get("sensitivity_results", 0) < 1:
                raise LexicalStorageError("typed sensitivity comparison results are empty")
        elif artifact == "null_replicate_summaries":
            required_families = {
                "within_book_reassignment",
                "frequency_preserving_synthetic",
            }
            null_summary = (
                scan.group_by("corpus_pair")
                .agg(
                    pl.col("null_family").unique().sort().alias("null_families"),
                    pl.col("iteration").max().alias("maximum_iteration"),
                )
                .collect(engine="streaming")
            )
            observed_families = {
                str(family)
                for families in null_summary.get_column("null_families")
                for family in families
            }
            if observed_families != required_families:
                raise LexicalStorageError("null output does not contain both registered families")
            for pair in ("hb_hb", "gnt_gnt", "hb_gnt_english_bridge"):
                pair_frame = null_summary.filter(pl.col("corpus_pair") == pair)
                maximum_iteration = (
                    None if pair_frame.is_empty() else pair_frame.item(0, "maximum_iteration")
                )
                if (
                    pair_frame.is_empty()
                    or maximum_iteration is None
                    or int(str(maximum_iteration)) != config.null_models.iterations_per_family
                ):
                    raise LexicalStorageError(
                        f"null output is incomplete for governed corpus pair {pair}"
                    )
        elif artifact == "evaluation_results":
            if not {"edition_complete", "critical_core"}.issubset(
                set(
                    scan.select("analysis_profile")
                    .unique()
                    .collect(engine="streaming")
                    .get_column("analysis_profile")
                )
            ):
                raise LexicalStorageError(
                    "Tier 3 evaluation omits primary or critical-core profile results"
                )
        elif artifact == "candidate_review_queue" and actual_count:
            queue_summary = scan.select(
                pl.col("review_eligible").all().alias("all_eligible"),
                pl.col("queue_rank").min().alias("minimum_rank"),
                pl.col("queue_rank").max().alias("maximum_rank"),
                pl.col("queue_rank").n_unique().alias("unique_rank_count"),
            ).collect(engine="streaming")
            if not bool(queue_summary.item(0, "all_eligible")):
                raise LexicalStorageError("review queue contains an ineligible candidate")
            if (
                queue_summary.item(0, "minimum_rank") != 1
                or queue_summary.item(0, "maximum_rank") != actual_count
                or queue_summary.item(0, "unique_rank_count") != actual_count
            ):
                raise LexicalStorageError("review queue ranks are not contiguous from one")
    except (LexicalStorageError, OSError, KeyError, ValueError, pl.exceptions.PolarsError) as exc:
        typer.echo(f"{label} failed: complete lexical artifacts are required: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    count = counts.get(artifact, 0)
    if count < 1 and not allow_empty:
        typer.echo(f"{label} failed: {artifact} is empty.", err=True)
        raise typer.Exit(code=1)
    suffix = " --force acknowledged; no identity-changing rebuild was needed." if force else ""
    typer.echo(f"{label} verified: {artifact} rows={count}.{suffix}")


@app.command("run-lexical-baseline")
def run_lexical_baseline_command(
    primary: Annotated[
        bool, typer.Option("--primary", help="Use the frozen verse-level primary scope.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[bool, typer.Option("--force", help="Acknowledge generated output.")] = False,
) -> None:
    """Verify the fully materialized detector rankings and candidate baseline."""

    if not primary:
        typer.echo("Lexical baseline failed: select --primary.", err=True)
        raise typer.Exit(code=1)
    _verify_lexical_stage(
        output_dir=output_dir,
        artifact="directional_rankings",
        label="Lexical baseline",
        force=force,
    )


@app.command("run-lexical-null-models")
def run_lexical_null_models_command(
    primary: Annotated[
        bool, typer.Option("--primary", help="Use the frozen verse-level primary scope.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[bool, typer.Option("--force", help="Acknowledge generated output.")] = False,
) -> None:
    """Verify both retained preregistered null-model families."""

    if not primary:
        typer.echo("Lexical null models failed: select --primary.", err=True)
        raise typer.Exit(code=1)
    _verify_lexical_stage(
        output_dir=output_dir,
        artifact="null_replicate_summaries",
        label="Lexical null models",
        force=force,
    )


@app.command("evaluate-lexical-baseline")
def evaluate_lexical_baseline_command(
    primary: Annotated[
        bool, typer.Option("--primary", help="Use the frozen Tier 3 primary evaluation.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[bool, typer.Option("--force", help="Acknowledge generated output.")] = False,
) -> None:
    """Verify the preregistered leakage-aware Tier 3 evaluation outputs."""

    if not primary:
        typer.echo("Lexical evaluation failed: select --primary.", err=True)
        raise typer.Exit(code=1)
    _verify_lexical_stage(
        output_dir=output_dir,
        artifact="evaluation_results",
        label="Lexical evaluation",
        force=force,
    )


@app.command("build-lexical-review-queue")
def build_lexical_review_queue_command(
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    force: Annotated[bool, typer.Option("--force", help="Acknowledge generated output.")] = False,
) -> None:
    """Verify the frozen-policy unreviewed Milestone 8 handoff queue."""

    _verify_lexical_stage(
        output_dir=output_dir,
        artifact="candidate_review_queue",
        label="Unreviewed lexical queue",
        force=force,
        allow_empty=True,
    )


@app.command("validate-lexical")
def validate_lexical_command(
    all_artifacts: Annotated[
        bool, typer.Option("--all", help="Validate every governed lexical artifact.")
    ] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat warnings as validation failures.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    database: Annotated[
        Path, typer.Option("--database", help="Anchored local DuckDB database path.")
    ] = Path("data/processed/project_echoes.duckdb"),
    determinism_reference_root: Annotated[
        Path | None,
        typer.Option(
            "--determinism-reference-root",
            help="First-run lexical schema directory for exact logical-hash comparison.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete validation report as JSON.")
    ] = False,
) -> None:
    """Strictly validate identities, evidence, nulls, evaluation, and determinism."""

    if not all_artifacts:
        typer.echo("Lexical validation failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        report = validate_lexical_artifacts(
            output_dir,
            database_path=database,
            determinism_reference_root=determinism_reference_root,
            strict=strict,
        )
    except (LexicalValidationError, OSError, ValueError) as exc:
        typer.echo(f"Lexical validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(
            f"Lexical validation: run={report.experiment_run_id}, "
            f"errors={report.error_count}, warnings={report.warning_count}, "
            f"informationals={report.informational_count}, passed={report.passed}, "
            f"scientific_gate={report.scientific_gate_passed}."
        )
    if not report.passed:
        raise typer.Exit(code=report.exit_code)


@app.command("lexical-summary")
def lexical_summary_command(
    all_artifacts: Annotated[
        bool, typer.Option("--all", help="Summarize every governed lexical artifact.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete summary as JSON.")
    ] = False,
) -> None:
    """Print a sanitized aggregate lexical-run summary."""

    if not all_artifacts:
        typer.echo("Lexical summary failed: select --all.", err=True)
        raise typer.Exit(code=1)
    try:
        summary = lexical_summary(output_dir)
    except (LexicalValidationError, OSError, ValueError) as exc:
        typer.echo(f"Lexical summary failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(summary.model_dump_json(indent=2))
        return
    typer.echo(
        f"Lexical run {summary.experiment_run_id} ({summary.experiment_version}); "
        f"status={summary.acceptance_status}."
    )
    typer.echo(f"Rows: {_counts(summary.table_counts)}")
    typer.echo(
        f"Review eligible={summary.review_eligible_count}; queue={summary.queue_count}; "
        f"English-derived={summary.english_derived_candidate_count}."
    )


def _show_lexical_payload(payload: dict[str, object] | None, candidate_pair_id: str) -> None:
    if payload is None:
        typer.echo(f"Lexical candidate not found: {candidate_pair_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


@app.command("show-lexical-candidate")
def show_lexical_candidate_command(
    candidate_pair_id: Annotated[str, typer.Argument(help="Stable candidate-pair ID.")],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
) -> None:
    """Display all text-free decomposed candidate evidence and calibration."""

    _show_lexical_payload(show_lexical_candidate(candidate_pair_id, output_dir), candidate_pair_id)


@app.command("show-lexical-evidence")
def show_lexical_evidence_command(
    candidate_pair_id: Annotated[str, typer.Argument(help="Stable candidate-pair ID.")],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
) -> None:
    """Display feature positions, alternatives, scores, penalties, and calibration."""

    _show_lexical_payload(show_lexical_evidence(candidate_pair_id, output_dir), candidate_pair_id)


@app.command("compare-lexical-ablation")
def compare_lexical_ablation_command(
    candidate_pair_id: Annotated[str, typer.Argument(help="Stable candidate-pair ID.")],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Generated lexical schema-v1 directory.")
    ] = DEFAULT_LEXICAL_ROOT,
) -> None:
    """Display English-derived evidence and mandatory removal-ablation status."""

    _show_lexical_payload(
        compare_lexical_ablation(candidate_pair_id, output_dir), candidate_pair_id
    )


@app.command("validate-run-manifest")
def validate_run_manifest_command(
    run_id: Annotated[str, typer.Argument(help="Scientific experiment run ID.")],
    execution_id: Annotated[
        str | None,
        typer.Option(
            "--execution-id",
            help="Exact execution attempt; defaults to the newest successful attempt.",
        ),
    ] = None,
    manifest_root: Annotated[
        Path,
        typer.Option(
            "--manifest-root",
            help="Ignored execution-manifest sidecar root.",
        ),
    ] = DEFAULT_EXECUTION_MANIFEST_ROOT,
    artifact_root: Annotated[
        Path | None,
        typer.Option(
            "--artifact-root",
            help=(
                "Exact canonical or archived lexical artifact root to authenticate; "
                "must be a direct sibling of the recorded schema-v1 directory."
            ),
        ),
    ] = None,
) -> None:
    """Validate execution provenance and exact canonical or archived output hashes."""
    project_root = Path.cwd().resolve()
    notices: list[str] = []
    try:
        manifest_path, manifest = resolve_execution_manifest(
            manifest_root,
            run_id=run_id,
            execution_id=execution_id,
        )
        failures = [
            *reproduction_environment_mismatches(
                manifest,
                project_root=project_root,
                notices=notices,
            ),
            *validate_execution_manifest_outputs(
                manifest,
                project_root=project_root,
                artifact_root=artifact_root,
            ),
        ]
    except (FileNotFoundError, OSError, ValidationError, ValueError) as exc:
        typer.echo(f"Run-manifest validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for notice in notices:
        typer.echo(f"Provenance notice: {notice}")
    if failures:
        typer.echo("Run-manifest validation failed:", err=True)
        for failure in failures:
            typer.echo(f"- {failure}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        "Run manifest validated: "
        f"run={manifest.run_id}, execution={manifest.execution_id}, path={manifest_path}"
    )


@app.command("reproduce")
def reproduce_command(
    run_id: Annotated[str, typer.Argument(help="Scientific experiment run ID.")],
    execution_id: Annotated[
        str | None,
        typer.Option(
            "--execution-id",
            help="Exact execution attempt; defaults to the newest successful attempt.",
        ),
    ] = None,
    manifest_root: Annotated[
        Path,
        typer.Option(
            "--manifest-root",
            help="Ignored execution-manifest sidecar root.",
        ),
    ] = DEFAULT_EXECUTION_MANIFEST_ROOT,
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Execute the authenticated argv; the default only prints it.",
        ),
    ] = False,
) -> None:
    """Resolve and print an exact command, executing it only with --execute."""
    project_root = Path.cwd().resolve()
    try:
        manifest_path, manifest = resolve_execution_manifest(
            manifest_root,
            run_id=run_id,
            execution_id=execution_id,
        )
    except (FileNotFoundError, OSError, ValidationError, ValueError) as exc:
        typer.echo(f"Reproduction resolution failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Resolved execution: run={manifest.run_id}, "
        f"execution={manifest.execution_id}, path={manifest_path}"
    )
    typer.echo(f"Command: {format_reproduction_command(manifest.reproduction_command)}")
    if not execute:
        typer.echo("Dry run only; pass --execute to run this argv without a shell.")
        return

    try:
        notices: list[str] = []
        mismatches = reproduction_environment_mismatches(
            manifest,
            project_root=project_root,
            notices=notices,
        )
        mismatches.extend(
            reproduction_command_path_mismatches(
                manifest,
                project_root=project_root,
            )
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Reproduction preflight failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for notice in notices:
        typer.echo(f"Provenance notice: {notice}")
    if mismatches:
        typer.echo("Reproduction preflight failed:", err=True)
        for mismatch in mismatches:
            typer.echo(f"- {mismatch}", err=True)
        raise typer.Exit(code=1)
    completed = subprocess.run(
        manifest.reproduction_command,
        cwd=project_root,
        check=False,
    )
    if completed.returncode != 0:
        typer.echo(
            f"Reproduction command failed with exit code {completed.returncode}.",
            err=True,
        )
        raise typer.Exit(code=1)


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
