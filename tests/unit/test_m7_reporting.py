"""Contracts for deterministic sanitized Milestone 7 reporting."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from echoes.lexical.config import (
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
)
from echoes.lexical.models import (
    LEXICAL_ARTIFACT_NAMES,
    LEXICAL_ARTIFACT_SCHEMAS,
    LEXICAL_METADATA_SCHEMA,
)
from echoes.lexical.storage import LexicalArtifactWriter
from echoes.reports.lexical_baseline import (
    REPORT_OUTPUT_NAMES,
    LexicalReportError,
    _ablation_summary_table,
    _artifact_scans,
    _csv_text,
    _english_ablation_table,
    _execution_pair_failures,
    _feature_count_table,
    _load_spot_criteria,
    _performance_tables,
    _rare_rule_effects_table,
    _reference_from_passage_id,
    _sensitivity_summary_table,
    compare_lexical_manifests,
    generate_lexical_baseline_reports,
    verify_execution_determinism,
)


def test_spot_check_registry_covers_all_required_structural_categories() -> None:
    criteria = _load_spot_criteria(Path("outputs/reports/m7-spot-check-config.json"))

    assert len(criteria) == 34
    assert {criterion.category for criterion in criteria} == {
        "positive_control",
        "lexical_evidence",
        "guardrail",
    }
    assert len({criterion.check_id for criterion in criteria}) == len(criteria)
    assert all(
        criterion.expected_presence or criterion.unavailable_reason for criterion in criteria
    )


def test_spot_check_registry_rejects_unregistered_predicate_column(tmp_path: Path) -> None:
    source = json.loads(
        Path("outputs/reports/m7-spot-check-config.json").read_text(encoding="utf-8")
    )
    source["criteria"][0]["predicates"][0]["column"] = "biblical_text"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(LexicalReportError, match="unknown column"):
        _load_spot_criteria(path)


def test_feature_count_table_is_aggregate_and_language_scoped() -> None:
    frame = pl.DataFrame(
        {
            "language_namespace": ["hb", "hb", "gk", "en"],
            "feature_family": ["lemma", "lemma", "lemma", "english_gloss"],
            "corpus_frequency": [2, 3, 4, 5],
            "document_frequency": [2, 2, 3, 4],
            "is_rare": [True, True, False, False],
            "is_high_frequency": [False, False, True, True],
            "is_formulaic": [False, False, True, True],
        }
    )

    result = _feature_count_table(frame.lazy())

    assert "feature_value" not in result.columns
    assert result.filter(pl.col("corpus_scope") == "hebrew")["vocabulary_size"].item() == 2
    assert set(result["corpus_scope"]) == {"hebrew", "greek", "english_derived_bridge"}


def test_detector_summary_uses_production_global_sentinels() -> None:
    frame = pl.DataFrame(
        {
            "detector": ["rrf_composite", "rrf_composite"],
            "representation_id": ["r1", "r1"],
            "benchmark_version": ["b1", "b1"],
            "benchmark_tier": [3, 3],
            "label_quality": ["tier3_weak_supervision_recovery"] * 2,
            "analysis_profile": ["edition_complete", "edition_complete"],
            "ranking_name": ["rrf_composite", "rrf_composite"],
            "ranking_role": ["system", "system"],
            "comparison_baseline": ["none", "none"],
            "comparison_count": [0, 0],
            "stratum_dimension": ["global", "mapping_status"],
            "stratum_value": ["all", "mapped_provisional"],
            "mapping_status": ["all_eligible", "mapped_provisional"],
            "corpus_pair": ["hb_hb", "hb_hb"],
            "split_strategy": ["held_out_genre", "held_out_genre"],
            "partition": ["test", "test"],
            "vote_stratum": ["all_votes", "26+"],
            "metric": ["recall_at_20", "recall_at_20"],
            "k": [20, 20],
            "value": [0.5, 0.6],
            "bootstrap_interval_low": [0.4, 0.5],
            "bootstrap_interval_high": [0.6, 0.7],
            "bootstrap_iterations": [100, 100],
            "bootstrap_seed": [1, 1],
            "eligible_query_count": [100, 25],
            "eligible_relationship_count": [120, 30],
            "excluded_count": [0, 0],
            "exclusion_reasons_json": ["{}", "{}"],
            "config_hash": ["a" * 64, "a" * 64],
            "preregistration_hash": ["b" * 64, "b" * 64],
            "frozen_before_test": [True, True],
            "notes": ["", ""],
        }
    )

    summary, by_stratum = _performance_tables(frame.lazy())

    assert by_stratum.height == 2
    assert summary.height == 1
    assert summary["mapping_status"].item() == "all_eligible"
    assert summary["vote_stratum"].item() == "all_votes"


def _candidate_frame(*, bridge_survives: bool = False) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "candidate_pair_id": ["candidate-a", "candidate-b"],
            "corpus_pair": ["hb_hb", "hb_gnt_english_bridge"],
            "shared_rare_lemma_count": [1, 0],
            "shared_rare_root_count": [0, 0],
            "rare_rule_passed": [False, True],
            "review_eligible": [False, False],
            "independent_co_signal_count": [0, 0],
            "formulaic_penalty": [0.5, 0.0],
            "local_context_penalty": [0.0, 0.0],
            "short_passage_penalty": [0.0, 0.0],
            "rrf_score": [0.1, 0.2],
            "contains_english_derived_evidence": [False, True],
            "english_ablation_survives": [False, bridge_survives],
            "passage_a_gloss_feature_count": [0, 3],
            "passage_b_gloss_feature_count": [0, 4],
            "passage_a_gloss_coverage": [0.0, 0.75],
            "passage_b_gloss_coverage": [0.0, 0.8],
            "gloss_overlap_count": [0, 2],
            "score_with_english_features": [0.0, 0.2],
            "score_after_removing_all_english_features": [0.0, 0.1 if bridge_survives else 0.0],
            "rank_with_english_features": [None, 1],
            "rank_after_removing_all_english_features": [None, 2 if bridge_survives else None],
            "non_english_evidence_remains": [False, bridge_survives],
            "classification_after_english_ablation": [
                "not_applicable",
                "surviving_non_english_evidence"
                if bridge_survives
                else "english_mediated_retrieval_lead_only",
            ],
        }
    )


def test_rare_rule_report_retains_failed_material_rare_evidence() -> None:
    result = _rare_rule_effects_table(_candidate_frame())
    failed = result.filter(pl.col("rare_evidence_material") & ~pl.col("rare_rule_passed"))

    assert failed["candidate_count"].item() == 1
    assert failed["minimum_co_signal_count"].item() == 0


def test_english_ablation_uses_persisted_scores_and_never_fabricates_rank() -> None:
    result = _english_ablation_table(_candidate_frame())

    assert result.height == 1
    assert result["score_with_english_features"].item() == 0.2
    assert result["score_after_removing_all_english_features"].item() == 0.0
    assert result["rank_after_removing_all_english_features"].item() is None
    assert result["non_english_evidence_remains"].item() is False


def test_english_ablation_can_report_persisted_non_english_survival() -> None:
    result = _english_ablation_table(_candidate_frame(bridge_survives=True))

    assert result["score_after_removing_all_english_features"].item() == 0.1
    assert result["rank_after_removing_all_english_features"].item() == 2
    assert result["english_ablation_survives"].item() is True


def test_ablation_summary_retains_named_subject_and_changed_counts() -> None:
    frame = pl.DataFrame(
        {
            "ablation_name": ["remove_tfidf", "remove_tfidf"],
            "subject_type": ["candidate_pair", "candidate_pair"],
            "corpus_pair": ["hb_hb", "hb_hb"],
            "changed": [True, False],
            "score_before": [0.2, 0.1],
            "score_after": [0.1, 0.1],
            "rank_before": [1, 2],
            "rank_after": [2, 2],
            "review_eligible_before": [True, False],
            "review_eligible_after": [False, False],
            "downgrade_required": [True, False],
            "evidence_digest": ["a" * 64, "b" * 64],
        }
    )

    result = _ablation_summary_table(frame.lazy())

    assert result["result_count"].item() == 2
    assert result["changed_count"].item() == 1
    assert result["rank_changed_count"].item() == 1


def test_sensitivity_summary_separates_comparable_and_excluded_rows() -> None:
    frame = pl.DataFrame(
        {
            "sensitivity_type": ["hebrew_qere_ketiv"] * 2,
            "corpus_pair": ["hb_hb"] * 2,
            "detector": ["rrf_composite"] * 2,
            "direction": ["forward"] * 2,
            "baseline_profile": ["edition_complete"] * 2,
            "comparison_profile": ["edition_complete"] * 2,
            "baseline_reading": ["qere"] * 2,
            "comparison_reading": ["ketiv"] * 2,
            "excluded_reason": [None, "missing_reference_join"],
            "affected_locus_count": [1, 1],
            "score_delta": [0.1, None],
            "rank_delta": [1, None],
            "top_k_overlap": [0.8, None],
            "baseline_sequence_digest": ["a" * 64, "b" * 64],
            "comparison_sequence_digest": ["c" * 64, "d" * 64],
        }
    )

    result = _sensitivity_summary_table(frame.lazy())

    assert result["result_count"].item() == 2
    assert result["comparable_result_count"].item() == 1
    assert result["excluded_result_count"].item() == 1


def _manifest(digest: str) -> dict[str, object]:
    return {
        "table_counts": {name: 1 for name in LEXICAL_ARTIFACT_NAMES},
        "table_logical_sha256": {name: digest * 64 for name in LEXICAL_ARTIFACT_NAMES},
        "table_physical_sha256": {name: digest * 64 for name in LEXICAL_ARTIFACT_NAMES},
    }


def _write_manifest_root(
    parent: Path,
    name: str,
    manifest: dict[str, object],
    *,
    run_id: str = "lexical-test-run",
) -> tuple[Path, dict[str, object]]:
    root = parent / name
    root.mkdir()
    path = root / "table-hashes.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = {
        "experiment_run_id": run_id,
        "runtime_seconds": 1.0,
        "stage_runtime_seconds_json": '{"fixture":1.0}',
        "peak_memory_bytes": 1024,
        "storage_footprint_bytes": 2048,
    }
    metadata_root = root / "lexical_metadata"
    metadata_root.mkdir()
    pl.DataFrame([metadata]).write_parquet(metadata_root / "part-00000.parquet")
    return path, metadata


def test_two_run_report_evidence_requires_all_logical_hashes(tmp_path: Path) -> None:
    first = _manifest("a")
    current = _manifest("a")
    path, _ = _write_manifest_root(tmp_path, "first", first)
    current_path, current_metadata = _write_manifest_root(tmp_path, "current", current)

    passed = compare_lexical_manifests(
        current,
        path,
        current_manifest_path=current_path,
        current_metadata=current_metadata,
        first_run_strict_validation_passed=True,
    )
    current_logical = current["table_logical_sha256"]
    assert isinstance(current_logical, dict)
    current_logical["candidate_pairs"] = "b" * 64
    current_path.write_text(json.dumps(current), encoding="utf-8")
    failed = compare_lexical_manifests(
        current,
        path,
        current_manifest_path=current_path,
        current_metadata=current_metadata,
        first_run_strict_validation_passed=True,
    )

    assert passed.status == "passed"
    assert failed.status == "failed"
    assert failed.differing_logical_tables == ("candidate_pairs",)


def test_two_run_report_evidence_rejects_count_differences(tmp_path: Path) -> None:
    first = _manifest("a")
    current = _manifest("a")
    current_counts = current["table_counts"]
    assert isinstance(current_counts, dict)
    current_counts["candidate_pairs"] = 2
    first_path, _ = _write_manifest_root(tmp_path, "first", first)
    current_path, current_metadata = _write_manifest_root(tmp_path, "current", current)

    result = compare_lexical_manifests(
        current,
        first_path,
        current_manifest_path=current_path,
        current_metadata=current_metadata,
        first_run_strict_validation_passed=True,
    )

    assert result.status == "failed"
    assert result.table_counts_match is False
    assert result.differing_count_tables == ("candidate_pairs",)


def test_two_run_report_evidence_rejects_self_comparison(tmp_path: Path) -> None:
    current = _manifest("a")
    path, current_metadata = _write_manifest_root(tmp_path, "current", current)

    with pytest.raises(LexicalReportError, match="distinct artifact root"):
        compare_lexical_manifests(
            current,
            path,
            current_manifest_path=path,
            current_metadata=current_metadata,
            first_run_strict_validation_passed=True,
        )


def test_two_run_report_evidence_rejects_noncanonical_alias(tmp_path: Path) -> None:
    first = _manifest("a")
    current = _manifest("a")
    first_path, _ = _write_manifest_root(tmp_path, "first", first)
    current_path, current_metadata = _write_manifest_root(tmp_path, "current", current)
    alias = first_path.with_name("alias.json")
    shutil.copyfile(first_path, alias)

    with pytest.raises(LexicalReportError, match=r"canonical table-hashes\.json"):
        compare_lexical_manifests(
            current,
            alias,
            current_manifest_path=current_path,
            current_metadata=current_metadata,
            first_run_strict_validation_passed=True,
        )


def test_two_run_report_evidence_requires_both_run_ids(tmp_path: Path) -> None:
    first = _manifest("a")
    current = _manifest("a")
    first_path, _ = _write_manifest_root(tmp_path, "first", first)
    current_path, _ = _write_manifest_root(tmp_path, "current", current)

    result = compare_lexical_manifests(
        current,
        first_path,
        current_manifest_path=current_path,
        first_run_strict_validation_passed=True,
    )

    assert result.status == "failed"
    assert result.run_ids_match is False


def test_two_run_report_evidence_rejects_mismatched_run_ids(tmp_path: Path) -> None:
    first = _manifest("a")
    current = _manifest("a")
    first_path, _ = _write_manifest_root(tmp_path, "first", first, run_id="run-first")
    current_path, current_metadata = _write_manifest_root(
        tmp_path,
        "current",
        current,
        run_id="run-second",
    )

    result = compare_lexical_manifests(
        current,
        first_path,
        current_manifest_path=current_path,
        current_metadata=current_metadata,
        first_run_strict_validation_passed=True,
    )

    assert result.status == "failed"
    assert result.run_ids_match is False


def test_missing_first_run_manifest_is_not_determinism_evidence(tmp_path: Path) -> None:
    result = compare_lexical_manifests(
        _manifest("a"),
        tmp_path / "absent.json",
        current_manifest_path=tmp_path / "current.json",
    )

    assert result.status == "not_verified"
    assert result.logical_hashes_match is False


def test_execution_evidence_requires_distinct_recovered_then_fresh_attempts() -> None:
    shared = {
        name: f"shared-{name}"
        for name in (
            "git_commit",
            "source_tree_hash",
            "python_version",
            "runtime_versions",
            "dependency_lock_hash",
            "config_hash",
            "configuration_files",
            "configuration_hashes",
            "dataset_manifest_path",
            "dataset_manifest_hash",
            "source_file_hashes",
            "dataset_versions",
            "random_seed",
            "random_seeds",
            "model_names",
            "model_versions",
            "model_status",
            "input_table_hashes",
            "exact_candidate_generation_method",
            "training_data_lineage",
            "evaluation_split_lineage",
            "human_review_history",
            "artifact_output_directory",
            "reproduction_command",
        )
    }
    timestamp = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    first = SimpleNamespace(
        execution_id="execution-first",
        timestamp=timestamp,
        run_id="lexical-run",
        resume_lineage=SimpleNamespace(
            status="validated_and_reused",
            recovered_composite=True,
        ),
        **shared,
    )
    second = SimpleNamespace(
        execution_id="execution-second",
        timestamp=timestamp + timedelta(seconds=1),
        run_id="lexical-run",
        resume_lineage=SimpleNamespace(
            status="not_requested",
            recovered_composite=False,
        ),
        **shared,
    )

    assert (
        _execution_pair_failures(  # type: ignore[arg-type]
            first,
            second,
            expected_run_id="lexical-run",
        )
        == []
    )

    second.source_tree_hash = "different"
    failures = _execution_pair_failures(  # type: ignore[arg-type]
        first,
        second,
        expected_run_id="lexical-run",
    )
    assert failures == ["governed execution inputs differ: source_tree_hash"]


def test_execution_evidence_without_exact_ids_is_not_verified(tmp_path: Path) -> None:
    result = verify_execution_determinism(
        project_root=tmp_path,
        manifest_root=tmp_path / "data/processed/lexical/execution-manifests",
        run_id="lexical-run",
        first_execution_id=None,
        second_execution_id=None,
        first_artifact_root=None,
        second_artifact_root=tmp_path / "data/processed/lexical/schema-v1",
    )

    assert result.status == "not_verified"
    assert result.failures == ("both exact successful execution IDs are required",)


def test_missing_artifact_set_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "lexical" / "schema-v1"
    root.mkdir(parents=True)

    with pytest.raises(LexicalReportError, match="artifact set is unavailable"):
        _artifact_scans(root)


def test_safe_verse_reference_is_derived_from_readable_passage_id() -> None:
    passage_id = (
        "P_HB_EDITION_COMPLETE_QERE_VERSE_GEN_001_002~"
        "a2bb544b87e7926cfe23d24875e240bb39e41a5f5ca3121df3e10d98fbb62e42"
    )

    assert _reference_from_passage_id(passage_id) == "GEN 1:2"
    assert _reference_from_passage_id("opaque") == "reference_unavailable_from_identifier"


def test_csv_renderer_rejects_nonfinite_values() -> None:
    with pytest.raises(LexicalReportError, match="non-finite"):
        _csv_text(pl.DataFrame({"safe_metric": [float("inf")]}))


def test_output_inventory_is_exact_and_contains_no_publication_or_review_output() -> None:
    assert len(REPORT_OUTPUT_NAMES) == 10
    assert "m7-unreviewed-candidate-queue.csv" in REPORT_OUTPUT_NAMES
    assert all("review-decision" not in name for name in REPORT_OUTPUT_NAMES)
    assert all("publication" not in name for name in REPORT_OUTPUT_NAMES)


def _empty_governed_artifact_set(root: Path) -> None:
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        for name in LEXICAL_ARTIFACT_NAMES:
            if name != "lexical_metadata":
                writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, physical = writer.content_hashes()
        metadata = pl.DataFrame(
            [
                {
                    "experiment_run_id": "synthetic-empty-m7-report-run",
                    "experiment_version": config.experiment_version,
                    "lexical_schema_version": 1,
                    "candidate_pair_schema_version": 1,
                    "configuration_hash": lexical_config_sha256(config),
                    "preregistration_hash": lexical_preregistration_sha256(preregistration),
                    "input_corpus_hashes_json": json.dumps(
                        {
                            "identity": {
                                "hebrew": preregistration.inputs.hebrew.identity_sha256,
                                "greek": preregistration.inputs.greek.identity_sha256,
                            },
                            "content": {
                                "hebrew": preregistration.inputs.hebrew.content_sha256,
                                "greek": preregistration.inputs.greek.content_sha256,
                            },
                            "analytical": {
                                "hebrew": preregistration.inputs.hebrew.analytical_sha256,
                                "greek": preregistration.inputs.greek.analytical_sha256,
                            },
                            "oshb": preregistration.inputs.oshb_supplement_hashes,
                        },
                        sort_keys=True,
                    ),
                    "passage_hashes_json": json.dumps(
                        preregistration.inputs.passages.logical_hashes, sort_keys=True
                    ),
                    "benchmark_hashes_json": json.dumps(
                        preregistration.inputs.benchmark.logical_hashes, sort_keys=True
                    ),
                    "feature_vocabulary_hashes_json": "{}",
                    "sparse_index_hashes_json": "{}",
                    "table_logical_hashes_json": json.dumps(logical, sort_keys=True),
                    "table_physical_hashes_json": json.dumps(physical, sort_keys=True),
                    "ranking_count": 0,
                    "candidate_count": 0,
                    "null_iteration_count": 0,
                    "evaluation_count": 0,
                    "runtime_seconds": 0.0,
                    "stage_runtime_seconds_json": '{"fixture":0.0}',
                    "peak_memory_bytes": 0,
                    "storage_footprint_bytes": 0,
                    "numerical_environment_json": "{}",
                    "thread_controls_json": "{}",
                    "acceptance_status": "scientifically_incomplete_synthetic_fixture",
                    "notes": "synthetic report fixture",
                }
            ],
            schema=LEXICAL_METADATA_SCHEMA,
            orient="row",
        )
        writer.finalize(metadata)


def test_complete_empty_bundle_is_reported_fail_closed_and_blocks_m8(tmp_path: Path) -> None:
    root = tmp_path / "lexical" / "schema-v1"
    _empty_governed_artifact_set(root)
    first_root = tmp_path / "lexical" / "first-run"
    shutil.copytree(root, first_root)
    first_manifest = first_root / "table-hashes.json"
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    (report_directory / "m7-lexical-feature-audit.md").write_text(
        "# Milestone 7 lexical-feature and feasibility audit\n\nSynthetic aggregate audit.\n",
        encoding="utf-8",
    )

    artifacts = generate_lexical_baseline_reports(
        artifact_root=root,
        output_directory=report_directory,
        comparison_manifest=first_manifest,
    )

    report = (report_directory / "milestone-7-lexical-baseline-report.md").read_text(
        encoding="utf-8"
    )
    assert artifacts.determinism.status == "failed"
    assert artifacts.determinism.independent_roots is True
    assert artifacts.determinism.first_run_strict_validation_passed is False
    assert artifacts.execution_determinism.status == "not_verified"
    assert artifacts.acceptance_gate_passed is False
    assert len(artifacts.paths) == 11
    assert "**Milestone 8 is blocked.**" in report
    assert "## Exact recommended Milestone 8 task" not in report
