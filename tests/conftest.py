"""Shared legally safe fixtures for Hebrew and Greek ingestion tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from echoes.corpus.greek_storage import (
    ProcessedGreekCorpus,
    load_greek_duckdb,
    write_processed_greek_corpus,
)
from echoes.corpus.storage import ProcessedCorpus, load_hebrew_duckdb, write_processed_corpus
from echoes.ingest.macula_greek import GreekAdapterResult, parse_macula_greek_nodes
from echoes.ingest.macula_hebrew import AdapterResult, parse_macula_hebrew_nodes
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest, load_source_catalog
from echoes.settings import NormalizationConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACULA_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_hebrew"
GREEK_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_greek"


@dataclass(frozen=True, slots=True)
class StoredFixtureCorpus:
    processed: ProcessedCorpus
    database: Path
    output_dir: Path


@pytest.fixture(scope="session")
def macula_source() -> SourceManifest:
    source = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml").find(
        "macula-hebrew"
    )
    assert source is not None
    return source


@pytest.fixture(scope="session")
def normalization_config() -> NormalizationConfig:
    loaded = load_config(PROJECT_ROOT / "config" / "normalization.yaml")
    assert isinstance(loaded, NormalizationConfig)
    return loaded


@pytest.fixture()
def adapter_result(
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> AdapterResult:
    return parse_macula_hebrew_nodes(
        MACULA_FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading=normalization_config.ketiv_qere.analysis_reading,
    )


@pytest.fixture()
def stored_fixture_corpus(
    tmp_path: Path,
    adapter_result: AdapterResult,
    macula_source: SourceManifest,
) -> StoredFixtureCorpus:
    output_dir = tmp_path / "processed" / "fixture"
    database = tmp_path / "processed" / "fixture.duckdb"
    raw_hashes = {
        path.relative_to(MACULA_FIXTURE_ROOT).as_posix(): sha256_file(path)
        for path in MACULA_FIXTURE_ROOT.rglob("*.xml")
    }
    processed = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=sha256_file(PROJECT_ROOT / "config" / "normalization.yaml"),
        raw_file_hashes=raw_hashes,
        output_dir=output_dir,
    )
    load_hebrew_duckdb(processed, database)
    return StoredFixtureCorpus(processed, database, output_dir)


@dataclass(frozen=True, slots=True)
class StoredGreekFixtureCorpus:
    processed: ProcessedGreekCorpus
    database: Path
    output_dir: Path


@pytest.fixture(scope="session")
def greek_source() -> SourceManifest:
    source = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml").find(
        "macula-greek"
    )
    assert source is not None
    return source


@pytest.fixture()
def greek_adapter_result(
    greek_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> GreekAdapterResult:
    return parse_macula_greek_nodes(
        GREEK_FIXTURE_ROOT,
        source=greek_source,
        normalization=normalization_config.greek,
    )


@pytest.fixture()
def stored_greek_fixture_corpus(
    tmp_path: Path,
    greek_adapter_result: GreekAdapterResult,
    greek_source: SourceManifest,
) -> StoredGreekFixtureCorpus:
    output_dir = tmp_path / "processed" / "greek-fixture"
    database = tmp_path / "processed" / "fixture.duckdb"
    raw_hashes = {
        path.relative_to(GREEK_FIXTURE_ROOT).as_posix(): sha256_file(path)
        for path in GREEK_FIXTURE_ROOT.rglob("*.xml")
    }
    processed = write_processed_greek_corpus(
        greek_adapter_result,
        source=greek_source,
        normalization_config_hash=sha256_file(PROJECT_ROOT / "config" / "normalization.yaml"),
        raw_file_hashes=raw_hashes,
        output_dir=output_dir,
    )
    load_greek_duckdb(processed, database)
    return StoredGreekFixtureCorpus(processed, database, output_dir)
