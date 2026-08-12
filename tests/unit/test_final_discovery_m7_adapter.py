"""Authenticated M7 reuse adapter regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.m7_adapter import (
    M7AdapterError,
    M7HydratedEvidenceLookup,
    authenticate_m7_input,
    build_m7_hydration_index,
    build_m7_lexical_projection,
    hydrate_m7_shared_evidence,
    iter_m7_raw_evidence,
)
from echoes.final_discovery.models import EvidenceRow
from echoes.lexical.models import LEXICAL_ARTIFACT_NAMES
from echoes.lexical.validation import shared_evidence_digest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hydration_fixture(tmp_path: Path, *, count: int) -> tuple[Path, tuple[EvidenceRow, ...]]:
    root = tmp_path / "hydration-schema-v1"
    pairs = root / "candidate_pairs"
    shared = root / "shared_evidence"
    pairs.mkdir(parents=True)
    shared.mkdir(parents=True)
    pair_rows: list[dict[str, object]] = []
    shared_rows: list[dict[str, object]] = []
    logical_hashes = {
        name: hashlib.sha256(name.encode()).hexdigest()
        for name in ("candidate_pairs", "candidate_evidence", "shared_evidence")
    }
    table_counts = {
        "candidate_pairs": count,
        "candidate_evidence": count,
        "shared_evidence": count,
    }
    manifest_path = root / "table-hashes.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_counts": table_counts,
                "table_logical_sha256": logical_hashes,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    manifest_sha256 = _sha256(manifest_path)
    evidence_rows: list[EvidenceRow] = []
    for index in range(count):
        source_pair_id = f"M7PAIR-{index:04d}"
        passage_a_id = f"a-{index:04d}"
        passage_b_id = f"b-{index:04d}"
        shared_evidence_id = f"M7EVID-{index:04d}"
        pair_rows.append(
            {
                "candidate_pair_id": source_pair_id,
                "passage_a_id": passage_a_id,
                "passage_b_id": passage_b_id,
            }
        )
        shared_row = {
            "evidence_id": shared_evidence_id,
            "candidate_pair_id": source_pair_id,
            "evidence_family": "lemma",
            "feature_id": f"LF-{index:04d}",
            "feature_value": f"value-{index:04d}",
            "passage_a_positions_json": "[1]",
            "passage_b_positions_json": "[2]",
            "corpus_frequency": 2,
            "document_frequency": 2,
            "passage_a_local_frequency": 1,
            "passage_b_local_frequency": 1,
            "association_score": 0.5,
            "pmi": None,
            "log_likelihood": None,
            "frequency_control": None,
            "score_formula": "inverse_corpus_frequency_evidence_weight",
            "detector_contributions_json": '{"rare_lemma_root":0.5}',
            "independence_expected_count": 0.25,
            "contains_primary_rare_item": True,
            "counts_as_independent_co_signal": False,
            "english_derived": False,
            "thread_controls_json": "{}",
            "acceptance_status": "retained",
            "notes": "bounded hydration fixture",
        }
        shared_rows.append(shared_row)
        trace = {
            "representation": "canonical_m7_reciprocal_rank_fusion",
            "m7_candidate_pair_id": source_pair_id,
            "m7_projection_audit_counts": table_counts,
            "m7_shared_evidence_locator": {
                "artifact": "canonical_m7_shared_evidence",
                "candidate_pair_id": source_pair_id,
                "selection_key": "candidate_pair_id",
                "source_manifest_sha256": manifest_sha256,
                "source_table_logical_sha256": logical_hashes["shared_evidence"],
            },
            "m7_shared_evidence_count": 1,
            "m7_shared_evidence_ids": [shared_evidence_id],
            "m7_shared_evidence_digest": shared_evidence_digest([shared_row]),
            "m7_shared_evidence_hydrated": False,
        }
        evidence_rows.append(
            EvidenceRow(
                evidence_id=f"FINAL-EVID-{index:04d}",
                candidate_pair_id=candidate_pair_id(passage_a_id, passage_b_id),
                passage_a_id=passage_a_id,
                passage_b_id=passage_b_id,
                detector_id="m7_lexical_rrf",
                family="lexical",
                independence_group="lexical_m7",
                raw_score=0.5,
                normalized_score=0.5,
                normalization_method="fixture",
                empirical_p_value=0.5,
                null_method="fixture",
                contains_english_derived_evidence=False,
                original_language_evidence_remains=True,
                counts_for_independence=True,
                trace_json=canonical_json(trace),
                source_artifact_id="m7-canonical-schema-v1",
                source_artifact_sha256=manifest_sha256,
            )
        )
    pl.DataFrame(pair_rows).write_parquet(pairs / "part-00000.parquet")
    pl.DataFrame(shared_rows).write_parquet(shared / "part-00000.parquet")
    return root, tuple(evidence_rows)


def test_authenticate_m7_input_checks_manifest_inventory_and_each_file(tmp_path: Path) -> None:
    root = tmp_path / "schema-v1"
    part = root / "candidate_pairs" / "part-00000.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"bounded fixture leaf")
    manifest = {
        "schema_version": 1,
        "table_counts": {name: 0 for name in LEXICAL_ARTIFACT_NAMES},
        "table_logical_sha256": {name: "1" * 64 for name in LEXICAL_ARTIFACT_NAMES},
        "table_physical_sha256": {name: "2" * 64 for name in LEXICAL_ARTIFACT_NAMES},
        "file_sha256": {"candidate_pairs/part-00000.parquet": _sha256(part)},
        "artifacts": {},
    }
    manifest_path = root / "table-hashes.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    report = authenticate_m7_input(
        root,
        expected_manifest_sha256=_sha256(manifest_path),
        verify_individual_files=True,
    )
    assert report.file_count == 1
    assert report.verified_file_count == 1

    part.write_bytes(b"tampered")
    with pytest.raises(M7AdapterError, match="hash mismatch"):
        authenticate_m7_input(
            root,
            expected_manifest_sha256=_sha256(manifest_path),
            verify_individual_files=True,
        )


def test_projection_reuses_m7_rrf_and_encodes_infinite_no_threshold_sentinel(
    tmp_path: Path,
) -> None:
    root = tmp_path / "schema-v1"
    pairs = root / "candidate_pairs"
    evidence = root / "candidate_evidence"
    shared = root / "shared_evidence"
    pairs.mkdir(parents=True)
    evidence.mkdir(parents=True)
    shared.mkdir(parents=True)
    pl.DataFrame(
        {
            "candidate_pair_id": ["M7PAIR"],
            "passage_a_id": ["A"],
            "passage_b_id": ["B"],
            "passage_a_reference": ["GEN 1:1"],
            "passage_b_reference": ["EXO 1:1"],
            "known_link_status": ["represented_in_openbible_snapshot"],
            "openbible_relationship_ids_json": ['["REL-1"]'],
            "disputed_passage_flag": [False],
            "reference_gap": [False],
            "ketiv_structural_uncertainty": [False],
            "direct_adjacency": [True],
            "nearby_context": [False],
            "exact_duplicate": [False],
            "near_exact_duplicate": [True],
            "formulaic_evidence_flag": [True],
            "contains_english_derived_evidence": [True],
            "non_english_evidence_remains": [True],
            "score_after_removing_all_english_features": [0.012],
            "english_ablation_survives": [True],
        }
    ).write_parquet(pairs / "part-00000.parquet")
    pl.DataFrame(
        {
            "candidate_pair_id": ["M7PAIR"],
            "raw_rrf_score": [0.031],
            "rrf_score": [0.031],
            "estimated_empirical_fdr": [float("inf")],
            "benjamini_hochberg_q_value": [0.2],
            "both_null_families_present": [False],
            "detector_trace_digest": ["3" * 64],
            "ablation_digest": ["4" * 64],
            "evidence_digest": ["5" * 64],
        }
    ).write_parquet(evidence / "part-00000.parquet")
    pl.DataFrame(
        {
            "evidence_id": ["M7EVID"],
            "candidate_pair_id": ["M7PAIR"],
            "evidence_family": ["lemma"],
            "feature_id": ["LF_say"],
            "feature_value": ["say"],
            "passage_a_positions_json": ["[1]"],
            "passage_b_positions_json": ["[2]"],
            "corpus_frequency": [2],
            "document_frequency": [2],
            "passage_a_local_frequency": [1],
            "passage_b_local_frequency": [1],
            "association_score": [0.5],
            "pmi": [None],
            "log_likelihood": [None],
            "frequency_control": [None],
            "score_formula": ["inverse_corpus_frequency_evidence_weight"],
            "detector_contributions_json": ['{"rare_lemma_root":0.5}'],
            "independence_expected_count": [0.25],
            "contains_primary_rare_item": [True],
            "counts_as_independent_co_signal": [False],
            "english_derived": [False],
            "thread_controls_json": ["{}"],
            "acceptance_status": ["retained"],
            "notes": ["exact fixture evidence"],
        }
    ).write_parquet(shared / "part-00000.parquet")
    table_counts = {name: 0 for name in LEXICAL_ARTIFACT_NAMES}
    table_counts.update({"candidate_pairs": 1, "candidate_evidence": 1, "shared_evidence": 1})
    (root / "table-hashes.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_counts": table_counts,
                "table_logical_sha256": {
                    name: hashlib.sha256(name.encode()).hexdigest()
                    for name in LEXICAL_ARTIFACT_NAMES
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    output = tmp_path / "m7-projection.parquet"
    build_m7_lexical_projection(
        root,
        output,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
    )
    config = load_final_discovery_config()
    registration = next(item for item in config.detectors if item.detector_id == "m7_lexical_rrf")

    row = next(
        iter_m7_raw_evidence(
            output,
            registration=registration,
            source_artifact_sha256=_sha256(root / "table-hashes.json"),
            batch_size=1,
        )
    )
    trace = json.loads(row.trace_json)

    assert row.raw_score == pytest.approx(0.031)
    assert row.english_ablation_raw_score == pytest.approx(0.012)
    assert row.family == "lexical"
    assert row.source_knownness_status == "known_m7_snapshot"
    assert row.source_known_relationship_ids == ("REL-1",)
    assert row.source_quality is not None
    assert row.source_quality.local_context
    assert row.source_quality.exact_or_near_duplicate
    assert row.source_quality.formulaic_language
    assert trace["m7_empirical_fdr"] == "positive_infinity_no_qualified_threshold"
    assert trace["m7_both_null_families_present"] is False
    assert trace["m7_shared_evidence_count"] == 1
    assert trace["m7_shared_evidence_ids"] == ["M7EVID"]
    assert trace["m7_shared_evidence_digest"]
    assert trace["m7_shared_evidence_hydrated"] is False
    assert "m7_shared_evidence" not in trace
    assert trace["m7_projection_audit_counts"] == {
        "candidate_evidence": 1,
        "candidate_pairs": 1,
        "shared_evidence": 1,
    }

    hydrated = hydrate_m7_shared_evidence(
        (row,),
        root,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "hydration-spill",
        batch_size=1,
    )[0]
    hydrated_trace = json.loads(hydrated.trace_json)
    assert hydrated_trace["m7_shared_evidence_hydrated"] is True
    assert hydrated_trace["m7_shared_evidence"][0]["feature_value"] == "say"
    assert hydrated_trace["m7_shared_evidence"][0]["passage_a_positions_json"] == "[1]"

    tampered_projection = tmp_path / "m7-projection-tampered.parquet"
    pl.read_parquet(output).with_columns(
        pl.lit("[]").alias("m7_shared_evidence_ids_json")
    ).write_parquet(tampered_projection)
    with pytest.raises(M7AdapterError, match="IDs disagree"):
        tuple(
            iter_m7_raw_evidence(
                tampered_projection,
                registration=registration,
                source_artifact_sha256=_sha256(root / "table-hashes.json"),
                batch_size=1,
            )
        )

    duplicated = pl.concat(
        [
            pl.read_parquet(evidence / "part-00000.parquet"),
            pl.read_parquet(evidence / "part-00000.parquet"),
        ]
    )
    duplicated.write_parquet(evidence / "part-00000.parquet")
    manifest_path = root / "table-hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["table_counts"]["candidate_evidence"] = 2
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(M7AdapterError, match="one row per candidate ID"):
        build_m7_lexical_projection(
            root,
            tmp_path / "duplicate-projection.parquet",
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "duplicate-spill",
        )


def test_hydration_index_streams_a_large_selection_through_declared_batch_cap(
    tmp_path: Path,
) -> None:
    root, source_rows = _hydration_fixture(tmp_path, count=5)
    requested = tuple(source_rows[index] for index in (3, 0, 4, 1, 2))

    with pytest.raises(M7AdapterError, match="declared batch cap of 2"):
        hydrate_m7_shared_evidence(
            requested,
            root,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "bounded-tuple-spill",
            selection_batch_size=2,
        )

    index_path = tmp_path / "hydrated.sqlite3"
    receipt = build_m7_hydration_index(
        (row for row in requested),
        root,
        index_path,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "streaming-spill",
        selection_batch_size=2,
        batch_size=1,
    )

    assert receipt.row_count == 5
    assert receipt.source_scan_count == 1
    assert receipt.selection_batch_size == 2
    assert receipt.maximum_selection_batch_rows_observed == 2
    assert receipt.arrow_batch_size == 1
    with M7HydratedEvidenceLookup(index_path, receipt) as lookup:
        hydrated = tuple(lookup(row) for row in requested)
        assert lookup.lookup_count == len(requested)

    assert tuple(row.evidence_id for row in hydrated) == tuple(row.evidence_id for row in requested)
    assert tuple(json.loads(row.trace_json)["m7_candidate_pair_id"] for row in hydrated) == tuple(
        json.loads(row.trace_json)["m7_candidate_pair_id"] for row in requested
    )
    for row in hydrated:
        trace = json.loads(row.trace_json)
        assert trace["m7_shared_evidence_hydrated"] is True
        assert trace["m7_shared_evidence_hydration_scope"] == ("explicit_bounded_review_subset")
        assert len(trace["m7_shared_evidence"]) == 1
