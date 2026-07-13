"""Strict validation of persisted Milestone 6 benchmark artifacts and anchors."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Self, cast

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.acquire.sources import AcquisitionReceipt, verify_acquisition
from echoes.benchmarks.identity import (
    MappingIdentityPayload,
    RelationshipIdentityPayload,
    SourceRecordIdentityPayload,
    build_mapping_identity,
    build_pair_identities,
    build_relationship_identity,
    canonical_payload_json,
)
from echoes.benchmarks.models import BENCHMARK_ARTIFACT_NAMES
from echoes.benchmarks.pipeline import (
    M5_EXPECTED_LOGICAL_HASHES,
    M5_EXPECTED_RUN_ID,
    PassageInputMetadata,
    _passage_metadata,
    _split_assignment_id,
    benchmark_config_fingerprint,
)
from echoes.benchmarks.references import openbible_reference_corpus
from echoes.benchmarks.storage import (
    BENCHMARK_SCHEMA_DIRECTORY,
    HASH_MANIFEST_NAME,
    logical_parquet_hash,
)
from echoes.benchmarks.tier1 import validate_tier1_quotations
from echoes.manifests.sources import SourceManifest, SourceStatus, load_source_catalog
from echoes.segment.streams import (
    GREEK_ANALYTICAL_DIGEST,
    GREEK_CONTENT_DIGEST,
    GREEK_IDENTITY_DIGEST,
    HEBREW_ANALYTICAL_DIGEST,
    HEBREW_CONTENT_DIGEST,
    HEBREW_IDENTITY_DIGEST,
    OSHB_LOGICAL_DIGESTS,
)
from echoes.settings import BenchmarkConfig, load_config

OPENBIBLE_PRODUCTION_VERSION = "snapshot-2026-07-12-sha256-18e63e370308"
OPENBIBLE_PRODUCTION_ARCHIVE_SHA256 = (
    "18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492"
)
OPENBIBLE_PRODUCTION_FILE_SHA256 = (
    "eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37"
)
OPENBIBLE_PRODUCTION_CANONICAL_SHA256 = (
    "e3b2b3bb8c0097382ce4385c38342d4d4d07dd3cde05b331c0998a007840482e"
)
OPENBIBLE_PRODUCTION_SOURCE_AUDIT: dict[str, int] = {
    "raw_row_count": 344_799,
    "parsed_row_count": 344_799,
    "invalid_row_count": 0,
    "exact_duplicate_occurrence_count": 0,
    "duplicate_directed_pair_count": 0,
    "unique_directed_relationship_count": 344_799,
    "unique_unordered_pair_count": 314_921,
    "reverse_pair_count": 29_878,
    "self_link_count": 0,
    "negative_weight_count": 1_239,
    "zero_weight_count": 2_277,
    "positive_weight_count": 341_283,
    "distinct_weight_count": 418,
    "weight_min": -86,
    "weight_q1": 2,
    "weight_median": 3,
    "weight_q3": 6,
    "weight_max": 1_281,
}


class BenchmarkValidationError(RuntimeError):
    """Raised when benchmark validation cannot inspect governed inputs."""


class BenchmarkValidationIssue(BaseModel):
    """One stable validation finding."""

    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warning", "informational"]
    code: str
    message: str
    artifact: str | None = None


class BenchmarkValidationReport(BaseModel):
    """Machine-readable strict benchmark acceptance report."""

    model_config = ConfigDict(extra="forbid")

    benchmark_run_id: str | None
    strict: bool
    table_counts: dict[str, int]
    logical_table_hashes: dict[str, str]
    physical_table_hashes: dict[str, str]
    issues: list[BenchmarkValidationIssue]
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    informational_count: int = Field(ge=0)
    passed: bool

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        observed = Counter(issue.severity for issue in self.issues)
        if self.error_count != observed["error"]:
            raise ValueError("benchmark validation error count does not reconcile")
        if self.warning_count != observed["warning"]:
            raise ValueError("benchmark validation warning count does not reconcile")
        if self.informational_count != observed["informational"]:
            raise ValueError("benchmark validation informational count does not reconcile")
        return self

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dict(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _error(
    issues: list[BenchmarkValidationIssue],
    code: str,
    message: str,
    *,
    artifact: str | None = None,
) -> None:
    issues.append(
        BenchmarkValidationIssue(
            severity="error",
            code=code,
            message=message,
            artifact=artifact,
        )
    )


def _count_error(
    issues: list[BenchmarkValidationIssue],
    code: str,
    message: str,
    count: int,
    *,
    artifact: str,
) -> None:
    """Append one stable counted error without exposing row-level source data."""

    if count:
        _error(issues, code, f"{message} Count={count}.", artifact=artifact)


def _sql_hash_partition(
    *,
    seed: int,
    value_sql: str,
    test_fraction: float,
    development_fraction: float,
) -> str:
    """Render DuckDB SQL equivalent to the governed SHA-256 split rule."""

    first_boundary = repr(test_fraction)
    second_boundary = repr(test_fraction + development_fraction)
    fraction = (
        "CAST(CAST(('0x' || substr(sha256(CAST("
        f"{seed} AS VARCHAR) || '|' || {value_sql}), 1, 16)) AS UBIGINT) AS DOUBLE) "
        "/ 18446744073709551616.0"
    )
    return (
        f"CASE WHEN {fraction} < {first_boundary} THEN 'test' "
        f"WHEN {fraction} < {second_boundary} THEN 'development' ELSE 'train' END"
    )


def _sql_genre(book_sql: str, config: BenchmarkConfig) -> str:
    """Render the governed 66-book broad-genre lookup as a SQL expression."""

    clauses = " ".join(
        f"WHEN '{book}' THEN '{genre}'" for book, genre in sorted(config.book_genres.items())
    )
    return f"CASE {book_sql} {clauses} ELSE 'unresolved' END"


@contextmanager
def _bounded_validation_connection(
    database_path: Path,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a read-only validator connection with bounded RAM and local spill cleanup."""

    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=f".{database_path.stem}-benchmark-validation-",
        dir=database_path.parent,
    ) as temporary_directory:
        escaped_directory = temporary_directory.replace("'", "''")
        with duckdb.connect(str(database_path), read_only=True) as connection:
            connection.execute("SET memory_limit='2GiB'")
            connection.execute("SET threads=1")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory='{escaped_directory}'")
            yield connection


def _hash_validation(
    schema_root: Path,
    issues: list[BenchmarkValidationIssue],
) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    manifest_path = schema_root / HASH_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkValidationError(f"invalid benchmark hash manifest: {exc}") from exc
    raw_expected_logical = manifest.get("table_logical_sha256", {})
    raw_expected_physical = manifest.get("table_physical_sha256", {})
    raw_expected_counts = manifest.get("table_counts", {})
    expected_logical = raw_expected_logical if isinstance(raw_expected_logical, dict) else {}
    expected_physical = raw_expected_physical if isinstance(raw_expected_physical, dict) else {}
    expected_counts = raw_expected_counts if isinstance(raw_expected_counts, dict) else {}
    if manifest.get("artifact_schema_version") != 1:
        _error(
            issues,
            "hash_manifest_schema_mismatch",
            "Benchmark hash manifest must use artifact schema version 1.",
        )
    expected_names = set(BENCHMARK_ARTIFACT_NAMES)
    for field, observed in (
        ("table_counts", expected_counts),
        ("table_logical_sha256", expected_logical),
        ("table_physical_sha256", expected_physical),
    ):
        if not isinstance(observed, dict) or set(observed) != expected_names:
            _error(
                issues,
                "hash_manifest_artifact_set_mismatch",
                f"{field} does not name exactly the ten governed benchmark artifacts.",
            )
    logical: dict[str, str] = {}
    physical: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name in BENCHMARK_ARTIFACT_NAMES:
        path = schema_root / name / "part-00000.parquet"
        if not path.is_file():
            raise BenchmarkValidationError(f"missing benchmark artifact: {path}")
        counts[name] = int(
            pl.scan_parquet(path).select(pl.len()).collect(engine="streaming").item()
        )
        logical[name] = logical_parquet_hash(path, name)
        physical[name] = _sha256_file(path)
        if expected_counts.get(name) != counts[name]:
            _error(
                issues,
                "hash_manifest_count_mismatch",
                f"Hash-manifest row count mismatch for {name}.",
                artifact=name,
            )
        if expected_logical.get(name) != logical[name]:
            _error(
                issues,
                "logical_hash_mismatch",
                f"Logical hash mismatch for {name}.",
                artifact=name,
            )
        if expected_physical.get(name) != physical[name]:
            _error(
                issues,
                "physical_hash_mismatch",
                f"Physical hash mismatch for {name}.",
                artifact=name,
            )
    return logical, physical, counts


