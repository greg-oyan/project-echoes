"""Source-manifest schema and cross-record validation tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from echoes.manifests.sources import (
    SourceAcquisitionSpec,
    SourceManifest,
    SourceManifestError,
    SourceStatus,
    load_source_catalog,
    serialize_source_catalog,
    summarize_sources,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "source_manifests"


def test_valid_source_manifest_loads_and_summarizes() -> None:
    catalog = load_source_catalog(FIXTURES / "valid.yaml")
    summary = summarize_sources(catalog)

    assert [source.source_id for source in catalog.sources] == [
        "fixture-primary",
        "fixture-reference",
    ]
    assert summary.total == 2
    assert summary.by_role == {"primary_discovery": 1, "reference": 1}
    assert summary.licensing_complete == 0
    assert summary.licensing_incomplete == 2


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("duplicate-id.yaml", "duplicate source_id"),
        ("invalid-enum.yaml", "invented_role"),
        ("invalid-hash.yaml", "SHA-256"),
        ("approved-unresolved.yaml", "complete licensing review"),
        ("acquired-no-version.yaml", "requires version_or_commit"),
        ("restricted-git-trackable.yaml", "Git-trackable"),
    ],
)
def test_invalid_source_manifests_fail_with_actionable_errors(
    fixture_name: str,
    message: str,
) -> None:
    with pytest.raises(SourceManifestError, match=message):
        load_source_catalog(FIXTURES / fixture_name)


def test_source_catalog_round_trips_through_normalized_yaml(tmp_path: Path) -> None:
    catalog = load_source_catalog(FIXTURES / "valid.yaml")
    serialized = tmp_path / "round-trip.yaml"
    serialized.write_text(serialize_source_catalog(catalog), encoding="utf-8")

    reloaded = load_source_catalog(serialized)

    assert reloaded == catalog


def test_download_date_rejects_non_iso_format() -> None:
    catalog = load_source_catalog(FIXTURES / "valid.yaml")
    values = catalog.sources[0].model_dump(mode="json")
    values["download_date"] = "07/10/2026"

    with pytest.raises(ValidationError, match="download_date must use YYYY-MM-DD"):
        SourceManifest.model_validate(values)


def test_http_zip_spec_requires_one_content_hash_pinned_zip() -> None:
    valid = {
        "method": "http_zip",
        "version_label": "snapshot-2026-07-12-sha256-aaaaaaaaaaaa",
        "archive_sha256": "a" * 64,
        "files": [
            {
                "path": "cross-references.zip",
                "url": "https://example.invalid/cross-references.zip",
            }
        ],
    }

    spec = SourceAcquisitionSpec.model_validate(valid)

    assert spec.upstream_commit is None
    assert spec.archive_sha256 == "a" * 64

    for update, message in (
        ({"archive_sha256": None}, "requires archive_sha256"),
        ({"upstream_commit": "1" * 40}, "may not define upstream_commit"),
        ({"files": []}, "exactly one archive file"),
        (
            {
                "files": [
                    {
                        "path": "cross-references.txt",
                        "url": "https://example.invalid/cross-references.txt",
                    }
                ]
            },
            ".zip suffix",
        ),
    ):
        values = {**valid, **update}
        with pytest.raises(ValidationError, match=message):
            SourceAcquisitionSpec.model_validate(values)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("version_prefix", "archive SHA-256 prefix"),
        ("missing_extracted_hash", "hash for every expected file"),
        ("missing_archive_schema", "requires archive_schema"),
    ],
)
def test_approved_http_zip_source_requires_complete_content_identity(
    mutation: str,
    message: str,
) -> None:
    catalog = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml")
    source = catalog.find("openbible-cross-references")
    assert source is not None
    values = source.model_dump(mode="json")
    if mutation == "version_prefix":
        wrong_version = "snapshot-2026-07-12-sha256-ffffffffffff"
        values["version_or_commit"] = wrong_version
        assert isinstance(values["acquisition"], dict)
        values["acquisition"]["version_label"] = wrong_version
    elif mutation == "missing_extracted_hash":
        values["file_hashes"] = {}
    else:
        values["archive_schema"] = None

    with pytest.raises(ValidationError, match=message):
        SourceManifest.model_validate(values)


def test_production_catalog_contains_the_governed_source_set() -> None:
    catalog = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml")

    assert {source.source_id for source in catalog.sources} == {
        "etcbc-dead-sea-scrolls",
        "greek-critical-apparatus",
        "hebrew-critical-apparatus",
        "macula-greek",
        "macula-hebrew",
        "openbible-cross-references",
        "oshb-morphhb",
        "project-echoes-tier1-quotations",
        "septuagint-catss",
        "stepbible-data",
        "targum-corpus",
        "ubs-parallel-passages",
    }
    macula = catalog.find("macula-hebrew")
    assert macula is not None
    assert macula.status is SourceStatus.VALIDATED
    assert macula.version_or_commit == "7ab368fcb14e4ad2e0f784138241a098fb516ec4"
    assert macula.acquisition is not None
    assert macula.acquisition.version_label == "25.08.11"
    assert set(macula.file_hashes) == {
        "README.md",
        "LICENSE.md",
        "WLC/nodes/macula-hebrew.xml",
    }
    greek = catalog.find("macula-greek")
    assert greek is not None
    assert greek.version_or_commit == "b5b7ecec0882a3e9a609ecac99e157391e5d9b46"
    assert greek.acquisition is not None
    assert greek.acquisition.version_label == "24.06.17"
    assert set(greek.file_hashes) == {
        "README.md",
        "LICENSE.md",
        "Nestle1904/nodes/26-jude.xml",
    }
    oshb = catalog.find("oshb-morphhb")
    assert oshb is not None
    assert oshb.version_or_commit == "3d15126fb1ef74867fc1434be1942e837932691f"
    assert oshb.acquisition is not None
    assert oshb.acquisition.version_label == "master-3d15126"
    assert set(oshb.file_hashes) == {
        "README.md",
        "LICENSE.md",
        "wlc/2Kgs.xml",
    }
    openbible = catalog.find("openbible-cross-references")
    assert openbible is not None
    assert openbible.acquisition is not None
    assert openbible.acquisition.method == "http_zip"
    assert openbible.acquisition.archive_sha256 == (
        "18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492"
    )
    assert openbible.expected_files == ["cross_references.txt"]
    assert openbible.archive_schema is not None
    assert openbible.archive_schema.canonical_record_stream_schema_version == "openbible-tsv-v1"
    tier1 = catalog.find("project-echoes-tier1-quotations")
    assert tier1 is not None
    assert tier1.status is SourceStatus.PLANNED
    assert tier1.version_or_commit == "schema-v1-header-only-sha256-7d6875481395"
    assert tier1.expected_files == ["data/benchmarks/tier1_quotations.csv"]
    assert tier1.file_hashes == {
        "data/benchmarks/tier1_quotations.csv": (
            "7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b"
        )
    }
    hashed_sources = {
        "macula-hebrew",
        "macula-greek",
        "openbible-cross-references",
        "oshb-morphhb",
        "project-echoes-tier1-quotations",
    }
    assert all(
        not source.file_hashes
        for source in catalog.sources
        if source.source_id not in hashed_sources
    )
