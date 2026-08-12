"""Scale-safe detector calibration equivalence and failure-safety tests."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel

from echoes.final_discovery.anomaly import PairFamilyScores, anomaly_evidence
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.disk_calibration import (
    DiskCalibrationError,
    PairStratum,
    calibrate_anomaly_evidence_disk_backed,
    calibrate_detector_evidence_disk_backed,
    project_anomaly_pair_scores_disk_backed,
)
from echoes.final_discovery.ensemble import calibrate_detector_evidence
from echoes.final_discovery.features import candidate_pair_id, empirical_percentile
from echoes.final_discovery.models import (
    EvidenceFamily,
    EvidenceRow,
    PassageRecord,
    QualityFlags,
    RawEvidence,
)
from echoes.final_discovery.nulls import (
    DetectorNullCalibrationRow,
    production_detector_calibration,
)
from echoes.final_discovery.storage import (
    FinalDiscoveryStorageError,
    read_jsonl,
    sha256_file,
    write_jsonl_atomic,
    write_jsonl_stream_atomic,
)

CONFIG = load_final_discovery_config()
TEST_CONFIG = CONFIG.model_copy(
    update={"calibration": CONFIG.calibration.model_copy(update={"production_iterations": 100})}
)
REGISTRATIONS = {item.detector_id: item for item in TEST_CONFIG.detectors}
SOURCE_HASH = "d" * 64


def _candidate_order(row: BaseModel) -> tuple[str, ...]:
    return (str(row.model_dump()["candidate_pair_id"]),)


def _raw(
    detector_id: str,
    left: str,
    right: str,
    score: float,
    *,
    ablated_score: float | None = None,
    m7_nulls_present: bool = True,
    formulaic_control: bool = False,
) -> RawEvidence:
    registration = REGISTRATIONS[detector_id]
    trace = (
        {"m7_both_null_families_present": m7_nulls_present, "selected": [left, right]}
        if detector_id == "m7_lexical_rrf"
        else {"detector": detector_id, "selected": [left, right]}
    )
    return RawEvidence(
        candidate_pair_id=candidate_pair_id(left, right),
        passage_a_id=min(left, right),
        passage_b_id=max(left, right),
        detector_id=detector_id,
        family=registration.family,
        independence_group=registration.independence_group,
        raw_score=score,
        contains_english_derived_evidence=registration.contains_english_derived_evidence,
        english_ablation_raw_score=ablated_score,
        original_language_evidence_remains=True,
        counts_for_independence=registration.counts_for_independence,
        trace_json=json.dumps(trace, sort_keys=True),
        source_artifact_id=f"fixture-{detector_id}",
        source_artifact_sha256=SOURCE_HASH,
        source_quality=(
            QualityFlags(
                disputed_passage=False,
                reference_gap=False,
                ketiv_uncertainty=False,
                formulaic_language=True,
                overlapping_passages=False,
                unresolved_data_error=False,
                invalid_trace=False,
            )
            if formulaic_control
            else None
        ),
    )


def _write_raw(path: Path, rows: list[RawEvidence]) -> None:
    write_jsonl_atomic(path, rows, sort_key="candidate_pair_id")


def _passage(
    passage_id: str,
    *,
    corpus: str,
    book: str,
    genre: str,
    token_count: int,
    formulaic: bool = False,
) -> PassageRecord:
    values = tuple(f"v-{index}" for index in range(token_count))
    return PassageRecord(
        passage_id=passage_id,
        reference=passage_id,
        corpus=corpus,  # type: ignore[arg-type]
        book=book,
        genre=genre,
        analysis_profile="edition_complete",
        analysis_reading="qere" if corpus == "hebrew" else "source",
        granularity="verse",
        token_count=token_count,
        original_text="text",
        normalized_text="text",
        lemma_sequence=values,
        root_sequence=values,
        pos_sequence=values,
        morphology_sequence=values,
        semantic_domains=values,
        entities=values,
        participants=values,
        frames=values,
        formulaic_language=formulaic,
        source_digest="a" * 64,
    )


def _assert_preserved_failure_state(
    output_directory: Path,
    temp_directory: Path,
    *,
    workspace_prefix: str,
    database_name: str,
) -> None:
    assert not output_directory.exists()
    staging_directories = tuple(output_directory.parent.glob(f".{output_directory.name}.*.tmp"))
    assert len(staging_directories) == 1
    staging = staging_directories[0]
    run_id = staging.name.removeprefix(f".{output_directory.name}.").removesuffix(".tmp")
    assert len(run_id) == 32
    int(run_id, 16)

    workspace = temp_directory / f"{workspace_prefix}-{run_id}.work"
    assert workspace.is_dir()
    assert (workspace / database_name).is_file()
    assert (workspace / "spill").is_dir()


def test_disk_calibration_is_bit_exact_for_nulls_and_evidence_with_ties(
    tmp_path: Path,
) -> None:
    pairs = (
        ("A", "B", "books-1"),
        ("C", "D", "books-1"),
        ("E", "F", "books-2"),
        ("G", "H", "books-2"),
    )
    detectors = (
        "m7_lexical_rrf",
        "lemma_root_sequence_semantic",
        "semantic_domain_overlap",
        "stratified_representation_anomaly",
    )
    scores = (0.5, 0.5, 0.2, 0.9)
    rows = [
        _raw(
            detector_id,
            left,
            right,
            scores[index],
            ablated_score=(0.1 if detector_id == "m7_lexical_rrf" and index == 0 else None),
        )
        for detector_id in detectors
        for index, (left, right, _) in enumerate(pairs)
    ]
    first_path = tmp_path / "stage-3" / "raw-evidence.jsonl"
    second_path = tmp_path / "stage-4-6" / "raw-evidence.jsonl"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    _write_raw(first_path, rows[::2])
    _write_raw(second_path, rows[1::2])
    strata = {candidate_pair_id(left, right): stratum for left, right, stratum in pairs}

    in_memory = production_detector_calibration(
        rows,
        strata,
        config=TEST_CONFIG,
        iterations=TEST_CONFIG.calibration.production_iterations,
    )
    expected_evidence = calibrate_detector_evidence(
        rows,
        config=TEST_CONFIG,
        calibration=in_memory,
    )
    result = calibrate_detector_evidence_disk_backed(
        (first_path, second_path),
        tuple(
            PairStratum(candidate_pair_id=pair_id, stratum=stratum)
            for pair_id, stratum in sorted(strata.items())
        ),
        tmp_path / "calibration",
        config=TEST_CONFIG,
        iterations=TEST_CONFIG.calibration.production_iterations,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
        threads=2,
        batch_size=2,
    )

    observed_evidence = read_jsonl(result.evidence_path, EvidenceRow)
    observed_nulls = read_jsonl(result.detector_null_path, DetectorNullCalibrationRow)
    assert {(row.detector_id, row.candidate_pair_id): row for row in observed_evidence} == {
        (row.detector_id, row.candidate_pair_id): row for row in expected_evidence
    }
    assert {(row.detector_id, row.candidate_pair_id): row for row in observed_nulls} == {
        (row.detector_id, row.candidate_pair_id): row for row in in_memory.rows()
    }
    assert [(row.candidate_pair_id, row.detector_id) for row in observed_evidence] == sorted(
        (row.candidate_pair_id, row.detector_id) for row in observed_evidence
    )
    assert [(row.candidate_pair_id, row.detector_id) for row in observed_nulls] == sorted(
        (row.candidate_pair_id, row.detector_id) for row in observed_nulls
    )
    assert result.receipt.raw_evidence_row_count == len(rows)
    assert result.receipt.candidate_pair_count == len(pairs)
    assert result.receipt.detector_count == len(detectors)
    assert result.receipt.detector_stratum_count == len(detectors) * 2
    provenance = json.loads(result.provenance_path.read_text(encoding="ascii"))
    assert provenance["reference_score_arrays_persisted"] is False
    assert "reference_scores_by_detector_and_stratum" not in provenance
    assert not tuple((tmp_path / "spill").iterdir())


def test_disk_calibration_preserves_failure_state_for_duplicate_detector_pair(
    tmp_path: Path,
) -> None:
    row = _raw("semantic_domain_overlap", "A", "B", 0.7)
    paths = (tmp_path / "one.jsonl", tmp_path / "two.jsonl")
    for path in paths:
        _write_raw(path, [row])
    output = tmp_path / "calibration"

    with pytest.raises(DiskCalibrationError, match="one score per detector/pair"):
        calibrate_detector_evidence_disk_backed(
            paths,
            {row.candidate_pair_id: "one-stratum"},
            output,
            config=TEST_CONFIG,
            iterations=TEST_CONFIG.calibration.production_iterations,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
            batch_size=1,
        )

    _assert_preserved_failure_state(
        output,
        tmp_path / "spill",
        workspace_prefix="disk-calibration",
        database_name="disk-calibration.duckdb",
    )


@pytest.mark.parametrize("include_missing,include_extra", [(True, False), (False, True)])
def test_disk_calibration_requires_exact_pair_strata_coverage(
    tmp_path: Path,
    *,
    include_missing: bool,
    include_extra: bool,
) -> None:
    rows = [
        _raw("semantic_domain_overlap", "A", "B", 0.7),
        _raw("semantic_domain_overlap", "C", "D", 0.3),
    ]
    path = tmp_path / "raw.jsonl"
    _write_raw(path, rows)
    strata = {rows[0].candidate_pair_id: "one-stratum"}
    if not include_missing:
        strata[rows[1].candidate_pair_id] = "one-stratum"
    if include_extra:
        strata[candidate_pair_id("E", "F")] = "one-stratum"

    with pytest.raises(DiskCalibrationError, match="exact raw-evidence pair population"):
        calibrate_detector_evidence_disk_backed(
            (path,),
            strata,
            tmp_path / "calibration",
            config=TEST_CONFIG,
            iterations=TEST_CONFIG.calibration.production_iterations,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
        )


def test_disk_calibration_rejects_bad_m7_trace_and_registered_lineage(tmp_path: Path) -> None:
    bad_m7 = _raw("m7_lexical_rrf", "A", "B", 0.7, m7_nulls_present=False)
    path = tmp_path / "m7.jsonl"
    _write_raw(path, [bad_m7])
    with pytest.raises(DiskCalibrationError, match="both canonical M7 null families"):
        calibrate_detector_evidence_disk_backed(
            (path,),
            {bad_m7.candidate_pair_id: "one-stratum"},
            tmp_path / "bad-m7",
            config=TEST_CONFIG,
            iterations=TEST_CONFIG.calibration.production_iterations,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
        )

    valid = _raw("semantic_domain_overlap", "C", "D", 0.4)
    malformed = valid.model_copy(update={"independence_group": "wrong-lineage"})
    malformed_path = tmp_path / "lineage.jsonl"
    _write_raw(malformed_path, [malformed])
    with pytest.raises(DiskCalibrationError, match="lineage disagrees"):
        calibrate_detector_evidence_disk_backed(
            (malformed_path,),
            {valid.candidate_pair_id: "one-stratum"},
            tmp_path / "bad-lineage",
            config=TEST_CONFIG,
            iterations=TEST_CONFIG.calibration.production_iterations,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
        )


def test_stream_writer_is_interruption_safe_and_never_replaces(tmp_path: Path) -> None:
    first = _raw("semantic_domain_overlap", "A", "B", 0.7)
    second = _raw("semantic_domain_overlap", "C", "D", 0.3)
    target = tmp_path / "stream.jsonl"

    def interrupted() -> Iterator[RawEvidence]:
        yield first
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        write_jsonl_stream_atomic(
            target,
            interrupted(),
            order_key=_candidate_order,
        )
    assert not target.exists()
    assert not tuple(tmp_path.glob(".stream.jsonl.*.tmp"))

    receipt = write_jsonl_stream_atomic(
        target,
        iter(sorted((first, second), key=lambda row: row.candidate_pair_id)),
        order_key=_candidate_order,
    )
    original_hash = sha256_file(target)
    assert receipt.sha256 == original_hash
    with pytest.raises(FinalDiscoveryStorageError, match="refusing to replace"):
        write_jsonl_stream_atomic(
            target,
            (first,),
            order_key=_candidate_order,
        )
    assert sha256_file(target) == original_hash


def test_disk_calibration_never_replaces_a_completed_bundle(tmp_path: Path) -> None:
    row = _raw("semantic_domain_overlap", "A", "B", 0.7)
    path = tmp_path / "raw.jsonl"
    _write_raw(path, [row])
    output = tmp_path / "calibration"
    result = calibrate_detector_evidence_disk_backed(
        (path,),
        {row.candidate_pair_id: "one-stratum"},
        output,
        config=TEST_CONFIG,
        iterations=TEST_CONFIG.calibration.production_iterations,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
    )
    original_receipt_hash = sha256_file(result.receipt_path)

    with pytest.raises(DiskCalibrationError, match="refuses to replace"):
        calibrate_detector_evidence_disk_backed(
            (path,),
            {row.candidate_pair_id: "one-stratum"},
            output,
            config=TEST_CONFIG,
            iterations=TEST_CONFIG.calibration.production_iterations,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
        )
    assert sha256_file(result.receipt_path) == original_receipt_hash


def test_disk_anomaly_pair_projection_matches_stage_six_oracle(tmp_path: Path) -> None:
    rows = [
        _raw("m7_lexical_rrf", "A", "B", 0.8),
        _raw("semantic_domain_overlap", "A", "B", 0.7),
        _raw("grammar_sequence_alignment", "A", "B", 0.6, formulaic_control=True),
        _raw("m7_lexical_rrf", "C", "D", 0.8),
        _raw("semantic_domain_overlap", "C", "D", 0.2),
        _raw("m7_lexical_rrf", "E", "F", 0.1),
    ]
    paths = (tmp_path / "stage-3.jsonl", tmp_path / "stage-4.jsonl")
    _write_raw(paths[0], rows[::2])
    _write_raw(paths[1], rows[1::2])
    references: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        references[row.detector_id].append(row.raw_score)
    grouped: dict[str, list[RawEvidence]] = defaultdict(list)
    for row in rows:
        grouped[row.candidate_pair_id].append(row)
    expected: list[PairFamilyScores] = []
    for pair_id, pair_rows in sorted(grouped.items()):
        family_scores: dict[EvidenceFamily, float] = {}
        for row in pair_rows:
            normalized = empirical_percentile(row.raw_score, references[row.detector_id])
            family_scores[row.family] = max(family_scores.get(row.family, 0.0), normalized)
        if len(family_scores) < 2:
            continue
        first = pair_rows[0]
        expected.append(
            PairFamilyScores(
                candidate_pair_id=pair_id,
                passage_a_id=first.passage_a_id,
                passage_b_id=first.passage_b_id,
                family_scores=family_scores,
                formulaic_control=any(
                    row.source_quality is not None and row.source_quality.formulaic_language
                    for row in pair_rows
                ),
            )
        )

    result = project_anomaly_pair_scores_disk_backed(
        paths,
        tmp_path / "anomaly-inputs",
        config=TEST_CONFIG,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
        threads=2,
        batch_size=2,
    )

    assert read_jsonl(result.pair_family_scores_path, PairFamilyScores) == tuple(expected)
    assert result.receipt.raw_evidence_row_count == len(rows)
    assert result.receipt.eligible_pair_count == len(expected)
    assert not tuple((tmp_path / "spill").iterdir())


def test_disk_anomaly_pair_projection_preserves_failure_state(tmp_path: Path) -> None:
    row = _raw("semantic_domain_overlap", "A", "B", 0.7)
    paths = (tmp_path / "projection-one.jsonl", tmp_path / "projection-two.jsonl")
    for path in paths:
        _write_raw(path, [row])
    output = tmp_path / "anomaly-inputs"
    temp_directory = tmp_path / "spill"

    with pytest.raises(DiskCalibrationError, match="one score per detector/pair"):
        project_anomaly_pair_scores_disk_backed(
            paths,
            output,
            config=TEST_CONFIG,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=temp_directory,
            batch_size=1,
        )

    _assert_preserved_failure_state(
        output,
        temp_directory,
        workspace_prefix="anomaly-pair-projection",
        database_name="anomaly-pair-projection.duckdb",
    )


def test_disk_robust_anomaly_is_model_dump_exact_across_strata_and_ties(
    tmp_path: Path,
) -> None:
    random_source = random.Random(9113)
    passages: dict[str, PassageRecord] = {}
    observations: list[PairFamilyScores] = []
    randomized_ties = tuple(random_source.choice((0.05, 0.15, 0.15, 0.25, 0.35)) for _ in range(12))
    groups = (
        ("zero", "hebrew", "Genesis", "Exodus", "narrative", 10, 10, (0.2, 0.2, 0.2, 0.4)),
        (
            "mad",
            "hebrew",
            "Psalms",
            "Isaiah",
            "poetry",
            10,
            15,
            (0.05, 0.15, 0.35, 0.45, 0.15),
        ),
        ("cross", "greek", "Matthew", "Romans", "discourse", 8, 8, (0.25, 0.25)),
        (
            "random",
            "hebrew",
            "Job",
            "Proverbs",
            "wisdom",
            12,
            13,
            randomized_ties,
        ),
    )
    observation_index = 0
    for label, corpus, left_book, right_book, genre, left_count, right_count, deviations in groups:
        for index, deviation in enumerate(deviations):
            left_id = f"{label}-{index:02d}-a"
            right_id = f"{label}-{index:02d}-b"
            passages[left_id] = _passage(
                left_id,
                corpus=corpus,
                book=left_book,
                genre=genre,
                token_count=left_count,
                formulaic=(observation_index == 2),
            )
            passages[right_id] = _passage(
                right_id,
                corpus=corpus,
                book=right_book,
                genre=genre,
                token_count=right_count,
            )
            score_items = [
                ("lexical", 0.5 - deviation),
                ("semantic", 0.5 + deviation),
            ]
            random_source.shuffle(score_items)
            observations.append(
                PairFamilyScores(
                    candidate_pair_id=candidate_pair_id(left_id, right_id),
                    passage_a_id=left_id,
                    passage_b_id=right_id,
                    family_scores=dict(score_items),  # type: ignore[arg-type]
                    formulaic_control=(observation_index == 7),
                )
            )
            observation_index += 1
    observations.sort(key=lambda row: row.candidate_pair_id)
    input_path = tmp_path / "pair-family-scores.jsonl"
    write_jsonl_atomic(input_path, observations, sort_key="candidate_pair_id")
    registrations = {item.detector_id: item for item in TEST_CONFIG.detectors}
    expected = anomaly_evidence(
        observations,
        passages,
        registrations=registrations,
        source_artifact_id="stage-3-5-family-evidence",
        source_artifact_sha256="b" * 64,
    )

    result = calibrate_anomaly_evidence_disk_backed(
        input_path,
        passages,
        tmp_path / "robust-anomaly",
        config=TEST_CONFIG,
        source_artifact_id="stage-3-5-family-evidence",
        source_artifact_sha256="b" * 64,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
        threads=2,
        batch_size=3,
    )
    observed = read_jsonl(result.anomaly_evidence_path, RawEvidence)

    assert [row.model_dump(mode="json") for row in observed] == [
        row.model_dump(mode="json") for row in expected
    ]
    assert result.receipt.candidate_pair_count == len(observations)
    assert result.receipt.anomaly_stratum_count == len(groups)
    assert result.receipt.output_ordering == "candidate_pair_id,detector_id"
    assert not tuple((tmp_path / "spill").iterdir())


def test_disk_robust_anomaly_preserves_failure_state_for_missing_passage(
    tmp_path: Path,
) -> None:
    observation = PairFamilyScores(
        candidate_pair_id=candidate_pair_id("A", "B"),
        passage_a_id="A",
        passage_b_id="B",
        family_scores={"lexical": 0.4, "semantic": 0.8},
    )
    input_path = tmp_path / "pair-family-scores.jsonl"
    write_jsonl_atomic(input_path, [observation], sort_key="candidate_pair_id")
    passages = {
        passage.passage_id: passage
        for passage in (
            _passage(
                "A",
                corpus="hebrew",
                book="Genesis",
                genre="narrative",
                token_count=4,
            ),
            _passage(
                "C",
                corpus="hebrew",
                book="Exodus",
                genre="narrative",
                token_count=4,
            ),
        )
    }
    output = tmp_path / "robust-anomaly"
    temp_directory = tmp_path / "spill"

    with pytest.raises(DiskCalibrationError, match="missing passage for anomaly pair"):
        calibrate_anomaly_evidence_disk_backed(
            input_path,
            passages,
            output,
            config=TEST_CONFIG,
            source_artifact_id="stage-3-5-family-evidence",
            source_artifact_sha256="b" * 64,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=temp_directory,
            batch_size=1,
        )

    _assert_preserved_failure_state(
        output,
        temp_directory,
        workspace_prefix="robust-anomaly",
        database_name="robust-anomaly.duckdb",
    )