def _manifest_governance_validation(
    openbible: SourceManifest,
    tier1: SourceManifest,
    config: BenchmarkConfig,
    issues: list[BenchmarkValidationIssue],
) -> None:
    acquisition = openbible.acquisition
    source_file = config.sources.openbible.source_file
    violations: list[str] = []
    if openbible.status not in {SourceStatus.APPROVED, SourceStatus.VALIDATED}:
        violations.append("OpenBible source is not approved or validated")
    if not openbible.licensing_complete:
        violations.append("OpenBible licensing review is incomplete")
    if openbible.source_id != config.sources.openbible.source_id:
        violations.append("OpenBible source ID differs between manifest and config")
    if openbible.version_or_commit != config.sources.openbible.snapshot_version:
        violations.append("OpenBible snapshot version differs between manifest and config")
    if (
        acquisition is None
        or acquisition.archive_sha256 != config.sources.openbible.snapshot_sha256
    ):
        violations.append("OpenBible archive hash differs between manifest and config")
    if openbible.file_hashes.get(source_file) != config.sources.openbible.source_file_sha256:
        violations.append("OpenBible extracted-file hash differs between manifest and config")
    if openbible.raw_data_git_policy.value != "ignored_local_only":
        violations.append("OpenBible raw-data Git policy is not ignored_local_only")
    if config.enabled_source_ids != [openbible.source_id]:
        violations.append("Milestone 6 enables a source other than governed OpenBible")
    if (
        config.sources.openbible.tier != 3
        or config.sources.openbible.primary_evaluation_eligible
        or config.sources.openbible.tier1_promotion_allowed
        or not config.sources.openbible.weak_supervision_eligible
        or not config.sources.openbible.knownness_filter_eligible
    ):
        violations.append("OpenBible configuration violates Tier 3 eligibility boundaries")
    if (
        tier1.status is not SourceStatus.PLANNED
        or tier1.repository_or_location != config.sources.tier1.schema_location
        or tier1.expected_files != [config.sources.tier1.schema_location]
        or tier1.file_hashes.get(config.sources.tier1.schema_location)
        != config.sources.tier1.header_sha256
        or tier1.acquisition is not None
    ):
        violations.append("Tier 1 manifest does not describe the planned header-only schema")
    if (
        config.sources.tier1.expected_current_row_count != 0
        or config.sources.tier1.automated_population_allowed
        or config.sources.tier1.automated_verification_allowed
        or not config.sources.tier1.require_human_curation
        or not config.sources.tier1.require_independent_review
    ):
        violations.append("Tier 1 configuration violates the human-curation boundary")
    if openbible.version_or_commit == OPENBIBLE_PRODUCTION_VERSION and (
        acquisition is None
        or acquisition.archive_sha256 != OPENBIBLE_PRODUCTION_ARCHIVE_SHA256
        or openbible.file_hashes.get(source_file) != OPENBIBLE_PRODUCTION_FILE_SHA256
    ):
        violations.append("Production OpenBible content-addressed snapshot constants changed")
    for message in violations:
        _error(issues, "benchmark_manifest_governance_violation", message)


