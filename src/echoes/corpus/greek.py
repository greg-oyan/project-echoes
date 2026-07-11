"""End-to-end governed Greek acquisition verification, ingestion, and validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from echoes.acquire import AcquisitionReceipt, verify_acquisition
from echoes.corpus.greek_storage import (
    GREEK_PARQUET_FILES,
    GreekCorpusSummary,
    ProcessedGreekCorpus,
    greek_corpus_summary,
    load_greek_duckdb,
)
from echoes.corpus.greek_validation import validate_greek_corpus
from echoes.corpus.validation import CorpusValidationReport
from echoes.ingest.macula_greek import GreekIngestionSummary
from echoes.manifests.sources import SourceManifest, load_source_catalog
from echoes.settings import GreekIngestionConfig, NormalizationConfig, load_config


class GreekPipelineError(RuntimeError):
    """Raised when Greek pipeline configuration or source governance is inconsistent."""


@dataclass(frozen=True, slots=True)
class GreekPipelineResult:
    source: SourceManifest
    receipt: AcquisitionReceipt
    adapter_summary: GreekIngestionSummary
    processed: ProcessedGreekCorpus
    validation: CorpusValidationReport
    summary: GreekCorpusSummary
    processing_seconds: float


def load_greek_source(manifest_path: Path) -> SourceManifest:
    """Load the single governed MACULA Greek source declaration."""
    source = load_source_catalog(manifest_path).find("macula-greek")
    if source is None:
        raise GreekPipelineError("source manifest does not define macula-greek")
    return source


def load_greek_configs(config_dir: Path) -> tuple[NormalizationConfig, GreekIngestionConfig]:
    """Load and type-check active normalization and full-corpus expectations."""
    normalization = load_config(config_dir / "normalization.yaml")
    ingestion = load_config(config_dir / "greek_ingestion.yaml")
    if not isinstance(normalization, NormalizationConfig):
        raise GreekPipelineError("normalization.yaml loaded with an unexpected schema")
    if not isinstance(ingestion, GreekIngestionConfig):
        raise GreekPipelineError("greek_ingestion.yaml loaded with an unexpected schema")
    if ingestion.status != "ready":
        raise GreekPipelineError("Greek ingestion configuration is not ready")
    return normalization, ingestion


def default_greek_processed_directory(source: SourceManifest, data_root: Path) -> Path:
    """Return the safe versioned processed path for the approved source."""
    if source.acquisition is None:
        raise GreekPipelineError("macula-greek has no acquisition version label")
    return data_root / "processed" / source.source_id / source.acquisition.version_label


def ingest_greek_corpus(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    config_dir: Path = Path("config"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
    force: bool = False,
) -> GreekPipelineResult:
    """Verify the pinned acquisition, transform it, store it, and run the full gate."""
    started = perf_counter()
    source = load_greek_source(manifest_path)
    normalization, ingestion = load_greek_configs(config_dir)
    _, receipt = verify_acquisition(source, data_root=data_root)
    resolved_output = output_dir or default_greek_processed_directory(source, data_root)
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    worker_command = [
        sys.executable,
        "-m",
        "echoes.corpus.greek_worker",
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
        raise GreekPipelineError(f"isolated Parquet worker failed: {detail}")
    try:
        payload = json.loads(worker.stdout.strip().splitlines()[-1])
        adapter_summary = GreekIngestionSummary.model_validate(payload["adapter_summary"])
        processed = ProcessedGreekCorpus(
            output_dir=resolved_output,
            run_id=str(payload["run_id"]),
            parquet_paths={
                name: resolved_output / filename for name, filename in GREEK_PARQUET_FILES.items()
            },
            file_hashes={str(key): str(value) for key, value in payload["file_hashes"].items()},
            logical_hashes={
                str(key): str(value) for key, value in payload["logical_hashes"].items()
            },
        )
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GreekPipelineError(f"invalid isolated worker result: {exc}") from exc
    load_greek_duckdb(processed, resolved_database)
    validation = validate_greek_corpus(
        resolved_output,
        database_path=resolved_database,
        normalization=normalization.greek,
        expected_books=ingestion.expected_books,
        expected_chapters=ingestion.expected_chapters,
        expected_tokens=ingestion.expected_tokens,
        expected_missing_verses=ingestion.expected_missing_verses,
        expected_out_of_sequence_verses=ingestion.expected_out_of_sequence_verses,
    )
    summary = greek_corpus_summary(resolved_database)
    return GreekPipelineResult(
        source=source,
        receipt=receipt,
        adapter_summary=adapter_summary,
        processed=processed,
        validation=validation,
        summary=summary,
        processing_seconds=round(perf_counter() - started, 6),
    )


def validate_existing_greek_corpus(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    config_dir: Path = Path("config"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
) -> CorpusValidationReport:
    """Validate an existing processed corpus without downloading or rewriting it."""
    source = load_greek_source(manifest_path)
    normalization, ingestion = load_greek_configs(config_dir)
    resolved_output = output_dir or default_greek_processed_directory(source, data_root)
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    return validate_greek_corpus(
        resolved_output,
        database_path=resolved_database,
        normalization=normalization.greek,
        expected_books=ingestion.expected_books,
        expected_chapters=ingestion.expected_chapters,
        expected_tokens=ingestion.expected_tokens,
        expected_missing_verses=ingestion.expected_missing_verses,
        expected_out_of_sequence_verses=ingestion.expected_out_of_sequence_verses,
    )
