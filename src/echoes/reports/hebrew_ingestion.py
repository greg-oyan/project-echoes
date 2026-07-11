"""Sanitized Milestone 2 ingestion-report rendering."""

from __future__ import annotations

import platform
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from echoes.corpus.hebrew import HebrewPipelineResult
from echoes.corpus.models import ValidationSeverity


class ManualSpotCheck(BaseModel):
    """Recorded human judgment for one configured reference without source text."""

    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: str = Field(min_length=1)
    details: str = Field(min_length=1)


def _percent(populated: int, total: int) -> str:
    return f"{(populated / total) * 100:.4f}%" if total else "0.0000%"


def render_hebrew_ingestion_report(
    result: HebrewPipelineResult,
    *,
    determinism_notes: list[str],
    spot_checks: list[ManualSpotCheck],
) -> str:
    """Render metadata, statistics, findings, and manual checks without corpus text."""
    summary = result.summary
    validation = result.validation
    completeness = validation.completeness
    errors = [issue for issue in validation.issues if issue.severity is ValidationSeverity.ERROR]
    warnings = [
        issue for issue in validation.issues if issue.severity is ValidationSeverity.WARNING
    ]
    acquisition_method = (
        result.source.acquisition.method if result.source.acquisition is not None else "unknown"
    )
    lines = [
        "# Milestone 2 Hebrew ingestion report",
        "",
        "Status: **PASSED**" if validation.passed else "Status: **FAILED**",
        "",
        "This report contains provenance, hashes, aggregate statistics, and validation findings. "
        "It intentionally contains no biblical source text or gloss quotations.",
        "",
        "## Source and acquisition",
        "",
        f"- Source: {result.source.source_name}",
        f"- Edition: {result.source.edition}",
        f"- Release label: {result.receipt.version_label}",
        f"- Commit: `{result.receipt.upstream_commit}`",
        f"- License: {result.source.license}",
        f"- Redistribution policy: `{result.source.redistribution_status.value}`",
        f"- Acquisition method: `{acquisition_method}`",
        f"- Acquisition timestamp: `{result.receipt.acquired_at.isoformat()}`",
        f"- Acquisition command: `{result.receipt.acquisition_command}`",
        f"- Tool version: `{result.receipt.tool_version}`",
        "",
        "### Acquired-file SHA-256 inventory",
        "",
        "| Relative file | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    lines.extend(
        f"| `{item.relative_path}` | {item.size_bytes} | `{item.sha256}` |"
        for item in result.receipt.files
    )
    lines.extend(
        [
            "",
            "## Ingestion and schema",
            "",
            f"- Ingestion run ID: `{validation.ingestion_run_id}`",
            f"- Canonical schema version: `{validation.schema_version}`",
            f"- Normalization configuration hash: `{validation.normalization_config_hash}`",
            f"- Source records: {validation.total_source_records}",
            f"- Processed tokens: {summary.total_tokens}",
            f"- Books: {summary.total_books}",
            f"- Chapters: {validation.chapter_count}",
            f"- Verses: {validation.verse_count}",
            f"- Hebrew tokens: {summary.hebrew_tokens}",
            f"- Aramaic tokens: {summary.aramaic_tokens}",
            f"- Ketiv/Qere-marked tokens: {summary.ketiv_qere_count}",
            f"- Variant tokens: {summary.variant_count}",
            f"- Punctuation tokens: {summary.punctuation_count}",
            f"- Processing time: {result.processing_seconds:.3f} seconds",
            "",
            "### Tokens by book",
            "",
            "| Book | Tokens |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| {book} | {count} |" for book, count in summary.tokens_by_book.items())
    total = summary.total_tokens
    lines.extend(
        [
            "",
            "## Annotation completeness",
            "",
            "| Annotation | Populated | Missing | Coverage |",
            "|---|---:|---:|---:|",
        ]
    )
    for label in ("lemma", "morphology", "syntax", "semantic_domain", "participant", "gloss"):
        missing = int(completeness[f"missing_{label}"])
        lines.append(
            f"| {label} | {total - missing} | {missing} | {_percent(total - missing, total)} |"
        )
    lines.extend(
        [
            "",
            "## Validation",
            "",
            f"- Errors: {len(errors)}",
            f"- Warnings: {len(warnings)}",
            f"- Informational findings: {len(validation.issues) - len(errors) - len(warnings)}",
            "",
        ]
    )
    for issue in [*errors, *warnings]:
        lines.append(f"- **{issue.severity.value} / {issue.code}:** {issue.message}")
    if not errors and not warnings:
        lines.append("- No validation errors or warnings.")
    lines.extend(["", "## Determinism", ""])
    lines.extend(f"- {note}" for note in determinism_notes)
    lines.extend(
        [
            "",
            "## Manual spot checks",
            "",
            "| Reference | Category | Status | Recorded judgment |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {check.reference} | {check.category} | {check.status} | {check.details} |"
        for check in spot_checks
    )
    lines.extend(
        [
            "",
            "## Local environment",
            "",
            f"- Python: `{platform.python_version()}`",
            f"- Operating system: `{platform.system()} {platform.release()}`",
            f"- Machine: `{platform.machine()}`",
            "",
            "## Known limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in result.source.known_limitations)
    lines.extend(
        [
            "",
            "## Acceptance gate",
            "",
            (
                "The Milestone 2 acceptance gate passed."
                if validation.passed
                else "The Milestone 2 acceptance gate did not pass."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_hebrew_ingestion_report(
    result: HebrewPipelineResult,
    path: Path,
    *,
    determinism_notes: list[str],
    spot_checks: list[ManualSpotCheck],
) -> None:
    """Write the sanitized report to its tracked documentation location."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_hebrew_ingestion_report(
            result,
            determinism_notes=determinism_notes,
            spot_checks=spot_checks,
        ),
        encoding="utf-8",
    )