def _mapping_database_validation(
    database_path: Path, issues: list[BenchmarkValidationIssue]
) -> None:
    try:
        with _bounded_validation_connection(database_path) as connection:

            def scalar(sql: str) -> int:
                row = connection.execute(sql).fetchone()
                if row is None:
                    raise BenchmarkValidationError("mapping validation query returned no row")
                return int(row[0])

            checks = (
                (
                    """
                    SELECT count(*) FROM benchmark_mapping_target_passages t
                    LEFT JOIN passages p ON p.passage_id=t.target_passage_id
                    WHERE p.passage_id IS NULL
                    """,
                    "missing_mapping_target",
                    "Mapped target passage IDs do not exist.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_endpoint_mappings m
                    WHERE m.mapping_status IN
                          ('mapped_verified','mapped_provisional','mapped_partial')
                      AND json_array_length(m.target_passage_ids_json)=0
                    """,
                    "empty_successful_mapping",
                    "Successful mappings have no passage IDs.",
                ),
                (
                    """
                    WITH target_counts AS (
                      SELECT mapping_id,endpoint_id,count(*) AS n,
                             count(DISTINCT position) AS positions
                      FROM benchmark_mapping_target_passages GROUP BY ALL
                    )
                    SELECT count(*) FROM benchmark_endpoint_mappings m
                    LEFT JOIN target_counts t USING(mapping_id,endpoint_id)
                    WHERE json_array_length(m.target_passage_ids_json)<>coalesce(t.n,0)
                       OR json_array_length(m.target_reference_sequence_json)<>coalesce(t.n,0)
                       OR coalesce(t.n,0)<>coalesce(t.positions,0)
                    """,
                    "mapping_target_count_mismatch",
                    "Mapping JSON and normalized target-passage rows do not reconcile.",
                ),
                (
                    """
                    WITH json_targets AS (
                      SELECT m.mapping_id,m.endpoint_id,CAST(j.key AS BIGINT)+1 AS position,
                             trim(CAST(j.value AS VARCHAR), '\"') AS target_passage_id
                      FROM benchmark_endpoint_mappings m,
                           json_each(m.target_passage_ids_json) j
                    )
                    SELECT count(*) FROM (
                      SELECT coalesce(t.mapping_id,j.mapping_id) AS mapping_id
                      FROM benchmark_mapping_target_passages t
                      FULL OUTER JOIN json_targets j
                        USING(mapping_id,endpoint_id,position,target_passage_id)
                      WHERE t.mapping_id IS NULL OR j.mapping_id IS NULL
                    )
                    """,
                    "mapping_target_sequence_mismatch",
                    "Ordered normalized targets differ from target_passage_ids_json.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_mapping_target_passages t
                    JOIN passages p ON p.passage_id=t.target_passage_id
                    JOIN benchmark_endpoint_mappings m USING(mapping_id,endpoint_id)
                    LEFT JOIN json_each(m.target_reference_sequence_json) j
                      ON CAST(j.key AS BIGINT)+1=t.position
                    WHERE trim(CAST(j.value AS VARCHAR), '\"') IS DISTINCT FROM p.start_reference
                       OR p.corpus<>m.target_corpus
                       OR p.analysis_profile<>m.target_analysis_profile
                       OR p.analysis_reading<>m.target_analysis_reading
                       OR p.granularity<>m.target_granularity
                    """,
                    "mapping_target_fact_mismatch",
                    "Target references or governed passage stream facts do not reconcile.",
                ),
                (
                    """
                    SELECT count(*) FROM (
                      SELECT e.endpoint_id,p.profile,count(m.mapping_id) AS n
                      FROM benchmark_endpoints e
                      CROSS JOIN (VALUES ('edition_complete'),('critical_core')) p(profile)
                      LEFT JOIN benchmark_endpoint_mappings m
                        ON m.endpoint_id=e.endpoint_id
                       AND m.target_analysis_profile=p.profile
                      GROUP BY ALL HAVING n<>1
                    )
                    """,
                    "mapping_cardinality_mismatch",
                    "Every endpoint must have exactly one mapping per governed profile.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_endpoint_mappings
                    WHERE mapping_method='same_label_extant_reference'
                      AND (mapping_status='mapped_verified' OR mapping_confidence='verified')
                    """,
                    "same_label_false_verification",
                    "A same-label mapping is mislabeled as verified.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_endpoint_mappings
                    WHERE target_granularity<>'verse'
                       OR (target_corpus='hebrew' AND target_analysis_reading<>'qere')
                       OR (target_corpus='greek' AND target_analysis_reading<>'source')
                    """,
                    "wrong_mapping_stream",
                    "Mappings target a prohibited passage stream.",
                ),
            )
            for sql, code, message in checks:
                _count_error(
                    issues,
                    code,
                    message,
                    scalar(sql),
                    artifact="benchmark_endpoint_mappings",
                )

            disputed_mismatch = scalar(
                """
                WITH risk_targets AS (
                  SELECT m.mapping_id,t.target_passage_id
                  FROM benchmark_endpoint_mappings m
                  JOIN benchmark_endpoint_mappings edition
                    ON edition.endpoint_id=m.endpoint_id
                   AND edition.target_analysis_profile='edition_complete'
                  JOIN benchmark_mapping_target_passages t
                    ON t.mapping_id=edition.mapping_id
                   AND t.endpoint_id=edition.endpoint_id
                ), target_flags AS (
                  SELECT t.mapping_id,bool_or(p.disputed_passage_flag) AS disputed
                  FROM risk_targets t
                  JOIN passages p ON p.passage_id=t.target_passage_id
                  GROUP BY t.mapping_id
                ), disputed_values AS (
                  SELECT DISTINCT t.mapping_id,
                         trim(CAST(j.value AS VARCHAR), '"') AS disputed_id
                  FROM risk_targets t
                  JOIN passages p ON p.passage_id=t.target_passage_id,
                       json_each(p.disputed_passage_ids_json) j
                ), disputed_lists AS (
                  SELECT mapping_id,to_json(list(disputed_id ORDER BY disputed_id)) AS ids_json
                  FROM disputed_values GROUP BY mapping_id
                )
                SELECT count(*) FROM benchmark_endpoint_mappings m
                LEFT JOIN target_flags f USING(mapping_id)
                LEFT JOIN disputed_lists d USING(mapping_id)
                WHERE m.disputed_passage_flag<>coalesce(f.disputed,false)
                   OR m.disputed_passage_ids_json<>coalesce(d.ids_json,'[]')
                """
            )
            _count_error(
                issues,
                "mapping_disputed_flag_mismatch",
                "Disputed-passage flags or IDs do not reproduce from mapped passages.",
                disputed_mismatch,
                artifact="benchmark_endpoint_mappings",
            )

            reference_gap_mismatch = scalar(
                """
                WITH coordinates AS (
                  SELECT m.mapping_id,t.position,p.reference_gap,
                         CAST(split_part(split_part(p.start_reference,' ',2),':',1) AS INTEGER)
                           AS chapter,
                         CAST(split_part(split_part(p.start_reference,' ',2),':',2) AS INTEGER)
                           AS verse
                  FROM benchmark_endpoint_mappings m
                  JOIN benchmark_endpoint_mappings edition
                    ON edition.endpoint_id=m.endpoint_id
                   AND edition.target_analysis_profile='edition_complete'
                  JOIN benchmark_mapping_target_passages t
                    ON t.mapping_id=edition.mapping_id
                   AND t.endpoint_id=edition.endpoint_id
                  JOIN passages p ON p.passage_id=t.target_passage_id
                ), ordered AS (
                  SELECT *,lag(chapter) OVER (PARTITION BY mapping_id ORDER BY position)
                               AS previous_chapter,
                           lag(verse) OVER (PARTITION BY mapping_id ORDER BY position)
                               AS previous_verse
                  FROM coordinates
                ), expected AS (
                  SELECT mapping_id,bool_or(
                    reference_gap OR
                    (previous_chapter=chapter AND verse<>previous_verse+1) OR
                    (previous_chapter<>chapter AND
                     (chapter<>previous_chapter+1 OR verse<>1))
                  ) AS reference_gap
                  FROM ordered GROUP BY mapping_id
                )
                SELECT count(*) FROM benchmark_endpoint_mappings m
                LEFT JOIN expected e USING(mapping_id)
                WHERE m.reference_gap<>coalesce(e.reference_gap,false)
                """
            )
            _count_error(
                issues,
                "mapping_reference_gap_mismatch",
                "Reference-gap flags do not reproduce from ordered extant targets.",
                reference_gap_mismatch,
                artifact="benchmark_endpoint_mappings",
            )

            status_mismatch = scalar(
                """
                WITH mapping_targets AS (
                  SELECT m.mapping_id,m.endpoint_id,m.target_analysis_profile,
                         t.position,p.start_reference,p.reference_gap,
                         CAST(split_part(split_part(p.start_reference,' ',2),':',1) AS INTEGER)
                           AS chapter,
                         CAST(split_part(split_part(p.start_reference,' ',2),':',2) AS INTEGER)
                           AS verse
                  FROM benchmark_endpoint_mappings m
                  LEFT JOIN benchmark_mapping_target_passages t
                    USING(mapping_id,endpoint_id)
                  LEFT JOIN passages p ON p.passage_id=t.target_passage_id
                ), ordered_targets AS (
                  SELECT *,lag(chapter) OVER (PARTITION BY mapping_id ORDER BY position)
                               AS previous_chapter,
                           lag(verse) OVER (PARTITION BY mapping_id ORDER BY position)
                               AS previous_verse
                  FROM mapping_targets
                ), target_facts AS (
                  SELECT m.mapping_id,m.endpoint_id,m.target_analysis_profile,
                         count(t.target_passage_id) AS target_count,
                         arg_min(p.start_reference,t.position)
                           FILTER (WHERE t.target_passage_id IS NOT NULL) AS first_reference,
                         arg_max(p.start_reference,t.position)
                           FILTER (WHERE t.target_passage_id IS NOT NULL) AS last_reference,
                         coalesce(to_json(list(p.start_reference ORDER BY t.position)
                           FILTER (WHERE t.target_passage_id IS NOT NULL)),'[]')
                           AS reference_sequence_json
                  FROM benchmark_endpoint_mappings m
                  LEFT JOIN benchmark_mapping_target_passages t
                    USING(mapping_id,endpoint_id)
                  LEFT JOIN passages p ON p.passage_id=t.target_passage_id
                  GROUP BY ALL
                ), gap_facts AS (
                  SELECT mapping_id,coalesce(bool_or(
                           reference_gap OR
                           (previous_chapter=chapter AND verse<>previous_verse+1) OR
                           (previous_chapter<>chapter AND
                            (chapter<>previous_chapter+1 OR verse<>1))
                         ) FILTER (WHERE position IS NOT NULL),false) AS reference_gap
                  FROM ordered_targets GROUP BY mapping_id
                ), facts AS (
                  SELECT m.*,e.parse_status,e.parsed_book,e.parsed_start_chapter,
                         e.parsed_start_verse,e.parsed_end_chapter,e.parsed_end_verse,e.is_range,
                         t.target_count,t.first_reference,t.last_reference,
                         t.reference_sequence_json,
                         coalesce(ec.target_count,0) AS edition_target_count,
                         ec.reference_sequence_json AS edition_reference_sequence_json,
                         coalesce(eg.reference_gap,false) AS expected_reference_gap,
                         CASE WHEN t.first_reference IS NULL THEN NULL ELSE
                           CAST(split_part(split_part(t.first_reference,' ',2),':',1) AS INTEGER)
                         END AS first_chapter,
                         CASE WHEN t.first_reference IS NULL THEN NULL ELSE
                           CAST(split_part(split_part(t.first_reference,' ',2),':',2) AS INTEGER)
                         END AS first_verse,
                         CASE WHEN t.last_reference IS NULL THEN NULL ELSE
                           CAST(split_part(split_part(t.last_reference,' ',2),':',1) AS INTEGER)
                         END AS last_chapter,
                         CASE WHEN t.last_reference IS NULL THEN NULL ELSE
                           CAST(split_part(split_part(t.last_reference,' ',2),':',2) AS INTEGER)
                         END AS last_verse
                  FROM benchmark_endpoint_mappings m
                  JOIN benchmark_endpoints e USING(endpoint_id)
                  JOIN target_facts t USING(mapping_id,endpoint_id,target_analysis_profile)
                  LEFT JOIN target_facts ec
                    ON ec.endpoint_id=m.endpoint_id
                   AND ec.target_analysis_profile='edition_complete'
                  LEFT JOIN gap_facts eg ON eg.mapping_id=ec.mapping_id
                ), expected AS (
                  SELECT *,
                    CASE
                      WHEN parse_status<>'parsed' OR parsed_book IS NULL THEN
                        CASE WHEN starts_with(parse_status,'invalid')
                             THEN 'invalid' ELSE 'unresolved_reference' END
                      WHEN target_count=0 AND target_analysis_profile='critical_core'
                           AND edition_target_count>0 THEN 'excluded_by_profile'
                      WHEN target_count=0 THEN 'unresolved_missing_target'
                      WHEN expected_reference_gap OR NOT (
                        (NOT is_range AND target_count=1
                         AND first_chapter=parsed_start_chapter
                         AND first_verse=parsed_start_verse)
                        OR (is_range AND edition_target_count>0
                            AND reference_sequence_json=edition_reference_sequence_json
                            AND first_chapter=parsed_start_chapter
                            AND first_verse=parsed_start_verse
                            AND last_chapter=parsed_end_chapter
                            AND last_verse=parsed_end_verse
                            AND NOT expected_reference_gap)
                      ) THEN 'mapped_partial'
                      ELSE 'mapped_provisional'
                    END AS expected_status
                  FROM facts
                )
                SELECT count(*) FROM expected
                WHERE mapping_status<>expected_status
                   OR mapping_method<>CASE
                        WHEN parse_status<>'parsed' OR parsed_book IS NULL
                          THEN 'no_mapping_invalid_or_unsupported_reference'
                        WHEN expected_status='excluded_by_profile'
                          THEN 'critical_core_profile_compatibility'
                        ELSE 'same_label_extant_reference' END
                   OR mapping_confidence<>CASE
                        WHEN expected_status='excluded_by_profile' THEN 'profile_excluded'
                        WHEN expected_status IN
                             ('invalid','unresolved_reference','unresolved_missing_target')
                          THEN 'unresolved'
                        WHEN expected_status='mapped_partial' THEN 'partial_provisional'
                        ELSE 'provisional_mechanical' END
                   OR ambiguity_reason IS DISTINCT FROM CASE
                        WHEN parse_status<>'parsed' OR parsed_book IS NULL THEN parse_status
                        WHEN expected_status='excluded_by_profile' THEN
                          'target exists in edition_complete but is excluded by critical_core'
                        WHEN expected_status='unresolved_missing_target' THEN
                          'exact target reference is absent from the pinned source edition'
                        WHEN expected_status='mapped_partial' THEN
                          'range maps only to ordered extant verses or contains a reference gap'
                        WHEN expected_status='mapped_provisional' THEN
                          'same-label mapping has no approved external versification crosswalk'
                        ELSE ambiguity_reason END
                """
            )
            _count_error(
                issues,
                "mapping_status_recomputation_mismatch",
                "Mapping status, confidence, method, or ambiguity does not reproduce.",
                status_mismatch,
                artifact="benchmark_endpoint_mappings",
            )

            stream_inference_mismatches = 0
            cursor = connection.execute(
                "SELECT e.source_reference,m.target_corpus,m.target_analysis_reading "
                "FROM benchmark_endpoint_mappings m JOIN benchmark_endpoints e "
                "USING(endpoint_id) ORDER BY m.mapping_id"
            )
            while batch := cursor.fetchmany(10_000):
                for source_reference, corpus, reading in batch:
                    expected_corpus = openbible_reference_corpus(str(source_reference)) or "hebrew"
                    expected_reading = "qere" if expected_corpus == "hebrew" else "source"
                    if corpus != expected_corpus or reading != expected_reading:
                        stream_inference_mismatches += 1
            _count_error(
                issues,
                "mapping_target_corpus_inference_mismatch",
                "Mapping corpus or reading does not reproduce from preserved source aliases.",
                stream_inference_mismatches,
                artifact="benchmark_endpoint_mappings",
            )

            mapping_identity_mismatches = 0
            cursor = connection.execute(
                "SELECT mapping_id,endpoint_id,target_corpus,target_analysis_profile,"
                "target_analysis_reading,target_granularity,mapping_method,crosswalk_version,"
                "target_passage_ids_json FROM benchmark_endpoint_mappings ORDER BY mapping_id"
            )
            while batch := cursor.fetchmany(10_000):
                for row in batch:
                    try:
                        target_ids = json.loads(str(row[8]))
                        if not isinstance(target_ids, list) or not all(
                            isinstance(value, str) for value in target_ids
                        ):
                            raise ValueError("target IDs must be strings")
                        identity = build_mapping_identity(
                            MappingIdentityPayload(
                                endpoint_id=str(row[1]),
                                target_corpus=cast(Any, row[2]),
                                target_analysis_profile=cast(Any, row[3]),
                                target_analysis_reading=cast(Any, row[4]),
                                target_granularity=cast(Any, row[5]),
                                mapping_method=str(row[6]),
                                crosswalk_version=(None if row[7] is None else str(row[7])),
                                target_passage_ids=tuple(target_ids),
                            )
                        )
                    except (ValueError, TypeError):
                        mapping_identity_mismatches += 1
                        continue
                    if row[0] != identity.identifier:
                        mapping_identity_mismatches += 1
            _count_error(
                issues,
                "mapping_identity_mismatch",
                "Mapping IDs do not reproduce from their governed identity payload.",
                mapping_identity_mismatches,
                artifact="benchmark_endpoint_mappings",
            )
    except Exception as exc:
        raise BenchmarkValidationError(f"could not validate benchmark DuckDB: {exc}") from exc


