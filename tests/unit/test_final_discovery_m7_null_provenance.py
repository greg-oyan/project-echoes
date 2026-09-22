"""Negative M7 calibration is valid only with authenticated source null execution."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.m7_adapter import (
    build_m7_lexical_projection,
    hydrate_m7_shared_evidence,
    iter_m7_raw_evidence,
)
from echoes.final_discovery.m7_null_provenance import (
    M7NullProvenanceError,
    authenticate_m7_null_provenance,
)
from echoes.lexical.config import load_lexical_config
from echoes.lexical.models import LEXICAL_ARTIFACT_SCHEMAS
from echoes.lexical.statistics import calibrate_null_counts
from echoes.lexical.validation import _derived_null_seed, null_replicate_logical_hash

CONFIG = load_lexical_config()
TABLES = (
    "candidate_pairs",
    "candidate_evidence",
    "candidate_detector_scores",
    "null_replicate_summaries",
    "threshold_calibration",
)


def _row(name: str, **values: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for column, dtype in LEXICAL_ARTIFACT_SCHEMAS[name].items():  # type: ignore[index]
        if dtype == pl.String:
            result[column] = "fixture"
        elif dtype == pl.Boolean:
            result[column] = False
        elif dtype in (pl.Float32, pl.Float64):
            result[column] = 0.0
        else:
            result[column] = 0
    result.update(values)
    return result


def _write(root: Path, name: str, rows: list[dict[str, object]]) -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema=LEXICAL_ARTIFACT_SCHEMAS[name]).write_parquet(  # type: ignore[index]
        directory / "part-00000.parquet"
    )


def _seal(root: Path) -> str:
    counts = {name: pl.read_parquet(root / name / "part-00000.parquet").height for name in TABLES}
    counts["shared_evidence"] = 0
    manifest = {
        "schema_version": 1,
        "table_counts": counts,
        "table_logical_sha256": {
            name: hashlib.sha256(name.encode()).hexdigest() for name in counts
        },
        "file_sha256": {
            leaf.relative_to(root).as_posix(): hashlib.sha256(leaf.read_bytes()).hexdigest()
            for leaf in root.rglob("*.parquet")
        },
    }
    path = root / "table-hashes.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, qualified: bool = False) -> tuple[Path, str, dict[str, Any]]:
    root = tmp_path / "m7"
    observed = 10000 if qualified else 100
    null_count = 1 if qualified else 1000
    _write(
        root,
        "candidate_pairs",
        [
            _row(
                "candidate_pairs",
                candidate_pair_id="M7PAIR",
                passage_a_id="A",
                passage_b_id="B",
                passage_a_reference="GEN 1:1",
                passage_b_reference="EXO 1:1",
                corpus_pair="hb_hb",
                analysis_profile="edition_complete",
                review_eligible=qualified,
            )
        ],
    )
    _write(
        root,
        "candidate_detector_scores",
        [
            _row(
                "candidate_detector_scores",
                candidate_pair_id="M7PAIR",
                detector="rrf_composite",
                representation_id="REP",
            )
        ],
    )
    selected_threshold = CONFIG.candidate_thresholds.rrf_score_grid[0] if qualified else 1.0
    fdr = null_count / observed if qualified else math.inf
    _write(
        root,
        "candidate_evidence",
        [
            _row(
                "candidate_evidence",
                candidate_pair_id="M7PAIR",
                raw_rrf_score=0.03,
                rrf_score=0.03,
                estimated_empirical_fdr=fdr,
                benjamini_hochberg_q_value=0.2,
                both_null_families_present=qualified,
                selected_score_threshold=selected_threshold,
                null_model_empirical_rate=(null_count / 20000 if qualified else math.inf),
                calibration_selection_scope="frozen_corpus_pair_rrf_threshold",
                detector_trace_digest="1" * 64,
                evidence_digest="2" * 64,
                ablation_digest="3" * 64,
            )
        ],
    )
    null_rows = []
    for family in ("within_book_reassignment", "frequency_preserving_synthetic"):
        base_seed = (
            CONFIG.null_models.within_book_reassignment.seed
            if family == "within_book_reassignment"
            else CONFIG.null_models.frequency_preserving_synthetic.seed
        )
        for iteration in range(1, 101):
            conditioning = {
                "passage_count_preserved": True,
                "passage_lengths_preserved": True,
                "conditioning_labels_preserved": True,
                "representation_isolation_preserved": True,
                "label_or_order_shuffle": False,
                "candidate_sample_size": CONFIG.null_models.calibration_pair_sample_size,
                "calibration_pair_scope": CONFIG.null_models.calibration_pair_scope,
                "global_all_pairs_claim_allowed": False,
                "exact_feature_totals_preserved": True,
                "no_original_sequences_copied": True,
                "conditioning_scope": "book_then_genre_when_sparse",
                "minimum_book_token_count": CONFIG.null_models.synthetic_minimum_book_token_count,
                "frequency_deviation_count": 1,
                "maximum_absolute_frequency_deviation": 1.0,
                "mean_absolute_frequency_deviation": 0.1,
            }
            for threshold in CONFIG.candidate_thresholds.rrf_score_grid:
                row = _row(
                    "null_replicate_summaries",
                    null_run_id=f"{family}-{iteration}",
                    null_family=family,
                    iteration=iteration,
                    seed=_derived_null_seed(base_seed, "hb_hb|REP", family, iteration),
                    corpus_pair="hb_hb",
                    representation_id="REP",
                    detector="rrf_composite",
                    threshold_id=f"T{threshold}",
                    candidate_count=null_count,
                    score_quantiles_json=json.dumps({"q025": 0.1, "q50": 0.2, "q975": 0.3}),
                    conditioning_json=json.dumps(conditioning),
                    passage_count=100,
                    token_count=1000,
                    length_digest="a" * 64,
                    frequency_digest="b" * 64,
                )
                row["logical_output_hash"] = null_replicate_logical_hash(row)
                null_rows.append(row)
    _write(root, "null_replicate_summaries", null_rows)
    thresholds = []
    for threshold in CONFIG.candidate_thresholds.rrf_score_grid:
        calibration = calibrate_null_counts(threshold, observed, [null_count] * 200)
        selected = qualified and threshold == selected_threshold
        thresholds.append(
            _row(
                "threshold_calibration",
                threshold_id=f"T{threshold}",
                corpus_pair="hb_hb",
                representation_id="REP",
                detector="rrf_composite",
                score_threshold=threshold,
                observed_candidate_count=observed,
                mean_null_candidate_count=calibration.null_mean_count,
                null_interval_low=calibration.null_interval_low,
                null_interval_high=calibration.null_interval_high,
                observed_to_null_enrichment=calibration.enrichment,
                empirical_tail_probability=calibration.empirical_upper_tail_probability,
                estimated_empirical_fdr=calibration.raw_empirical_fdr,
                eligible_candidate_count=observed,
                threshold_selection_scope=CONFIG.null_models.calibration_pair_scope,
                qualifies_empirical_fdr=qualified,
                selected=selected,
                frozen_before_test=True,
                selection_reason=(
                    "lowest_registered_threshold_qualifying_both_null_families"
                    if selected
                    else "qualifies_but_not_lowest_selected_threshold"
                    if qualified
                    else "exceeds_maximum_empirical_fdr_in_at_least_one_null_family"
                ),
            )
        )
    _write(root, "threshold_calibration", thresholds)
    digest = _seal(root)
    manifest = json.loads((root / "table-hashes.json").read_text())
    projection_names = ("candidate_pairs", "candidate_evidence", "shared_evidence")
    trace = {
        "representation": "canonical_m7_reciprocal_rank_fusion",
        "m7_source_manifest_sha256": digest,
        "m7_source_table_logical_sha256": {
            name: manifest["table_logical_sha256"][name] for name in projection_names
        },
        "m7_projection_audit_counts": {
            name: manifest["table_counts"][name] for name in projection_names
        },
        "m7_candidate_pair_id": "M7PAIR",
        "m7_passage_references": {"A": "GEN 1:1", "B": "EXO 1:1"},
        "raw_rrf_score": 0.03,
        "rrf_score": 0.03,
        "m7_empirical_fdr": fdr if qualified else "positive_infinity_no_qualified_threshold",
        "m7_bh_q_value": 0.2,
        "m7_both_null_families_present": qualified,
        "m7_detector_trace_digest": "1" * 64,
        "m7_evidence_digest": "2" * 64,
        "m7_ablation_digest": "3" * 64,
    }
    return root, digest, trace


@pytest.mark.parametrize("qualified", [False, True])
def test_authenticates_execution_without_relabeling_threshold_outcome(
    tmp_path: Path, qualified: bool
) -> None:
    root, digest, trace = _fixture(tmp_path, qualified=qualified)
    context = authenticate_m7_null_provenance(
        root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
    )
    context.validate_trace(trace, digest)
    assert trace["m7_both_null_families_present"] is qualified
    assert context.receipt["no_qualified_threshold_candidate_count"] == int(not qualified)
    assert context.receipt["iterations_per_family"] == 100
    detached_receipt = context.receipt
    detached_receipt["source_null_execution_authenticated"] = False
    assert context.receipt["source_null_execution_authenticated"] is True
    assert len(context.provenance_sha256) == 64


@pytest.mark.parametrize(
    "name,replacement",
    [
        ("m7_candidate_pair_id", "OTHER"),
        ("m7_evidence_digest", "4" * 64),
        ("m7_both_null_families_present", True),
        ("m7_both_null_families_present", 0),
        ("m7_empirical_fdr", 0.0),
        ("rrf_score", 0.99),
        ("raw_rrf_score", 0.99),
        ("m7_bh_q_value", 0.0),
        ("m7_passage_references", {"C": "GEN 1:1", "D": "EXO 1:1"}),
        ("m7_source_manifest_sha256", "0" * 64),
        ("m7_source_table_logical_sha256", {}),
        ("m7_projection_audit_counts", {}),
    ],
)
def test_rejects_trace_not_bound_to_exact_source_candidate(
    tmp_path: Path, name: str, replacement: object
) -> None:
    root, digest, trace = _fixture(tmp_path)
    context = authenticate_m7_null_provenance(
        root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
    )
    trace[name] = replacement
    with pytest.raises(M7NullProvenanceError):
        context.validate_trace(trace, digest)


@pytest.mark.parametrize(
    "defect",
    [
        "missing_family",
        "missing_iteration",
        "wrong_stratum",
        "selected_threshold",
        "candidate_sentinel",
        "missing_rrf",
        "duplicate_candidate",
        "candidate_review_eligible",
        "extra_null_threshold",
        "duplicate_null_replicate",
    ],
)
def test_source_null_or_candidate_inconsistency_fails_closed(tmp_path: Path, defect: str) -> None:
    root, _, _ = _fixture(tmp_path)
    if defect in {
        "missing_family",
        "missing_iteration",
        "wrong_stratum",
        "extra_null_threshold",
        "duplicate_null_replicate",
    }:
        name = "null_replicate_summaries"
        frame = pl.read_parquet(root / name / "part-00000.parquet")
        if defect == "missing_family":
            frame = frame.filter(pl.col("null_family") == "within_book_reassignment")
        elif defect == "missing_iteration":
            frame = frame.filter(pl.col("iteration") != 100)
        elif defect == "wrong_stratum":
            frame = frame.with_columns(pl.lit("other").alias("representation_id"))
        elif defect == "extra_null_threshold":
            extra = frame.filter(pl.col("threshold_id") == "T0.02").with_columns(
                pl.lit("ORPHAN-THRESHOLD").alias("threshold_id")
            )
            frame = pl.concat([frame, extra])
        else:
            frame = pl.concat([frame, frame.head(1)])
    elif defect == "selected_threshold":
        name = "threshold_calibration"
        frame = pl.read_parquet(root / name / "part-00000.parquet").with_columns(
            pl.lit(True).alias("selected")
        )
    elif defect == "candidate_sentinel":
        name = "candidate_evidence"
        frame = pl.read_parquet(root / name / "part-00000.parquet").with_columns(
            pl.lit(0.9).alias("selected_score_threshold")
        )
    elif defect == "missing_rrf":
        name = "candidate_detector_scores"
        frame = pl.read_parquet(root / name / "part-00000.parquet").with_columns(
            pl.lit("bm25").alias("detector")
        )
    elif defect == "candidate_review_eligible":
        name = "candidate_pairs"
        frame = pl.read_parquet(root / name / "part-00000.parquet").with_columns(
            pl.lit(True).alias("review_eligible")
        )
    else:
        name = "candidate_pairs"
        frame = pl.read_parquet(root / name / "part-00000.parquet")
        frame = pl.concat([frame, frame])
    frame.write_parquet(root / name / "part-00000.parquet")
    digest = _seal(root)
    with pytest.raises(M7NullProvenanceError):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
        )


def test_manifest_and_physical_file_hashes_are_required(tmp_path: Path) -> None:
    root, digest, _ = _fixture(tmp_path)
    with pytest.raises(M7NullProvenanceError, match="manifest SHA-256"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256="0" * 64, temp_directory=tmp_path / "spill"
        )
    leaf = root / "candidate_evidence" / "part-00000.parquet"
    with leaf.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(M7NullProvenanceError, match="file hash mismatch"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
        )


def test_missing_candidate_membership_cannot_hide_behind_matching_counts(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    name = "candidate_evidence"
    frame = pl.read_parquet(root / name / "part-00000.parquet").with_columns(
        pl.lit("ORPHAN").alias("candidate_pair_id")
    )
    frame.write_parquet(root / name / "part-00000.parquet")
    digest = _seal(root)
    with pytest.raises(M7NullProvenanceError, match="membership"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
        )


def test_exact_schema_and_leaf_inventory_are_required(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    leaf = root / "candidate_evidence" / "part-00000.parquet"
    pl.read_parquet(leaf).drop("both_null_families_present").write_parquet(leaf)
    digest = _seal(root)
    with pytest.raises(M7NullProvenanceError, match="schema mismatch"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
        )
    other = leaf.with_name("part-00001.parquet")
    other.write_bytes(leaf.read_bytes())
    with pytest.raises(M7NullProvenanceError, match="inventory mismatch"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
        )


def test_authentication_never_writes_inside_source_tree(tmp_path: Path) -> None:
    root, digest, _ = _fixture(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    with pytest.raises(M7NullProvenanceError, match="outside the source tree"):
        authenticate_m7_null_provenance(
            root, expected_manifest_sha256=digest, temp_directory=root / "spill"
        )
    authenticate_m7_null_provenance(
        root, expected_manifest_sha256=digest, temp_directory=tmp_path / "spill"
    )
    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == before


def test_unchanged_adapter_and_hydration_preserve_authenticated_negative_outcome(
    tmp_path: Path,
) -> None:
    root, _, _ = _fixture(tmp_path)
    pairs = root / "candidate_pairs" / "part-00000.parquet"
    pl.read_parquet(pairs).with_columns(
        pl.lit("not_represented_in_openbible_snapshot").alias("known_link_status"),
        pl.lit("[]").alias("openbible_relationship_ids_json"),
        pl.lit(True).alias("non_english_evidence_remains"),
        pl.lit(True).alias("english_ablation_survives"),
    ).write_parquet(pairs)
    _write(root, "shared_evidence", [])
    digest = _seal(root)
    context = authenticate_m7_null_provenance(
        root, expected_manifest_sha256=digest, temp_directory=tmp_path / "audit-spill"
    )
    projection = build_m7_lexical_projection(
        root,
        tmp_path / "projection.parquet",
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "projection-spill",
    )
    registration = next(
        item
        for item in load_final_discovery_config().detectors
        if item.detector_id == "m7_lexical_rrf"
    )
    raw = next(
        iter_m7_raw_evidence(projection, registration=registration, source_artifact_sha256=digest)
    )
    trace = json.loads(raw.trace_json)
    assert trace["m7_both_null_families_present"] is False
    context.validate_trace(trace, raw.source_artifact_sha256)
    hydrated = hydrate_m7_shared_evidence(
        (raw,),
        root,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "hydrate-spill",
    )[0]
    hydrated_trace = json.loads(hydrated.trace_json)
    assert hydrated_trace["m7_shared_evidence_hydrated"] is True
    assert hydrated_trace["m7_both_null_families_present"] is False
    context.validate_trace(hydrated_trace, hydrated.source_artifact_sha256)
