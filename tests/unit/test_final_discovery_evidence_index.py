from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from echoes.final_discovery.evidence_index import (
    EvidenceIndexError,
    EvidenceOffsetLookup,
    build_evidence_offset_index,
    read_evidence_offset_index_receipt,
)
from echoes.final_discovery.features import candidate_pair_id, evidence_id
from echoes.final_discovery.models import EvidenceRow, FinalCandidate, QualityFlags
from echoes.final_discovery.storage import (
    StreamArtifactReceipt,
    sha256_file,
    write_jsonl_atomic,
    write_jsonl_stream_atomic,
)


def _evidence(
    left: str,
    right: str,
    detector_id: str,
    family: str,
    independence_group: str,
    *,
    source_hash: str,
) -> EvidenceRow:
    pair_id = candidate_pair_id(left, right)
    return EvidenceRow.model_validate(
        {
            "evidence_id": evidence_id(pair_id, detector_id, source_hash),
            "candidate_pair_id": pair_id,
            "passage_a_id": min(left, right),
            "passage_b_id": max(left, right),
            "detector_id": detector_id,
            "family": family,
            "independence_group": independence_group,
            "raw_score": 0.8,
            "normalized_score": 0.75,
            "normalization_method": "fixture-percentile",
            "empirical_p_value": 0.05,
            "null_method": "fixture-null",
            "contains_english_derived_evidence": False,
            "original_language_evidence_remains": True,
            "counts_for_independence": True,
            "trace_json": json.dumps(
                {"detector": detector_id, "pair": pair_id},
                sort_keys=True,
                separators=(",", ":"),
            ),
            "source_artifact_id": f"fixture-{detector_id}",
            "source_artifact_sha256": source_hash,
        }
    )


def _fixture_rows() -> tuple[EvidenceRow, ...]:
    rows = (
        _evidence(
            "passage-a",
            "passage-b",
            "predicate-argument",
            "grammar_syntax",
            "grammar-syntax",
            source_hash="a" * 64,
        ),
        _evidence(
            "passage-a",
            "passage-b",
            "semantic-original",
            "semantic",
            "semantic-original",
            source_hash="b" * 64,
        ),
        _evidence(
            "passage-c",
            "passage-d",
            "event-sequence",
            "structure_narrative",
            "structure-narrative",
            source_hash="c" * 64,
        ),
    )
    return tuple(sorted(rows, key=lambda row: (row.candidate_pair_id, row.detector_id)))


def _write_source(path: Path, rows: tuple[EvidenceRow, ...]) -> StreamArtifactReceipt:
    return write_jsonl_stream_atomic(
        path,
        rows,
        order_key=lambda row: (row.candidate_pair_id, row.detector_id),
    )


def _candidate(rows: tuple[EvidenceRow, ...]) -> FinalCandidate:
    first = rows[0]
    return FinalCandidate(
        candidate_pair_id=first.candidate_pair_id,
        passage_a_id=first.passage_a_id,
        passage_b_id=first.passage_b_id,
        passage_a_reference="Fixture A",
        passage_b_reference="Fixture B",
        ensemble_score=0.7,
        empirical_p_value=0.1,
        bh_q_value=0.2,
        empirical_fdr=0.3,
        knownness_status="unknown",
        known_relationship_ids=(),
        quality=QualityFlags(
            disputed_passage=False,
            reference_gap=False,
            ketiv_uncertainty=False,
            formulaic_language=False,
            overlapping_passages=False,
            unresolved_data_error=False,
            invalid_trace=False,
        ),
        evidence_ids=tuple(sorted(row.evidence_id for row in rows)),
        detector_ids=tuple(sorted(row.detector_id for row in rows)),
        families=tuple(sorted({row.family for row in rows})),
        qualifying_independence_groups=tuple(sorted({row.independence_group for row in rows})),
        original_language_independence_groups=tuple(
            sorted({row.independence_group for row in rows})
        ),
        contains_english_derived_evidence=False,
        score_without_english=0.7,
        english_ablation_empirical_p_value=0.1,
        english_ablation_bh_q_value=0.2,
        english_ablation_empirical_fdr=0.3,
        english_ablation_survives=True,
        tier_a_eligible=False,
        tier_a_exclusion_reasons=("fixture_not_statistically_eligible",),
        tier_b_rank=None,
        output_label="retained_excluded",
    )