def _metadata_validation(
    *,
    table_counts: dict[str, int],
    leakage_counts: dict[str, int],
    split_counts: dict[str, int],
    negative_counts: dict[str, int],
    metadata: dict[str, object],
    config: BenchmarkConfig,
    source: SourceManifest,
    receipt: AcquisitionReceipt,
    passage: PassageInputMetadata,
    logical: dict[str, str],
    physical: dict[str, str],
    issues: list[BenchmarkValidationIssue],
) -> None:
    source_audit = _json_dict(metadata.get("source_audit_json"))
    expected_configuration_hash = benchmark_config_fingerprint(config)
    scalar_counts = {
        "relationship_count": table_counts["benchmark_relationships"],
        "endpoint_count": table_counts["benchmark_endpoints"],
        "mapping_count": table_counts["benchmark_endpoint_mappings"],
    }
    for field, expected in scalar_counts.items():
        if metadata.get(field) != expected:
            _error(
                issues,
                "metadata_count_mismatch",
                f"Benchmark metadata {field} does not reconcile: expected {expected}.",
                artifact="benchmark_metadata",
            )
    if metadata.get("configuration_hash") != expected_configuration_hash:
        _error(
            issues,
            "metadata_configuration_hash_mismatch",
            "Benchmark metadata configuration hash does not reproduce.",
            artifact="benchmark_metadata",
        )
    expected_source_versions = {source.source_id: source.version_or_commit}
    expected_archive_hashes = {source.source_id: config.sources.openbible.snapshot_sha256}
    if _json_dict(metadata.get("source_versions_json")) != expected_source_versions:
        _error(
            issues,
            "metadata_source_version_mismatch",
            "Benchmark metadata source version differs from the source manifest.",
            artifact="benchmark_metadata",
        )
    if _json_dict(metadata.get("source_archive_hashes_json")) != expected_archive_hashes:
        _error(
            issues,
            "metadata_archive_hash_mismatch",
            "Benchmark metadata archive hash differs from the benchmark config.",
            artifact="benchmark_metadata",
        )
    if _json_dict(metadata.get("source_file_hashes_json")) != source.file_hashes:
        _error(
            issues,
            "metadata_source_file_hash_mismatch",
            "Benchmark metadata extracted-file hashes differ from the source manifest.",
            artifact="benchmark_metadata",
        )
    canonical_stream = source_audit.get("canonical_stream_sha256")
    if canonical_stream != receipt.canonical_record_stream_sha256:
        _error(
            issues,
            "canonical_source_stream_mismatch",
            "Canonical source-record digest differs from the verified acquisition receipt.",
            artifact="benchmark_metadata",
        )
    if (
        source.version_or_commit == OPENBIBLE_PRODUCTION_VERSION
        and canonical_stream != OPENBIBLE_PRODUCTION_CANONICAL_SHA256
    ):
        _error(
            issues,
            "production_canonical_source_stream_mismatch",
            "Production OpenBible canonical source-record digest changed.",
            artifact="benchmark_metadata",
        )
    if metadata.get("tier1_header_sha256") != config.sources.tier1.header_sha256:
        _error(
            issues,
            "metadata_tier1_hash_mismatch",
            "Benchmark metadata Tier 1 header hash differs from the governed config.",
            artifact="benchmark_metadata",
        )
    expected_upstream = (
        {
            "greek": GREEK_IDENTITY_DIGEST,
            "hebrew": HEBREW_IDENTITY_DIGEST,
        },
        {
            "greek": GREEK_CONTENT_DIGEST,
            "hebrew": HEBREW_CONTENT_DIGEST,
        },
        {
            "greek": GREEK_ANALYTICAL_DIGEST,
            "hebrew": HEBREW_ANALYTICAL_DIGEST,
        },
        OSHB_LOGICAL_DIGESTS,
    )
    observed_upstream = (
        passage.primary_identity_digests,
        passage.surface_lemma_digests,
        passage.analytical_digests,
        passage.oshb_supplement_digests,
    )
    if observed_upstream != expected_upstream:
        _error(
            issues,
            "upstream_corpus_anchor_changed",
            "A Hebrew, Greek, or OSHB input digest differs from the fixed Milestone 6 anchors.",
            artifact="benchmark_metadata",
        )
    if (
        metadata.get("passage_input_run_id") != passage.run_id
        or _json_dict(metadata.get("passage_logical_hashes_json")) != passage.logical_hashes
    ):
        _error(
            issues,
            "metadata_passage_anchor_mismatch",
            "Benchmark metadata passage inputs differ from the verified Milestone 5 inputs.",
            artifact="benchmark_metadata",
        )
    aggregate_contracts = (
        ("leakage_group_counts_json", leakage_counts),
        ("split_counts_json", split_counts),
        ("negative_counts_json", negative_counts),
    )
    for field, observed in aggregate_contracts:
        if _json_dict(metadata.get(field)) != observed:
            _error(
                issues,
                "metadata_aggregate_mismatch",
                f"Benchmark metadata {field} does not reconcile with persisted rows.",
                artifact="benchmark_metadata",
            )
    expected_content_logical = {
        name: value for name, value in logical.items() if name != "benchmark_metadata"
    }
    expected_content_physical = {
        name: value for name, value in physical.items() if name != "benchmark_metadata"
    }
    if _json_dict(metadata.get("logical_table_hashes_json")) != expected_content_logical:
        _error(
            issues,
            "metadata_logical_hash_mismatch",
            "Benchmark metadata content-table logical hashes do not reproduce.",
            artifact="benchmark_metadata",
        )
    if _json_dict(metadata.get("physical_table_hashes_json")) != expected_content_physical:
        _error(
            issues,
            "metadata_physical_hash_mismatch",
            "Benchmark metadata content-table physical hashes do not reproduce.",
            artifact="benchmark_metadata",
        )
    identity_payload = {
        "benchmark_schema_version": config.benchmark_schema_version,
        "canonical_source_record_stream_sha256": receipt.canonical_record_stream_sha256,
        "configuration_hash": expected_configuration_hash,
        "openbible_archive_sha256": config.sources.openbible.snapshot_sha256,
        "passage_input_run_id": passage.run_id,
        "passage_logical_hashes": passage.logical_hashes,
        "tier1_header_sha256": config.sources.tier1.header_sha256,
    }
    identity_hash = hashlib.sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_run_id = f"benchmark-v1-{identity_hash[:20]}"
    expected_version = f"known-links-v1-{identity_hash[:12]}"
    if (
        metadata.get("benchmark_run_id") != expected_run_id
        or metadata.get("benchmark_version") != expected_version
    ):
        _error(
            issues,
            "benchmark_identity_mismatch",
            "Benchmark run ID or version does not reproduce from governed logical inputs.",
            artifact="benchmark_metadata",
        )


def _database_metadata(database_path: Path) -> dict[str, object]:
    try:
        with _bounded_validation_connection(database_path) as connection:
            cursor = connection.execute("SELECT * FROM benchmark_metadata")
            rows = cast(list[tuple[object, ...]], cursor.fetchall())
            description = cursor.description
    except Exception as exc:
        raise BenchmarkValidationError(f"could not read benchmark metadata: {exc}") from exc
    if len(rows) != 1 or description is None:
        raise BenchmarkValidationError(
            f"benchmark_metadata must contain exactly one row; observed {len(rows)}"
        )
    names = [str(item[0]) for item in description]
    return dict(zip(names, rows[0], strict=True))


def _database_group_counts(
    connection: duckdb.DuckDBPyConnection, table: str, columns: tuple[str, ...]
) -> dict[str, int]:
    selected = ",".join(columns)
    rows = cast(
        list[tuple[object, ...]],
        connection.execute(
            f'SELECT {selected},count(*) FROM "{table}" GROUP BY {selected} ORDER BY {selected}'
        ).fetchall(),
    )
    return {"|".join(str(value) for value in row[:-1]): int(str(row[-1])) for row in rows}


def _configured_leakage_crossing_count(
    connection: duckdb.DuckDBPyConnection,
    *,
    split_name: str,
    group_types: tuple[str, ...],
) -> int:
    if not group_types:
        return 0
    placeholders = ",".join("?" for _ in group_types)
    row = connection.execute(
        f"""
        SELECT count(*) FROM (
          SELECT l.group_type,l.leakage_group_id
          FROM benchmark_leakage_groups l
          JOIN benchmark_split_assignments s USING(relationship_id)
          WHERE s.split_strategy=? AND s.partition<>'excluded'
            AND l.group_type IN ({placeholders})
          GROUP BY l.group_type,l.leakage_group_id
          HAVING count(DISTINCT s.partition)>1
        )
        """,
        [split_name, *group_types],
    ).fetchone()
    if row is None:
        raise BenchmarkValidationError("leakage crossing query returned no row")
    return int(row[0])


