"""Reference-only end-to-end fixture for the governed OpenBible adapter seam."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import duckdb
import polars as pl
import pytest

from echoes.acquire import AcquisitionError, acquire_source, verify_acquisition
from echoes.benchmarks.mapping import (
    PassageReferenceIndex,
    PassageTarget,
    map_benchmark_endpoints,
)
from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_NAMES,
    BENCHMARK_ARTIFACT_SCHEMAS,
    BenchmarkArtifactName,
    BenchmarkEndpointMappingRow,
    BenchmarkEndpointRow,
    BenchmarkMetadataRow,
    BenchmarkRow,
)
from echoes.benchmarks.openbible import audit_openbible_source, parse_openbible_source
from echoes.benchmarks.pipeline import _records_relationships_endpoints
from echoes.benchmarks.references import (
    ReferenceParseError,
    ReferenceParseStatus,
    parse_openbible_reference,
)
from echoes.benchmarks.storage import (
    load_benchmark_duckdb,
    read_benchmark_artifacts,
    write_benchmark_artifacts,
)
from echoes.manifests.sources import SourceManifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "openbible_synthetic" / "cross_references.txt"
ZERO_HASH = "0" * 64


class _HttpZipResponse(io.BytesIO):
    """Minimal repeatable HTTPS response used only inside the temporary acquisition."""

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": "application/zip",
            "ETag": '"synthetic-fixture"',
            "Last-Modified": "Sun, 12 Jul 2026 00:00:00 GMT",
        }
        self.status = 200

    def geturl(self) -> str:
        return "https://example.invalid/openbible-synthetic.zip"


def _deterministic_zip(payload: bytes) -> bytes:
    output = io.BytesIO()
    member = zipfile.ZipInfo(
        "cross_references.txt",
        date_time=(2026, 7, 12, 0, 0, 0),
    )
    member.compress_type = zipfile.ZIP_DEFLATED
    member.create_system = 3
    member.external_attr = (stat.S_IFREG | 0o644) << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member, payload)
    return output.getvalue()


def _synthetic_source(payload: bytes, archive_payload: bytes) -> SourceManifest:
    archive_hash = hashlib.sha256(archive_payload).hexdigest()
    version = f"snapshot-2026-07-12-sha256-{archive_hash[:12]}"
    return SourceManifest.model_validate(
        {
            "source_id": "openbible-cross-references",
            "source_name": "Project Echoes synthetic OpenBible-shape fixture",
            "corpus": "Synthetic reference coordinates only",
            "role": "benchmark",
            "language": ["english"],
            "edition": "Project-authored synthetic fixture v1",
            "provider": "Project Echoes test suite",
            "repository_or_location": "tests/fixtures/openbible_synthetic/cross_references.txt",
            "version_or_commit": version,
            "download_date": None,
            "license": "CC0 1.0 Universal for the project-authored synthetic fixture",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "license_review_status": "complete",
            "required_attribution": "No attribution required for synthetic fixture rows",
            "redistribution_status": "permitted",
            "machine_processing_status": "permitted",
            "raw_data_git_policy": "ignored_local_only",
            "expected_files": ["cross_references.txt"],
            "file_hashes": {
                "cross_references.txt": hashlib.sha256(payload).hexdigest(),
            },
            "ingest_adapter": "echoes.benchmarks.openbible",
            "acquisition": {
                "method": "http_zip",
                "version_label": version,
                "archive_sha256": archive_hash,
                "files": [
                    {
                        "path": "openbible-synthetic.zip",
                        "url": "https://example.invalid/openbible-synthetic.zip",
                        "size_bytes": len(archive_payload),
                    }
                ],
            },
            "archive_schema": {
                "archive_format": "zip",
                "data_file": "cross_references.txt",
                "encoding": "utf-8",
                "byte_order_mark": "none",
                "newline_convention": "lf",
                "delimiter": "\t",
                "header": [
                    "From Verse",
                    "To Verse",
                    "Votes",
                    "#www.openbible.info CC-BY 2026-07-06",
                ],
                "column_count": 3,
                "reference_syntax": "Book.Chapter.Verse",
                "range_syntax": "Book.Chapter.Verse-Book.Chapter.Verse",
                "weight_representation": "signed decimal integer vote",
                "directionality": "a_to_b",
                "canonical_record_stream_schema_version": "openbible-tsv-v1",
            },
            "research_purpose": "Exercise the Milestone 6 reference-only integration seam.",
            "known_limitations": ["Contains no biblical wording or production source rows."],
            "notes": ["All post-header rows were authored solely for automated tests."],
            "confirmed_information": ["Fixture content consists only of references and votes."],
            "unresolved_questions": [],
            "status": "approved",
        }
    )


def _passage_targets() -> PassageReferenceIndex:
    targets: list[PassageTarget] = []

    def add(
        corpus: Literal["hebrew", "greek"],
        reading: Literal["qere", "source"],
        book: str,
        chapter: int,
        verse: int,
        *,
        profiles: tuple[Literal["edition_complete", "critical_core"], ...] = (
            "edition_complete",
            "critical_core",
        ),
        disputed_ids: tuple[str, ...] = (),
    ) -> None:
        for profile in profiles:
            targets.append(
                PassageTarget(
                    passage_id=f"synthetic-{profile}-{book}-{chapter}-{verse}",
                    corpus=corpus,
                    analysis_profile=profile,
                    analysis_reading=reading,
                    book=book,
                    chapter=chapter,
                    verse=verse,
                    reference=f"{book} {chapter}:{verse}",
                    token_count=1,
                    disputed_passage_flag=bool(disputed_ids),
                    disputed_passage_ids=disputed_ids,
                    reference_gap=False,
                )
            )

    add("hebrew", "qere", "GEN", 1, 1)
    add("hebrew", "qere", "GEN", 1, 3)
    add("greek", "source", "JHN", 1, 1)
    add("greek", "source", "MAT", 1, 1)
    add("greek", "source", "MAT", 2, 1)
    add(
        "greek",
        "source",
        "JHN",
        7,
        53,
        profiles=("edition_complete",),
        disputed_ids=("synthetic-disputed-nt",),
    )
    return PassageReferenceIndex(targets)


def _frame(name: BenchmarkArtifactName, rows: Iterable[BenchmarkRow]) -> pl.DataFrame:
    values = [row.model_dump() for row in rows]
    if not values:
        return pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
    return pl.DataFrame(values, schema=BENCHMARK_ARTIFACT_SCHEMAS[name], orient="row")


def _mapping_statuses(
    source_reference: str,
    profile: str,
    *,
    endpoints: Iterable[BenchmarkEndpointRow],
    mappings: Iterable[BenchmarkEndpointMappingRow],
) -> set[str]:
    endpoint_ids = {
        endpoint.endpoint_id
        for endpoint in endpoints
        if endpoint.source_reference == source_reference
    }
    return {
        mapping.mapping_status
        for mapping in mappings
        if mapping.endpoint_id in endpoint_ids and mapping.target_analysis_profile == profile
    }


def test_synthetic_openbible_archive_through_mapping_and_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover acquisition, raw audit, source semantics, mappings, and storage."""

    payload = FIXTURE_PATH.read_bytes()
    archive_payload = _deterministic_zip(payload)
    source = _synthetic_source(payload, archive_payload)
    assert source.acquisition is not None
    data_root = tmp_path / "data"

    tampered = bytearray(archive_payload)
    tampered[0] ^= 0x01
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _HttpZipResponse(bytes(tampered)),
    )
    with pytest.raises(AcquisitionError, match="SHA-256 mismatch"):
        acquire_source(source, data_root=data_root)

    def synthetic_urlopen(_request: object, timeout: int) -> _HttpZipResponse:
        assert timeout == 120
        return _HttpZipResponse(archive_payload)

    monkeypatch.setattr(urllib.request, "urlopen", synthetic_urlopen)
    acquisition_root, receipt = acquire_source(source, data_root=data_root)
    source_path = acquisition_root / "cross_references.txt"
    assert source_path.read_bytes() == payload
    assert (acquisition_root / "_archive" / "openbible-synthetic.zip").read_bytes() == (
        archive_payload
    )
    assert receipt.archive is not None
    assert receipt.archive.sha256 == source.acquisition.archive_sha256
    assert receipt.files[0].sha256 == source.file_hashes["cross_references.txt"]

    def reject_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("offline verification must not perform network access")

    monkeypatch.setattr(urllib.request, "urlopen", reject_network)
    verified_root, verified_receipt = verify_acquisition(source, data_root=data_root)
    assert verified_root == acquisition_root
    assert verified_receipt.canonical_record_stream_sha256 == receipt.canonical_record_stream_sha256

    parsed = parse_openbible_source(source_path)
    audit = audit_openbible_source(parsed)
    assert parsed.raw_row_count == 13
    assert parsed.parsed_row_count == 12
    assert parsed.invalid_row_count == 1
    assert parsed.records[-1].parse_status == "invalid_weight"
    assert parsed.canonical_stream_sha256 == receipt.canonical_record_stream_sha256
    assert audit["exact_duplicate_occurrence_count"] == 1
    assert audit["duplicate_directed_pair_count"] == 1
    assert audit["reverse_pair_count"] == 1
    assert audit["self_link_count"] == 1
    assert audit["zero_weight_count"] == 1
    assert audit["positive_weight_count"] == 11
    assert audit["reference_kind_counts"] == {
        "cross_chapter_range": 2,
        "same_chapter_range": 1,
        "single": 9,
    }

    with pytest.raises(ReferenceParseError) as invalid_book:
        parse_openbible_reference("Fiction.1.1")
    assert invalid_book.value.status is ReferenceParseStatus.UNKNOWN_BOOK
    with pytest.raises(ReferenceParseError) as invalid_verse:
        parse_openbible_reference("John.1.999", verse_bounds={("JHN", 1): 51})
    assert invalid_verse.value.status is ReferenceParseStatus.INVALID_VERSE
    with pytest.raises(ReferenceParseError) as backward_range:
        parse_openbible_reference("John.2.1-John.1.1")
    assert backward_range.value.status is ReferenceParseStatus.BACKWARD_RANGE

    (
        source_records,
        relationships,
        relationship_links,
        endpoints,
        issues,
        _spans,
        _source_record_keys,
        imported_audit,
    ) = _records_relationships_endpoints(source, receipt, source_path)
    assert imported_audit == audit
    assert len(source_records) == 13
    assert len(relationships) == 10
    assert len(relationship_links) == 11
    assert len(endpoints) == 20
    assert {issue.code for issue in issues} == {
        "endpoint_reference_unmapped",
        "self_link_excluded",
        "source_parse_error",
    }
    duplicate = next(
        relationship for relationship in relationships if relationship.source_record_count == 2
    )
    assert duplicate.source_reference_a == "Gen.1.1"
    assert duplicate.source_reference_b == "John.1.1"

    mapping_result = map_benchmark_endpoints(endpoints, _passage_targets())
    mappings = mapping_result.mappings
    assert len(mappings) == 40
    assert _mapping_statuses(
        "John.1.1",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"mapped_provisional"}
    assert _mapping_statuses(
        "Gen.1.1-Gen.1.3",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"mapped_partial"}
    assert _mapping_statuses(
        "Matt.1.1-Matt.2.1",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"mapped_provisional"}
    assert _mapping_statuses(
        "Fiction.1.1",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_reference"}
    assert _mapping_statuses(
        "John.2.1-John.1.1",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_reference"}
    assert _mapping_statuses(
        "John.1.999",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_missing_target"}
    assert _mapping_statuses(
        "John.5.4",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_missing_target"}
    assert _mapping_statuses(
        "John.5.4",
        "critical_core",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_missing_target"}
    assert _mapping_statuses(
        "Rev.22.21",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"unresolved_missing_target"}
    assert _mapping_statuses(
        "John.7.53",
        "edition_complete",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"mapped_provisional"}
    assert _mapping_statuses(
        "John.7.53",
        "critical_core",
        endpoints=endpoints,
        mappings=mappings,
    ) == {"excluded_by_profile"}
    disputed_mapping = next(
        mapping
        for mapping in mappings
        if mapping.endpoint_id
        in {
            endpoint.endpoint_id
            for endpoint in endpoints
            if endpoint.source_reference == "John.7.53"
        }
        and mapping.target_analysis_profile == "edition_complete"
    )
    assert disputed_mapping.disputed_passage_flag
    assert json.loads(disputed_mapping.disputed_passage_ids_json) == ["synthetic-disputed-nt"]

    metadata = BenchmarkMetadataRow(
        benchmark_run_id="benchmark-v1-synthetic-integration",
        benchmark_version="synthetic-integration-v1",
        source_versions_json=json.dumps({source.source_id: source.version_or_commit}),
        source_archive_hashes_json=json.dumps(
            {source.source_id: source.acquisition.archive_sha256}
        ),
        source_file_hashes_json=json.dumps(source.file_hashes),
        source_audit_json=json.dumps(audit, sort_keys=True),
        tier1_header_sha256=ZERO_HASH,
        passage_input_run_id="passages-v1-synthetic",
        passage_logical_hashes_json="{}",
        relationship_count=len(relationships),
        endpoint_count=len(endpoints),
        mapping_count=len(mappings),
        leakage_group_counts_json="{}",
        split_counts_json="{}",
        negative_counts_json="{}",
        configuration_hash=ZERO_HASH,
        logical_table_hashes_json="{}",
        physical_table_hashes_json="{}",
        processing_environment_json='{"fixture":true}',
        runtime_seconds=0.0,
        storage_footprint_bytes=0,
    )
    frames = {
        name: pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
        for name in BENCHMARK_ARTIFACT_NAMES
    }
    frames["benchmark_source_records"] = _frame("benchmark_source_records", source_records)
    frames["benchmark_relationships"] = _frame("benchmark_relationships", relationships)
    frames["benchmark_relationship_source_records"] = _frame(
        "benchmark_relationship_source_records", relationship_links
    )
    frames["benchmark_endpoints"] = _frame("benchmark_endpoints", endpoints)
    frames["benchmark_endpoint_mappings"] = _frame("benchmark_endpoint_mappings", mappings)
    frames["benchmark_issues"] = _frame("benchmark_issues", issues)
    frames["benchmark_metadata"] = _frame("benchmark_metadata", [metadata])

    stored = write_benchmark_artifacts(frames, tmp_path / "processed" / "benchmarks")
    loaded = read_benchmark_artifacts(stored.schema_root)
    assert loaded["benchmark_source_records"].height == 13
    assert loaded["benchmark_relationships"].height == 10
    assert loaded["benchmark_endpoint_mappings"].height == 40

    database = tmp_path / "synthetic.duckdb"
    load_benchmark_duckdb(stored, database)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM openbible_duplicate_pairs").fetchone() == (
            1,
        )
        assert connection.execute("SELECT count(*) FROM openbible_reverse_pairs").fetchone() == (2,)
        corpus_view_counts = tuple(
            connection.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
            for view in (
                "within_old_testament_relationships",
                "within_new_testament_relationships",
                "cross_testament_relationships",
            )
        )
        observed_statuses = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT mapping_status FROM benchmark_endpoint_mappings"
            ).fetchall()
        }
    assert corpus_view_counts == (1, 1, 6)
    assert observed_statuses == {
        "excluded_by_profile",
        "mapped_partial",
        "mapped_provisional",
        "unresolved_missing_target",
        "unresolved_reference",
    }