def test_offset_index_lookup_is_exact_compact_and_candidate_aware(tmp_path: Path) -> None:
    rows = _fixture_rows()
    source = tmp_path / "evidence.jsonl"
    source_receipt = _write_source(source, rows)
    index = tmp_path / "evidence-index.sqlite3"

    receipt = build_evidence_offset_index(
        source,
        index,
        expected_source_sha256=source_receipt.sha256,
        expected_evidence_row_count=3,
        expected_maximum_rows_per_pair=2,
    )

    assert read_evidence_offset_index_receipt(index) == receipt
    assert receipt.evidence_row_count == 3
    assert receipt.candidate_pair_count == 2
    assert receipt.maximum_rows_per_pair == 2
    assert receipt.payload_bytes_copied_into_index == 0
    connection = sqlite3.connect(index)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        offsets = connection.execute(
            "SELECT candidate_pair_id,start_offset,byte_length,row_count "
            "FROM pair_offsets ORDER BY candidate_pair_id"
        ).fetchall()
    finally:
        connection.close()
    assert tables == {"index_metadata", "pair_offsets"}
    assert len(offsets) == 2
    assert sum(int(row[2]) for row in offsets) == source.stat().st_size
    assert sorted(int(row[3]) for row in offsets) == [1, 2]

    pair_id = next(
        pair_id
        for pair_id in {row.candidate_pair_id for row in rows}
        if sum(row.candidate_pair_id == pair_id for row in rows) == 2
    )
    pair_rows = tuple(row for row in rows if row.candidate_pair_id == pair_id)
    lookup = EvidenceOffsetLookup(index, source)
    with pytest.raises(EvidenceIndexError, match="not open"):
        lookup(pair_id)
    with lookup:
        assert lookup.receipt == receipt
        assert lookup(pair_id) == pair_rows
        assert lookup(_candidate(pair_rows)) == pair_rows
        with pytest.raises(EvidenceIndexError, match="absent"):
            lookup("FDPAIR~" + "0" * 64)
        stale = _candidate(pair_rows).model_copy(
            update={"evidence_ids": (pair_rows[0].evidence_id,)}
        )
        with pytest.raises(EvidenceIndexError, match=r"disagree.*exactly"):
            lookup(stale)
    with pytest.raises(EvidenceIndexError, match="not open"):
        lookup(pair_id)


@pytest.mark.parametrize(
    ("row_delta", "sha256", "maximum", "match"),
    (
        (1, None, 2, "has 3 rows; expected 4"),
        (0, "0" * 64, 2, "SHA-256"),
        (0, None, 3, "maximum rows per pair is 2; expected 3"),
    ),
)
def test_offset_index_rejects_authenticated_population_mismatches(
    tmp_path: Path,
    row_delta: int,
    sha256: str | None,
    maximum: int,
    match: str,
) -> None:
    rows = _fixture_rows()
    source = tmp_path / "evidence.jsonl"
    source_receipt = _write_source(source, rows)
    index = tmp_path / "evidence-index.sqlite3"

    with pytest.raises(EvidenceIndexError, match=match):
        build_evidence_offset_index(
            source,
            index,
            expected_source_sha256=sha256 or source_receipt.sha256,
            expected_evidence_row_count=len(rows) + row_delta,
            expected_maximum_rows_per_pair=maximum,
        )
    assert not index.exists()
    assert not tuple(tmp_path.glob(".evidence-index.sqlite3.*"))