def _split_expected_ctes(configured: Any, config: BenchmarkConfig) -> str:
    """Build an independent expected-assignment relation for one split strategy."""

    proportions = configured.proportions
    book_a = "coalesce(book_a,'UNRESOLVED')"
    book_b = "coalesce(book_b,'UNRESOLVED')"
    book_a_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql=book_a,
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    book_b_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql=book_b,
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    source_a_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql="reference_a",
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    source_b_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql="reference_b",
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    pair_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql=f"least({book_a},{book_b}) || '|' || greatest({book_a},{book_b})",
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    genre_a = _sql_genre(book_a, config)
    genre_b = _sql_genre(book_b, config)
    genre_a_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql=genre_a,
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )
    genre_b_partition = _sql_hash_partition(
        seed=configured.seed,
        value_sql=genre_b,
        test_fraction=proportions.test,
        development_fraction=proportions.development,
    )

    def priority(first: str, second: str) -> str:
        return (
            f"CASE WHEN ({first})='test' OR ({second})='test' THEN 'test' "
            f"WHEN ({first})='development' OR ({second})='development' "
            "THEN 'development' ELSE 'train' END"
        )

    strategy = configured.strategy
    if strategy == "held_out_book":
        candidate_partition = priority(book_a_partition, book_b_partition)
        strategy_reason = "NULL"
    elif strategy == "held_out_book_pair":
        candidate_partition = pair_partition
        strategy_reason = "NULL"
    elif strategy == "held_out_source_passage":
        candidate_partition = (
            f"CASE WHEN ({source_a_partition})=({source_b_partition}) "
            f"THEN ({source_a_partition}) ELSE 'excluded' END"
        )
        strategy_reason = (
            "CASE WHEN contains(reference_a,'-') OR contains(reference_b,'-') "
            "THEN 'range_overlap_guard' "
            f"WHEN ({source_a_partition})<>({source_b_partition}) "
            "THEN 'endpoint_partition_conflict' ELSE NULL END"
        )
    elif strategy == "held_out_genre":
        candidate_partition = priority(genre_a_partition, genre_b_partition)
        strategy_reason = "NULL"
    else:
        candidate_partition = "'excluded'"
        strategy_reason = "'unsupported_split_strategy'"

    included_tiers = ",".join(str(value) for value in configured.included_tiers)
    statuses = ",".join(f"'{value}'" for value in config.mapping.weak_supervision_statuses)
    enforced = ",".join(f"'{value}'" for value in configured.enforced_leakage_groups)
    base_reason = (
        f"CASE WHEN tier NOT IN ({included_tiers}) THEN 'tier_not_included' "
        + (
            "WHEN NOT mapping_eligible THEN 'mapping_ineligible' "
            if configured.mapping_required
            else ""
        )
        + (
            "WHEN relationship_family_key IS NULL THEN 'relationship_family_unavailable' "
            if strategy == "held_out_relationship_family"
            else ""
        )
        + f"ELSE {strategy_reason} END"
    )
    return f"""
        WITH endpoint_facts AS (
          SELECT r.relationship_id,r.tier,
                 max(e.parsed_book) FILTER (WHERE e.endpoint_side='a') AS book_a,
                 max(e.parsed_book) FILTER (WHERE e.endpoint_side='b') AS book_b,
                 max(e.source_reference) FILTER (WHERE e.endpoint_side='a') AS reference_a,
                 max(e.source_reference) FILTER (WHERE e.endpoint_side='b') AS reference_b,
                 coalesce(bool_and(m.mapping_status IN ({statuses})),false)
                   AS mapping_eligible,
                 CAST(NULL AS VARCHAR) AS relationship_family_key
          FROM benchmark_relationships r
          LEFT JOIN benchmark_endpoints e USING(relationship_id)
          LEFT JOIN benchmark_endpoint_mappings m
            ON m.endpoint_id=e.endpoint_id
           AND m.target_analysis_profile='edition_complete'
          GROUP BY r.relationship_id,r.tier
        ), raw_base AS (
          SELECT *,{candidate_partition} AS candidate_partition,
                 {base_reason} AS base_reason
          FROM endpoint_facts
        ), base AS (
          SELECT relationship_id,
                 CASE WHEN base_reason IS NULL THEN candidate_partition ELSE 'excluded' END
                   AS base_partition,
                 base_reason
          FROM raw_base
        ), conflict_memberships AS (
          SELECT l.relationship_id,l.leakage_group_id,l.group_type,b.base_partition
          FROM benchmark_leakage_groups l
          JOIN base b USING(relationship_id)
          WHERE b.base_reason IS NULL AND l.group_type IN ({enforced})
        ), conflicting_groups AS (
          SELECT leakage_group_id,group_type
          FROM conflict_memberships
          GROUP BY leakage_group_id,group_type
          HAVING count(DISTINCT base_partition)>1
        ), relationship_conflicts AS (
          SELECT m.relationship_id,m.leakage_group_id,m.group_type
          FROM conflict_memberships m
          JOIN conflicting_groups c USING(leakage_group_id,group_type)
          QUALIFY row_number() OVER (
            PARTITION BY m.relationship_id ORDER BY m.group_type,m.leakage_group_id
          )=1
        ), exact_groups AS (
          SELECT relationship_id,min(leakage_group_id) AS leakage_group_id
          FROM benchmark_leakage_groups
          WHERE group_type='exact_unordered_pair'
          GROUP BY relationship_id
        ), expected AS (
          SELECT b.relationship_id,
                 CASE WHEN c.relationship_id IS NOT NULL THEN 'excluded'
                      ELSE b.base_partition END AS expected_partition,
                 CASE WHEN c.relationship_id IS NOT NULL THEN 'excluded'
                      WHEN b.base_reason IS NOT NULL THEN 'excluded'
                      ELSE 'eligible' END AS expected_eligibility,
                 CASE WHEN c.relationship_id IS NOT NULL
                      THEN 'leakage_group_partition_conflict:' || c.group_type
                      ELSE b.base_reason END AS expected_reason,
                 CASE WHEN c.relationship_id IS NOT NULL THEN c.leakage_group_id
                      ELSE x.leakage_group_id END AS expected_leakage_group_id
          FROM base b
          LEFT JOIN relationship_conflicts c USING(relationship_id)
          LEFT JOIN exact_groups x USING(relationship_id)
        )
    """


def _split_database_validation(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: BenchmarkConfig,
    metadata: dict[str, object],
    issues: list[BenchmarkValidationIssue],
) -> None:
    """Recompute split completeness, eligibility, partitions, and provenance."""

    def scalar(sql: str, parameters: tuple[object, ...] = ()) -> int:
        row = connection.execute(sql, list(parameters)).fetchone()
        if row is None:
            raise BenchmarkValidationError("split validation query returned no row")
        return int(row[0])

    _count_error(
        issues,
        "split_foreign_key_failure",
        "A split assignment references a missing relationship.",
        scalar(
            "SELECT count(*) FROM benchmark_split_assignments s "
            "LEFT JOIN benchmark_relationships r USING(relationship_id) "
            "WHERE r.relationship_id IS NULL"
        ),
        artifact="benchmark_split_assignments",
    )
    configured_names = ",".join(f"('{item.name}')" for item in config.splits)
    _count_error(
        issues,
        "split_completeness_mismatch",
        "Every relationship must have exactly one row for every configured split.",
        scalar(
            f"""
            SELECT count(*) FROM (
              SELECT r.relationship_id,c.split_strategy,count(s.relationship_id) AS n
              FROM benchmark_relationships r
              CROSS JOIN (VALUES {configured_names}) c(split_strategy)
              LEFT JOIN benchmark_split_assignments s
                ON s.relationship_id=r.relationship_id
               AND s.split_strategy=c.split_strategy
              GROUP BY r.relationship_id,c.split_strategy HAVING n<>1
            )
            """
        ),
        artifact="benchmark_split_assignments",
    )

    identity_mismatches = 0
    cursor = connection.execute(
        "SELECT split_assignment_id,benchmark_version,config_hash,relationship_id,"
        "split_strategy FROM benchmark_split_assignments ORDER BY split_assignment_id"
    )
    while batch := cursor.fetchmany(10_000):
        for identifier, version, config_hash, relationship_id, strategy in batch:
            expected = _split_assignment_id(
                benchmark_version=str(version),
                config_hash=str(config_hash),
                relationship_id=str(relationship_id),
                strategy=str(strategy),
            )
            if identifier != expected:
                identity_mismatches += 1
    _count_error(
        issues,
        "split_identity_mismatch",
        "Split-assignment IDs do not reproduce from their governed payload.",
        identity_mismatches,
        artifact="benchmark_split_assignments",
    )

    for configured in config.splits:
        expected_ctes = _split_expected_ctes(configured, config)
        common_join = (
            expected_ctes + " SELECT count(*) FROM benchmark_split_assignments s "
            "JOIN expected e USING(relationship_id) WHERE s.split_strategy=? AND "
        )
        _count_error(
            issues,
            "split_partition_behavior_mismatch",
            f"Split {configured.name} partitions do not reproduce from held-out values.",
            scalar(
                common_join + "s.partition<>e.expected_partition",
                (configured.name,),
            ),
            artifact="benchmark_split_assignments",
        )
        _count_error(
            issues,
            "split_eligibility_mismatch",
            f"Split {configured.name} eligibility or exclusions do not reproduce.",
            scalar(
                common_join + "(s.eligibility_status<>e.expected_eligibility "
                "OR s.exclusion_reason IS DISTINCT FROM e.expected_reason)",
                (configured.name,),
            ),
            artifact="benchmark_split_assignments",
        )
        _count_error(
            issues,
            "split_leakage_group_reconciliation_mismatch",
            f"Split {configured.name} leakage-group attribution does not reproduce.",
            scalar(
                common_join + "s.leakage_group_id IS DISTINCT FROM e.expected_leakage_group_id",
                (configured.name,),
            ),
            artifact="benchmark_split_assignments",
        )
        _count_error(
            issues,
            "split_provenance_mismatch",
            f"Split {configured.name} seed, version, or configuration provenance changed.",
            scalar(
                "SELECT count(*) FROM benchmark_split_assignments WHERE split_strategy=? "
                "AND (seed<>? OR benchmark_version<>? OR config_hash<>?)",
                (
                    configured.name,
                    configured.seed,
                    str(metadata["benchmark_version"]),
                    str(metadata["configuration_hash"]),
                ),
            ),
            artifact="benchmark_split_assignments",
        )


def _eligible_positive_ctes(config: BenchmarkConfig) -> str:
    """Return the independently reproducible held-out-book positive-template relation."""

    held_out = next(item for item in config.splits if item.strategy == "held_out_book")
    passage_a_partition = _sql_hash_partition(
        seed=held_out.seed,
        value_sql="a.book",
        test_fraction=held_out.proportions.test,
        development_fraction=held_out.proportions.development,
    )
    passage_b_partition = _sql_hash_partition(
        seed=held_out.seed,
        value_sql="b.book",
        test_fraction=held_out.proportions.test,
        development_fraction=held_out.proportions.development,
    )
    return f"""
        WITH endpoint_targets AS (
          SELECT e.relationship_id,e.endpoint_side,
                 count(t.target_passage_id) AS target_count,
                 min(t.target_passage_id) AS target_passage_id
          FROM benchmark_endpoints e
          JOIN benchmark_endpoint_mappings m
            ON m.endpoint_id=e.endpoint_id
           AND m.target_analysis_profile='edition_complete'
          LEFT JOIN benchmark_mapping_target_passages t
            ON t.mapping_id=m.mapping_id AND t.endpoint_id=m.endpoint_id
          GROUP BY e.relationship_id,e.endpoint_side
        ), relationship_targets AS (
          SELECT relationship_id,
                 max(target_count) FILTER (WHERE endpoint_side='a') AS count_a,
                 max(target_count) FILTER (WHERE endpoint_side='b') AS count_b,
                 max(target_passage_id) FILTER (WHERE endpoint_side='a') AS passage_a_id,
                 max(target_passage_id) FILTER (WHERE endpoint_side='b') AS passage_b_id
          FROM endpoint_targets GROUP BY relationship_id
        ), eligible_positives AS (
          SELECT t.relationship_id,t.passage_a_id,t.passage_b_id,s.partition,
                 least(a.book,b.book) || '|' || greatest(a.book,b.book) AS book_pair
          FROM relationship_targets t
          JOIN benchmark_split_assignments s USING(relationship_id)
          JOIN passages a ON a.passage_id=t.passage_a_id
          JOIN passages b ON b.passage_id=t.passage_b_id
          WHERE s.split_strategy='held_out_book' AND s.partition<>'excluded'
            AND t.count_a=1 AND t.count_b=1
            AND t.passage_a_id<>t.passage_b_id
            AND ({passage_a_partition})=({passage_b_partition})
            AND ({passage_a_partition})=s.partition
        )
    """


