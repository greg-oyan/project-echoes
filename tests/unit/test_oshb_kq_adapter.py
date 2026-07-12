"""OSHB Ketiv/Qere supplement adapter tests over synthetic aligned fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echoes.corpus.models import CanonicalToken
from echoes.ingest.oshb_ketiv_qere import build_kq_supplement
from echoes.manifests.sources import SourceManifest
from echoes.settings import NormalizationConfig

OSHB_KQ_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "oshb_kq"


def _registry_by_id(result) -> dict[str, dict]:
    return {row["locus_id"]: row for row in result.locus_registry.to_dicts()}


def test_locus_kinds_and_counts(kq_supplement_result) -> None:
    summary = kq_supplement_result.summary

    assert summary.loci == 7
    assert summary.paired_loci == 5
    assert summary.ketiv_only_loci == 1
    assert summary.qere_only_loci == 1
    assert summary.ketiv_tokens == 7  # five single ketiv + one two-word ketiv run
    assert summary.loci_by_book == {"DAN": 1, "GEN": 6}


def test_paired_locus_keys_into_vacant_slot_with_stable_identity(
    kq_supplement_result,
) -> None:
    registry = _registry_by_id(kq_supplement_result)
    locus = registry["KQL_GEN_001_001_0002"]

    assert locus["kind"] == "paired"
    assert json.loads(locus["ketiv_word_slots_json"]) == [2]
    assert json.loads(locus["qere_word_slots_json"]) == [3]
    assert locus["surface_match_tier"] == "exact"
    assert locus["alignment_method"] == "vacant_slot_adjacency"
    assert locus["alignment_confidence"] == 1.0
    assert locus["conflict"] is False
    ketiv_ids = json.loads(locus["ketiv_token_ids_json"])
    assert len(ketiv_ids) == 1
    assert ketiv_ids[0].startswith("HB_GEN_001_001_0002~")
    qere_ids = json.loads(locus["macula_qere_token_ids_json"])
    assert qere_ids == ["HB_GEN_001_001_0003"]


def test_ketiv_tokens_satisfy_canonical_schema_v2(kq_supplement_result) -> None:
    rows = kq_supplement_result.ketiv_tokens.to_dicts()

    assert rows
    for row in rows:
        token = CanonicalToken.model_validate(row)
        assert token.is_variant
        assert token.variant_type == "ketiv"
        assert token.variant_group_id is not None
        assert token.is_default_reading is False
        assert token.ketiv_form == token.surface_form
        assert token.qere_form is None
        assert token.source_id == "oshb-morphhb"


def test_exegesis_and_masora_notes_do_not_break_adjacency(kq_supplement_result) -> None:
    registry = _registry_by_id(kq_supplement_result)

    # GEN 1:1 has an exegesis note between ketiv and variant note.
    assert registry["KQL_GEN_001_001_0002"]["kind"] == "paired"
    # GEN 1:5 has a Masora note between two ketiv words of one locus.
    locus = registry["KQL_GEN_001_005_0002"]
    assert locus["kind"] == "paired"
    assert json.loads(locus["ketiv_word_slots_json"]) == [2, 3]
    assert json.loads(locus["qere_word_slots_json"]) == [4, 5]
    assert locus["alignment_confidence"] == 0.9  # multi-word locus


def test_ketiv_only_and_qere_only_loci(kq_supplement_result) -> None:
    registry = _registry_by_id(kq_supplement_result)

    ketiv_only = registry["KQL_GEN_001_002_0002"]
    assert ketiv_only["kind"] == "ketiv_only"
    assert json.loads(ketiv_only["macula_qere_token_ids_json"]) == []
    assert ketiv_only["surface_match_tier"] == "not_applicable"
    assert ketiv_only["alignment_confidence"] == 0.9

    qere_only = registry["KQL_GEN_001_003_0002"]
    assert qere_only["kind"] == "qere_only"
    assert json.loads(qere_only["ketiv_token_ids_json"]) == []
    assert qere_only["variant_group_id"] is None
    assert qere_only["surface_match_tier"] == "exact"


def test_conflicts_are_recorded_never_reconciled(kq_supplement_result) -> None:
    registry = _registry_by_id(kq_supplement_result)
    conflicts = {row["locus_id"]: row for row in kq_supplement_result.conflicts.to_dicts()}

    mismatch = registry["KQL_GEN_001_004_0002"]
    assert mismatch["surface_match_tier"] == "mismatch"
    assert mismatch["conflict"] is True
    assert mismatch["alignment_confidence"] == 0.3
    conflict_row = conflicts["KQL_GEN_001_004_0002"]
    assert conflict_row["primary_value"] != conflict_row["supplement_value"]
    assert conflict_row["primary_source_id"] == "macula-hebrew"
    assert conflict_row["supplement_source_id"] == "oshb-morphhb"

    consonantal = registry["KQL_GEN_001_006_0002"]
    assert consonantal["surface_match_tier"] == "consonantal"
    assert consonantal["conflict"] is True
    assert consonantal["alignment_confidence"] == 0.7
    assert "KQL_GEN_001_006_0002" in conflicts


def test_aramaic_passages_set_ketiv_language(kq_supplement_result) -> None:
    tokens = {row["token_id"]: row for row in kq_supplement_result.ketiv_tokens.to_dicts()}
    dan = [row for row in tokens.values() if row["book"] == "DAN"]

    assert len(dan) == 1
    assert dan[0]["language"] == "aramaic"
    assert any(issue.code == "language-inferred" for issue in kq_supplement_result.issues)


def test_oshb_slash_markup_is_stripped_from_surface_and_preserved_raw(
    kq_supplement_result,
) -> None:
    tokens = kq_supplement_result.ketiv_tokens.to_dicts()
    slashed = [
        row for row in tokens if json.loads(row["source_extras_json"])["oshb_text"] == "ה/סערה"
    ]

    assert len(slashed) == 1
    assert slashed[0]["surface_form"] == "הסערה"


def test_supplement_build_is_deterministic(
    kq_primary_tokens,
    oshb_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    first = build_kq_supplement(
        OSHB_KQ_FIXTURE_ROOT,
        kq_primary_tokens,
        source=oshb_source,
        normalization=normalization_config.hebrew,
    )
    second = build_kq_supplement(
        OSHB_KQ_FIXTURE_ROOT,
        kq_primary_tokens,
        source=oshb_source,
        normalization=normalization_config.hebrew,
    )

    assert first.ketiv_tokens.equals(second.ketiv_tokens)
    assert first.locus_registry.equals(second.locus_registry)
    assert first.conflicts.equals(second.conflicts)
    assert first.summary == second.summary


def test_token_ids_never_collide_with_primary(kq_supplement_result, kq_primary_tokens) -> None:
    primary_ids = set(kq_primary_tokens["token_id"].to_list())
    ketiv_ids = set(kq_supplement_result.ketiv_tokens["token_id"].to_list())

    assert len(ketiv_ids) == kq_supplement_result.ketiv_tokens.height
    assert not (ketiv_ids & primary_ids)


def test_primary_frame_is_never_modified(
    kq_primary_tokens,
    oshb_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    from echoes.corpus.validation import corpus_content_digest, corpus_identity_digest

    before_identity = corpus_identity_digest(kq_primary_tokens)
    before_content = corpus_content_digest(kq_primary_tokens)

    build_kq_supplement(
        OSHB_KQ_FIXTURE_ROOT,
        kq_primary_tokens,
        source=oshb_source,
        normalization=normalization_config.hebrew,
    )

    assert corpus_identity_digest(kq_primary_tokens) == before_identity
    assert corpus_content_digest(kq_primary_tokens) == before_content


def test_unknown_book_file_fails(tmp_path, kq_primary_tokens, oshb_source, normalization_config):
    from echoes.ingest.oshb_ketiv_qere import KQIngestionError

    target = tmp_path / "wlc"
    target.mkdir(parents=True)
    (target / "Atlantis.xml").write_text(
        (OSHB_KQ_FIXTURE_ROOT / "wlc" / "Gen.xml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(KQIngestionError, match="unknown OSHB book file"):
        build_kq_supplement(
            tmp_path,
            kq_primary_tokens,
            source=oshb_source,
            normalization=normalization_config.hebrew,
        )
