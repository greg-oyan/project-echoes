"""End-to-end Milestone 6 benchmark construction without retrieval or scoring."""

from __future__ import annotations

import gc
import hashlib
import json
import platform
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, cast

import duckdb
import polars as pl
from pydantic import BaseModel

from echoes import __version__
from echoes.acquire.sources import AcquisitionReceipt, verify_acquisition
from echoes.benchmarks.identity import (
    EndpointIdentityPayload,
    RelationshipIdentityPayload,
    build_endpoint_identity,
    build_pair_identities,
    build_relationship_identity,
    build_source_record_identity,
)
from echoes.benchmarks.leakage import (
    LeakageEndpoint,
    RelationshipLeakageInput,
    iter_leakage_group_rows,
)
from echoes.benchmarks.mapping import (
    PassageReferenceIndex,
    iter_benchmark_endpoint_mappings,
)
from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_SCHEMAS,
    BenchmarkArtifactName,
    BenchmarkEndpointMappingRow,
    BenchmarkEndpointRow,
    BenchmarkIssueRow,
    BenchmarkLeakageGroupRow,
    BenchmarkMetadataRow,
    BenchmarkRelationshipRow,
    BenchmarkRelationshipSourceRecordRow,
    BenchmarkSeverity,
    BenchmarkSourceRecordRow,
)
from echoes.benchmarks.negatives import (
    CanonicalPassagePair,
    KnownPositivePair,
    NegativePassage,
    Partition,
    PresumedNegativeDefinition,
    generate_presumed_negatives,
    iter_mapped_positive_pairs,
)
from echoes.benchmarks.openbible import audit_openbible_source, parse_openbible_source
from echoes.benchmarks.references import (
    OPENBIBLE_REFERENCE_SCHEME,
    ReferenceParseError,
    ReferenceSpan,
    openbible_reference_corpus,
    parse_openbible_reference,
)
from echoes.benchmarks.splits import SplitRelationship
from echoes.benchmarks.storage import (
    BenchmarkArtifactStager,
    BenchmarkStorageResult,
    load_benchmark_duckdb,
)
from echoes.benchmarks.tier1 import validate_tier1_quotations
from echoes.manifests.sources import SourceManifest, load_source_catalog
from echoes.settings import BenchmarkConfig, load_config

OPENBIBLE_SOURCE_ID = "openbible-cross-references"
MODEL_FRAME_BATCH_SIZE = 50_000
M5_EXPECTED_RUN_ID = "passages-v1-00e261abea9ed44ef087"
M5_EXPECTED_LOGICAL_HASHES = {
    "passage_adjacency": "1ca8c79f92b2742e12586b6c72eaddbcc834d5bce818b909f33b2c10b9db69bd",
    "passage_membership": "726c6b9339a78e7806bac90f7d91930c7f86bec7c7c0be6a51bdedb7a54d40bd",
    "passages": "00047c9dc16ceaefdc0ff1b18a8fb2b4480a1be0534ed861cf5c11706d2048a0",
    "segmentation_exclusions": "6a0e475398e76730b5a7a92370ee319b803c0d17ba45e01b7155fa3b28c7e209",
    "segmentation_issues": "2f3a57eada1dda388ca99bf67cd0b6de70fb31afa1abc1980eafbf605359eac3",
    "segmentation_metadata": "87b88f0b3d4efa88c9d4668ba1eb0aba5fce244b0350130a033deb1a087578cf",
}


class BenchmarkBuildError(RuntimeError):
    """Raised when a governed benchmark build cannot satisfy its input contracts."""


@dataclass(frozen=True, slots=True)
class PassageInputMetadata:
    """Deterministic passage inputs and upstream corpus anchors."""

    run_id: str
    logical_hashes: dict[str, str]
    source_versions: dict[str, str]
    primary_identity_digests: dict[str, str]
    surface_lemma_digests: dict[str, str]
    analytical_digests: dict[str, str]
    oshb_supplement_digests: dict[str, str]


