"""Regression coverage for final-discovery ordering of M7 projection rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.features import candidate_pair_id
from echoes.final_discovery.m7_adapter import (
    M7AdapterError,
    build_m7_lexical_projection,
    iter_m7_raw_evidence,
)
from echoes.lexical.models import LEXICAL_ARTIFACT_COLUMNS, LEXICAL_ARTIFACT_NAMES


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_ordering_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "schema-v1"
    pairs = root / "candidate_pairs"
    evidence = root / "candidate_evidence"
    shared = root / "shared_evidence"
    pairs.mkdir(parents=True)
    evidence.mkdir(parents=True)
    shared.mkdir(parents=True)

    source_ids = ("M7-A", "M7-B")
    passage_pairs = (("P01A", "P01B"), ("P03A", "P03B"))
    pl.DataFrame(
        {
            "candidate_pair_id": list(source_ids),
            "passage_a_id": [pair[0] for pair in passage_pairs],
            "passage_b_id": [pair[1] for pair in passage_pairs],
            "passage_a_reference": ["GEN 1:1", "GEN 1:3"],
            "passage_b_reference": ["EXO 1:1", "EXO 1:3"],
            "known_link_status": [
                "not_represented_in_openbible_snapshot",
                "not_represented_in_openbible_snapshot",
            ],
            "openbible_relationship_ids_json": ["[]", "[]"],
            "disputed_passage_flag": [False, False],
            "reference_gap": [False, False],
            "ketiv_structural_uncertainty": [False, False],
            "direct_adjacency": [False, False],
            "nearby_context": [False, False],
            "exact_duplicate": [False, False],
            "near_exact_duplicate": [False, False],
            "formulaic_evidence_flag": [False, False],
            "contains_english_derived_evidence": [False, False],
            "non_english_evidence_remains": [True, True],
            "score_after_removing_all_english_features": [0.02, 0.01],
            "english_ablation_survives": [True, True],
        }
    ).write_parquet(pairs / "part-00000.parquet")
    pl.DataFrame(
        {
            "candidate_pair_id": list(source_ids),
            "raw_rrf_score": [0.02, 0.01],
            "rrf_score": [0.02, 0.01],
            "estimated_empirical_fdr": [0.2, 0.1],
            "benjamini_hochberg_q_value": [0.2, 0.1],
            "both_null_families_present": [True, True],
            "detector_trace_digest": ["1" * 64, "2" * 64],
            "ablation_digest": ["3" * 64, "4" * 64],
            "evidence_digest": ["5" * 64, "6" * 64],
        }
    ).write_parquet(evidence / "part-00000.parquet")

    shared_rows: list[dict[str, object]] = []
    for index, source_id in enumerate(source_ids):
        shared_rows.append(
            {
                "evidence_id": f"M7EVID-{index}",
                "candidate_pair_id": source_id,
                "evidence_family": "lemma",
                "feature_id": f"LF-{index}",
                "feature_value": f"value-{index}",
                "passage_a_positions_json": "[0]",
                "passage_b_positions_json": "[0]",
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
                "notes": "final-ID ordering regression fixture",
            }
        )
    assert set(shared_rows[0]) == set(LEXICAL_ARTIFACT_COLUMNS["shared_evidence"])
    pl.DataFrame(shared_rows).write_parquet(shared / "part-00000.parquet")

    table_counts = {name: 0 for name in LEXICAL_ARTIFACT_NAMES}
    table_counts.update(
        {
            "candidate_pairs": 2,
            "candidate_evidence": 2,
            "shared_evidence": 2,
        }
    )
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
    return root


def test_projection_orders_by_transformed_final_candidate_pair_id(tmp_path: Path) -> None:
    root = _write_ordering_fixture(tmp_path)
    output = tmp_path / "m7-projection.parquet"
    build_m7_lexical_projection(
        root,
        output,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
    )
    registration = next(
        item
        for item in load_final_discovery_config().detectors
        if item.detector_id == "m7_lexical_rrf"
    )
    rows = tuple(
        iter_m7_raw_evidence(
            output,
            registration=registration,
            source_artifact_sha256=_sha256(root / "table-hashes.json"),
            batch_size=1,
        )
    )

    expected_final_ids = sorted(
        (
            candidate_pair_id("P01A", "P01B"),
            candidate_pair_id("P03A", "P03B"),
        )
    )
    assert [row.candidate_pair_id for row in rows] == expected_final_ids
    assert [row.passage_a_id for row in rows] == ["P03A", "P01A"]
    assert [json.loads(row.trace_json)["m7_candidate_pair_id"] for row in rows] == [
        "M7-B",
        "M7-A",
    ]
    assert pl.read_parquet(output)["candidate_pair_id"].to_list() == ["M7-B", "M7-A"]

    source_ordered = tmp_path / "source-ordered.parquet"
    pl.read_parquet(output).sort("candidate_pair_id").write_parquet(source_ordered)
    with pytest.raises(M7AdapterError, match="final candidate IDs"):
        tuple(
            iter_m7_raw_evidence(
                source_ordered,
                registration=registration,
                source_artifact_sha256=_sha256(root / "table-hashes.json"),
                batch_size=1,
            )
        )
