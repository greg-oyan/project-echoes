"""Focused passage-input projection tests for final-discovery-v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from echoes.final_discovery.models import PassageRecord
from echoes.final_discovery.passages import (
    PassageParquetSources,
    PassageProjectionError,
    PassageProjectionScope,
    iter_passage_records_from_parquet,
    project_passage_rows,
    read_passage_records_jsonl,
    write_passage_records_jsonl,
)
from echoes.manifest import sha256_file
from echoes.segment.identity import IdentityMember, build_passage_identity, payload_from_membership
from echoes.segment.models import PASSAGE_COLUMNS, PASSAGE_POLARS_SCHEMA, PassageRow

SHA = "a" * 64
GENRES = {"GEN": "torah", "MAT": "gospels_and_acts"}
PRIMARY_SCOPE = PassageProjectionScope()


def _passage(
    *,
    corpus: str,
    profile: str,
    reading: str,
    book: str,
    reference: str,
    token_id: str,
    ketiv_uncertain: bool = False,
) -> PassageRow:
    identity = build_passage_identity(
        payload_from_membership(
            corpus=corpus,  # type: ignore[arg-type]
            analysis_profile=profile,  # type: ignore[arg-type]
            analysis_reading=reading,  # type: ignore[arg-type]
            granularity="verse",
            book=book,
            source_unit_id=None,
            members=[IdentityMember(token_id, 1, reference)],
        )
    )
    is_hebrew = corpus == "hebrew"
    return PassageRow(
        passage_id=identity.passage_id,
        identity_payload_sha256=identity.payload_sha256,
        segmentation_run_id="fixture",
        corpus=corpus,  # type: ignore[arg-type]
        analysis_profile=profile,  # type: ignore[arg-type]
        analysis_reading=reading,  # type: ignore[arg-type]
        granularity="verse",
        book=book,
        book_order=1,
        start_reference=reference,
        end_reference=reference,
        reference_sequence_json=json.dumps([reference]),
        token_ids_json=json.dumps([token_id]),
        source_unit_id=None,
        constituent_verse_passage_ids_json="[]",
        start_token_id=token_id,
        end_token_id=token_id,
        start_stream_position_in_corpus=1,
        end_stream_position_in_corpus=1,
        token_count=1,
        visible_token_count=1,
        zero_width_token_count=0,
        punctuation_token_count=0,
        word_count=1,
        sentence_count=1,
        clause_count=1,
        source_ids_json=json.dumps([f"macula-{corpus}"]),
        source_versions_json='["fixture"]',
        surface_text="אָמַר" if is_hebrew else "λέγει",
        normalized_text="אמר" if is_hebrew else "λέγει",
        unpointed_text="אמר" if is_hebrew else None,
        folded_text=None if is_hebrew else "λεγει",
        lemma_sequence_json='["say"]',
        root_sequence_json='["say"]',
        part_of_speech_sequence_json='["verb"]',
        semantic_domain_sequence_json='["speech"]',
        entity_ids_json="[null]",
        participant_ids_json='["speaker"]',
        disputed_passage_flag=False,
        disputed_passage_ids_json="[]",
        reference_gap=False,
        ketiv_structural_uncertainty=ketiv_uncertain,
        profile_truncated=profile == "critical_core",
        sensitivity_exclusion_count=1 if profile == "critical_core" else 0,
        previous_passage_id=None,
        next_passage_id=None,
        overlap_with_previous_token_count=0,
        overlap_with_next_token_count=0,
        segmentation_config_hash=SHA,
        created_by_schema_version=1,
    )


def _hebrew_token(token_id: str) -> dict[str, object]:
    return {
        "token_id": token_id,
        "corpus": "hebrew",
        "book": "GEN",
        "morphology_json": '{"tense":"perfect","person":3}',
        "english_gloss": "said",
        "clause_id": "c-unique-source-id",
        "syntactic_function": "predicate",
        "syntactic_head_source_id": None,
    }


def _greek_token(token_id: str) -> dict[str, object]:
    return {
        "token_id": token_id,
        "corpus": "greek",
        "book": "MAT",
        "morphology_json": '{"tense":"present"}',
        "english_gloss": "says",
        "frame_json": '{"role":"predicate","frame":"speech"}',
    }


def _project(
    passages: list[PassageRow | dict[str, object]],
    *,
    hebrew_tokens: list[dict[str, object]],
    greek_tokens: list[dict[str, object]],
    scope: PassageProjectionScope = PRIMARY_SCOPE,
) -> list[PassageRecord]:
    return list(
        project_passage_rows(
            passages,
            hebrew_tokens=hebrew_tokens,
            greek_tokens=greek_tokens,
            book_genres=GENRES,
            passage_source_sha256="1" * 64,
            hebrew_token_source_sha256="2" * 64,
            greek_token_source_sha256="3" * 64,
            genre_source_sha256="4" * 64,
            scope=scope,
        )
    )


def test_primary_projection_aligns_governed_and_token_annotations() -> None:
    hebrew_id = "HB_GEN_001_001_0001"
    greek_id = "GNT_MAT_001_001_0001"
    hebrew = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="qere",
        book="GEN",
        reference="GEN 1:1",
        token_id=hebrew_id,
    )
    greek = _passage(
        corpus="greek",
        profile="edition_complete",
        reading="source",
        book="MAT",
        reference="MAT 1:1",
        token_id=greek_id,
    )

    records = _project(
        [hebrew, greek],
        hebrew_tokens=[_hebrew_token(hebrew_id)],
        greek_tokens=[_greek_token(greek_id)],
    )
    by_corpus = {record.corpus: record for record in records}

    assert set(by_corpus) == {"hebrew", "greek"}
    assert by_corpus["hebrew"].genre == "torah"
    assert by_corpus["hebrew"].token_ids == (hebrew_id,)
    assert by_corpus["hebrew"].original_text == "אָמַר"
    assert by_corpus["hebrew"].morphology_sequence == ('{"person":3,"tense":"perfect"}',)
    assert by_corpus["hebrew"].frames == (
        '{"has_clause_assignment":true,"has_syntactic_head":false,'
        '"syntactic_function":"predicate"}',
    )
    assert "c-unique-source-id" not in by_corpus["hebrew"].frames[0]
    assert by_corpus["greek"].frames == ('{"frame":"speech","role":"predicate"}',)
    assert by_corpus["greek"].token_ids == (greek_id,)
    assert by_corpus["greek"].english_gloss == "says"
    assert len(by_corpus["greek"].source_digest) == 64


def test_sensitivity_records_are_opt_in_and_never_replace_primary_text() -> None:
    qere_id = "HB_GEN_001_001_0001"
    ketiv_id = "HB_GEN_001_001_0002"
    qere = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="qere",
        book="GEN",
        reference="GEN 1:1",
        token_id=qere_id,
    )
    greek_critical_id = "GNT_MAT_001_001_0001"
    critical = _passage(
        corpus="greek",
        profile="critical_core",
        reading="source",
        book="MAT",
        reference="MAT 1:1",
        token_id=greek_critical_id,
    )
    ketiv = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="ketiv",
        book="GEN",
        reference="GEN 1:1",
        token_id=ketiv_id,
        ketiv_uncertain=True,
    )
    tokens = [_hebrew_token(qere_id), _hebrew_token(ketiv_id)]

    greek_tokens = [_greek_token(greek_critical_id)]
    primary = _project(
        [qere, critical, ketiv],
        hebrew_tokens=tokens,
        greek_tokens=greek_tokens,
    )
    sensitivities = _project(
        [qere, critical, ketiv],
        hebrew_tokens=tokens,
        scope=PassageProjectionScope(
            include_greek_critical_core=True,
            include_hebrew_ketiv=True,
        ),
        greek_tokens=greek_tokens,
    )

    assert [record.passage_id for record in primary] == [qere.passage_id]
    assert len({record.passage_id for record in sensitivities}) == 3
    ketiv_record = next(record for record in sensitivities if record.analysis_reading == "ketiv")
    assert ketiv_record.ketiv_uncertainty
    qere_record = next(
        record
        for record in sensitivities
        if record.analysis_profile == "edition_complete" and record.analysis_reading == "qere"
    )
    assert qere_record.original_text == primary[0].original_text


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing canonical hebrew token_id"),
        ("duplicate_token", "duplicate canonical hebrew token_id"),
        ("duplicate_passage", "duplicate M5 passage_id"),
        ("scope_collision", "duplicate M5 verse scope key"),
        ("sequence", "lemma_sequence_json length must equal token_count"),
    ],
)
def test_projection_fails_exactly_on_broken_identity_or_alignment(
    mutation: str,
    message: str,
) -> None:
    token_id = "HB_GEN_001_001_0001"
    passage = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="qere",
        book="GEN",
        reference="GEN 1:1",
        token_id=token_id,
    )
    passage_rows: list[PassageRow | dict[str, object]] = [passage]
    token_rows = [_hebrew_token(token_id)]
    if mutation == "missing":
        token_rows = []
    elif mutation == "duplicate_token":
        token_rows = [*token_rows, dict(token_rows[0])]
    elif mutation == "duplicate_passage":
        passage_rows.append(passage)
    elif mutation == "scope_collision":
        second_token_id = "HB_GEN_001_001_0002"
        passage_rows.append(
            _passage(
                corpus="hebrew",
                profile="edition_complete",
                reading="qere",
                book="GEN",
                reference="GEN 1:1",
                token_id=second_token_id,
            )
        )
        token_rows.append(_hebrew_token(second_token_id))
    else:
        invalid = passage.model_dump(mode="python")
        invalid["lemma_sequence_json"] = "[]"
        passage_rows = [invalid]

    with pytest.raises(PassageProjectionError, match=message):
        _project(passage_rows, hebrew_tokens=token_rows, greek_tokens=[])


def test_jsonl_round_trip_is_atomic_authenticated_and_duplicate_safe(tmp_path: Path) -> None:
    token_id = "HB_GEN_001_001_0001"
    passage = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="qere",
        book="GEN",
        reference="GEN 1:1",
        token_id=token_id,
    )
    record = _project(
        [passage],
        hebrew_tokens=[_hebrew_token(token_id)],
        greek_tokens=[],
    )[0]
    output = tmp_path / "passages.jsonl"

    receipt = write_passage_records_jsonl([record], output)

    assert receipt.row_count == 1
    assert receipt.sha256 == sha256_file(output)
    assert list(read_passage_records_jsonl(output, expected_sha256=receipt.sha256)) == [record]
    with pytest.raises(PassageProjectionError, match="refusing to overwrite"):
        write_passage_records_jsonl([record], output)
    with pytest.raises(PassageProjectionError, match="duplicate PassageRecord"):
        write_passage_records_jsonl([record, record], tmp_path / "duplicate.jsonl")
    assert not (tmp_path / "duplicate.jsonl").exists()


def _write_hash_manifest(directory: Path, hashes: dict[str, str]) -> None:
    (directory / "table-hashes.json").write_text(
        json.dumps({"parquet_sha256": hashes}),
        encoding="utf-8",
    )


def test_parquet_projection_authenticates_each_source(tmp_path: Path) -> None:
    token_id = "HB_GEN_001_001_0001"
    passage = _passage(
        corpus="hebrew",
        profile="edition_complete",
        reading="qere",
        book="GEN",
        reference="GEN 1:1",
        token_id=token_id,
    )
    passage_root = tmp_path / "m5"
    relative_leaf = Path(
        "passages/corpus=hebrew/analysis_profile=edition_complete/"
        "analysis_reading=qere/granularity=verse/book=GEN/part-00000.parquet"
    )
    leaf = passage_root / relative_leaf
    leaf.parent.mkdir(parents=True)
    pl.DataFrame(
        [passage.model_dump(mode="python")],
        schema=PASSAGE_POLARS_SCHEMA,
        orient="row",
    ).select(PASSAGE_COLUMNS).write_parquet(leaf)
    _write_hash_manifest(passage_root, {relative_leaf.as_posix(): sha256_file(leaf)})

    hebrew_dir = tmp_path / "hebrew"
    greek_dir = tmp_path / "greek"
    hebrew_dir.mkdir()
    greek_dir.mkdir()
    hebrew_path = hebrew_dir / "tokens.parquet"
    greek_path = greek_dir / "tokens.parquet"
    pl.DataFrame([_hebrew_token(token_id)]).write_parquet(hebrew_path)
    pl.DataFrame([_greek_token("GNT_MAT_001_001_0001")]).write_parquet(greek_path)
    _write_hash_manifest(hebrew_dir, {"tokens.parquet": sha256_file(hebrew_path)})
    _write_hash_manifest(greek_dir, {"tokens.parquet": sha256_file(greek_path)})
    sources = PassageParquetSources(
        passage_root=passage_root,
        hebrew_tokens_path=hebrew_path,
        greek_tokens_path=greek_path,
        benchmark_config_path=Path("config/benchmark.yaml"),
    )

    records = list(iter_passage_records_from_parquet(sources))

    assert [record.passage_id for record in records] == [passage.passage_id]
    broken = json.loads((hebrew_dir / "table-hashes.json").read_text(encoding="utf-8"))
    broken["parquet_sha256"]["tokens.parquet"] = hashlib.sha256(b"wrong").hexdigest()
    (hebrew_dir / "table-hashes.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(PassageProjectionError, match="Parquet SHA-256 mismatch"):
        list(iter_passage_records_from_parquet(sources))
