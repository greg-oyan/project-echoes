"""Generate sanitized Milestone 6 benchmark reports from governed artifacts."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal, cast

import duckdb
from generate_m6_spot_check_evidence import generate_spot_check_evidence

from echoes.benchmarks.models import BENCHMARK_ARTIFACT_NAMES
from echoes.benchmarks.tier1 import validate_tier1_quotations

DEFAULT_DATABASE = Path("data/processed/project_echoes.duckdb")
DEFAULT_SCHEMA_ROOT = Path("data/processed/benchmarks/schema-v1")
DEFAULT_OUTPUT_DIR = Path("outputs/reports")
DEFAULT_TIER1 = Path("data/benchmarks/tier1_quotations.csv")
DEFAULT_SPOT_CONFIG = Path("outputs/reports/m6-spot-check-config.json")

AcceptanceStatus = Literal["pending", "passed", "failed"]
GateStatus = Literal["pending", "passed", "failed"]


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    _atomic_text(path, buffer.getvalue())


def _rows(
    connection: duckdb.DuckDBPyConnection, sql: str, parameters: Sequence[object] = ()
) -> list[tuple[object, ...]]:
    return cast(list[tuple[object, ...]], connection.execute(sql, list(parameters)).fetchall())


def _scalar(
    connection: duckdb.DuckDBPyConnection, sql: str, parameters: Sequence[object] = ()
) -> object:
    row = cast(tuple[object, ...] | None, connection.execute(sql, list(parameters)).fetchone())
    if row is None:
        raise ValueError(f"query returned no aggregate row: {sql}")
    return row[0]


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError(f"expected integer query result, received {type(value).__name__}")
    return value


def _object(value: object) -> dict[str, Any]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("benchmark metadata JSON must contain an object")
    return cast(dict[str, Any], parsed)


def _metadata(connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    cursor = connection.execute("SELECT * FROM benchmark_metadata")
    rows = cast(list[tuple[object, ...]], cursor.fetchall())
    if len(rows) != 1:
        raise ValueError(f"benchmark_metadata must contain exactly one row; observed {len(rows)}")
    description = cursor.description
    if description is None:
        raise ValueError("benchmark metadata has no column description")
    names = [str(item[0]) for item in description]
    return dict(zip(names, rows[0], strict=True))


def _load_hash_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"hash manifest must contain an object: {path}")
    return cast(dict[str, Any], payload)


def _pr6_merge_commit(explicit: str | None) -> str:
    if explicit:
        return explicit
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--merges",
            "--grep=Merge pull request #6",
            "--format=%H",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    commit = result.stdout.strip()
    if not commit:
        raise ValueError("could not identify the PR #6 merge commit")
    return commit


def _markdown_table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    rendered = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    rendered.extend(
        "| "
        + " | ".join(
            str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ") for value in row
        )
        + " |"
        for row in rows
    )
    return rendered


def _table_counts(connection: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    tables = (
        "benchmark_source_records",
        "benchmark_relationships",
        "benchmark_relationship_source_records",
        "benchmark_endpoints",
        "benchmark_endpoint_mappings",
        "benchmark_leakage_groups",
        "benchmark_split_assignments",
        "benchmark_presumed_negatives",
        "benchmark_issues",
        "benchmark_metadata",
    )
    return [
        (table, _integer(_scalar(connection, f'SELECT count(*) FROM "{table}"')))
        for table in tables
    ]


def _write_supporting_csvs(
    connection: duckdb.DuckDBPyConnection,
    *,
    output_dir: Path,
    source_audit: dict[str, Any],
    tier1_rows: int,
) -> dict[str, list[tuple[object, ...]]]:
    counts: list[tuple[object, ...]] = [(name, count) for name, count in _table_counts(connection)]
    for key in (
        "raw_row_count",
        "parsed_row_count",
        "invalid_row_count",
        "exact_duplicate_occurrence_count",
        "duplicate_directed_pair_count",
        "unique_directed_relationship_count",
        "unique_unordered_pair_count",
        "reverse_pair_count",
        "self_link_count",
        "negative_weight_count",
        "zero_weight_count",
        "positive_weight_count",
        "distinct_weight_count",
    ):
        counts.append((f"source_audit.{key}", source_audit.get(key)))
    corpus_rows: list[tuple[object, ...]] = [
        (
            "old_testament_to_old_testament",
            _scalar(connection, "SELECT count(*) FROM within_old_testament_relationships"),
        ),
        (
            "new_testament_to_new_testament",
            _scalar(connection, "SELECT count(*) FROM within_new_testament_relationships"),
        ),
        (
            "cross_testament",
            _scalar(connection, "SELECT count(*) FROM cross_testament_relationships"),
        ),
    ]
    counts.extend((f"corpus_pair.{name}", value) for name, value in corpus_rows)
    counts.append(("tier1.data_rows", tier1_rows))
    _atomic_csv(output_dir / "m6-benchmark-counts.csv", ("measure", "value"), counts)

    mapping_rows = _rows(
        connection,
        """
        SELECT target_analysis_profile,target_corpus,mapping_status,mapping_confidence,
               count(*) AS mapping_count
        FROM benchmark_endpoint_mappings
        GROUP BY ALL ORDER BY ALL
        """,
    )
    _atomic_csv(
        output_dir / "m6-mapping-status.csv",
        ("analysis_profile", "target_corpus", "mapping_status", "mapping_confidence", "count"),
        mapping_rows,
    )

    risk_rows = _rows(
        connection,
        """
        SELECT coalesce(e.parsed_book,'unresolved') AS book,
               m.target_analysis_profile,m.mapping_status,m.mapping_confidence,
               m.reference_gap,m.disputed_passage_flag,
               CASE
                 WHEN m.reference_gap THEN 'reference_gap'
                 WHEN m.disputed_passage_flag THEN 'disputed_passage'
                 WHEN m.mapping_status='mapped_provisional' THEN 'provisional_same_label'
                 ELSE m.mapping_status
               END AS risk_type,
               count(*) AS endpoint_count
        FROM benchmark_endpoint_mappings m
        JOIN benchmark_endpoints e USING(endpoint_id)
        WHERE m.mapping_status NOT IN ('mapped_verified')
           OR m.reference_gap OR m.disputed_passage_flag
        GROUP BY ALL ORDER BY ALL
        """,
    )
    _atomic_csv(
        output_dir / "m6-versification-risks.csv",
        (
            "book",
            "analysis_profile",
            "mapping_status",
            "mapping_confidence",
            "reference_gap",
            "disputed_passage",
            "risk_type",
            "endpoint_count",
        ),
        risk_rows,
    )

    risk_reference_rows = _rows(
        connection,
        """
        WITH aggregated AS (
          SELECT coalesce(e.parsed_book,'unresolved') AS book,
                 e.source_reference,
                 m.target_analysis_profile,m.mapping_status,m.mapping_confidence,
                 m.reference_gap,m.disputed_passage_flag,
                 CASE
                   WHEN m.reference_gap THEN 'reference_gap'
                   WHEN m.disputed_passage_flag THEN 'disputed_passage'
                   WHEN m.mapping_status='mapped_provisional' THEN 'provisional_same_label'
                   ELSE m.mapping_status
                 END AS risk_type,
                 count(*) AS endpoint_count
          FROM benchmark_endpoint_mappings m
          JOIN benchmark_endpoints e USING(endpoint_id)
          WHERE m.mapping_status NOT IN ('mapped_verified')
             OR m.reference_gap OR m.disputed_passage_flag
          GROUP BY ALL
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY book,target_analysis_profile,risk_type
            ORDER BY source_reference,mapping_status,mapping_confidence,
                     reference_gap,disputed_passage_flag
          ) AS sample_ordinal
          FROM aggregated
        )
        SELECT book,source_reference,target_analysis_profile,mapping_status,
               mapping_confidence,reference_gap,disputed_passage_flag,risk_type,
               endpoint_count,sample_ordinal
        FROM ranked WHERE sample_ordinal<=3
        ORDER BY book,target_analysis_profile,risk_type,sample_ordinal
        """,
    )
    _atomic_csv(
        output_dir / "m6-versification-risk-references.csv",
        (
            "book",
            "source_reference",
            "analysis_profile",
            "mapping_status",
            "mapping_confidence",
            "reference_gap",
            "disputed_passage",
            "risk_type",
            "endpoint_count",
            "sample_ordinal",
        ),
        risk_reference_rows,
    )

    split_rows = _rows(
        connection,
        """
        SELECT split_strategy,partition,eligibility_status,
               coalesce(exclusion_reason,'') AS exclusion_reason,count(*) AS assignment_count
        FROM benchmark_split_assignments GROUP BY ALL ORDER BY ALL
        """,
    )
    _atomic_csv(
        output_dir / "m6-split-counts.csv",
        ("split_strategy", "partition", "eligibility_status", "exclusion_reason", "count"),
        split_rows,
    )

    negative_rows = _rows(
        connection,
        """
        SELECT negative_strategy,split_strategy,partition,count(*) AS negative_count
        FROM benchmark_presumed_negatives GROUP BY ALL ORDER BY ALL
        """,
    )
    _atomic_csv(
        output_dir / "m6-presumed-negative-counts.csv",
        ("negative_strategy", "split_strategy", "partition", "count"),
        negative_rows,
    )
    return {
        "counts": counts,
        "corpus": corpus_rows,
        "mapping": mapping_rows,
        "risks": risk_rows,
        "risk_references": risk_reference_rows,
        "splits": split_rows,
        "negatives": negative_rows,
    }


def _determinism(
    current: dict[str, Any], first_path: Path | None
) -> tuple[str, list[tuple[object, ...]]]:
    if first_path is None:
        return "pending: no first-run hash manifest was supplied", []
    first = _load_hash_manifest(first_path)
    current_logical = cast(dict[str, object], current.get("table_logical_sha256", {}))
    first_logical = cast(dict[str, object], first.get("table_logical_sha256", {}))
    current_physical = cast(dict[str, object], current.get("table_physical_sha256", {}))
    first_physical = cast(dict[str, object], first.get("table_physical_sha256", {}))
    names = sorted(
        set(current_logical) | set(first_logical) | set(current_physical) | set(first_physical)
    )
    rows: list[tuple[object, ...]] = [
        (
            name,
            first_logical.get(name),
            current_logical.get(name),
            first_logical.get(name) == current_logical.get(name),
            first_physical.get(name),
            current_physical.get(name),
            name != "benchmark_metadata",
            first_physical.get(name) == current_physical.get(name),
        )
        for name in names
    ]
    passed = set(names) == set(BENCHMARK_ARTIFACT_NAMES) and all(
        bool(row[3]) and (not bool(row[6]) or bool(row[7])) for row in rows
    )
    return ("passed" if passed else "failed"), rows


def _validation_rows(
    connection: duckdb.DuckDBPyConnection,
    metadata: dict[str, object],
    tier1_rows: int,
) -> list[tuple[str, object, bool]]:
    source_audit = _object(metadata["source_audit_json"])
    source_record_count = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_source_records")
    )
    parsed_source_count = _integer(
        _scalar(
            connection,
            "SELECT count(*) FROM benchmark_source_records WHERE parse_status='parsed'",
        )
    )
    self_link_occurrences = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_issues WHERE code='self_link_excluded'")
    )
    source_link_count = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_relationship_source_records")
    )
    relationship_count = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_relationships")
    )
    metadata_relationship_count = _integer(metadata["relationship_count"])
    non_tier3 = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_relationships WHERE tier<>3")
    )
    eligibility_violations = _integer(
        _scalar(
            connection,
            "SELECT count(*) FROM benchmark_relationships "
            "WHERE primary_evaluation_eligible OR tier1_eligible",
        )
    )
    negative_control_violations = _integer(
        _scalar(
            connection,
            "SELECT count(*) FROM benchmark_presumed_negatives "
            "WHERE NOT presumed_negative OR NOT positive_graph_checked "
            "OR NOT reverse_pair_checked OR NOT passage_overlap_checked "
            "OR NOT leakage_checked",
        )
    )
    error_issues = _integer(
        _scalar(
            connection,
            "SELECT count(*) FROM benchmark_issues WHERE severity='error'",
        )
    )
    endpoint_count = _integer(_scalar(connection, "SELECT count(*) FROM benchmark_endpoints"))
    mapping_count = _integer(
        _scalar(connection, "SELECT count(*) FROM benchmark_endpoint_mappings")
    )
    split_count = _integer(_scalar(connection, "SELECT count(*) FROM benchmark_split_assignments"))
    exact_pair_memberships = _integer(
        _scalar(
            connection,
            "SELECT count(*) FROM benchmark_leakage_groups WHERE group_type='exact_unordered_pair'",
        )
    )
    return [
        (
            "source audit raw rows reconcile",
            f"{source_audit.get('raw_row_count')} / {source_record_count}",
            source_audit.get("raw_row_count") == source_record_count,
        ),
        (
            "source audit parsed rows reconcile",
            f"{source_audit.get('parsed_row_count')} / {parsed_source_count}",
            source_audit.get("parsed_row_count") == parsed_source_count,
        ),
        (
            "parsed non-self rows have source links",
            f"{parsed_source_count - self_link_occurrences} / {source_link_count}",
            parsed_source_count - self_link_occurrences == source_link_count,
        ),
        (
            "metadata relationship count reconciles",
            f"{metadata_relationship_count} / {relationship_count}",
            metadata_relationship_count == relationship_count,
        ),
        (
            "OpenBible remains Tier 3",
            non_tier3,
            non_tier3 == 0,
        ),
        (
            "no OpenBible primary-evaluation or Tier1 eligibility",
            eligibility_violations,
            eligibility_violations == 0,
        ),
        ("Tier 1 remains empty", tier1_rows, tier1_rows == 0),
        (
            "presumed-negative boolean controls all true",
            negative_control_violations,
            negative_control_violations == 0,
        ),
        (
            "two endpoints per relationship",
            f"{endpoint_count} / {relationship_count * 2}",
            endpoint_count == relationship_count * 2,
        ),
        (
            "two mapping profiles per endpoint",
            f"{mapping_count} / {endpoint_count * 2}",
            mapping_count == endpoint_count * 2,
        ),
        (
            "five split assignments per relationship",
            f"{split_count} / {relationship_count * 5}",
            split_count == relationship_count * 5,
        ),
        (
            "exact unordered leakage membership per relationship",
            f"{exact_pair_memberships} / {relationship_count}",
            exact_pair_memberships == relationship_count,
        ),
        (
            "persisted error issues",
            error_issues,
            error_issues == 0,
        ),
    ]


def generate_reports(
    *,
    database: Path,
    schema_root: Path,
    output_dir: Path,
    tier1_path: Path,
    spot_config: Path,
    first_run_hash_manifest: Path | None,
    first_run_id: str | None,
    acceptance_status: AcceptanceStatus,
    pr6_merge_commit: str | None,
    manual_reviewer: str | None = None,
    manual_review_date: str | None = None,
    manual_verdict: GateStatus = "pending",
    quality_gate_status: GateStatus = "pending",
    repository_audit_status: GateStatus = "pending",
    ci_status: GateStatus = "pending",
    ci_url: str | None = None,
    pull_request_url: str | None = None,
) -> Path:
    hash_manifest = _load_hash_manifest(schema_root / "table-hashes.json")
    with duckdb.connect(str(database), read_only=True) as connection:
        metadata = _metadata(connection)
        tier1_validation = validate_tier1_quotations(
            tier1_path,
            expected_sha256=str(metadata["tier1_header_sha256"]),
        )
        tier1_rows = tier1_validation.row_count
        source_audit = _object(metadata["source_audit_json"])
        source_versions = _object(metadata["source_versions_json"])
        archive_hashes = _object(metadata["source_archive_hashes_json"])
        source_file_hashes = _object(metadata["source_file_hashes_json"])
        supporting = _write_supporting_csvs(
            connection,
            output_dir=output_dir,
            source_audit=source_audit,
            tier1_rows=tier1_rows,
        )
        validation = _validation_rows(connection, metadata, tier1_rows)
        leakage_counts = _rows(
            connection,
            "SELECT group_type,count(DISTINCT leakage_group_id),count(*) "
            "FROM benchmark_leakage_groups GROUP BY 1 ORDER BY 1",
        )
        issue_counts = _rows(
            connection,
            "SELECT severity,code,count(*) FROM benchmark_issues GROUP BY ALL ORDER BY ALL",
        )

    spot_path = generate_spot_check_evidence(
        database=database,
        config=spot_config,
        output=output_dir / "m6-spot-check-evidence.md",
        tier1_path=tier1_path,
        manual_reviewer=manual_reviewer,
        manual_review_date=manual_review_date,
        manual_verdict=manual_verdict,
    )
    determinism_status, determinism_rows = _determinism(hash_manifest, first_run_hash_manifest)
    artifact_checks_passed = all(row[2] for row in validation)
    current_run_id = str(metadata["benchmark_run_id"])
    first_run_matches = first_run_id is not None and first_run_id == current_run_id
    if acceptance_status == "passed":
        failures: list[str] = []
        if not artifact_checks_passed:
            failures.append("artifact-level validation checks failed")
        if determinism_status != "passed":
            failures.append("two-run logical/expected-physical determinism did not pass")
        if not first_run_matches:
            failures.append("first-run ID is missing or differs from the current run ID")
        if manual_verdict != "passed":
            failures.append("manual spot-check review has not passed")
        if quality_gate_status != "passed":
            failures.append("local quality and full-regression gates have not passed")
        if repository_audit_status != "passed":
            failures.append("repository/data audit has not passed")
        if ci_status != "passed" or not ci_url:
            failures.append("GitHub Actions evidence is absent or not passed")
        if not pull_request_url:
            failures.append("the unmerged Milestone 6 pull-request URL is absent")
        if failures:
            raise ValueError(
                "refusing to declare Milestone 6 acceptance passed: " + "; ".join(failures)
            )
    current_logical = cast(dict[str, object], hash_manifest["table_logical_sha256"])
    current_physical = cast(dict[str, object], hash_manifest["table_physical_sha256"])
    hash_rows = [
        (name, current_logical.get(name, ""), current_physical.get(name, ""))
        for name in sorted(set(current_logical) | set(current_physical))
    ]
    mapping_summary = [(row[0], row[1], row[2], row[3], row[4]) for row in supporting["mapping"]]
    corpus_summary = [(row[0], row[1]) for row in supporting["corpus"]]
    split_summary = [tuple(row) for row in supporting["splits"]]
    negative_summary = [tuple(row) for row in supporting["negatives"]]
    source_version = source_versions.get("openbible-cross-references", "unknown")
    archive_hash = archive_hashes.get("openbible-cross-references", "unknown")
    merge_commit = _pr6_merge_commit(pr6_merge_commit)
    report = [
        "# Milestone 6 known-link benchmark report",
        "",
        "## Objective",
        "",
        "Establish a governed, versioned known-relationship benchmark using the "
        "OpenBible cross-reference graph strictly as Tier 3 weak supervision and broad "
        "knownness support, while retaining an empty human-curation-only Tier 1 schema.",
        "",
        "## Repository and decision provenance",
        "",
        f"- PR #6 merge commit: `{merge_commit}`",
        "- Governing decision: ADR 0014, *Known-link benchmark identity, tiering, mapping, "
        "and leakage control*.",
        f"- Benchmark run ID: `{metadata['benchmark_run_id']}`",
        f"- Benchmark version: `{metadata['benchmark_version']}`",
        "- Benchmark schema version: `1`; relationship-ID schema version: `1`; mapping "
        "schema version: `1`.",
        "",
        "## Source, license, and snapshot",
        "",
        "The exact OpenBible link graph is approved under CC BY 4.0 with OpenBible.info "
        "attribution, a source/license link, preserved notices, and modification notices. "
        "Separately copyrighted ESV quotations are excluded. The acquired archive contains "
        "reference identifiers, integer votes, and attribution only; no biblical text.",
        "",
        f"- Snapshot label: `{source_version}`",
        f"- Archive SHA-256: `{archive_hash}`",
        f"- Extracted-file hashes: `{json.dumps(source_file_hashes, sort_keys=True)}`",
        "- Canonical source-record stream SHA-256: "
        f"`{source_audit.get('canonical_stream_sha256')}`",
        "- Acquisition: source-approved, content-addressed ZIP with safe extraction, local "
        "receipt, and offline exact verification; raw/extracted data remains Git-ignored.",
        f"- Archive schema: `{source_audit.get('encoding')}` encoding, "
        f"`{source_audit.get('newline_convention')}` newlines, three data fields "
        "(source reference, target reference, signed vote) plus an attribution header.",
        "",
        "## Data model and identity",
        "",
        "Source records preserve every occurrence, original references, weight, direction, "
        "raw-record hash, file, line provenance, and parse status. Relationship identity "
        "derives only from the source/version/scheme, normalized endpoints, and source "
        "direction; passage mappings, votes, paths, timestamps, splits, and row numbers do "
        "not participate. Mapping identity remains separate and records ordered verse targets, "
        "method, profile, reading, confidence, gaps, disputed text, and ambiguity.",
        "",
        "Direction is never silently symmetrized. Reverse relationships remain distinct "
        "directed relationships with a shared unordered-pair identity. Duplicate occurrences "
        "remain traceable through relationship-to-source-record links; votes are source ranking "
        "evidence, not confidence or literary-dependence probability.",
        "",
        "## Tier governance and Tier 1 placeholder",
        "",
        "OpenBible is Tier 3, weak-supervision and knownness-filter eligible, never primary-"
        "evaluation or Tier-1 eligible, and cannot be the sole positive benchmark. Tier 1 "
        "requires human curation and independent review; automated verification is prohibited.",
        "",
        f"- Tier 1 data rows: `{tier1_rows}`",
        f"- Tier 1 header SHA-256: `{metadata['tier1_header_sha256']}`",
        "",
        "## Reference parsing and passage mapping",
        "",
        "The parser preserves the OpenBible source scheme and handles governed aliases, "
        "single verses, same-chapter ranges, and cross-chapter ranges. Cross-book ranges and "
        "invalid/backward/out-of-scheme references remain explicit issues rather than silent "
        "loss. Milestone 6 maps only to verse passages under `edition_complete`: Hebrew uses "
        "Qere and Greek uses the source reading. Old Testament same-label mappings are "
        "provisional (`same_label_extant_reference`), never verified crosswalk equivalence. "
        "Omitted verses are never fabricated; partial ranges, disputed text, reference gaps, "
        "and critical-core exclusions remain explicit.",
        "",
        "### Mapping-status distribution",
        "",
        *_markdown_table(("Profile", "Corpus", "Status", "Confidence", "Count"), mapping_summary),
        "",
        "Detailed aggregate risks are in `m6-versification-risks.csv`. A bounded, "
        "deterministically selected reference-level view (at most three references per "
        "book/profile/risk stratum) is in `m6-versification-risk-references.csv`; this "
        "satisfies reference-level auditability without publishing a bulk source graph. No "
        "biblical text is included.",
        "",
        "## Source graph statistics",
        "",
        f"- Raw / parsed / invalid rows: `{source_audit.get('raw_row_count')}` / "
        f"`{source_audit.get('parsed_row_count')}` / `{source_audit.get('invalid_row_count')}`",
        f"- Exact duplicate occurrences / duplicate directed pairs: "
        f"`{source_audit.get('exact_duplicate_occurrence_count')}` / "
        f"`{source_audit.get('duplicate_directed_pair_count')}`",
        f"- Unique directed / unordered relationships: "
        f"`{source_audit.get('unique_directed_relationship_count')}` / "
        f"`{source_audit.get('unique_unordered_pair_count')}`",
        f"- Reverse unordered pairs / self-links: `{source_audit.get('reverse_pair_count')}` / "
        f"`{source_audit.get('self_link_count')}`",
        f"- Weight minimum / Q1 / median / Q3 / maximum: "
        f"`{source_audit.get('weight_min')}` / `{source_audit.get('weight_q1')}` / "
        f"`{source_audit.get('weight_median')}` / `{source_audit.get('weight_q3')}` / "
        f"`{source_audit.get('weight_max')}`",
        f"- Negative / zero / positive weights: `{source_audit.get('negative_weight_count')}` / "
        f"`{source_audit.get('zero_weight_count')}` / "
        f"`{source_audit.get('positive_weight_count')}`",
        "- Reference-range distribution: "
        f"`{json.dumps(source_audit.get('reference_kind_counts', {}), sort_keys=True)}`",
        "",
        "### Corpus-pair distribution",
        "",
        *_markdown_table(("Corpus pair", "Relationships"), corpus_summary),
        "",
        "All artifact and source-audit counts are also recorded in `m6-benchmark-counts.csv`.",
        "",
        "## Leakage controls and splits",
        "",
        "Independent leakage views cover exact directed/unordered pairs, duplicate source "
        "records, shared endpoints, atomic overlapping source/target coordinates, shared "
        "target passages, declared relationship families, and shared provenance. Atomic "
        "book/ordinal groups avoid both quadratic hub pairs and one unrestricted global "
        "connected component.",
        "",
        *_markdown_table(("Group type", "Distinct groups", "Membership rows"), leakage_counts),
        "",
        "Held-out book, book-pair, source-passage, relationship-family contract, and broad-"
        "genre strategies assign whole configured leakage groups deterministically. Missing "
        "family labels are marked unsupported rather than invented. Tier 3 partitions are "
        "weak-supervision infrastructure, not definitive scholarly evaluation sets.",
        "",
        *_markdown_table(
            ("Strategy", "Partition", "Eligibility", "Exclusion reason", "Count"),
            split_summary,
        ),
        "",
        "The same distribution is recorded in `m6-split-counts.csv`.",
        "",
        "## Presumed negatives",
        "",
        "The build uses deterministic, indexed, bounded-probe generation for length-matched "
        "random unlinked, same-book, same-book-pair, same-broad-genre, and nearby-context "
        "strategies. Every pair is checked against the known graph in both directions, passage "
        "overlap, split partition, and leakage constraints. These are presumed negatives only; "
        "absence from known-link sources is not proof of nonrelationship.",
        "",
        *_markdown_table(
            ("Negative strategy", "Split strategy", "Partition", "Count"),
            negative_summary,
        ),
        "",
        "The same distribution is recorded in `m6-presumed-negative-counts.csv`.",
        "",
        "## Metric contract",
        "",
        "Pure synthetic-fixture contracts cover Recall@5/10/20, mean reciprocal rank, "
        "nDCG@20, Precision@10/configurable K, coverage, and performance by book, broad genre, "
        "passage-length bucket, corpus pair, relationship class, tier, and mapping confidence. "
        "Every output requires benchmark version, tiers, mapping eligibility, split, label "
        "quality, eligible/excluded query counts, and reasons. No retrieval model was run; "
        "OpenBible-only results must be labeled Tier 3 weak-supervision recovery.",
        "",
        "## Determinism, hashes, runtime, and storage",
        "",
        f"- First benchmark run ID supplied for comparison: `{first_run_id or 'not supplied'}`",
        f"- Two-run logical and expected-physical comparison: `{determinism_status}`",
        f"- First and second run IDs match: `{first_run_matches}`",
        f"- Current runtime: `{metadata['runtime_seconds']}` seconds",
        f"- Current storage footprint: `{metadata['storage_footprint_bytes']}` bytes",
        "",
        *_markdown_table(("Artifact", "Logical SHA-256", "Physical SHA-256"), hash_rows),
        "",
    ]
    if determinism_rows:
        report.extend(
            [
                "### Two-run logical comparison",
                "",
                *_markdown_table(
                    (
                        "Artifact",
                        "First logical hash",
                        "Second logical hash",
                        "Logical equal",
                        "First physical hash",
                        "Second physical hash",
                        "Physical equality required",
                        "Physical equal",
                    ),
                    determinism_rows,
                ),
                "",
            ]
        )
    report.extend(
        [
            "## Validation results",
            "",
            *_markdown_table(("Check", "Observed", "Passed"), validation),
            "",
            "Persisted issue distribution:",
            "",
            *_markdown_table(("Severity", "Code", "Count"), issue_counts),
            "",
            "The final repository quality suite, strict corpus/passage/benchmark validators, "
            "pre-commit hooks, and GitHub Actions remain authoritative for closure beyond these "
            "artifact-level checks.",
            "",
            "## Scripted and manual spot checks",
            "",
            f"Deterministic criterion-driven evidence is recorded in `{spot_path.name}`. Missing "
            "real-snapshot categories are explicitly recorded as audited absences; no example "
            "is fabricated and no biblical text is reproduced.",
            f"Manual review verdict: `{manual_verdict}`; reviewer: "
            f"`{manual_reviewer or 'not supplied'}`; date: "
            f"`{manual_review_date or 'not supplied'}`.",
            "",
            "## Known limitations",
            "",
            "- OpenBible is heterogeneous Tier 3 weak supervision, not scholarly ground truth.",
            "- Tier 1 remains empty, so no primary high-confidence evaluation benchmark exists.",
            "- Same-label Old Testament mappings remain provisional without an approved external "
            "versification crosswalk.",
            "- Cross-reference absence does not establish nonrelationship; generated negatives are "
            "presumed only.",
            "- Relationship-family labels are unavailable for OpenBible and are not invented.",
            "- No lexical baseline, retrieval model, candidate discovery, embeddings, or "
            "Milestone 7 work has been run in this milestone.",
            "",
            "## Acceptance assessment",
            "",
            f"- Declared final acceptance status: `{acceptance_status}`",
            f"- Artifact-level validation checks all passed: `{artifact_checks_passed}`",
            "- Two-run logical and expected-physical determinism passed: "
            f"`{determinism_status == 'passed'}`",
            f"- First and second run IDs match: `{first_run_matches}`",
            f"- Manual spot-check review: `{manual_verdict}`",
            f"- Local quality/full-regression gates: `{quality_gate_status}`",
            f"- Repository and data audit: `{repository_audit_status}`",
            f"- Unmerged pull request: `{pull_request_url or 'not supplied'}`",
            f"- GitHub Actions: `{ci_status}` ({ci_url or 'no run URL supplied'})",
            "- Milestone 6 may be marked complete only when the declared status is `passed`, the "
            "two-run comparison passes, every repository/full-corpus quality command passes, all "
            "anchors remain unchanged, and the unmerged PR is CI-green.",
            "",
            "## Exact recommended Milestone 7 task",
            "",
            "Execute Milestone 7 only: implement the transparent lexical baseline (TF-IDF, BM25, "
            "rare-lemma, phrase, and ordered-sequence scoring), candidate-evidence output, both "
            "registered repeated null families, the configurable conjunctive rare-evidence rule, "
            "and tier/mapping-confidence-separated known-link recovery evaluation. Do not begin "
            "Milestone 8 candidate review.",
        ]
    )
    output = output_dir / "milestone-6-known-link-benchmark-report.md"
    _atomic_text(output, "\n".join(report).rstrip() + "\n")
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--schema-root", type=Path, default=DEFAULT_SCHEMA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--tier1-path", type=Path, default=DEFAULT_TIER1)
    parser.add_argument("--spot-config", type=Path, default=DEFAULT_SPOT_CONFIG)
    parser.add_argument("--first-run-hash-manifest", type=Path)
    parser.add_argument("--first-run-id")
    parser.add_argument(
        "--acceptance-status", choices=("pending", "passed", "failed"), default="pending"
    )
    parser.add_argument("--pr6-merge-commit")
    parser.add_argument("--manual-reviewer")
    parser.add_argument("--manual-review-date")
    parser.add_argument(
        "--manual-verdict", choices=("pending", "passed", "failed"), default="pending"
    )
    parser.add_argument(
        "--quality-gate-status", choices=("pending", "passed", "failed"), default="pending"
    )
    parser.add_argument(
        "--repository-audit-status",
        choices=("pending", "passed", "failed"),
        default="pending",
    )
    parser.add_argument("--ci-status", choices=("pending", "passed", "failed"), default="pending")
    parser.add_argument("--ci-url")
    parser.add_argument("--pull-request-url")
    return parser


def main() -> None:
    args = _parser().parse_args()
    output = generate_reports(
        database=args.database,
        schema_root=args.schema_root,
        output_dir=args.output_dir,
        tier1_path=args.tier1_path,
        spot_config=args.spot_config,
        first_run_hash_manifest=args.first_run_hash_manifest,
        first_run_id=args.first_run_id,
        acceptance_status=cast(AcceptanceStatus, args.acceptance_status),
        pr6_merge_commit=args.pr6_merge_commit,
        manual_reviewer=args.manual_reviewer,
        manual_review_date=args.manual_review_date,
        manual_verdict=cast(GateStatus, args.manual_verdict),
        quality_gate_status=cast(GateStatus, args.quality_gate_status),
        repository_audit_status=cast(GateStatus, args.repository_audit_status),
        ci_status=cast(GateStatus, args.ci_status),
        ci_url=args.ci_url,
        pull_request_url=args.pull_request_url,
    )
    print(output)


if __name__ == "__main__":
    main()
