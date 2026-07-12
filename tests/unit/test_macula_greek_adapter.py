"""MACULA Greek adapter tests over legally safe synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echoes.ingest.macula_greek import (
    GreekIngestionError,
    parse_macula_greek_nodes,
)
from echoes.manifests.sources import SourceManifest
from echoes.settings import NormalizationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GREEK_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_greek"


def test_adapter_maps_fixture_tokens_one_to_one(
    greek_adapter_result,
) -> None:
    result = greek_adapter_result

    assert result.summary.source_records == 7
    assert result.summary.processed_tokens == 7
    assert result.summary.books == 1
    assert result.summary.chapters == 1
    assert result.summary.verses == 2
    token_ids = result.tokens["token_id"].to_list()
    assert token_ids == [
        "GNT_JUD_001_001_0001",
        "GNT_JUD_001_001_0002",
        "GNT_JUD_001_001_0003",
        "GNT_JUD_001_001_0004",
        "GNT_JUD_001_001_0005",
        "GNT_JUD_001_002_0001",
        "GNT_JUD_001_002_0002",
    ]
    assert result.tokens["position_in_corpus"].to_list() == list(range(1, 8))


def test_adapter_separates_punctuation_losslessly(greek_adapter_result) -> None:
    tokens = {row["token_id"]: row for row in greek_adapter_result.tokens.to_dicts()}
    final_word = tokens["GNT_JUD_001_001_0005"]

    assert final_word["surface_form"] == "λόγου,"
    assert final_word["normalized_form"] == "λόγου"
    assert final_word["trailing_punctuation"] == ","
    assert final_word["leading_punctuation"] == ""
    reconstructed = (
        final_word["leading_punctuation"]
        + final_word["normalized_form"]
        + final_word["trailing_punctuation"]
    )
    assert reconstructed == final_word["surface_form"]
    assert greek_adapter_result.summary.punctuation_bearing_tokens == 2


def test_adapter_preserves_elision_and_folds_forms(greek_adapter_result) -> None:
    tokens = {row["token_id"]: row for row in greek_adapter_result.tokens.to_dicts()}
    elided = tokens["GNT_JUD_001_001_0004"]
    first = tokens["GNT_JUD_001_001_0001"]

    assert elided["is_elided"] is True
    assert elided["surface_form"] == elided["normalized_form"]
    assert first["is_elided"] is False
    # Case folding also maps final sigma to medial sigma.
    assert first["folded_form"] == "δουλοσ"
    assert first["surface_form"] == "Δοῦλος"
    assert greek_adapter_result.summary.elided_tokens == 1


def test_adapter_preserves_annotations_and_provenance(greek_adapter_result) -> None:
    tokens = {row["token_id"]: row for row in greek_adapter_result.tokens.to_dicts()}
    first = tokens["GNT_JUD_001_001_0001"]
    verb = tokens["GNT_JUD_001_001_0003"]

    assert first["lemma"] == "δοῦλος (II)"
    assert first["strong_number"] == "1401"
    assert first["part_of_speech"] == "noun"
    assert first["semantic_domain"] == "087005"
    assert first["word_sense"] == "87.76"
    assert first["english_gloss"] == "servant"
    assert first["source_record_id"] == "n99001001001"
    assert first["source_word_id"] == "JUD 1:1!1"
    assert first["source_edition_reference"] == "JUD 1:1"
    assert first["source_normalized_form"] == "δοῦλος"
    morphology = json.loads(first["morphology_json"])
    assert morphology["FunctionalTag"] == "N-NSM"
    assert morphology["Case"] == "Nominative"
    frame = json.loads(verb["frame_json"])
    assert frame["Frame"] == "A0:n99001001001"
    assert verb["participant_id"] == "n99001001001"
    extras = json.loads(first["source_extras_json"])
    assert extras["attributes"]["Unicode"] == "Δοῦλος"
    assert verb["syntactic_function"] == "V"
    assert verb["clause_id"] is not None


def test_adapter_is_deterministic(
    greek_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    first = parse_macula_greek_nodes(
        GREEK_FIXTURE_ROOT,
        source=greek_source,
        normalization=normalization_config.greek,
    )
    second = parse_macula_greek_nodes(
        GREEK_FIXTURE_ROOT,
        source=greek_source,
        normalization=normalization_config.greek,
    )

    assert first.tokens.equals(second.tokens)
    assert first.source_records.equals(second.source_records)
    assert first.summary == second.summary


def _write_fixture(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_book_filename_reference_mismatch_fails(
    tmp_path: Path,
    greek_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    original = (GREEK_FIXTURE_ROOT / "Nestle1904" / "nodes" / "26-jude.xml").read_text(
        encoding="utf-8"
    )
    _write_fixture(tmp_path / "Nestle1904" / "nodes" / "27-revelation.xml", original)

    with pytest.raises(GreekIngestionError, match="book-number mismatch"):
        parse_macula_greek_nodes(
            tmp_path,
            source=greek_source,
            normalization=normalization_config.greek,
        )


def test_duplicate_word_reference_fails(
    tmp_path: Path,
    greek_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    original = (GREEK_FIXTURE_ROOT / "Nestle1904" / "nodes" / "26-jude.xml").read_text(
        encoding="utf-8"
    )
    duplicated = original.replace('ref="JUD 1:2!2"', 'ref="JUD 1:2!1"')
    _write_fixture(tmp_path / "Nestle1904" / "nodes" / "26-jude.xml", duplicated)

    with pytest.raises(GreekIngestionError, match="share one source word reference"):
        parse_macula_greek_nodes(
            tmp_path,
            source=greek_source,
            normalization=normalization_config.greek,
        )


def test_missing_xml_id_fails(
    tmp_path: Path,
    greek_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    original = (GREEK_FIXTURE_ROOT / "Nestle1904" / "nodes" / "26-jude.xml").read_text(
        encoding="utf-8"
    )
    broken = original.replace('xml:id="n99001002002" ', "", 1)
    _write_fixture(tmp_path / "Nestle1904" / "nodes" / "26-jude.xml", broken)

    with pytest.raises(GreekIngestionError, match="without xml:id"):
        parse_macula_greek_nodes(
            tmp_path,
            source=greek_source,
            normalization=normalization_config.greek,
        )
