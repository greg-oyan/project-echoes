"""Deterministic, source-text-free reporting for Milestone 5 artifacts.

The report is derived from the persisted DuckDB passage views and explicit
validation, determinism, spot-check, and acceptance evidence supplied by the
caller.  It intentionally never selects reconstructed text, token surfaces,
lemmas, roots, glosses, or other bulk biblical content.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from echoes.segment.models import SegmentationMetadataRow

REQUIRED_REPORT_RELATIONS: frozenset[str] = frozenset(
    {
        "passages",
        "passage_membership",
        "segmentation_exclusions",
        "segmentation_issues",
        "segmentation_metadata",
    }
)

PASSAGE_COUNT_COLUMNS: tuple[str, ...] = (
    "corpus",
    "analysis_profile",
    "analysis_reading",
    "granularity",
    "book",
    "passage_count",
    "membership_rows",
    "reference_gap_count",
    "disputed_passage_count",
    "ketiv_uncertain_count",
    "sensitivity_exclusion_count",
)
REFERENCE_GAP_COLUMNS: tuple[str, ...] = (
    "passage_id",
    "corpus",
    "analysis_profile",
    "analysis_reading",
    "granularity",
    "book",
    "start_reference",
    "end_reference",
    "reference_sequence_json",
    "token_count",
)
DISPUTED_PASSAGE_COLUMNS: tuple[str, ...] = (
    "passage_id",
    "corpus",
    "analysis_profile",
    "analysis_reading",
    "granularity",
    "book",
    "start_reference",
    "end_reference",
    "disputed_passage_ids_json",
    "token_count",
)
KETIV_EXCLUSION_COLUMNS: tuple[str, ...] = (
    "exclusion_id",
    "analysis_profile",
    "granularity",
    "token_id",
    "locus_id",
    "source_reference",
    "reason_code",
    "resolution_status",
    "related_passage_ids_json",
    "source_id",
    "source_version",
)


class PassageReportError(RuntimeError):
    """Raised when persisted passage evidence cannot support a report."""


class PassageValidationEvidence(BaseModel):
    """Sanitized summary from the independent persisted-artifact validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    informational_count: int = Field(ge=0)


class PassageDeterminismEvidence(BaseModel):
    """Comparison result from two complete runs over identical inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_run_id: str = Field(min_length=1)
    second_run_id: str = Field(min_length=1)
    first_runtime_seconds: float = Field(ge=0)
    second_runtime_seconds: float = Field(ge=0)
    first_output_size_bytes: int = Field(ge=0)
    second_output_size_bytes: int = Field(ge=0)
    run_ids_match: bool
    logical_hashes_match: bool
    physical_hashes_match: bool
    input_digests_match: bool

    @property
    def passed(self) -> bool:
        """Whether every governed deterministic comparison matched."""

        return all(
            (
                self.run_ids_match,
                self.logical_hashes_match,
                self.physical_hashes_match,
                self.input_digests_match,
            )
        )


class PassagePartitionRuntime(BaseModel):
    """Optional measured runtime for one stream/granularity partition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus: str = Field(min_length=1)
    analysis_profile: str = Field(min_length=1)
    analysis_reading: str = Field(min_length=1)
    granularity: str = Field(min_length=1)
    runtime_seconds: float = Field(ge=0)


class PassageSpotCheckEvidence(BaseModel):
    """A source-text-free record of one manual or scripted passage check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    passage_id: str = Field(min_length=1)
    corpus: str = Field(min_length=1)
    analysis_profile: str = Field(min_length=1)
    analysis_reading: str = Field(min_length=1)
    granularity: str = Field(min_length=1)
    token_count: int = Field(ge=1)
    membership_count: int = Field(ge=1)
    verification_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_ids: str = Field(min_length=1)
    disputed_passage: bool
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    exclusion_count: int = Field(ge=0)
    neighbor_check: str = Field(min_length=1)
    status: str = Field(min_length=1)


class PassageAcceptanceEvidence(BaseModel):
    """One named Milestone 5 acceptance assertion and concise evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate: str = Field(min_length=1)
    passed: bool
    evidence: str = Field(min_length=1)


