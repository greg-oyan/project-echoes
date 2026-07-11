"""Fixture parsing, mapping, identity, language, and error-path tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from echoes.corpus.models import CanonicalToken, Language
from echoes.ingest.macula_hebrew import (
    AdapterResult,
    HebrewIngestionError,
    parse_macula_hebrew_nodes,
    validate_canonical_identities,
)
from echoes.manifests.sources import SourceManifest
from echoes.settings import NormalizationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_hebrew"


def _modified_fixture(tmp_path: Path, old: str, new: str) -> Path:
    destination = tmp_path / "macula"
    shutil.copytree(FIXTURE_ROOT, destination)
    chapter = destination / "WLC" / "nodes" / "01-Gen-001.xml"
    chapter.write_text(
        chapter.read_text(encoding="utf-8").replace(old, new, 1),
        encoding="utf-8",
    )
    return destination


def test_fixture_ingestion_maps_complete_canonical_records(
    adapter_result: AdapterResult,
) -> None:
    tokens = adapter_result.token_models()
    assert adapter_result.summary.processed_tokens == 9
    assert adapter_result.summary.source_records == 9
    assert adapter_result.summary.hebrew_tokens == 7
    assert adapter_result.summary.aramaic_tokens == 2
    assert adapter_result.summary.variant_tokens == 2
    assert adapter_result.summary.punctuation_tokens == 1
    assert [token.token_id for token in tokens[:3]] == [
        "HB_GEN_001_001_0001.01",
        "HB_GEN_001_001_0001.02",
        "HB_GEN_001_001_0002",
    ]


def test_adapter_preserves_source_provenance_syntax_variants_and_missing_values(
    adapter_result: AdapterResult,
) -> None:
    tokens = adapter_result.token_models()
    first = tokens[0]
    variants = [token for token in tokens if token.is_variant]
    ketiv = next(token for token in variants if token.variant_type == "ketiv")
    qere = next(token for token in variants if token.variant_type == "qere")
    aramaic = next(token for token in tokens if token.language is Language.ARAMAIC)
    incomplete = next(token for token in tokens if token.source_word_id == "GEN 1:1!5")

    assert first.source_record_id == "o010010010011"
    assert first.source_row_reference.endswith("#o010010010011")
    assert first.clause_id is not None
    assert first.sentence_id is not None
    assert json.loads(first.source_extras_json)["alternate_tree_count"] == 1
    assert ketiv.ketiv_form == ketiv.surface_form
    assert qere.qere_form == qere.surface_form
    assert ketiv.token_id != qere.token_id
    assert ketiv.variant_group_id == qere.variant_group_id
    assert not ketiv.is_default_reading
    assert qere.is_default_reading
    assert ketiv.normalized_form != qere.normalized_form
    assert first.source_edition_reference == "GEN 1:1"
    assert aramaic.book == "EZR"
    assert incomplete.lemma is None
    assert incomplete.morphology_json is None

    invalid_variant = qere.model_dump(mode="python")
    invalid_variant["variant_group_id"] = None
    with pytest.raises(ValidationError, match="stable variant group"):
        CanonicalToken.model_validate(invalid_variant)


def test_repeated_parsing_and_filesystem_order_produce_identical_ids(
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(FIXTURE_ROOT, copied)
    for index, path in enumerate(reversed(sorted(copied.rglob("*.xml")))):
        path.touch()
        assert index >= 0

    first = parse_macula_hebrew_nodes(
        FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading=normalization_config.ketiv_qere.analysis_reading,
    )
    second = parse_macula_hebrew_nodes(
        copied,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading=normalization_config.ketiv_qere.analysis_reading,
    )

    assert [token.token_id for token in first.token_models()] == [
        token.token_id for token in second.token_models()
    ]
    assert [token.source_record_id for token in first.token_models()] == [
        token.source_record_id for token in second.token_models()
    ]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("o010010010012", "o010010010011", "duplicate source record IDs"),
        ('word="GEN 1:1!5"', 'word="ABC 1:1!5"', "unknown canonical"),
        ('word="GEN 1:1!5"', 'word="GEN 99:1!5"', "invalid chapter"),
        ('morph="HVqp3ms"', 'morph="???"', "malformed morphology"),
    ],
)
def test_invalid_source_structures_fail_clearly(
    old: str,
    new: str,
    message: str,
    tmp_path: Path,
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    fixture = _modified_fixture(tmp_path, old, new)

    with pytest.raises(HebrewIngestionError, match=message):
        parse_macula_hebrew_nodes(
            fixture,
            source=macula_source,
            normalization=normalization_config.hebrew,
            analysis_reading=normalization_config.ketiv_qere.analysis_reading,
        )


def test_analysis_reading_switch_changes_only_the_derived_stream(
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    qere = parse_macula_hebrew_nodes(
        FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading="qere",
    )
    ketiv = parse_macula_hebrew_nodes(
        FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading="ketiv",
    )

    assert qere.tokens.equals(ketiv.tokens)
    assert qere.summary.processed_tokens == ketiv.summary.processed_tokens == 9
    assert qere.analysis_tokens.height == ketiv.analysis_tokens.height == 8
    assert qere.analysis_tokens["token_id"].to_list() != ketiv.analysis_tokens["token_id"].to_list()
    assert qere.analysis_tokens["analysis_position_in_corpus"].to_list() == list(range(1, 9))
    assert ketiv.analysis_tokens["analysis_position_in_corpus"].to_list() == list(range(1, 9))
    qere_selected = qere.analysis_tokens.filter(pl.col("variant_type") == "qere").row(0, named=True)
    ketiv_selected = ketiv.analysis_tokens.filter(pl.col("variant_type") == "ketiv").row(
        0, named=True
    )
    assert qere_selected["analysis_position_in_verse"] == 4
    assert ketiv_selected["analysis_position_in_verse"] == 4
    assert qere_selected["analysis_position_in_clause"] == 4
    assert ketiv_selected["analysis_position_in_clause"] == 4
    assert qere_selected["token_id"] != ketiv_selected["token_id"]
    assert qere.analysis_tokens.equals(
        parse_macula_hebrew_nodes(
            FIXTURE_ROOT,
            source=macula_source,
            normalization=normalization_config.hebrew,
            analysis_reading="qere",
        ).analysis_tokens
    )
    assert ketiv.analysis_tokens.equals(
        parse_macula_hebrew_nodes(
            FIXTURE_ROOT,
            source=macula_source,
            normalization=normalization_config.hebrew,
            analysis_reading="ketiv",
        ).analysis_tokens
    )


def test_unpaired_reading_is_not_silently_dropped(
    tmp_path: Path,
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    fixture = _modified_fixture(
        tmp_path,
        (
            '            <m xml:id="o010010010030" word="GEN 1:1!3" lang="H" '
            'pos="verb" morph="HVqp3ms" type="ketiv" after="">כתב</m>\n'
        ),
        "",
    )
    result = parse_macula_hebrew_nodes(
        fixture,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading="ketiv",
    )

    qere = next(token for token in result.token_models() if token.variant_type == "qere")
    assert result.tokens.height == result.analysis_tokens.height == 8
    assert qere.token_id in result.analysis_tokens["token_id"].to_list()


def test_token_id_and_canonical_position_collisions_fail(
    adapter_result: AdapterResult,
) -> None:
    tokens = adapter_result.token_models()
    first = tokens[0]
    collision = first.model_copy(update={"source_record_id": "distinct-source-id"})

    with pytest.raises(HebrewIngestionError, match="token-ID collisions"):
        validate_canonical_identities([first, collision])

    position_collision = tokens[1].model_copy(
        update={
            "position_in_verse": first.position_in_verse,
            "token_id": "HB_GEN_001_001_9999",
        }
    )
    with pytest.raises(HebrewIngestionError, match="duplicate canonical token positions"):
        validate_canonical_identities([first, position_collision])
