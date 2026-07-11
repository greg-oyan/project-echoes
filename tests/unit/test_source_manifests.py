"""Source-manifest schema and cross-record validation tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from echoes.manifests.sources import (
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


def test_production_catalog_contains_the_governed_source_set() -> None:
    catalog = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml")

    assert {source.source_id for source in catalog.sources} == {
        "etcbc-dead-sea-scrolls",
        "greek-critical-apparatus",
        "hebrew-critical-apparatus",
        "macula-greek",
        "macula-hebrew",
        "openbible-cross-references",
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
    assert all(
        not source.file_hashes for source in catalog.sources if source.source_id != "macula-hebrew"
    )
