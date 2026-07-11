"""End-to-end governed Hebrew acquisition verification, ingestion, and validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from echoes.acquire import AcquisitionReceipt, verify_acquisition
from echoes.corpus.storage import (
    PARQUET_FILES,
    CorpusSummary,
    ProcessedCorpus,
    corpus_summary,
    load_hebrew_duckdb,
)
from echoes.corpus.validation import CorpusValidationReport, validate_hebrew_corpus
from echoes.ingest.macula_hebrew import IngestionSummary
from echoes.manifests.sources import SourceManifest, load_source_catalog
from echoes.settings import HebrewIngestionConfig, NormalizationConfig, load_config


class HebrewPipelineError(RuntimeError):
    """Raised when Hebrew pipeline configuration or source governance is inconsistent."""


@dataclass(frozen=True, slots=True)
class HebrewPipelineResult:
    source: SourceManifest
    receipt: AcquisitionReceipt
    adapter_summary: IngestionSummary
    processed: ProcessedCorpus
    validation: CorpusValidationReport
    summary: CorpusSummary
    processing_seconds: float


def load_hebrew_source(manifest_path: Path) -> SourceManifest:
    """Load the single governed MACULA Hebrew source declaration."""
    source = load_source_catalog(manifest_path).find("macula-hebrew")
    if source is None:
        raise HebrewPipelineError("source manifest does not define macula-hebrew")
    return source


def load_hebrew_configs(config_dir: Path) -> tuple[NormalizationConfig, HebrewIngestionConfig]:
    """Load and type-check active normalization and full-corpus expectations."""
    normalization = load_config(config_dir / "normalization.yaml")
    ingestion = load_config(config_dir / "hebrew_ingestion.yaml")
    if not isinstance(normalization, NormalizationConfig):
        raise HebrewPipelineError("normalization.yaml loaded with an unexpected schema")
    if not isinstance(ingestion, HebrewIngestionConfig):
        raise HebrewPipelineError("hebrew_ingestion.yaml loaded with an unexpected schema")
    if ingestion.status != "ready":
        raise HebrewPipelineError("Hebrew ingestion configuration is not ready")
    return normalization, ingestion


def default_processed_directory(source: SourceManifest, data_root: Path) -> Path:
    """Return the safe versioned processed path for the approved source."""
    if source.acquisition is None:
        raise HebrewPipelineError("macula-hebrew has no acquisition version label")
    return data_root / "processed" / source.source_id / source.acquisition.version_label


def ingest_hebrew_corpus(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    config_dir: Path = Path("config"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
    force: bool = False,
) -> HebrewPipelineResult:
    """Verify the pinned acquisition, transform it, store it, and run the full gate."""
    started = perf_counter()
    source = load_hebrew_source(manifest_path)
    normalization, ingestion = load_hebrew_configs(config_dir)
    _, receipt = verify_acquisition(source, data_root=data_root)
    resolved_output = output_dir or default_processed_directory(source, data_root)
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    worker_command = [
        sys.executable,
        "-m",
        "echoes.corpus.hebrew_worker",
        "--manifest-path",
        str(manifest_path.resolve()),
        "--config-dir",
        str(config_dir.resolve()),
        "--data-root",
        str(data_root.resolve()),
        "--output-dir",
        str(resolved_output.resolve()),
    ]
    if force:
        worker_command.append("--force")
    worker_environment = os.environ.copy()
    worker_environment["PYTHONUTF8"] = "1"
    worker = subprocess.run(
        worker_command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=worker_environment,
    )
    if worker.returncode != 0:
        detail = worker.stderr.strip() or worker.stdout.strip() or "unknown worker failure"
        raise HebrewPipelineError(f"isolated Parquet worker failed: {detail}")
    try:
        payload = json.loads(worker.stdout.strip().splitlines()[-1])
        adapter_summary = IngestionSummary.model_validate(payload["adapter_summary"])
        processed = ProcessedCorpus(
            output_dir=resolved_output,
            run_id=str(payload["run_id"]),
            parquet_paths={
                name: resolved_output / filename for name, filename in PARQUET_FILES.items()
            },
            file_hashes={str(key): str(value) for key, value in payload["file_hashes"].items()},
            logical_hashes={
                str(key): str(value) for key, value in payload["logical_hashes"].items()
            },
        )
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HebrewPipelineError(f"invalid isolated worker result: {exc}") from exc
    load_hebrew_duckdb(processed, resolved_database)
    validation = validate_hebrew_corpus(
        resolved_output,
        database_path=resolved_database,
        normalization=normalization.hebrew,
        analysis_reading=normalization.ketiv_qere.analysis_reading,
        expected_books=ingestion.expected_books,
        expected_chapters=ingestion.expected_chapters,
        expected_tokens=ingestion.expected_tokens,
    )
    summary = corpus_summary(resolved_database)
    return HebrewPipelineResult(
        source=source,
        receipt=receipt,
        adapter_summary=adapter_summary,
        processed=processed,
        validation=validation,
        summary=summary,
        processing_seconds=round(perf_counter() - started, 6),
    )


def validate_existing_hebrew_corpus(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    config_dir: Path = Path("config"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
) -> CorpusValidationReport:
    """Validate an existing processed corpus without downloading or rewriting it."""
    source = load_hebrew_source(manifest_path)
    normalization, ingestion = load_hebrew_configs(config_dir)
    resolved_output = output_dir or default_processed_directory(source, data_root)
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    return validate_hebrew_corpus(
        resolved_output,
        database_path=resolved_database,
        normalization=normalization.hebrew,
        analysis_reading=normalization.ketiv_qere.analysis_reading,
        expected_books=ingestion.expected_books,
        expected_chapters=ingestion.expected_chapters,
        expected_tokens=ingestion.expected_tokens,
    )