def _expected_contrastive_id(
    *,
    benchmark_version: str,
    generation_config_hash: str,
    negative_strategy: str,
    passage_a_id: str,
    passage_b_id: str,
    seed: int,
    split_strategy: str,
) -> str:
    payload = json.dumps(
        {
            "benchmark_version": benchmark_version,
            "generation_config_hash": generation_config_hash,
            "negative_strategy": negative_strategy,
            "passage_a_id": passage_a_id,
            "passage_b_id": passage_b_id,
            "seed": seed,
            "split_strategy": split_strategy,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"BC_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _negative_database_validation(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: BenchmarkConfig,
    metadata: dict[str, object],
    issues: list[BenchmarkValidationIssue],
) -> None:
    """Recompute every persisted presumed-negative safety and ratio contract."""

    def scalar(sql: str, parameters: tuple[object, ...] = ()) -> int:
        row = connection.execute(sql, list(parameters)).fetchone()
        if row is None:
            raise BenchmarkValidationError("negative validation query returned no row")
        return int(row[0])

    basic_checks = (
        (
            """
            SELECT count(*) FROM benchmark_presumed_negatives n
            LEFT JOIN passages a ON a.passage_id=n.passage_a_id
            LEFT JOIN passages b ON b.passage_id=n.passage_b_id
            WHERE a.passage_id IS NULL OR b.passage_id IS NULL
            """,
            "presumed_negative_missing_passage",
            "A presumed negative references a missing passage.",
        ),
        (
            """
            SELECT count(*) FROM benchmark_presumed_negatives n
            JOIN passages a ON a.passage_id=n.passage_a_id
            JOIN passages b ON b.passage_id=n.passage_b_id
            WHERE a.analysis_profile<>'edition_complete'
               OR b.analysis_profile<>'edition_complete'
               OR a.granularity<>'verse' OR b.granularity<>'verse'
               OR (a.corpus='hebrew' AND a.analysis_reading<>'qere')
               OR (b.corpus='hebrew' AND b.analysis_reading<>'qere')
               OR (a.corpus='greek' AND a.analysis_reading<>'source')
               OR (b.corpus='greek' AND b.analysis_reading<>'source')
            """,
            "presumed_negative_passage_stream_mismatch",
            "Presumed negatives must use governed edition-complete verse streams.",
        ),
        (
            "SELECT count(*)-count(DISTINCT contrastive_id) FROM benchmark_presumed_negatives",
            "duplicate_contrastive_identity",
            "Presumed-negative identities are not unique.",
        ),
        (
            """
            SELECT count(*)-count(DISTINCT (
              negative_strategy,least(passage_a_id,passage_b_id),
              greatest(passage_a_id,passage_b_id)
            )) FROM benchmark_presumed_negatives
            """,
            "duplicate_presumed_negative_pair",
            "A strategy contains duplicate unordered presumed-negative pairs.",
        ),
        (
            """
            SELECT count(*) FROM benchmark_presumed_negatives
            WHERE passage_a_id>=passage_b_id OR NOT presumed_negative
               OR NOT positive_graph_checked OR NOT reverse_pair_checked
               OR NOT passage_overlap_checked OR NOT leakage_checked
               OR lower(notes) LIKE '%proven negative%'
            """,
            "presumed_negative_control_violation",
            "A presumed negative violates labeling, ordering, or checked-flag contracts.",
        ),
        (
            """
            SELECT count(*) FROM benchmark_presumed_negatives n
            JOIN passages a ON a.passage_id=n.passage_a_id
            JOIN passages b ON b.passage_id=n.passage_b_id
            WHERE a.corpus=b.corpus
              AND a.analysis_profile=b.analysis_profile
              AND a.analysis_reading=b.analysis_reading
              AND a.start_stream_position_in_corpus<=b.end_stream_position_in_corpus
              AND b.start_stream_position_in_corpus<=a.end_stream_position_in_corpus
            """,
            "presumed_negative_passage_overlap",
            "A presumed negative contains passages with actual token-position overlap.",
        ),
        (
            """
            WITH endpoint_targets AS (
              SELECT e.relationship_id,e.endpoint_side,t.target_passage_id
              FROM benchmark_endpoints e
              JOIN benchmark_endpoint_mappings m USING(endpoint_id)
              JOIN benchmark_mapping_target_passages t USING(mapping_id,endpoint_id)
              WHERE m.target_analysis_profile='edition_complete'
            ), positive_pairs AS (
              SELECT a.target_passage_id AS a,b.target_passage_id AS b
              FROM endpoint_targets a JOIN endpoint_targets b USING(relationship_id)
              WHERE a.endpoint_side='a' AND b.endpoint_side='b'
            )
            SELECT count(DISTINCT n.contrastive_id) FROM benchmark_presumed_negatives n
            JOIN positive_pairs p
              ON least(n.passage_a_id,n.passage_b_id)=least(p.a,p.b)
             AND greatest(n.passage_a_id,n.passage_b_id)=greatest(p.a,p.b)
            """,
            "presumed_negative_positive_collision",
            "A presumed negative collides with the complete mapped positive graph.",
        ),
    )
    for sql, code, message in basic_checks:
        _count_error(
            issues,
            code,
            message,
            scalar(sql),
            artifact="benchmark_presumed_negatives",
        )

    held_out = next(item for item in config.splits if item.strategy == "held_out_book")
    partition_a = _sql_hash_partition(
        seed=held_out.seed,
        value_sql="a.book",
        test_fraction=held_out.proportions.test,
        development_fraction=held_out.proportions.development,
    )
    partition_b = _sql_hash_partition(
        seed=held_out.seed,
        value_sql="b.book",
        test_fraction=held_out.proportions.test,
        development_fraction=held_out.proportions.development,
    )
    genre_a = _sql_genre("a.book", config)
    genre_b = _sql_genre("b.book", config)
    fact_mismatch = scalar(
        f"""
        SELECT count(*) FROM benchmark_presumed_negatives n
        JOIN passages a ON a.passage_id=n.passage_a_id
        JOIN passages b ON b.passage_id=n.passage_b_id
        WHERE n.length_difference<>abs(a.token_count-b.token_count)
           OR n.corpus_pair<>least(a.corpus,b.corpus) || '|' || greatest(a.corpus,b.corpus)
           OR n.book_pair<>least(a.book,b.book) || '|' || greatest(a.book,b.book)
           OR n.genre_pair<>least(({genre_a}),({genre_b})) || '|' ||
                            greatest(({genre_a}),({genre_b}))
        """
    )
    _count_error(
        issues,
        "presumed_negative_derived_fact_mismatch",
        "Length, corpus, book, or genre facts do not reproduce from passage data.",
        fact_mismatch,
        artifact="benchmark_presumed_negatives",
    )
    partition_mismatch = scalar(
        f"""
        SELECT count(*) FROM benchmark_presumed_negatives n
        JOIN passages a ON a.passage_id=n.passage_a_id
        JOIN passages b ON b.passage_id=n.passage_b_id
        WHERE n.partition<>({partition_a}) OR n.partition<>({partition_b})
        """
    )
    _count_error(
        issues,
        "presumed_negative_partition_mismatch",
        "Passage books and persisted negatives disagree with held-out-book partitioning.",
        partition_mismatch,
        artifact="benchmark_presumed_negatives",
    )

    expected_strategies = {
        item.strategy: item
        for item in config.presumed_negatives
        if item.enabled and item.ratio_per_eligible_positive > 0
    }
    observed_strategies = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT negative_strategy FROM benchmark_presumed_negatives"
        ).fetchall()
    }
    if observed_strategies != set(expected_strategies):
        _error(
            issues,
            "presumed_negative_strategy_set_mismatch",
            "Persisted presumed-negative strategies differ from enabled configuration.",
            artifact="benchmark_presumed_negatives",
        )

    eligible_ctes = _eligible_positive_ctes(config)
    eligible_positive_count = scalar(eligible_ctes + " SELECT count(*) FROM eligible_positives")
    for strategy, configured in expected_strategies.items():
        provenance_mismatch = scalar(
            """
            SELECT count(*) FROM benchmark_presumed_negatives
            WHERE negative_strategy=? AND (
              seed<>? OR split_strategy<>'held_out_book'
              OR benchmark_version<>? OR generation_config_hash<>?
            )
            """,
            (
                strategy,
                configured.seed,
                str(metadata["benchmark_version"]),
                str(metadata["configuration_hash"]),
            ),
        )
        _count_error(
            issues,
            "presumed_negative_provenance_mismatch",
            f"Strategy {strategy} seed, split, version, or configuration provenance changed.",
            provenance_mismatch,
            artifact="benchmark_presumed_negatives",
        )
        observed_count = scalar(
            "SELECT count(*) FROM benchmark_presumed_negatives WHERE negative_strategy=?",
            (strategy,),
        )
        expected_count = math.ceil(eligible_positive_count * configured.ratio_per_eligible_positive)
        if observed_count != expected_count:
            _error(
                issues,
                "presumed_negative_ratio_mismatch",
                f"Strategy {strategy} expected {expected_count} rows from "
                f"{eligible_positive_count} eligible positives; observed {observed_count}.",
                artifact="benchmark_presumed_negatives",
            )

        if strategy == "length_matched_random_unlinked":
            constraint_sql = (
                "SELECT count(*) FROM benchmark_presumed_negatives n "
                "JOIN passages a ON a.passage_id=n.passage_a_id "
                "JOIN passages b ON b.passage_id=n.passage_b_id "
                "WHERE n.negative_strategy=? AND "
                f"abs(a.token_count-b.token_count)>{configured.length_tolerance_tokens}"
            )
        elif strategy == "same_book_unlinked":
            constraint_sql = (
                "SELECT count(*) FROM benchmark_presumed_negatives n "
                "JOIN passages a ON a.passage_id=n.passage_a_id "
                "JOIN passages b ON b.passage_id=n.passage_b_id "
                "WHERE n.negative_strategy=? AND a.book<>b.book"
            )
        elif strategy == "same_book_pair_unlinked":
            constraint_sql = (
                eligible_ctes + " SELECT count(*) FROM benchmark_presumed_negatives n "
                "WHERE n.negative_strategy=? AND NOT EXISTS ("
                "SELECT 1 FROM eligible_positives p WHERE p.partition=n.partition "
                "AND p.book_pair=n.book_pair)"
            )
        elif strategy == "same_broad_genre_unlinked":
            constraint_sql = (
                "SELECT count(*) FROM benchmark_presumed_negatives n "
                "JOIN passages a ON a.passage_id=n.passage_a_id "
                "JOIN passages b ON b.passage_id=n.passage_b_id "
                "WHERE n.negative_strategy=? AND "
                f"({genre_a})<>({genre_b})"
            )
        else:
            constraint_sql = (
                "WITH verse_ordinals AS (SELECT passage_id,book,corpus,analysis_profile,"
                "analysis_reading,row_number() OVER (PARTITION BY corpus,analysis_profile,"
                "analysis_reading,book ORDER BY start_stream_position_in_corpus,passage_id) "
                "AS ordinal FROM passages WHERE granularity='verse') "
                "SELECT count(*) FROM benchmark_presumed_negatives n "
                "JOIN verse_ordinals a ON a.passage_id=n.passage_a_id "
                "JOIN verse_ordinals b ON b.passage_id=n.passage_b_id "
                "WHERE n.negative_strategy=? AND "
                "(a.book<>b.book OR abs(a.ordinal-b.ordinal)>5)"
            )
        _count_error(
            issues,
            "presumed_negative_strategy_constraint_mismatch",
            f"Strategy {strategy} rows violate their configured passage constraint.",
            scalar(constraint_sql, (strategy,)),
            artifact="benchmark_presumed_negatives",
        )

    identity_mismatches = 0
    cursor = connection.execute(
        "SELECT contrastive_id,benchmark_version,generation_config_hash,negative_strategy,"
        "passage_a_id,passage_b_id,seed,split_strategy "
        "FROM benchmark_presumed_negatives ORDER BY contrastive_id"
    )
    while batch := cursor.fetchmany(10_000):
        for row in batch:
            expected = _expected_contrastive_id(
                benchmark_version=str(row[1]),
                generation_config_hash=str(row[2]),
                negative_strategy=str(row[3]),
                passage_a_id=str(row[4]),
                passage_b_id=str(row[5]),
                seed=int(row[6]),
                split_strategy=str(row[7]),
            )
            if row[0] != expected:
                identity_mismatches += 1
    _count_error(
        issues,
        "presumed_negative_identity_mismatch",
        "Contrastive IDs do not reproduce from their governed generation payload.",
        identity_mismatches,
        artifact="benchmark_presumed_negatives",
    )