class PassageReportContext(BaseModel):
    """Non-artifact evidence required to make report status claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation: PassageValidationEvidence
    determinism: PassageDeterminismEvidence
    acceptance_checks: tuple[PassageAcceptanceEvidence, ...] = Field(min_length=1)
    spot_checks: tuple[PassageSpotCheckEvidence, ...] = ()
    partition_runtimes: tuple[PassagePartitionRuntime, ...] = ()
    known_limitations: tuple[str, ...] = ()
    adr_number: str = "0013"
    next_recommended_task: str = Field(min_length=1)

    @property
    def all_acceptance_gates_passed(self) -> bool:
        """Require explicit gate, validation, and determinism success."""

        return (
            self.validation.passed
            and self.determinism.passed
            and all(check.passed for check in self.acceptance_checks)
        )


@dataclass(frozen=True, slots=True)
class PassageReportData:
    """Sanitized aggregate evidence collected from persisted DuckDB views."""

    metadata: SegmentationMetadataRow
    stream_counts: pl.DataFrame
    book_counts: pl.DataFrame
    length_distributions: pl.DataFrame
    reference_gap_summary: pl.DataFrame
    reference_gap_passages: pl.DataFrame
    disputed_summary: pl.DataFrame
    disputed_passages: pl.DataFrame
    ketiv_uncertainty_summary: pl.DataFrame
    ketiv_resolution_summary: pl.DataFrame
    exclusion_summary: pl.DataFrame
    ketiv_exclusions: pl.DataFrame
    generation_issue_summary: pl.DataFrame


@dataclass(frozen=True, slots=True)
class PassageReportArtifacts:
    """Paths and content hashes for one deterministic report bundle."""

    report_path: Path
    csv_paths: tuple[Path, ...]
    sha256_by_name: dict[str, str]


def _query_frame(connection: duckdb.DuckDBPyConnection, query: str) -> pl.DataFrame:
    return connection.execute(query).pl()


def _relation_names(connection: duckdb.DuckDBPyConnection) -> set[str]:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _metadata(connection: duckdb.DuckDBPyConnection) -> SegmentationMetadataRow:
    cursor = connection.execute("SELECT * FROM segmentation_metadata")
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise PassageReportError(
            f"segmentation_metadata must contain exactly one row; found {len(rows)}"
        )
    columns = [str(description[0]) for description in cursor.description]
    return SegmentationMetadataRow.model_validate(dict(zip(columns, rows[0], strict=True)))


def collect_passage_report_data(database_path: Path) -> PassageReportData:
    """Collect only aggregate and identifier-level evidence from passage views."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            missing = sorted(REQUIRED_REPORT_RELATIONS - _relation_names(connection))
            if missing:
                raise PassageReportError(
                    "passage report database is missing required relations: " + ", ".join(missing)
                )
            metadata = _metadata(connection)
            stream_counts = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity,
                       CAST(count(*) AS BIGINT) AS passage_count,
                       CAST(sum(token_count) AS BIGINT) AS membership_rows,
                       CAST(count(*) FILTER (WHERE reference_gap) AS BIGINT)
                           AS reference_gap_count,
                       CAST(count(*) FILTER (WHERE disputed_passage_flag) AS BIGINT)
                           AS disputed_passage_count,
                       CAST(count(*) FILTER (WHERE ketiv_structural_uncertainty) AS BIGINT)
                           AS ketiv_uncertain_count,
                       CAST(sum(sensitivity_exclusion_count) AS BIGINT)
                           AS sensitivity_exclusion_count
                FROM passages
                GROUP BY corpus, analysis_profile, analysis_reading, granularity
                ORDER BY corpus, analysis_profile, analysis_reading, granularity
                """,
            )
            book_counts = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity, book,
                       CAST(count(*) AS BIGINT) AS passage_count,
                       CAST(sum(token_count) AS BIGINT) AS membership_rows,
                       CAST(count(*) FILTER (WHERE reference_gap) AS BIGINT)
                           AS reference_gap_count,
                       CAST(count(*) FILTER (WHERE disputed_passage_flag) AS BIGINT)
                           AS disputed_passage_count,
                       CAST(count(*) FILTER (WHERE ketiv_structural_uncertainty) AS BIGINT)
                           AS ketiv_uncertain_count,
                       CAST(sum(sensitivity_exclusion_count) AS BIGINT)
                           AS sensitivity_exclusion_count
                FROM passages
                GROUP BY corpus, analysis_profile, analysis_reading, granularity, book,
                         book_order
                ORDER BY corpus, analysis_profile, analysis_reading, granularity,
                         book_order, book
                """,
            )
            length_distributions = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity,
                       CAST(count(*) AS BIGINT) AS passage_count,
                       CAST(min(token_count) AS BIGINT) AS minimum,
                       round(avg(token_count), 3) AS mean,
                       CAST(quantile_cont(token_count, 0.25) AS BIGINT) AS p25,
                       CAST(quantile_cont(token_count, 0.50) AS BIGINT) AS median,
                       CAST(quantile_cont(token_count, 0.75) AS BIGINT) AS p75,
                       CAST(quantile_cont(token_count, 0.95) AS BIGINT) AS p95,
                       CAST(max(token_count) AS BIGINT) AS maximum
                FROM passages
                GROUP BY corpus, analysis_profile, analysis_reading, granularity
                ORDER BY corpus, analysis_profile, analysis_reading, granularity
                """,
            )
            reference_gap_summary = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity,
                       CAST(count(*) AS BIGINT) AS passage_count
                FROM passages WHERE reference_gap
                GROUP BY corpus, analysis_profile, analysis_reading, granularity
                ORDER BY corpus, analysis_profile, analysis_reading, granularity
                """,
            )
            reference_gap_passages = _query_frame(
                connection,
                """
                SELECT passage_id, corpus, analysis_profile, analysis_reading,
                       granularity, book, start_reference, end_reference,
                       reference_sequence_json, token_count
                FROM passages WHERE reference_gap
                ORDER BY corpus, analysis_profile, analysis_reading, granularity,
                         book_order, start_stream_position_in_corpus, passage_id
                """,
            )
            disputed_summary = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity,
                       CAST(count(*) AS BIGINT) AS passage_count
                FROM passages WHERE disputed_passage_flag
                GROUP BY corpus, analysis_profile, analysis_reading, granularity
                ORDER BY corpus, analysis_profile, analysis_reading, granularity
                """,
            )
            disputed_passages = _query_frame(
                connection,
                """
                SELECT passage_id, corpus, analysis_profile, analysis_reading,
                       granularity, book, start_reference, end_reference,
                       disputed_passage_ids_json, token_count
                FROM passages WHERE disputed_passage_flag
                ORDER BY corpus, analysis_profile, analysis_reading, granularity,
                         book_order, start_stream_position_in_corpus, passage_id
                """,
            )
            ketiv_uncertainty_summary = _query_frame(
                connection,
                """
                SELECT analysis_profile, granularity,
                       CAST(count(*) AS BIGINT) AS passage_count
                FROM passages
                WHERE corpus = 'hebrew' AND analysis_reading = 'ketiv'
                  AND ketiv_structural_uncertainty
                GROUP BY analysis_profile, granularity
                ORDER BY analysis_profile, granularity
                """,
            )
            ketiv_resolution_summary = _query_frame(
                connection,
                """
                SELECT structural_resolution_status,
                       CAST(count(DISTINCT token_id) AS BIGINT) AS token_count
                FROM passage_membership
                WHERE corpus = 'hebrew' AND analysis_profile = 'edition_complete'
                  AND analysis_reading = 'ketiv' AND granularity = 'verse'
                GROUP BY structural_resolution_status
                ORDER BY structural_resolution_status
                """,
            )
            exclusion_summary = _query_frame(
                connection,
                """
                SELECT corpus, analysis_profile, analysis_reading, granularity,
                       reason_code, resolution_status,
                       CAST(count(*) AS BIGINT) AS exclusion_count
                FROM segmentation_exclusions
                GROUP BY corpus, analysis_profile, analysis_reading, granularity,
                         reason_code, resolution_status
                ORDER BY corpus, analysis_profile, analysis_reading, granularity,
                         reason_code, resolution_status
                """,
            )
            ketiv_exclusions = _query_frame(
                connection,
                """
                SELECT exclusion_id, analysis_profile, granularity, token_id, locus_id,
                       source_reference, reason_code, resolution_status,
                       related_passage_ids_json, source_id, source_version
                FROM segmentation_exclusions
                WHERE corpus = 'hebrew' AND analysis_reading = 'ketiv'
                ORDER BY analysis_profile, granularity, source_reference,
                         token_id, exclusion_id
                """,
            )
            generation_issue_summary = _query_frame(
                connection,
                """
                SELECT severity, code, CAST(count(*) AS BIGINT) AS issue_count
                FROM segmentation_issues
                GROUP BY severity, code
                ORDER BY severity, code
                """,
            )
    except PassageReportError:
        raise
    except (duckdb.Error, OSError, ValueError) as exc:
        raise PassageReportError(
            f"could not collect persisted passage report evidence: {exc}"
        ) from exc
    return PassageReportData(
        metadata=metadata,
        stream_counts=stream_counts,
        book_counts=book_counts,
        length_distributions=length_distributions,
        reference_gap_summary=reference_gap_summary,
        reference_gap_passages=reference_gap_passages,
        disputed_summary=disputed_summary,
        disputed_passages=disputed_passages,
        ketiv_uncertainty_summary=ketiv_uncertainty_summary,
        ketiv_resolution_summary=ketiv_resolution_summary,
        exclusion_summary=exclusion_summary,
        ketiv_exclusions=ketiv_exclusions,
        generation_issue_summary=generation_issue_summary,
    )


def _json_mapping(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise PassageReportError("metadata field must encode a JSON object")
    return cast(dict[str, Any], parsed)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _markdown_cell(value: object) -> str:
    return _cell(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _markdown_frame(frame: pl.DataFrame, columns: tuple[str, ...]) -> list[str]:
    header = "| " + " | ".join(column.replace("_", " ") for column in columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    lines = [header, separator]
    lines.extend(
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in frame.select(columns).iter_rows()
    )
    if frame.is_empty():
        empty_cells = ("none" if index == 0 else "" for index in range(len(columns)))
        lines.append("| " + " | ".join(empty_cells) + " |")
    return lines


def _mapping_table(mapping: dict[str, Any], value_label: str) -> list[str]:
    lines = [f"| Item | {value_label} |", "|---|---|"]
    if not mapping:
        return [*lines, "| none | |"]
    for key in sorted(mapping):
        value = mapping[key]
        rendered = (
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value)
        )
        lines.append(f"| `{_markdown_cell(key)}` | `{_markdown_cell(rendered)}` |")
    return lines


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            return f"{amount:.3f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")


def _status(passed: bool) -> str:
    return "PASSED" if passed else "FAILED"


def render_passage_segmentation_report(
    data: PassageReportData,
    context: PassageReportContext,
) -> str:
    """Render the complete sanitized Milestone 5 Markdown report."""

    metadata = data.metadata
    source_versions = _json_mapping(metadata.input_source_versions_json)
    primary_digests = _json_mapping(metadata.input_primary_identity_digests_json)
    content_digests = _json_mapping(metadata.input_surface_lemma_digests_json)
    analytical_digests = _json_mapping(metadata.input_analytical_digests_json)
    supplement_digests = _json_mapping(metadata.input_oshb_supplement_digests_json)
    table_counts = _json_mapping(metadata.table_counts_json)
    logical_hashes = _json_mapping(metadata.table_logical_hashes_json)
    physical_hashes = _json_mapping(metadata.table_physical_hashes_json)

    lines = [
        "# Milestone 5 passage segmentation report",
        "",
        f"Status: **{_status(context.all_acceptance_gates_passed)}**",
        "",
        "This report contains aggregate counts, identifiers, references, provenance, and "
        "hashes. It intentionally contains no reconstructed biblical text, token surfaces, "
        "lemmas, roots, or glosses.",
        "",
        "## Objective",
        "",
        "Produce deterministic clause, sentence, verse, two-verse, and five-verse passage "
        "representations for the governed Hebrew/Aramaic and Greek analytical streams while "
        "preserving exact membership, source identity, disputed-text policy, reference gaps, "
        "and Ketiv structural uncertainty.",
        "",
        "## Architecture",
        "",
        "Validated immutable corpus inputs are transformed into one governed analytical stream "
        "at a time, segmented per book, reconstructed with language-aware rules, and written as "
        "deterministically sorted partitioned Parquet. DuckDB exposes the Parquet artifacts as "
        "external views, so source tables and the high-volume membership relation are not "
        "duplicated.",
        "",
        "Logical artifacts: `passages`, `passage_membership`, `passage_adjacency`, "
        "`segmentation_exclusions`, `segmentation_issues`, and `segmentation_metadata`.",
        "",
        "## ADR decision",
        "",
        f"ADR {context.adr_number} governs passage identity, authoritative membership, source "
        "succession versus analytical continuity, profile boundaries, reconstruction, Ketiv "
        "uncertainty, explicit exclusions, storage, and determinism. ADR 0011 remains binding "
        "for disputed passages and the Mark-ending boundary.",
        "",
        "## Input corpora and versions",
        "",
        *_mapping_table(source_versions, "Pinned version"),
        "",
        "### Input digest table",
        "",
        "#### Primary identity digests",
        "",
        *_mapping_table(primary_digests, "SHA-256"),
        "",
        "#### Surface and lemma digests",
        "",
        *_mapping_table(content_digests, "SHA-256"),
        "",
        "#### Analytical digests",
        "",
        *_mapping_table(analytical_digests, "SHA-256"),
        "",
        "#### OSHB supplement digests",
        "",
        *_mapping_table(supplement_digests, "SHA-256"),
        "",
        "## Passage schema",
        "",
        f"- Passage schema version: `{metadata.passage_schema_version}`",
        f"- Passage-ID schema version: `{metadata.passage_id_schema_version}`",
        f"- Segmentation configuration hash: `{metadata.segmentation_config_hash}`",
        f"- Segmentation run ID: `{metadata.segmentation_run_id}`",
        "- Passage rows hold identity, reference, reconstruction, provenance, dispute, gap, "
        "uncertainty, and neighbor-overlap fields.",
        "- Membership rows hold exact ordered token membership and structural-resolution evidence.",
        "",
        "## Passage-ID method",
        "",
        "A readable prefix is followed by the complete SHA-256 of canonical JSON containing the "
        "ID-schema version, corpus, profile, reading, granularity, book, scoped source-unit ID, "
        "ordered reference sequence, and ordered token IDs. Paths, timestamps, row order, and "
        "mutable crosswalks do not participate.",
        "",
        "## Membership model",
        "",
        "`passage_membership` is authoritative. One-based positions, stream order, membership "
        "basis, and structural-resolution status are auditable per token. Passage start/end token "
        "IDs are convenience fields only; reported membership-row totals equal the validated sum "
        "of passage token counts.",
        "",
        "## Analytical-stream combinations",
        "",
        *_markdown_frame(
            data.stream_counts,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "passage_count",
                "membership_rows",
            ),
        ),
        "",
        "## Profile behavior",
        "",
        "`edition_complete` retains all inline source text. `critical_core` excludes exactly "
        "Mark 16:9-20, Mark 16:99, and John 7:53-8:11 from Greek analytical membership without "
        "deleting or renumbering source tokens. Profile exclusions break window continuity. "
        "Edition-omitted verse numbers are never fabricated, and extant source-order windows "
        "that span an omission are marked as reference gaps.",
        "",
        "## Reconstruction method",
        "",
        "Hebrew and Aramaic reconstruction follows source word grouping, morpheme order, selected "
        "Qere/Ketiv reading, maqqef and punctuation behavior, and zero-width handling. Greek "
        "reconstruction follows leading punctuation, source surface form, trailing punctuation, "
        "elision metadata, and source order. Surface, normalized, Hebrew unpointed, and Greek "
        "folded forms remain separate.",
        "",
        "## Full passage counts",
        "",
        *_markdown_frame(
            data.stream_counts,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "passage_count",
                "membership_rows",
                "reference_gap_count",
                "disputed_passage_count",
                "ketiv_uncertain_count",
                "sensitivity_exclusion_count",
            ),
        ),
        "",
        "### Counts by book",
        "",
        "The same deterministic rows are written to `m5-passage-counts.csv`.",
        "",
        *_markdown_frame(data.book_counts, PASSAGE_COUNT_COLUMNS),
        "",
        "## Passage-length distributions",
        "",
        *_markdown_frame(
            data.length_distributions,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "passage_count",
                "minimum",
                "mean",
                "p25",
                "median",
                "p75",
                "p95",
                "maximum",
            ),
        ),
        "",
        "## Reference-gap analysis",
        "",
        *_markdown_frame(
            data.reference_gap_summary,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "passage_count",
            ),
        ),
        "",
        "The identifier-level audit rows are in `m5-reference-gap-passages.csv`; no omitted "
        "verse record or reconstructed text is included.",
        "",
        "## Disputed-passage analysis",
        "",
        *_markdown_frame(
            data.disputed_summary,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "passage_count",
            ),
        ),
        "",
        "The identifier-level audit rows are in `m5-disputed-passages.csv`.",
        "",
        "## Ketiv structural-resolution analysis",
        "",
        "### Uncertain passages",
        "",
        *_markdown_frame(
            data.ketiv_uncertainty_summary,
            ("analysis_profile", "granularity", "passage_count"),
        ),
        "",
        "### Distinct Ketiv-stream token resolution statuses",
        "",
        *_markdown_frame(
            data.ketiv_resolution_summary,
            ("structural_resolution_status", "token_count"),
        ),
        "",
        "Unresolved clause membership is never fabricated. Every affected token remains in "
        "verse analysis and receives an explicit granularity-specific exclusion where required.",
        "",
        "## Explicit exclusion counts",
        "",
        *_markdown_frame(
            data.exclusion_summary,
            (
                "corpus",
                "analysis_profile",
                "analysis_reading",
                "granularity",
                "reason_code",
                "resolution_status",
                "exclusion_count",
            ),
        ),
        "",
        "Identifier-level Ketiv exclusion evidence is in `m5-ketiv-structural-exclusions.csv`.",
        "",
        "## Determinism results",
        "",
        f"- Overall: **{_status(context.determinism.passed)}**",
        f"- First run ID: `{context.determinism.first_run_id}`",
        f"- Second run ID: `{context.determinism.second_run_id}`",
        f"- Run IDs match: `{str(context.determinism.run_ids_match).lower()}`",
        f"- Logical hashes match: `{str(context.determinism.logical_hashes_match).lower()}`",
        f"- Physical hashes match: `{str(context.determinism.physical_hashes_match).lower()}`",
        f"- Input digests match: `{str(context.determinism.input_digests_match).lower()}`",
        "",
        "## Logical and physical output hashes",
        "",
        "### Logical table hashes",
        "",
        *_mapping_table(logical_hashes, "SHA-256"),
        "",
        "### Physical table hashes",
        "",
        *_mapping_table(physical_hashes, "SHA-256"),
        "",
        "## Runtime and storage footprint",
        "",
        f"- First full run: {context.determinism.first_runtime_seconds:.6f} seconds; "
        f"{_format_bytes(context.determinism.first_output_size_bytes)}",
        f"- Second full run: {context.determinism.second_runtime_seconds:.6f} seconds; "
        f"{_format_bytes(context.determinism.second_output_size_bytes)}",
        f"- Persisted current-run metadata: {metadata.runtime_seconds:.6f} seconds; "
        f"{_format_bytes(metadata.output_size_bytes)}",
        "",
        "### Runtime by corpus, profile, reading, and granularity",
        "",
    ]
    if context.partition_runtimes:
        runtime_frame = pl.DataFrame(
            [runtime.model_dump(mode="python") for runtime in context.partition_runtimes]
        ).sort(["corpus", "analysis_profile", "analysis_reading", "granularity"])
        lines.extend(
            _markdown_frame(
                runtime_frame,
                (
                    "corpus",
                    "analysis_profile",
                    "analysis_reading",
                    "granularity",
                    "runtime_seconds",
                ),
            )
        )
    else:
        lines.append("No partition-level runtime evidence was supplied.")
    lines.extend(
        [
            "",
            "### Logical table row counts",
            "",
            *_mapping_table(table_counts, "Rows"),
            "",
            "## Validation results",
            "",
            f"- Persisted-artifact validation: **{_status(context.validation.passed)}**",
            f"- Errors: {context.validation.error_count}",
            f"- Warnings: {context.validation.warning_count}",
            f"- Informational findings: {context.validation.informational_count}",
            "",
            "### Generation issue inventory",
            "",
            *_markdown_frame(
                data.generation_issue_summary,
                ("severity", "code", "issue_count"),
            ),
            "",
            "## Manual and scripted spot checks",
            "",
        ]
    )
    spot_columns = (
        "check_id",
        "category",
        "reference",
        "passage_id",
        "corpus",
        "analysis_profile",
        "analysis_reading",
        "granularity",
        "token_count",
        "membership_count",
        "verification_sha256",
        "source_ids",
        "disputed_passage",
        "reference_gap",
        "ketiv_structural_uncertainty",
        "exclusion_count",
        "neighbor_check",
        "status",
    )
    if context.spot_checks:
        spot_frame = pl.DataFrame(
            [spot.model_dump(mode="python") for spot in context.spot_checks]
        ).sort("check_id")
        lines.extend(_markdown_frame(spot_frame, spot_columns))
    else:
        lines.append("No spot-check evidence was supplied.")
    lines.extend(["", "## Known limitations", ""])
    if context.known_limitations:
        lines.extend(f"- {limitation}" for limitation in context.known_limitations)
    else:
        lines.append("- None recorded for this report bundle.")
    lines.extend(
        [
            "",
            "## Acceptance gate",
            "",
            "| Gate | Status | Evidence |",
            "|---|---|---|",
        ]
    )
    lines.extend(
        f"| {_markdown_cell(check.gate)} | {_status(check.passed)} | "
        f"{_markdown_cell(check.evidence)} |"
        for check in context.acceptance_checks
    )
    lines.extend(
        [
            "",
            "Every Milestone 5 acceptance gate passed."
            if context.all_acceptance_gates_passed
            else "At least one Milestone 5 acceptance gate remains unmet.",
            "",
            "## Exact next recommended task",
            "",
            context.next_recommended_task,
            "",
        ]
    )
    return "\n".join(lines)


def _csv_text(frame: pl.DataFrame, columns: tuple[str, ...]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in frame.select(columns).iter_rows():
        writer.writerow(_cell(value) for value in row)
    return buffer.getvalue()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_passage_segmentation_report(
    data: PassageReportData,
    context: PassageReportContext,
    output_directory: Path,
) -> PassageReportArtifacts:
    """Write the Markdown report and four deterministic sanitized CSVs."""

    output_directory.mkdir(parents=True, exist_ok=True)
    payloads = {
        "milestone-5-passage-segmentation-report.md": render_passage_segmentation_report(
            data, context
        ),
        "m5-passage-counts.csv": _csv_text(data.book_counts, PASSAGE_COUNT_COLUMNS),
        "m5-reference-gap-passages.csv": _csv_text(
            data.reference_gap_passages, REFERENCE_GAP_COLUMNS
        ),
        "m5-disputed-passages.csv": _csv_text(data.disputed_passages, DISPUTED_PASSAGE_COLUMNS),
        "m5-ketiv-structural-exclusions.csv": _csv_text(
            data.ketiv_exclusions, KETIV_EXCLUSION_COLUMNS
        ),
    }
    paths: list[Path] = []
    hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        normalized = payload if payload.endswith("\n") else payload + "\n"
        target = output_directory / name
        target.write_text(normalized, encoding="utf-8", newline="\n")
        paths.append(target)
        hashes[name] = _sha256_text(normalized)
    report_path = paths[0]
    return PassageReportArtifacts(
        report_path=report_path,
        csv_paths=tuple(paths[1:]),
        sha256_by_name=hashes,
    )