@dataclass(frozen=True, slots=True)
class BenchmarkBuildResult:
    """Completed run identity, storage, and report-ready counts."""

    benchmark_run_id: str
    benchmark_version: str
    source_audit: dict[str, object]
    mapping_status_counts: dict[str, int]
    corpus_pair_counts: dict[str, int]
    leakage_group_counts: dict[str, int]
    split_counts: dict[str, int]
    negative_counts: dict[str, int]
    storage: BenchmarkStorageResult
    database_path: Path
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class DefaultEndpointMapping:
    """Slim default-profile mapping retained after full mapping rows are framed."""

    endpoint_id: str
    mapping_status: str
    target_passage_ids_json: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def benchmark_config_fingerprint(config: BenchmarkConfig) -> str:
    """Hash the complete typed benchmark contract."""

    canonical = _canonical_json(config.model_dump(mode="json"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_object(value: str, *, label: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BenchmarkBuildError(f"invalid {label} JSON in passage metadata") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise BenchmarkBuildError(f"{label} must be a string-to-string JSON object")
    return cast(dict[str, str], parsed)


def _passage_metadata(database_path: Path) -> PassageInputMetadata:
    fields = (
        "segmentation_run_id",
        "table_logical_hashes_json",
        "input_source_versions_json",
        "input_primary_identity_digests_json",
        "input_surface_lemma_digests_json",
        "input_analytical_digests_json",
        "input_oshb_supplement_digests_json",
    )
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            row = connection.execute(
                f"SELECT {','.join(fields)} FROM segmentation_metadata"
            ).fetchone()
    except Exception as exc:
        raise BenchmarkBuildError(f"could not read passage input metadata: {exc}") from exc
    if row is None:
        raise BenchmarkBuildError("passage input metadata is absent")
    observed_logical = _json_object(str(row[1]), label="passage logical hashes")
    expected_content_logical = {
        key: value
        for key, value in M5_EXPECTED_LOGICAL_HASHES.items()
        if key != "segmentation_metadata"
    }
    metadata = PassageInputMetadata(
        run_id=str(row[0]),
        logical_hashes=dict(M5_EXPECTED_LOGICAL_HASHES),
        source_versions=_json_object(str(row[2]), label="source versions"),
        primary_identity_digests=_json_object(str(row[3]), label="identity digests"),
        surface_lemma_digests=_json_object(str(row[4]), label="surface/lemma digests"),
        analytical_digests=_json_object(str(row[5]), label="analytical digests"),
        oshb_supplement_digests=_json_object(str(row[6]), label="OSHB digests"),
    )
    if metadata.run_id != M5_EXPECTED_RUN_ID:
        raise BenchmarkBuildError(
            f"passage run changed: expected {M5_EXPECTED_RUN_ID}, observed {metadata.run_id}"
        )
    if observed_logical != expected_content_logical:
        raise BenchmarkBuildError("Milestone 5 passage logical hashes changed")
    return metadata


def _issue_id(code: str, payload: dict[str, object]) -> str:
    canonical = _canonical_json({"code": code, "payload": payload})
    return f"BI_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _parse_endpoint(reference: str) -> tuple[ReferenceSpan | None, str, str | None]:
    try:
        span = parse_openbible_reference(reference)
    except ReferenceParseError as exc:
        return None, exc.status.value, exc.detail
    return span, span.parse_status.value, None


def _model_frame_batches(
    rows: Iterable[BaseModel], name: BenchmarkArtifactName
) -> Iterator[pl.DataFrame]:
    """Yield bounded typed columnar batches without a final concatenation."""

    schema = BENCHMARK_ARTIFACT_SCHEMAS[name]
    iterator = iter(rows)
    while batch := list(islice(iterator, MODEL_FRAME_BATCH_SIZE)):
        data = {column: [getattr(row, column) for row in batch] for column in schema.names()}
        yield pl.DataFrame(data, schema=schema)


def _model_frame(rows: Iterable[BaseModel], name: BenchmarkArtifactName) -> pl.DataFrame:
    """Materialize fixture-sized rows; production uses bounded frame batches."""

    schema = BENCHMARK_ARTIFACT_SCHEMAS[name]
    chunks = list(_model_frame_batches(rows, name))
    if not chunks:
        return pl.DataFrame(schema=schema)
    if len(chunks) == 1:
        return chunks[0]
    return pl.concat(chunks, how="vertical", rechunk=False)


def _observed_mapping_rows(
    endpoints: Iterable[BenchmarkEndpointRow],
    index: PassageReferenceIndex,
    status_counts: Counter[str],
    default_mappings: dict[str, DefaultEndpointMapping],
) -> Iterator[BenchmarkEndpointMappingRow]:
    """Stream mappings while retaining only compact production summaries."""

    for item in iter_benchmark_endpoint_mappings(endpoints, index):
        status_counts[item.mapping_status] += 1
        if item.target_analysis_profile == "edition_complete":
            default_mappings[item.endpoint_id] = DefaultEndpointMapping(
                endpoint_id=item.endpoint_id,
                mapping_status=item.mapping_status,
                target_passage_ids_json=item.target_passage_ids_json,
            )
        yield item


def _observed_leakage_rows(
    rows: Iterable[BenchmarkLeakageGroupRow],
    status_counts: Counter[str],
) -> Iterator[BenchmarkLeakageGroupRow]:
    """Count leakage memberships as bounded production rows are consumed."""

    for item in rows:
        status_counts[item.group_type] += 1
        yield item


def _source_and_receipt(
    manifest_path: Path, data_root: Path
) -> tuple[SourceManifest, Path, AcquisitionReceipt]:
    source = load_source_catalog(manifest_path).find(OPENBIBLE_SOURCE_ID)
    if source is None:
        raise BenchmarkBuildError("OpenBible source manifest record is missing")
    try:
        directory, receipt = verify_acquisition(source, data_root=data_root)
    except Exception as exc:
        raise BenchmarkBuildError(f"OpenBible acquisition verification failed: {exc}") from exc
    return source, directory, receipt


def _records_relationships_endpoints(
    source: SourceManifest,
    receipt: AcquisitionReceipt,
    source_path: Path,
) -> tuple[
    list[BenchmarkSourceRecordRow],
    list[BenchmarkRelationshipRow],
    list[BenchmarkRelationshipSourceRecordRow],
    list[BenchmarkEndpointRow],
    list[BenchmarkIssueRow],
    dict[str, tuple[ReferenceSpan | None, ReferenceSpan | None]],
    dict[str, tuple[str, ...]],
    dict[str, object],
]:
    parsed = parse_openbible_source(source_path)
    audit = audit_openbible_source(parsed)
    if receipt.canonical_record_stream_sha256 != parsed.canonical_stream_sha256:
        raise BenchmarkBuildError("parsed OpenBible stream hash differs from acquisition receipt")
    if source.acquisition is None or source.acquisition.archive_sha256 is None:
        raise BenchmarkBuildError("OpenBible manifest has no authoritative archive hash")

    source_records: list[BenchmarkSourceRecordRow] = []
    record_ids_by_line: dict[int, str] = {}
    occurrence_counts: Counter[str] = Counter()
    for record in parsed.records:
        occurrence_counts[record.raw_record_sha256] += 1
        identity = build_source_record_identity(
            source_id=source.source_id,
            source_archive_sha256=source.acquisition.archive_sha256,
            raw_record_bytes=record.raw_record_bytes,
            duplicate_occurrence_ordinal=occurrence_counts[record.raw_record_sha256],
        )
        record_ids_by_line[record.source_line_number] = identity.identifier
        source_records.append(
            BenchmarkSourceRecordRow(
                source_record_id=identity.identifier,
                source_id=source.source_id,
                source_version=source.version_or_commit or "",
                source_archive_sha256=source.acquisition.archive_sha256,
                source_file=source_path.name,
                source_line_number=record.source_line_number,
                raw_record_sha256=record.raw_record_sha256,
                source_reference_a=record.source_reference_a,
                source_reference_b=record.source_reference_b,
                source_weight=record.source_weight,
                source_direction=record.source_direction,
                parse_status=record.parse_status,
                notes=record.notes,
            )
        )

    grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    endpoint_spans_by_key: dict[tuple[str, str], tuple[ReferenceSpan | None, str, str | None]] = {}
    issues: list[BenchmarkIssueRow] = []
    for record in parsed.records:
        if record.parse_status != "parsed":
            issues.append(
                BenchmarkIssueRow(
                    issue_id=_issue_id("source_parse_error", {"line": record.source_line_number}),
                    benchmark_run_id=None,
                    severity=BenchmarkSeverity.ERROR,
                    code="source_parse_error",
                    message=record.notes or record.parse_status,
                    artifact="benchmark_source_records",
                    source_record_id=record_ids_by_line[record.source_line_number],
                    relationship_id=None,
                    endpoint_id=None,
                    details_json=_canonical_json({"parse_status": record.parse_status}),
                )
            )
            continue
        span_a, status_a, detail_a = _parse_endpoint(record.source_reference_a)
        span_b, status_b, detail_b = _parse_endpoint(record.source_reference_b)
        normalized_a = span_a.normalized_source_reference if span_a else record.source_reference_a
        normalized_b = span_b.normalized_source_reference if span_b else record.source_reference_b
        endpoint_spans_by_key[("a", normalized_a)] = (span_a, status_a, detail_a)
        endpoint_spans_by_key[("b", normalized_b)] = (span_b, status_b, detail_b)
        if normalized_a == normalized_b:
            issues.append(
                BenchmarkIssueRow(
                    issue_id=_issue_id("self_link_excluded", {"line": record.source_line_number}),
                    benchmark_run_id=None,
                    severity=BenchmarkSeverity.INFORMATIONAL,
                    code="self_link_excluded",
                    message="Self-link source record retained but excluded from relationships.",
                    artifact="benchmark_relationships",
                    source_record_id=record_ids_by_line[record.source_line_number],
                    relationship_id=None,
                    endpoint_id=None,
                    details_json=_canonical_json({"source_reference": record.source_reference_a}),
                )
            )
            continue
        grouped[(normalized_a, normalized_b, record.source_direction)].append(record)

    relationships: list[BenchmarkRelationshipRow] = []
    links: list[BenchmarkRelationshipSourceRecordRow] = []
    endpoints: list[BenchmarkEndpointRow] = []
    spans_by_relationship: dict[str, tuple[ReferenceSpan | None, ReferenceSpan | None]] = {}
    source_record_keys: dict[str, tuple[str, ...]] = {}
    for (normalized_a, normalized_b, direction), records in sorted(grouped.items()):
        relationship_identity = build_relationship_identity(
            RelationshipIdentityPayload(
                source_id=source.source_id,
                source_version=source.version_or_commit or "",
                source_reference_scheme=OPENBIBLE_REFERENCE_SCHEME,
                normalized_source_endpoint_a=normalized_a,
                normalized_source_endpoint_b=normalized_b,
                source_direction=direction,
            )
        )
        directed, unordered = build_pair_identities(
            source_reference_scheme=OPENBIBLE_REFERENCE_SCHEME,
            normalized_endpoint_a=normalized_a,
            normalized_endpoint_b=normalized_b,
        )
        span_a, status_a, detail_a = endpoint_spans_by_key[("a", normalized_a)]
        span_b, status_b, detail_b = endpoint_spans_by_key[("b", normalized_b)]
        quality = "valid" if span_a is not None and span_b is not None else "mapping_limited"
        weights = [record.source_weight for record in records if record.source_weight is not None]
        record_ids = tuple(record_ids_by_line[record.source_line_number] for record in records)
        source_record_keys[relationship_identity.identifier] = tuple(
            record.raw_record_sha256 for record in records
        )
        relationships.append(
            BenchmarkRelationshipRow(
                relationship_id=relationship_identity.identifier,
                tier=3,
                source_id=source.source_id,
                source_version=source.version_or_commit or "",
                source_reference_scheme=OPENBIBLE_REFERENCE_SCHEME,
                source_reference_a=normalized_a,
                source_reference_b=normalized_b,
                relationship_direction=direction,
                relationship_class="broad_unspecified_cross_reference",
                source_record_count=len(records),
                source_weight_sum=sum(weights),
                source_weight_max=max(weights) if weights else None,
                canonical_directed_pair_id=directed.identifier,
                canonical_undirected_pair_id=unordered.identifier,
                weak_supervision_eligible=True,
                knownness_filter_eligible=True,
                primary_evaluation_eligible=False,
                tier1_eligible=False,
                data_quality_status=quality,
                license_status="cc_by_4_0_verified",
                provenance_json=_canonical_json(
                    {
                        "source_archive_sha256": source.acquisition.archive_sha256,
                        "source_record_ids": record_ids,
                        "votes_role": "source_ranking_not_confidence",
                    }
                ),
                notes="Tier 3 weak supervision and knownness support only.",
            )
        )
        links.extend(
            BenchmarkRelationshipSourceRecordRow(
                relationship_id=relationship_identity.identifier,
                source_record_id=record_id,
                link_role="supporting_source_record",
            )
            for record_id in record_ids
        )
        rendered_spans: list[ReferenceSpan | None] = []
        for side, reference, span, status, detail in (
            ("a", normalized_a, span_a, status_a, detail_a),
            ("b", normalized_b, span_b, status_b, detail_b),
        ):
            endpoint_identity = build_endpoint_identity(
                EndpointIdentityPayload(
                    relationship_id=relationship_identity.identifier,
                    endpoint_side=cast(Any, side),
                    normalized_source_reference=reference,
                )
            )
            endpoint = BenchmarkEndpointRow(
                endpoint_id=endpoint_identity.identifier,
                relationship_id=relationship_identity.identifier,
                endpoint_side=cast(Any, side),
                source_reference=reference,
                source_reference_scheme=OPENBIBLE_REFERENCE_SCHEME,
                parsed_book=span.start.canonical_book if span else None,
                parsed_start_chapter=span.start.chapter if span else None,
                parsed_start_verse=span.start.verse if span else None,
                parsed_end_chapter=span.end.chapter if span else None,
                parsed_end_verse=span.end.verse if span else None,
                is_range=span.is_range if span else "-" in reference,
                parse_status=status,
            )
            endpoints.append(endpoint)
            rendered_spans.append(span)
            if span is None:
                issues.append(
                    BenchmarkIssueRow(
                        issue_id=_issue_id(
                            "endpoint_reference_unmapped",
                            {"endpoint_id": endpoint.endpoint_id, "status": status},
                        ),
                        benchmark_run_id=None,
                        severity=BenchmarkSeverity.INFORMATIONAL,
                        code="endpoint_reference_unmapped",
                        message=detail or status,
                        artifact="benchmark_endpoints",
                        source_record_id=None,
                        relationship_id=relationship_identity.identifier,
                        endpoint_id=endpoint.endpoint_id,
                        details_json=_canonical_json(
                            {"parse_status": status, "source_reference": reference}
                        ),
                    )
                )
        spans_by_relationship[relationship_identity.identifier] = (
            rendered_spans[0],
            rendered_spans[1],
        )
    return (
        source_records,
        relationships,
        links,
        endpoints,
        issues,
        spans_by_relationship,
        source_record_keys,
        audit,
    )


def _leakage_inputs(
    relationships: list[BenchmarkRelationshipRow],
    endpoints: list[BenchmarkEndpointRow],
    default_mappings: dict[str, DefaultEndpointMapping],
    spans_by_relationship: dict[str, tuple[ReferenceSpan | None, ReferenceSpan | None]],
    source_record_keys: dict[str, tuple[str, ...]],
    index: PassageReferenceIndex,
) -> list[RelationshipLeakageInput]:
    endpoints_by_relationship: dict[str, list[BenchmarkEndpointRow]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_relationship[endpoint.relationship_id].append(endpoint)
    # Target overlap operates on the order of actual extant verse passages,
    # not on packed chapter/verse numbers.  The latter would make omitted
    # labels look like materialized target positions and could create false
    # overlap groups across an edition gap.
    target_coordinates = {
        target.passage_id: (target.book, ordinal)
        for stream, targets in index.by_stream.items()
        if stream[1] == "edition_complete"
        for ordinal, target in enumerate(targets, start=1)
    }
    result: list[RelationshipLeakageInput] = []

    for relationship in relationships:
        relationship_endpoints = sorted(
            endpoints_by_relationship[relationship.relationship_id],
            key=lambda item: item.endpoint_side,
        )
        spans = spans_by_relationship[relationship.relationship_id]
        if len(relationship_endpoints) != 2:
            raise BenchmarkBuildError(
                f"relationship {relationship.relationship_id} does not have two endpoints"
            )
        rendered: list[LeakageEndpoint] = []
        for endpoint, span in zip(relationship_endpoints, spans, strict=True):
            mapping = default_mappings[endpoint.endpoint_id]
            target_ids = tuple(json.loads(mapping.target_passage_ids_json))
            try:
                mapped_coordinates = [target_coordinates[value] for value in target_ids]
            except KeyError as exc:
                raise BenchmarkBuildError(
                    f"mapping for {endpoint.endpoint_id} targets an unknown passage: {exc}"
                ) from exc
            mapped_books = {book for book, _ordinal in mapped_coordinates}
            target_book = next(iter(mapped_books)) if len(mapped_books) == 1 else None
            target_ordinals = [ordinal for _book, ordinal in mapped_coordinates]
            if span is None:
                unresolved_ordinal = (
                    int.from_bytes(
                        hashlib.sha256(endpoint.source_reference.encode()).digest()[:8],
                        "big",
                    )
                    + 1
                )
                rendered.append(
                    LeakageEndpoint(
                        endpoint_key=endpoint.source_reference,
                        source_book="UNRESOLVED",
                        source_start_ordinal=unresolved_ordinal,
                        source_end_ordinal=unresolved_ordinal,
                    )
                )
                continue
            rendered.append(
                LeakageEndpoint(
                    endpoint_key=span.normalized_source_reference,
                    source_book=span.start.canonical_book,
                    source_start_ordinal=span.start.chapter * 1000 + span.start.verse,
                    source_end_ordinal=span.end.chapter * 1000 + span.end.verse,
                    target_passage_ids=target_ids,
                    target_book=target_book,
                    target_start_ordinal=min(target_ordinals) if target_ordinals else None,
                    target_end_ordinal=max(target_ordinals) if target_ordinals else None,
                )
            )
        duplicates = source_record_keys[relationship.relationship_id]
        result.append(
            RelationshipLeakageInput(
                relationship_id=relationship.relationship_id,
                canonical_directed_pair_id=relationship.canonical_directed_pair_id,
                canonical_undirected_pair_id=relationship.canonical_undirected_pair_id,
                endpoints=(rendered[0], rendered[1]),
                duplicate_source_record_keys=(duplicates if len(duplicates) > 1 else ()),
                source_provenance_keys=(),
                relationship_family_key=None,
            )
        )
    return result


def _hash_partition(seed: int, value: str, proportions: Any) -> str:
    number = int.from_bytes(hashlib.sha256(f"{seed}|{value}".encode()).digest()[:8], "big")
    fraction = number / (2**64)
    if fraction < proportions.test:
        return "test"
    if fraction < proportions.test + proportions.development:
        return "development"
    return "train"


def _split_inputs(
    relationships: list[BenchmarkRelationshipRow],
    endpoints: list[BenchmarkEndpointRow],
    default_mappings: dict[str, DefaultEndpointMapping],
    config: BenchmarkConfig,
) -> list[SplitRelationship]:
    endpoints_by_relationship: dict[str, list[BenchmarkEndpointRow]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_relationship[endpoint.relationship_id].append(endpoint)
    result: list[SplitRelationship] = []
    for relationship in relationships:
        values = sorted(
            endpoints_by_relationship[relationship.relationship_id],
            key=lambda item: item.endpoint_side,
        )
        if len(values) != 2:
            raise BenchmarkBuildError(
                f"relationship {relationship.relationship_id} does not have two endpoints"
            )
        mappings = [default_mappings[item.endpoint_id] for item in values]
        mapping_eligible = all(
            item.mapping_status in config.mapping.weak_supervision_statuses for item in mappings
        )
        books = cast(
            tuple[str, str],
            tuple(item.parsed_book or "UNRESOLVED" for item in values),
        )
        result.append(
            SplitRelationship(
                relationship_id=relationship.relationship_id,
                tier=relationship.tier,
                mapping_eligible=mapping_eligible,
                endpoint_books=books,
                endpoint_keys=(values[0].source_reference, values[1].source_reference),
                broad_genres=(
                    config.book_genres.get(books[0], "unresolved"),
                    config.book_genres.get(books[1], "unresolved"),
                ),
                relationship_family_key=None,
            )
        )
    return result


def _split_values(strategy: str, relationships: list[SplitRelationship]) -> set[str]:
    if strategy == "held_out_book":
        return {value for item in relationships for value in item.endpoint_books}
    if strategy == "held_out_book_pair":
        return {item.canonical_book_pair for item in relationships}
    if strategy == "held_out_source_passage":
        return {value for item in relationships for value in item.endpoint_keys}
    if strategy == "held_out_genre":
        return {value for item in relationships for value in item.broad_genres}
    return {"unsupported_relationship_family"}


def _split_assignment_id(
    *, benchmark_version: str, config_hash: str, relationship_id: str, strategy: str
) -> str:
    payload = _canonical_json(
        {
            "benchmark_version": benchmark_version,
            "config_hash": config_hash,
            "relationship_id": relationship_id,
            "split_strategy": strategy,
        }
    )
    return f"BSA_{hashlib.sha256(payload.encode()).hexdigest()}"


def _exact_pair_group_id(group_key: str) -> str:
    payload = _canonical_json(
        {
            "group_key": group_key,
            "group_method": "canonical_unordered_pair_identity",
            "group_type": "exact_unordered_pair",
        }
    )
    return f"BLG_{hashlib.sha256(payload.encode()).hexdigest()}"


def _priority_partition(values: Iterable[str]) -> Partition:
    value_set = set(values)
    if "test" in value_set:
        return "test"
    if "development" in value_set:
        return "development"
    return "train"


def _iter_split_frames(
    inputs: list[SplitRelationship],
    unordered_pairs: dict[str, str],
    config: BenchmarkConfig,
    benchmark_version: str,
    config_hash: str,
    leakage_path: Path,
    split_counts: Counter[str],
    heldout_book_partitions: dict[str, Partition],
) -> Iterator[pl.DataFrame]:
    """Yield one leakage-enforced strategy frame at a time."""

    schema = BENCHMARK_ARTIFACT_SCHEMAS["benchmark_split_assignments"]
    for configured in config.splits:
        chunks: list[pl.DataFrame] = []
        columns: dict[str, list[object]] = {name: [] for name in schema.names()}
        for relationship in inputs:
            reason: str | None = None
            if relationship.tier not in configured.included_tiers:
                reason = "tier_not_included"
            elif configured.mapping_required and not relationship.mapping_eligible:
                reason = "mapping_ineligible"
            elif configured.strategy == "held_out_relationship_family":
                reason = "relationship_family_unavailable"
            if reason is not None:
                partition: str = "excluded"
            else:
                if configured.strategy == "held_out_book":
                    partition = _priority_partition(
                        _hash_partition(configured.seed, value, configured.proportions)
                        for value in relationship.endpoint_books
                    )
                elif configured.strategy == "held_out_book_pair":
                    partition = _hash_partition(
                        configured.seed,
                        relationship.canonical_book_pair,
                        configured.proportions,
                    )
                elif configured.strategy == "held_out_source_passage":
                    if any("-" in value for value in relationship.endpoint_keys):
                        partition = "excluded"
                        reason = "range_overlap_guard"
                    else:
                        endpoint_partitions = {
                            _hash_partition(configured.seed, value, configured.proportions)
                            for value in relationship.endpoint_keys
                        }
                        if len(endpoint_partitions) != 1:
                            partition = "excluded"
                            reason = "endpoint_partition_conflict"
                        else:
                            partition = endpoint_partitions.pop()
                elif configured.strategy == "held_out_genre":
                    partition = _priority_partition(
                        _hash_partition(configured.seed, value, configured.proportions)
                        for value in relationship.broad_genres
                    )
                else:
                    partition = "excluded"
                    reason = "unsupported_split_strategy"
            values = {
                "split_assignment_id": _split_assignment_id(
                    benchmark_version=benchmark_version,
                    config_hash=config_hash,
                    relationship_id=relationship.relationship_id,
                    strategy=configured.name,
                ),
                "benchmark_version": benchmark_version,
                "relationship_id": relationship.relationship_id,
                "split_strategy": configured.name,
                "partition": partition,
                "leakage_group_id": _exact_pair_group_id(
                    unordered_pairs[relationship.relationship_id]
                ),
                "seed": configured.seed,
                "eligibility_status": "excluded" if reason else "eligible",
                "exclusion_reason": reason,
                "config_hash": config_hash,
            }
            for name in columns:
                columns[name].append(values[name])
            if len(columns["relationship_id"]) == MODEL_FRAME_BATCH_SIZE:
                chunks.append(pl.DataFrame(columns, schema=schema))
                columns = {name: [] for name in schema.names()}
        if columns["relationship_id"]:
            chunks.append(pl.DataFrame(columns, schema=schema))
        strategy_frame = (
            pl.concat(chunks, how="vertical", rechunk=False) if len(chunks) > 1 else chunks[0]
        )
        enforced = _exclude_split_leakage_conflicts(
            strategy_frame,
            leakage_path=leakage_path,
            enforced_group_types=frozenset(configured.enforced_leakage_groups),
        )
        for partition, count in enforced.group_by("partition").len().sort("partition").iter_rows():
            split_counts[f"{configured.name}|{partition}"] += count
        if configured.strategy == "held_out_book":
            heldout_book_partitions.update(
                {
                    relationship_id: cast(Partition, partition)
                    for relationship_id, partition in enforced.filter(
                        pl.col("partition") != "excluded"
                    )
                    .select("relationship_id", "partition")
                    .iter_rows()
                }
            )
        yield enforced


def _generate_splits(
    inputs: list[SplitRelationship],
    unordered_pairs: dict[str, str],
    config: BenchmarkConfig,
    benchmark_version: str,
    config_hash: str,
    leakage_path: Path,
) -> tuple[pl.DataFrame, dict[str, Partition]]:
    """Materialize fixture-sized split output; production stages strategy frames."""

    split_counts: Counter[str] = Counter()
    heldout_book_partitions: dict[str, Partition] = {}
    frames = list(
        _iter_split_frames(
            inputs,
            unordered_pairs,
            config,
            benchmark_version,
            config_hash,
            leakage_path,
            split_counts,
            heldout_book_partitions,
        )
    )
    result = pl.concat(frames, how="vertical", rechunk=False)
    return result, heldout_book_partitions


def _exclude_split_leakage_conflicts(
    assignments: pl.DataFrame,
    *,
    leakage_path: Path,
    enforced_group_types: frozenset[str],
) -> pl.DataFrame:
    """Exclude eligible rows from any configured group crossing partitions.

    Conflict exclusion is deterministic and deliberately non-transitive: it
    enforces every explicit leakage view without replacing those views with a
    single unrestricted graph component that hub references could collapse.
    """

    schema = BENCHMARK_ARTIFACT_SCHEMAS["benchmark_split_assignments"]
    memberships = (
        pl.scan_parquet(leakage_path)
        .filter(pl.col("group_type").is_in(sorted(enforced_group_types)))
        .select("leakage_group_id", "relationship_id", "group_type")
    )
    eligible_assignments = (
        assignments.lazy()
        .filter(pl.col("partition") != "excluded")
        .select("relationship_id", "partition")
    )
    joined = memberships.join(eligible_assignments, on="relationship_id", how="inner")
    conflicting_groups = (
        joined.group_by("leakage_group_id", "group_type")
        .agg(pl.col("partition").n_unique().alias("partition_count"))
        .filter(pl.col("partition_count") > 1)
        .select("leakage_group_id", "group_type")
    )
    conflicts = (
        joined.join(
            conflicting_groups,
            on=["leakage_group_id", "group_type"],
            how="inner",
        )
        .sort("relationship_id", "group_type", "leakage_group_id")
        .group_by("relationship_id", maintain_order=True)
        .agg(
            pl.col("leakage_group_id").first().alias("conflict_group_id"),
            pl.col("group_type").first().alias("conflict_group_type"),
        )
        .collect(engine="streaming")
    )
    if conflicts.is_empty():
        return assignments
    return (
        assignments.join(conflicts, on="relationship_id", how="left")
        .with_columns(
            pl.when(pl.col("conflict_group_id").is_not_null())
            .then(pl.lit("excluded"))
            .otherwise(pl.col("partition"))
            .alias("partition"),
            pl.when(pl.col("conflict_group_id").is_not_null())
            .then(pl.col("conflict_group_id"))
            .otherwise(pl.col("leakage_group_id"))
            .alias("leakage_group_id"),
            pl.when(pl.col("conflict_group_id").is_not_null())
            .then(pl.lit("excluded"))
            .otherwise(pl.col("eligibility_status"))
            .alias("eligibility_status"),
            pl.when(pl.col("conflict_group_id").is_not_null())
            .then(
                pl.concat_str(
                    pl.lit("leakage_group_partition_conflict:"),
                    pl.col("conflict_group_type"),
                )
            )
            .otherwise(pl.col("exclusion_reason"))
            .alias("exclusion_reason"),
        )
        .drop("conflict_group_id", "conflict_group_type")
        .cast(schema)
    )


def _passage_partition(book: str, config: BenchmarkConfig) -> Partition:
    split = next(item for item in config.splits if item.strategy == "held_out_book")
    return cast(Partition, _hash_partition(split.seed, book, split.proportions))


def _generate_negatives(
    index: PassageReferenceIndex,
    relationships: list[BenchmarkRelationshipRow],
    endpoints: list[BenchmarkEndpointRow],
    default_mappings: dict[str, DefaultEndpointMapping],
    heldout_book_partitions: dict[str, Partition],
    config: BenchmarkConfig,
    benchmark_version: str,
    config_hash: str,
) -> list[Any]:
    passage_identity = {
        target.passage_id: target.passage_id
        for stream, targets in index.by_stream.items()
        if stream[1] == "edition_complete"
        for target in targets
    }
    passage_books = {
        target.passage_id: target.book
        for stream, targets in index.by_stream.items()
        if stream[1] == "edition_complete"
        for target in targets
    }
    endpoints_by_relationship: dict[str, list[BenchmarkEndpointRow]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_relationship[endpoint.relationship_id].append(endpoint)
    positives: list[KnownPositivePair] = []
    positive_graph_pairs: set[CanonicalPassagePair] = set()
    for relationship in relationships:
        relationship_endpoints = sorted(
            endpoints_by_relationship[relationship.relationship_id],
            key=lambda item: item.endpoint_side,
        )
        if len(relationship_endpoints) != 2:
            raise BenchmarkBuildError(
                f"relationship {relationship.relationship_id} does not have two endpoints"
            )
        mappings = [default_mappings[item.endpoint_id] for item in relationship_endpoints]
        try:
            passage_lists = [
                [passage_identity[value] for value in json.loads(item.target_passage_ids_json)]
                for item in mappings
            ]
        except KeyError as exc:
            raise BenchmarkBuildError(
                f"relationship {relationship.relationship_id} maps to an unknown passage"
            ) from exc
        positive_graph_pairs.update(iter_mapped_positive_pairs(passage_lists[0], passage_lists[1]))

        partition = heldout_book_partitions.get(relationship.relationship_id)
        if partition is None:
            continue
        if len(passage_lists) != 2 or any(len(values) != 1 for values in passage_lists):
            continue
        if passage_lists[0][0] == passage_lists[1][0]:
            continue
        first_partition = _passage_partition(passage_books[passage_lists[0][0]], config)
        second_partition = _passage_partition(passage_books[passage_lists[1][0]], config)
        if first_partition != second_partition or first_partition != partition:
            continue
        positives.append(
            KnownPositivePair(
                relationship_id=relationship.relationship_id,
                passage_a_id=passage_lists[0][0],
                passage_b_id=passage_lists[1][0],
            )
        )

    passages: list[NegativePassage] = []
    for stream, targets in sorted(index.by_stream.items()):
        corpus, profile, _reading, book = stream
        if profile != "edition_complete":
            continue
        partition = _passage_partition(book, config)
        for ordinal, target in enumerate(targets, start=1):
            passages.append(
                NegativePassage(
                    passage_id=target.passage_id,
                    corpus=corpus,
                    book=book,
                    broad_genre=config.book_genres[book],
                    token_count=target.token_count,
                    ordinal_in_book=ordinal,
                    partition=partition,
                )
            )
    rows: list[Any] = []
    for item in config.presumed_negatives:
        if not item.enabled or item.ratio_per_eligible_positive == 0:
            continue
        definition = PresumedNegativeDefinition(
            benchmark_version=benchmark_version,
            strategy=item.strategy,
            split_strategy="held_out_book",
            generation_config_hash=config_hash,
            seed=item.seed,
            ratio=item.ratio_per_eligible_positive,
            length_tolerance=item.length_tolerance_tokens,
            nearby_distance=5,
            max_candidate_attempts=128,
        )
        rows.extend(
            generate_presumed_negatives(
                passages,
                positives,
                definition,
                positive_graph_pairs=positive_graph_pairs,
            )
        )
    return rows


def _corpus_pair_counts(
    relationships: list[BenchmarkRelationshipRow],
    endpoints: list[BenchmarkEndpointRow],
) -> dict[str, int]:
    endpoints_by_relationship: dict[str, list[BenchmarkEndpointRow]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_relationship[endpoint.relationship_id].append(endpoint)
    counts: Counter[str] = Counter()
    for relationship in relationships:
        values = endpoints_by_relationship[relationship.relationship_id]
        corpora = [openbible_reference_corpus(item.source_reference) for item in values]
        if len(corpora) != 2 or any(corpus is None for corpus in corpora):
            counts["unresolved"] += 1
        elif all(corpus == "hebrew" for corpus in corpora):
            counts["old_testament_to_old_testament"] += 1
        elif all(corpus == "greek" for corpus in corpora):
            counts["new_testament_to_new_testament"] += 1
        else:
            counts["cross_testament"] += 1
    return dict(sorted(counts.items()))


def build_benchmark(
    *,
    config_path: Path = Path("config/benchmark.yaml"),
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    tier1_path: Path = Path("data/benchmarks/tier1_quotations.csv"),
    data_root: Path = Path("data"),
    output_root: Path = Path("data/processed/benchmarks"),
    database_path: Path = Path("data/processed/project_echoes.duckdb"),
    force: bool = False,
) -> BenchmarkBuildResult:
    """Build all ten artifacts from fixed local inputs and load DuckDB."""

    started = time.perf_counter()
    loaded = load_config(config_path)
    if not isinstance(loaded, BenchmarkConfig):
        raise BenchmarkBuildError(f"{config_path} is not a benchmark configuration")
    config = loaded
    config_hash = benchmark_config_fingerprint(config)
    source, acquisition_directory, receipt = _source_and_receipt(manifest_path, data_root)
    source_path = acquisition_directory / config.sources.openbible.source_file
    tier1 = validate_tier1_quotations(
        tier1_path, expected_sha256=config.sources.tier1.header_sha256
    )
    passage_metadata = _passage_metadata(database_path)
    identity_payload = {
        "benchmark_schema_version": config.benchmark_schema_version,
        "canonical_source_record_stream_sha256": receipt.canonical_record_stream_sha256,
        "configuration_hash": config_hash,
        "openbible_archive_sha256": config.sources.openbible.snapshot_sha256,
        "passage_input_run_id": passage_metadata.run_id,
        "passage_logical_hashes": passage_metadata.logical_hashes,
        "tier1_header_sha256": tier1.sha256,
    }
    identity_hash = hashlib.sha256(_canonical_json(identity_payload).encode()).hexdigest()
    benchmark_run_id = f"benchmark-v1-{identity_hash[:20]}"
    benchmark_version = f"known-links-v1-{identity_hash[:12]}"
    with BenchmarkArtifactStager(output_root, force=force) as stager:
        index = PassageReferenceIndex.from_duckdb(database_path)
        (
            source_records,
            relationships,
            links,
            endpoints,
            issues,
            spans_by_relationship,
            source_record_keys,
            source_audit,
        ) = _records_relationships_endpoints(source, receipt, source_path)

        source_frame = _model_frame(source_records, "benchmark_source_records")
        del source_records
        gc.collect()
        stager.write_content("benchmark_source_records", source_frame)
        del source_frame
        gc.collect()

        link_frame = _model_frame(links, "benchmark_relationship_source_records")
        del links
        gc.collect()
        stager.write_content("benchmark_relationship_source_records", link_frame)
        del link_frame
        gc.collect()

        mapping_status_counter: Counter[str] = Counter()
        default_mappings: dict[str, DefaultEndpointMapping] = {}
        mapping_batches = _model_frame_batches(
            _observed_mapping_rows(
                endpoints,
                index,
                mapping_status_counter,
                default_mappings,
            ),
            "benchmark_endpoint_mappings",
        )
        stager.write_content_batches("benchmark_endpoint_mappings", mapping_batches)
        del mapping_batches
        gc.collect()
        mapping_count = sum(mapping_status_counter.values())
        if len(default_mappings) != len(endpoints):
            raise BenchmarkBuildError(
                "default-profile mapping count does not reconcile to endpoint count"
            )
        mapping_counts: dict[str, int] = dict(sorted(mapping_status_counter.items()))

        leakage_inputs = _leakage_inputs(
            relationships,
            endpoints,
            default_mappings,
            spans_by_relationship,
            source_record_keys,
            index,
        )
        leakage_count_counter: Counter[str] = Counter()
        raw_leakage_rows = iter_leakage_group_rows(leakage_inputs)
        observed_leakage_rows = _observed_leakage_rows(raw_leakage_rows, leakage_count_counter)
        leakage_batches = _model_frame_batches(
            observed_leakage_rows,
            "benchmark_leakage_groups",
        )
        del (
            leakage_inputs,
            spans_by_relationship,
            source_record_keys,
            raw_leakage_rows,
            observed_leakage_rows,
        )
        gc.collect()
        leakage_path = stager.write_content_batches("benchmark_leakage_groups", leakage_batches)
        del leakage_batches
        gc.collect()
        leakage_counts = dict(sorted(leakage_count_counter.items()))

        split_inputs = _split_inputs(relationships, endpoints, default_mappings, config)
        unordered_pairs = {
            item.relationship_id: item.canonical_undirected_pair_id for item in relationships
        }
        split_count_counter: Counter[str] = Counter()
        heldout_book_partitions: dict[str, Partition] = {}
        split_frames = _iter_split_frames(
            split_inputs,
            unordered_pairs,
            config,
            benchmark_version,
            config_hash,
            leakage_path,
            split_count_counter,
            heldout_book_partitions,
        )
        del split_inputs, unordered_pairs
        gc.collect()
        stager.write_content_batches("benchmark_split_assignments", split_frames)
        del split_frames
        gc.collect()
        split_counts = dict(sorted(split_count_counter.items()))

        negatives = _generate_negatives(
            index,
            relationships,
            endpoints,
            default_mappings,
            heldout_book_partitions,
            config,
            benchmark_version,
            config_hash,
        )
        negative_counts = dict(
            sorted(Counter(item.negative_strategy for item in negatives).items())
        )
        negative_frame = _model_frame(negatives, "benchmark_presumed_negatives")
        del negatives, heldout_book_partitions, index, default_mappings
        gc.collect()
        stager.write_content("benchmark_presumed_negatives", negative_frame)
        del negative_frame
        gc.collect()

        corpus_counts = _corpus_pair_counts(relationships, endpoints)
        relationship_count = len(relationships)
        endpoint_count = len(endpoints)
        relationship_frame = _model_frame(relationships, "benchmark_relationships")
        del relationships
        gc.collect()
        stager.write_content("benchmark_relationships", relationship_frame)
        del relationship_frame
        gc.collect()

        endpoint_frame = _model_frame(endpoints, "benchmark_endpoints")
        del endpoints
        gc.collect()
        stager.write_content("benchmark_endpoints", endpoint_frame)
        del endpoint_frame
        gc.collect()

        issue_frame = _model_frame(issues, "benchmark_issues")
        del issues
        gc.collect()
        stager.write_content("benchmark_issues", issue_frame)
        del issue_frame
        gc.collect()

        elapsed = time.perf_counter() - started
        metadata = BenchmarkMetadataRow(
            benchmark_run_id=benchmark_run_id,
            benchmark_version=benchmark_version,
            source_versions_json=_canonical_json({source.source_id: source.version_or_commit}),
            source_archive_hashes_json=_canonical_json(
                {source.source_id: config.sources.openbible.snapshot_sha256}
            ),
            source_file_hashes_json=_canonical_json(source.file_hashes),
            source_audit_json=_canonical_json(source_audit),
            tier1_header_sha256=tier1.sha256,
            passage_input_run_id=passage_metadata.run_id,
            passage_logical_hashes_json=_canonical_json(passage_metadata.logical_hashes),
            relationship_count=relationship_count,
            endpoint_count=endpoint_count,
            mapping_count=mapping_count,
            leakage_group_counts_json=_canonical_json(leakage_counts),
            split_counts_json=_canonical_json(split_counts),
            negative_counts_json=_canonical_json(negative_counts),
            configuration_hash=config_hash,
            logical_table_hashes_json="{}",
            physical_table_hashes_json="{}",
            processing_environment_json=_canonical_json(
                {
                    "echoes_version": __version__,
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                }
            ),
            runtime_seconds=elapsed,
            storage_footprint_bytes=0,
        )
        metadata_frame = _model_frame([metadata], "benchmark_metadata")
        storage = stager.finalize(metadata_frame)
        del metadata_frame
        gc.collect()
    load_benchmark_duckdb(storage, database_path)
    return BenchmarkBuildResult(
        benchmark_run_id=benchmark_run_id,
        benchmark_version=benchmark_version,
        source_audit=source_audit,
        mapping_status_counts=mapping_counts,
        corpus_pair_counts=corpus_counts,
        leakage_group_counts=leakage_counts,
        split_counts=split_counts,
        negative_counts=negative_counts,
        storage=storage,
        database_path=database_path,
        runtime_seconds=time.perf_counter() - started,
    )