def _database_relational_validation(
    *,
    database_path: Path,
    config: BenchmarkConfig,
    source: SourceManifest,
    source_audit: dict[str, object],
    metadata: dict[str, object],
    table_counts: dict[str, int],
    issues: list[BenchmarkValidationIssue],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    def scalar(
        connection: duckdb.DuckDBPyConnection,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> int:
        row = connection.execute(sql, list(parameters)).fetchone()
        if row is None:
            raise BenchmarkValidationError("benchmark validation query returned no row")
        return int(row[0])

    def require_zero(
        connection: duckdb.DuckDBPyConnection,
        sql: str,
        code: str,
        message: str,
        *,
        artifact: str | None = None,
        parameters: tuple[object, ...] = (),
    ) -> None:
        observed = scalar(connection, sql, parameters)
        if observed:
            _error(
                issues,
                code,
                f"{message} Count={observed}.",
                artifact=artifact,
            )

    try:
        with _bounded_validation_connection(database_path) as connection:
            for name, expected in table_counts.items():
                observed = scalar(connection, f'SELECT count(*) FROM "{name}"')
                if observed != expected:
                    _error(
                        issues,
                        "duckdb_parquet_count_mismatch",
                        f"DuckDB {name} count {observed} differs from Parquet count {expected}.",
                        artifact=name,
                    )

            expected_raw = source_audit.get("raw_row_count")
            if (
                not isinstance(expected_raw, int)
                or table_counts["benchmark_source_records"] != expected_raw
            ):
                _error(
                    issues,
                    "source_row_count_mismatch",
                    f"Source audit expects {expected_raw!r} rows; observed "
                    f"{table_counts['benchmark_source_records']}.",
                    artifact="benchmark_source_records",
                )
            parsed_rows = scalar(
                connection,
                "SELECT count(*) FROM benchmark_source_records WHERE parse_status='parsed'",
            )
            invalid_rows = table_counts["benchmark_source_records"] - parsed_rows
            if (
                source_audit.get("parsed_row_count") != parsed_rows
                or source_audit.get("invalid_row_count") != invalid_rows
            ):
                _error(
                    issues,
                    "source_parse_count_mismatch",
                    "Source-record parse statuses do not reconcile with the source audit.",
                    artifact="benchmark_source_records",
                )
            self_occurrences = scalar(
                connection,
                "SELECT count(*) FROM benchmark_issues WHERE code='self_link_excluded'",
            )
            expected_links = parsed_rows - self_occurrences
            if table_counts["benchmark_relationship_source_records"] != expected_links:
                _error(
                    issues,
                    "source_link_reconciliation_failure",
                    f"Expected {expected_links} parsed non-self source links; observed "
                    f"{table_counts['benchmark_relationship_source_records']}.",
                    artifact="benchmark_relationship_source_records",
                )
            require_zero(
                connection,
                "SELECT count(*)-count(DISTINCT (relationship_id,source_record_id)) "
                "FROM benchmark_relationship_source_records",
                "duplicate_relationship_source_link",
                "Relationship-to-source-record links are not unique.",
                artifact="benchmark_relationship_source_records",
            )
            require_zero(
                connection,
                "SELECT count(*) FROM benchmark_relationship_source_records l "
                "LEFT JOIN benchmark_source_records s USING(source_record_id) "
                "LEFT JOIN benchmark_relationships r USING(relationship_id) "
                "WHERE s.source_record_id IS NULL OR r.relationship_id IS NULL",
                "source_link_foreign_key_failure",
                "A relationship-source link references a missing row.",
                artifact="benchmark_relationship_source_records",
            )
            require_zero(
                connection,
                """
                SELECT count(*) FROM benchmark_relationships r
                LEFT JOIN (
                  SELECT l.relationship_id,count(*) AS n,sum(s.source_weight) AS weight_sum,
                         max(s.source_weight) AS weight_max
                  FROM benchmark_relationship_source_records l
                  JOIN benchmark_source_records s USING(source_record_id)
                  GROUP BY l.relationship_id
                ) a USING(relationship_id)
                WHERE a.relationship_id IS NULL OR r.source_record_count<>a.n
                   OR r.source_weight_sum<>a.weight_sum
                   OR r.source_weight_max IS DISTINCT FROM a.weight_max
                """,
                "relationship_source_aggregate_mismatch",
                "Relationship counts or weights do not reproduce from linked source records.",
                artifact="benchmark_relationships",
            )
            require_zero(
                connection,
                """
                SELECT count(*) FROM benchmark_relationships
                WHERE tier<>3 OR primary_evaluation_eligible OR tier1_eligible
                   OR NOT weak_supervision_eligible OR NOT knownness_filter_eligible
                   OR source_id<>? OR source_version<>?
                """,
                "tier3_governance_violation",
                "OpenBible relationships violate Tier 3 identity or eligibility gates.",
                artifact="benchmark_relationships",
                parameters=(
                    config.sources.openbible.source_id,
                    config.sources.openbible.snapshot_version,
                ),
            )
            require_zero(
                connection,
                """
                SELECT count(*) FROM benchmark_source_records
                WHERE source_id<>? OR source_version<>? OR source_archive_sha256<>?
                   OR source_file<>?
                """,
                "source_provenance_mismatch",
                "Persisted source records differ from the governed OpenBible snapshot.",
                artifact="benchmark_source_records",
                parameters=(
                    source.source_id,
                    source.version_or_commit or "",
                    config.sources.openbible.snapshot_sha256,
                    config.sources.openbible.source_file,
                ),
            )
            require_zero(
                connection,
                "SELECT count(*)-count(DISTINCT source_record_id) FROM benchmark_source_records",
                "duplicate_source_record_identity",
                "Source-record identities are not unique.",
                artifact="benchmark_source_records",
            )
            occurrence_counts: Counter[str] = Counter()
            cursor = connection.execute(
                "SELECT source_record_id,source_id,source_archive_sha256,raw_record_sha256,"
                "source_line_number FROM benchmark_source_records "
                "ORDER BY source_file,source_line_number,source_record_id"
            )
            while batch := cursor.fetchmany(10_000):
                for source_id_value, source_name, archive_hash, raw_hash, line_number in batch:
                    rendered_hash = str(raw_hash)
                    occurrence_counts[rendered_hash] += 1
                    payload = SourceRecordIdentityPayload(
                        source_id=str(source_name),
                        source_archive_sha256=str(archive_hash),
                        raw_record_sha256=rendered_hash,
                        duplicate_occurrence_ordinal=occurrence_counts[rendered_hash],
                    )
                    digest = hashlib.sha256(
                        canonical_payload_json(payload).encode("utf-8")
                    ).hexdigest()
                    if source_id_value != f"BSR_{digest}":
                        _error(
                            issues,
                            "source_record_identity_mismatch",
                            f"Source-record identity does not reproduce at line {line_number}.",
                            artifact="benchmark_source_records",
                        )
                        batch = []
                        break
                if not batch:
                    break

            require_zero(
                connection,
                "SELECT count(*)-count(DISTINCT relationship_id) FROM benchmark_relationships",
                "duplicate_relationship_identity",
                "Relationship identities are not unique.",
                artifact="benchmark_relationships",
            )
            cursor = connection.execute(
                "SELECT relationship_id,source_id,source_version,source_reference_scheme,"
                "source_reference_a,source_reference_b,relationship_direction,"
                "canonical_directed_pair_id,canonical_undirected_pair_id "
                "FROM benchmark_relationships ORDER BY relationship_id"
            )
            identity_failed = False
            while batch := cursor.fetchmany(10_000):
                for row in batch:
                    identity = build_relationship_identity(
                        RelationshipIdentityPayload(
                            source_id=str(row[1]),
                            source_version=str(row[2]),
                            source_reference_scheme=str(row[3]),
                            normalized_source_endpoint_a=str(row[4]),
                            normalized_source_endpoint_b=str(row[5]),
                            source_direction=str(row[6]),
                        )
                    )
                    directed, unordered = build_pair_identities(
                        source_reference_scheme=str(row[3]),
                        normalized_endpoint_a=str(row[4]),
                        normalized_endpoint_b=str(row[5]),
                    )
                    if (
                        identity.identifier != row[0]
                        or directed.identifier != row[7]
                        or unordered.identifier != row[8]
                    ):
                        _error(
                            issues,
                            "relationship_identity_mismatch",
                            f"Relationship identity does not reproduce: {row[0]}",
                            artifact="benchmark_relationships",
                        )
                        identity_failed = True
                        break
                if identity_failed:
                    break

            endpoint_checks = (
                (
                    "SELECT count(*)-count(DISTINCT endpoint_id) FROM benchmark_endpoints",
                    "duplicate_endpoint_identity",
                    "Endpoint identities are not unique.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_relationships r LEFT JOIN (
                      SELECT relationship_id,count(*) AS n,count(DISTINCT endpoint_side) AS sides
                      FROM benchmark_endpoints GROUP BY relationship_id
                    ) e USING(relationship_id)
                    WHERE e.relationship_id IS NULL OR e.n<>2 OR e.sides<>2
                    """,
                    "relationship_endpoint_cardinality_mismatch",
                    "Every relationship must have exactly one endpoint on each side.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_endpoints e
                    LEFT JOIN benchmark_relationships r USING(relationship_id)
                    WHERE r.relationship_id IS NULL
                       OR CASE WHEN e.endpoint_side='a'
                          THEN e.source_reference<>r.source_reference_a
                          ELSE e.source_reference<>r.source_reference_b END
                    """,
                    "endpoint_source_reference_mismatch",
                    "Endpoint references do not reproduce relationship references.",
                ),
                (
                    "SELECT count(*)-count(DISTINCT mapping_id) FROM benchmark_endpoint_mappings",
                    "duplicate_mapping_identity",
                    "Mapping identities are not unique.",
                ),
                (
                    """
                    SELECT count(*) FROM benchmark_endpoint_mappings m
                    LEFT JOIN benchmark_endpoints e USING(endpoint_id)
                    WHERE e.endpoint_id IS NULL
                    """,
                    "mapping_missing_endpoint",
                    "An endpoint mapping references a missing endpoint.",
                ),
            )
            for sql, code, message in endpoint_checks:
                require_zero(connection, sql, code, message)

            _split_database_validation(
                connection,
                config=config,
                metadata=metadata,
                issues=issues,
            )
            _negative_database_validation(
                connection,
                config=config,
                metadata=metadata,
                issues=issues,
            )

            require_zero(
                connection,
                "SELECT count(*)-count(DISTINCT (leakage_group_id,relationship_id)) "
                "FROM benchmark_leakage_groups",
                "duplicate_leakage_membership",
                "Leakage memberships are not unique.",
                artifact="benchmark_leakage_groups",
            )
            require_zero(
                connection,
                """
                SELECT count(*) FROM benchmark_leakage_groups l
                LEFT JOIN benchmark_relationships r USING(relationship_id)
                WHERE r.relationship_id IS NULL
                """,
                "leakage_group_missing_relationship",
                "A leakage membership references a missing relationship.",
                artifact="benchmark_leakage_groups",
            )
            require_zero(
                connection,
                """
                SELECT count(*) FROM (
                  SELECT leakage_group_id FROM benchmark_leakage_groups GROUP BY leakage_group_id
                  HAVING count(DISTINCT group_type)<>1 OR count(DISTINCT group_key)<>1
                     OR count(DISTINCT group_method)<>1
                )
                """,
                "inconsistent_leakage_group_identity",
                "A leakage-group ID has inconsistent type, key, or method values.",
                artifact="benchmark_leakage_groups",
            )
            for group_type in ("exact_directed_pair", "exact_unordered_pair"):
                require_zero(
                    connection,
                    """
                    SELECT count(*) FROM benchmark_relationships r LEFT JOIN (
                      SELECT relationship_id,count(*) AS n FROM benchmark_leakage_groups
                      WHERE group_type=? GROUP BY relationship_id
                    ) l USING(relationship_id)
                    WHERE l.relationship_id IS NULL OR l.n<>1
                    """,
                    "required_pair_leakage_group_missing",
                    f"Every relationship requires one {group_type} leakage membership.",
                    artifact="benchmark_leakage_groups",
                    parameters=(group_type,),
                )
            for split in config.splits:
                enforced = tuple(sorted(set(split.enforced_leakage_groups)))
                if not enforced:
                    continue
                crossing = _configured_leakage_crossing_count(
                    connection,
                    split_name=split.name,
                    group_types=enforced,
                )
                if crossing:
                    _error(
                        issues,
                        "configured_leakage_crosses_partitions",
                        f"Split {split.name} separates {crossing} configured leakage groups.",
                        artifact="benchmark_split_assignments",
                    )

            leakage_counts = _database_group_counts(
                connection, "benchmark_leakage_groups", ("group_type",)
            )
            split_counts = _database_group_counts(
                connection,
                "benchmark_split_assignments",
                ("split_strategy", "partition"),
            )
            negative_counts = _database_group_counts(
                connection, "benchmark_presumed_negatives", ("negative_strategy",)
            )
    except BenchmarkValidationError:
        raise
    except Exception as exc:
        raise BenchmarkValidationError(
            f"could not validate benchmark relational contracts: {exc}"
        ) from exc

    if source.version_or_commit == OPENBIBLE_PRODUCTION_VERSION:
        for key, expected in OPENBIBLE_PRODUCTION_SOURCE_AUDIT.items():
            if source_audit.get(key) != expected:
                _error(
                    issues,
                    "production_source_audit_mismatch",
                    f"Production OpenBible audit field {key} changed: expected {expected}, "
                    f"observed {source_audit.get(key)!r}.",
                    artifact="benchmark_metadata",
                )
    return leakage_counts, split_counts, negative_counts


def validate_benchmark_artifacts(
    *,
    config_path: Path = Path("config/benchmark.yaml"),
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    tier1_path: Path = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: Path = Path("data"),
    output_root: Path = Path("data/processed/benchmarks"),
    database_path: Path = Path("data/processed/project_echoes.duckdb"),
    strict: bool = False,
) -> BenchmarkValidationReport:
    """Validate source, tiers, identities, mappings, splits, negatives, and anchors."""

    loaded = load_config(config_path)
    if not isinstance(loaded, BenchmarkConfig):
        raise BenchmarkValidationError("benchmark configuration loaded with wrong schema")
    config = loaded
    issues: list[BenchmarkValidationIssue] = []
    catalog = load_source_catalog(manifest_path)
    source = catalog.find("openbible-cross-references")
    if source is None:
        raise BenchmarkValidationError("OpenBible source manifest is missing")
    tier1_source = catalog.find("project-echoes-tier1-quotations")
    if tier1_source is None:
        raise BenchmarkValidationError("Tier 1 source manifest is missing")
    _, receipt = verify_acquisition(source, data_root=data_root)
    validate_tier1_quotations(tier1_path, expected_sha256=config.sources.tier1.header_sha256)
    passage = _passage_metadata(database_path)
    if passage.run_id != M5_EXPECTED_RUN_ID or passage.logical_hashes != M5_EXPECTED_LOGICAL_HASHES:
        issues.append(
            BenchmarkValidationIssue(
                severity="error",
                code="passage_anchor_changed",
                message="Milestone 5 passage inputs changed.",
            )
        )
    schema_root = output_root / BENCHMARK_SCHEMA_DIRECTORY
    metadata = _database_metadata(database_path)
    source_audit = _json_dict(metadata["source_audit_json"])
    _manifest_governance_validation(source, tier1_source, config, issues)
    logical, physical, counts = _hash_validation(schema_root, issues)
    leakage_counts, split_counts, negative_counts = _database_relational_validation(
        database_path=database_path,
        config=config,
        source=source,
        source_audit=source_audit,
        metadata=metadata,
        table_counts=counts,
        issues=issues,
    )
    _mapping_database_validation(database_path, issues)
    _metadata_validation(
        table_counts=counts,
        leakage_counts=leakage_counts,
        split_counts=split_counts,
        negative_counts=negative_counts,
        metadata=metadata,
        config=config,
        source=source,
        receipt=receipt,
        passage=passage,
        logical=logical,
        physical=physical,
        issues=issues,
    )
    try:
        with _bounded_validation_connection(database_path) as connection:
            cursor = connection.execute(
                "SELECT severity,code,message,artifact FROM benchmark_issues "
                "ORDER BY severity,code,issue_id"
            )
            while batch := cursor.fetchmany(10_000):
                for severity, code, message, artifact in batch:
                    issues.append(
                        BenchmarkValidationIssue(
                            severity=cast(
                                Literal["error", "warning", "informational"],
                                str(severity),
                            ),
                            code=f"stored_{code}",
                            message=str(message),
                            artifact=str(artifact) if artifact else None,
                        )
                    )
    except Exception as exc:
        raise BenchmarkValidationError(f"could not read stored benchmark issues: {exc}") from exc
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    informational = sum(issue.severity == "informational" for issue in issues)
    passed = errors == 0 and (not strict or warnings == 0)
    return BenchmarkValidationReport(
        benchmark_run_id=str(metadata["benchmark_run_id"]),
        strict=strict,
        table_counts=counts,
        logical_table_hashes=logical,
        physical_table_hashes=physical,
        issues=issues,
        error_count=errors,
        warning_count=warnings,
        informational_count=informational,
        passed=passed,
    )