def test_offset_index_rejects_order_duplicates_identities_and_noncanonical_rows(
    tmp_path: Path,
) -> None:
    rows = _fixture_rows()

    out_of_order = tmp_path / "out-of-order.jsonl"
    write_jsonl_atomic(out_of_order, tuple(reversed(rows)), sort_key=None)
    with pytest.raises(EvidenceIndexError, match="strictly ordered"):
        build_evidence_offset_index(
            out_of_order,
            tmp_path / "out-of-order.sqlite3",
            expected_source_sha256=sha256_file(out_of_order),
            expected_evidence_row_count=3,
            expected_maximum_rows_per_pair=2,
        )

    duplicate_detector = rows[0].model_copy(
        update={
            "evidence_id": evidence_id(
                rows[0].candidate_pair_id,
                rows[0].detector_id,
                "d" * 64,
            ),
            "source_artifact_sha256": "d" * 64,
        }
    )
    duplicate_key = tmp_path / "duplicate-key.jsonl"
    write_jsonl_atomic(duplicate_key, (rows[0], duplicate_detector), sort_key=None)
    with pytest.raises(EvidenceIndexError, match="strictly ordered"):
        build_evidence_offset_index(
            duplicate_key,
            tmp_path / "duplicate-key.sqlite3",
            expected_source_sha256=sha256_file(duplicate_key),
            expected_evidence_row_count=2,
            expected_maximum_rows_per_pair=2,
        )

    later_pair = next(row for row in rows if row.candidate_pair_id != rows[0].candidate_pair_id)
    duplicate_evidence = later_pair.model_copy(update={"evidence_id": rows[0].evidence_id})
    duplicate_id = tmp_path / "duplicate-evidence-id.jsonl"
    write_jsonl_atomic(duplicate_id, (rows[0], duplicate_evidence), sort_key=None)
    with pytest.raises(EvidenceIndexError, match="duplicate evidence_id"):
        build_evidence_offset_index(
            duplicate_id,
            tmp_path / "duplicate-evidence-id.sqlite3",
            expected_source_sha256=sha256_file(duplicate_id),
            expected_evidence_row_count=2,
            expected_maximum_rows_per_pair=1,
        )

    wrong_pair = rows[0].model_copy(update={"candidate_pair_id": "FDPAIR~" + "f" * 64})
    wrong_identity = tmp_path / "wrong-pair.jsonl"
    write_jsonl_atomic(wrong_identity, (wrong_pair,), sort_key=None)
    with pytest.raises(EvidenceIndexError, match="candidate_pair_id identity"):
        build_evidence_offset_index(
            wrong_identity,
            tmp_path / "wrong-pair.sqlite3",
            expected_source_sha256=sha256_file(wrong_identity),
            expected_evidence_row_count=1,
            expected_maximum_rows_per_pair=1,
        )

    noncanonical = tmp_path / "noncanonical.jsonl"
    noncanonical.write_text(
        json.dumps(rows[0].model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="ascii",
        newline="",
    )
    with pytest.raises(EvidenceIndexError, match="noncanonical"):
        build_evidence_offset_index(
            noncanonical,
            tmp_path / "noncanonical.sqlite3",
            expected_source_sha256=sha256_file(noncanonical),
            expected_evidence_row_count=1,
            expected_maximum_rows_per_pair=1,
        )


def test_offset_index_and_lookup_fail_closed_on_existing_target_and_tampering(
    tmp_path: Path,
) -> None:
    rows = _fixture_rows()
    source = tmp_path / "evidence.jsonl"
    source_receipt = _write_source(source, rows)
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"preserve-me")
    with pytest.raises(EvidenceIndexError, match="refusing to replace"):
        build_evidence_offset_index(
            source,
            existing,
            expected_source_sha256=source_receipt.sha256,
            expected_evidence_row_count=3,
            expected_maximum_rows_per_pair=2,
        )
    assert existing.read_bytes() == b"preserve-me"

    index = tmp_path / "evidence-index.sqlite3"
    build_evidence_offset_index(
        source,
        index,
        expected_source_sha256=source_receipt.sha256,
        expected_evidence_row_count=3,
        expected_maximum_rows_per_pair=2,
    )
    source.write_bytes(source.read_bytes() + b"tampered")
    with (
        pytest.raises(EvidenceIndexError, match="source identity"),
        EvidenceOffsetLookup(index, source),
    ):
        pass


def test_lookup_revalidates_tampered_offset_rows(tmp_path: Path) -> None:
    rows = _fixture_rows()
    source = tmp_path / "evidence.jsonl"
    source_receipt = _write_source(source, rows)
    index = tmp_path / "evidence-index.sqlite3"
    build_evidence_offset_index(
        source,
        index,
        expected_source_sha256=source_receipt.sha256,
        expected_evidence_row_count=3,
        expected_maximum_rows_per_pair=2,
    )
    pair_id = rows[0].candidate_pair_id
    connection = sqlite3.connect(index)
    try:
        connection.execute(
            "UPDATE pair_offsets SET start_offset=start_offset+1 WHERE candidate_pair_id=?",
            (pair_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with (
        EvidenceOffsetLookup(index, source) as lookup,
        pytest.raises(EvidenceIndexError, match=r"invalid EvidenceRow|line-aligned"),
    ):
        lookup(pair_id)
