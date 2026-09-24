"""Exact pinned M7 projection reuse without rebuilding or overwriting evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from echoes.final_discovery import projection_cache
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.features import candidate_pair_id
from echoes.final_discovery.m7_adapter import iter_m7_raw_evidence
from echoes.final_discovery.projection_cache import ProjectionCacheError, reuse_tested_projection
from echoes.final_discovery.stages import StageArtifact, StageCompletionManifest
from echoes.lexical.models import LEXICAL_ARTIFACT_NAMES


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class CacheFixture:
    receipt: Path
    source: Path
    projection: Path
    output: Path
    manifest_sha256: str
    receipt_sha256: str

    def reuse(self) -> Path:
        return reuse_tested_projection(
            self.receipt,
            self.source,
            self.output,
            self.manifest_sha256,
            expected_receipt_sha256=self.receipt_sha256,
        )

    def alter_receipt(self, key: str, value: object, *, repin: bool = True) -> None:
        payload = json.loads(self.receipt.read_bytes())
        payload[key] = value
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        if repin:
            self.receipt_sha256 = _sha(self.receipt)


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CacheFixture:
    # Only the population-size constant is scaled; all authentication is real.
    monkeypatch.setattr(projection_cache, "_CANONICAL_PAIR_COUNT", 2)
    attempt = "a" * 32
    stage = tmp_path / "old" / "stages" / "01-authenticate_materialize_inputs"
    root = stage / "completed-attempts" / attempt / "artifacts" / "m7"
    (root / "candidate_pairs").mkdir(parents=True)
    source_leaf = root / "candidate_pairs" / "part-00000.parquet"
    pl.DataFrame({"candidate_pair_id": ["M7-A", "M7-B"]}).write_parquet(source_leaf)
    counts = dict.fromkeys(LEXICAL_ARTIFACT_NAMES, 0)
    counts.update(candidate_pairs=2, candidate_evidence=2, shared_evidence=0)
    logical = {name: hashlib.sha256(name.encode()).hexdigest() for name in LEXICAL_ARTIFACT_NAMES}
    manifest = root / "table-hashes.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_counts": counts,
                "table_logical_sha256": logical,
                "file_sha256": {"candidate_pairs/part-00000.parquet": _sha(source_leaf)},
            }
        ),
        encoding="utf-8",
    )
    manifest_sha = _sha(manifest)
    artifacts = tuple(
        StageArtifact(
            path="m7/" + path.relative_to(root).as_posix(),
            size=path.stat().st_size,
            sha256=_sha(path),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    inventory_hash = hashlib.sha256(
        json.dumps(
            [item.model_dump() for item in artifacts],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    completion = StageCompletionManifest(
        attempt_id=attempt,
        stage_number=1,
        stage_id="authenticate_materialize_inputs",
        stage_spec_sha256="1" * 64,
        started_at=datetime(2026, 9, 8, tzinfo=UTC),
        completed_at=datetime(2026, 9, 8, 1, tzinfo=UTC),
        input_sha256={"m7-table-hashes.json": manifest_sha},
        dependency_completion_sha256={},
        config_sha256="2" * 64,
        code_sha256="3" * 64,
        code_commit="06baacb0f1c9012a92f00a848bc381e696c9c454",
        artifacts_root=f"completed-attempts/{attempt}/artifacts",
        artifacts=artifacts,
        output_inventory_sha256=inventory_hash,
    )
    completion_path = stage / "completion.json"
    completion_path.write_text(completion.model_dump_json(), encoding="utf-8")
    bundle = tmp_path / "recovery"
    bundle.mkdir()
    projection = bundle / "m7-lexical-projection.parquet"
    rows = []
    for index in range(2):
        row: dict[str, object] = {
            "candidate_pair_id": f"M7-{index}",
            "passage_a_id": f"a-{index}",
            "passage_b_id": f"b-{index}",
            "passage_a_reference": f"GEN 1:{index + 1}",
            "passage_b_reference": f"EXO 1:{index + 1}",
            "known_link_status": "not_represented_in_openbible_snapshot",
            "openbible_relationship_ids_json": "[]",
            "non_english_evidence_remains": True,
            "score_after_removing_all_english_features": 0.02,
            "english_ablation_survives": True,
            "raw_rrf_score": 0.02,
            "rrf_score": 0.02,
            "estimated_empirical_fdr": 0.2,
            "benjamini_hochberg_q_value": 0.2,
            "both_null_families_present": True,
            "detector_trace_digest": "4" * 64,
            "ablation_digest": "5" * 64,
            "evidence_digest": "6" * 64,
            "m7_shared_evidence_count": 0,
            "m7_shared_evidence_ids_json": "[]",
            "m7_shared_evidence_digest": hashlib.sha256(b"[]").hexdigest(),
            "m7_projection_candidate_pair_count": 2,
            "m7_projection_candidate_evidence_count": 2,
            "m7_projection_shared_evidence_count": 0,
            "m7_source_manifest_sha256": manifest_sha,
            "m7_candidate_pairs_logical_sha256": logical["candidate_pairs"],
            "m7_candidate_evidence_logical_sha256": logical["candidate_evidence"],
            "m7_shared_evidence_logical_sha256": logical["shared_evidence"],
        }
        for name in (
            "disputed_passage_flag",
            "reference_gap",
            "ketiv_structural_uncertainty",
            "direct_adjacency",
            "nearby_context",
            "exact_duplicate",
            "near_exact_duplicate",
            "formulaic_evidence_flag",
            "contains_english_derived_evidence",
        ):
            row[name] = False
        rows.append(row)
    rows.sort(key=lambda row: candidate_pair_id(str(row["passage_a_id"]), str(row["passage_b_id"])))
    pl.DataFrame(rows).write_parquet(projection, row_group_size=1)
    final_ids = [
        candidate_pair_id(str(row["passage_a_id"]), str(row["passage_b_id"])) for row in rows
    ]
    original_test = tmp_path / "unavailable-original-test"
    payload = {
        "code_commit": "e265b59cc26bf33daf1eec832d54b71f29557c19",
        "complete_source_inventory_authenticated": True,
        "completed_at": "2026-09-09T04:04:28.145197+00:00",
        "completion_path": str(completion_path),
        "completion_sha256": _sha(completion_path),
        "downstream_order_condition_passed": True,
        "duckdb_memory_limit_bytes": 1073741824,
        "duckdb_threads": 1,
        "first_final_id": final_ids[0],
        "full_stream_reached_eof": True,
        "globally_unique_final_ids": True,
        "last_final_id": final_ids[-1],
        "output_path": str(original_test / projection.name),
        "output_row_count": 2,
        "output_sha256": _sha(projection),
        "result": "pass",
        "source_inventory_sha256": "7" * 64,
        "source_manifest_sha256": manifest_sha,
        "source_object_count": len(artifacts),
        "source_root": str(root),
        "started_at": "2026-09-09T03:38:05.319366+00:00",
        "stream_row_count": 2,
        "strict_final_identity_order": True,
        "table_counts": counts,
        "test_directory": str(original_test),
    }
    receipt = bundle / "receipt.json"
    receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current_source = tmp_path / "current-m7"
    shutil.copytree(root, current_source)
    output_dir = tmp_path / "stage-three"
    output_dir.mkdir()
    return CacheFixture(
        receipt,
        current_source,
        projection,
        output_dir / projection.name,
        manifest_sha,
        _sha(receipt),
    )


def test_reuses_identical_current_source_and_preserves_original_receipt(
    cache: CacheFixture,
) -> None:
    before_receipt = cache.receipt.read_bytes()
    before_projection = cache.projection.read_bytes()
    assert cache.reuse() == cache.output
    assert cache.output.read_bytes() == before_projection
    assert not cache.output.samefile(cache.projection)
    assert cache.receipt.read_bytes() == before_receipt
    assert cache.projection.read_bytes() == before_projection
    provenance = json.loads(cache.output.with_name(cache.output.name + ".reuse.json").read_bytes())
    assert base64.b64decode(provenance["source_receipt_bytes_base64"]) == before_receipt
    assert provenance["source_receipt_sha256"] == cache.receipt_sha256
    assert provenance["current_source_root"] == str(cache.source)
    registration = next(
        item
        for item in load_final_discovery_config().detectors
        if item.detector_id == "m7_lexical_rrf"
    )
    rows = tuple(
        iter_m7_raw_evidence(
            cache.output,
            registration=registration,
            source_artifact_sha256=cache.manifest_sha256,
            batch_size=1,
        )
    )
    assert len(rows) == 2
    assert rows[0].candidate_pair_id < rows[1].candidate_pair_id


def test_rejects_changed_receipt_even_if_still_valid_json(cache: CacheFixture) -> None:
    cache.alter_receipt("completed_at", "2026-09-10T00:00:00+00:00", repin=False)
    with pytest.raises(ProjectionCacheError, match="trusted pin"):
        cache.reuse()
    assert not cache.output.exists()


@pytest.mark.parametrize(
    "flag",
    [
        "complete_source_inventory_authenticated",
        "downstream_order_condition_passed",
        "full_stream_reached_eof",
        "globally_unique_final_ids",
        "strict_final_identity_order",
    ],
)
@pytest.mark.parametrize("value", [False, 1])
def test_rejects_incomplete_or_nonboolean_pass_flags(
    cache: CacheFixture, flag: str, value: object
) -> None:
    cache.alter_receipt(flag, value)
    with pytest.raises(ProjectionCacheError, match="ordering checks"):
        cache.reuse()
    assert not cache.output.exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("result", "fail"),
        ("code_commit", "a" * 40),
        ("output_row_count", 1),
        ("stream_row_count", 1),
        ("source_object_count", 3),
        ("completion_sha256", "f" * 64),
        ("source_manifest_sha256", "f" * 64),
    ],
)
def test_rejects_inconsistent_trusted_receipts(
    cache: CacheFixture, key: str, value: object
) -> None:
    cache.alter_receipt(key, value)
    with pytest.raises(ProjectionCacheError):
        cache.reuse()
    assert not cache.output.exists()


def test_rejects_modified_current_source(cache: CacheFixture) -> None:
    leaf = cache.source / "candidate_pairs" / "part-00000.parquet"
    leaf.write_bytes(leaf.read_bytes() + b"modified")
    with pytest.raises(ProjectionCacheError, match="source inventory"):
        cache.reuse()
    assert not cache.output.exists()


def test_rejects_unexpected_source_file(cache: CacheFixture) -> None:
    (cache.source / "unexpected.txt").write_text("unexpected")
    with pytest.raises(ProjectionCacheError, match="source inventory"):
        cache.reuse()


def test_rejects_projection_tampering(cache: CacheFixture) -> None:
    cache.projection.write_bytes(cache.projection.read_bytes() + b"modified")
    with pytest.raises(ProjectionCacheError, match="projection SHA-256"):
        cache.reuse()


@pytest.mark.parametrize(
    "field,value",
    [
        ("m7_projection_candidate_pair_count", 3),
        ("m7_shared_evidence_logical_sha256", "f" * 64),
        ("m7_source_manifest_sha256", "f" * 64),
    ],
)
def test_checks_embedded_binding_on_later_rows(
    cache: CacheFixture, field: str, value: object
) -> None:
    rows = pl.read_parquet(cache.projection).to_dicts()
    rows[-1][field] = value
    pl.DataFrame(rows).write_parquet(cache.projection, row_group_size=1)
    cache.alter_receipt("output_sha256", _sha(cache.projection))
    with pytest.raises(ProjectionCacheError, match="embedded binding"):
        cache.reuse()
    assert not cache.output.exists()


def test_checks_actual_parquet_row_count(cache: CacheFixture) -> None:
    pl.read_parquet(cache.projection).head(1).write_parquet(cache.projection)
    cache.alter_receipt("output_sha256", _sha(cache.projection))
    with pytest.raises(ProjectionCacheError, match="actual Parquet row count"):
        cache.reuse()


@pytest.mark.parametrize("existing", ["projection", "provenance"])
def test_never_replaces_existing_outputs(cache: CacheFixture, existing: str) -> None:
    target = (
        cache.output
        if existing == "projection"
        else cache.output.with_name(cache.output.name + ".reuse.json")
    )
    target.write_bytes(b"preserved")
    with pytest.raises(ProjectionCacheError, match="refusing to replace"):
        cache.reuse()
    assert target.read_bytes() == b"preserved"


def test_rejects_missing_cached_projection(cache: CacheFixture) -> None:
    cache.projection.unlink()
    with pytest.raises(ProjectionCacheError):
        cache.reuse()
    assert not cache.output.exists()


def test_no_production_population_override(
    cache: CacheFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projection_cache, "_CANONICAL_PAIR_COUNT", 1_248_779)
    with pytest.raises(ProjectionCacheError, match="complete canonical population"):
        cache.reuse()


def test_rejects_changed_adapter_source(
    cache: CacheFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        projection_cache,
        "_REVIEWED_SOURCE_BLOBS",
        {"src/echoes/final_discovery/m7_adapter.py": "f" * 40},
    )
    with pytest.raises(ProjectionCacheError, match="adapter source changed"):
        cache.reuse()
    assert not cache.output.exists()


def test_rejects_source_root_not_named_by_completion(cache: CacheFixture) -> None:
    cache.alter_receipt("source_root", str(cache.source))
    with pytest.raises(ProjectionCacheError, match="source root differs"):
        cache.reuse()


def test_rejects_missing_receipt(cache: CacheFixture) -> None:
    cache.receipt.unlink()
    with pytest.raises(ProjectionCacheError):
        cache.reuse()
    assert not cache.output.exists()


def test_rejects_changed_recorded_source_manifest(cache: CacheFixture) -> None:
    payload = json.loads(cache.receipt.read_bytes())
    manifest = Path(payload["source_root"]) / "table-hashes.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(ProjectionCacheError, match="source manifest binding"):
        cache.reuse()
    assert not cache.output.exists()


def test_rejects_copy_damage_and_preserves_cache(
    cache: CacheFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_copy = shutil.copyfileobj
    original_sha = _sha(cache.projection)

    def damage_copy(source: object, destination: object, *, length: int) -> None:
        original_copy(source, destination, length=length)  # type: ignore[arg-type]
        destination.write(b"damaged")  # type: ignore[attr-defined]

    monkeypatch.setattr(projection_cache.shutil, "copyfileobj", damage_copy)
    with pytest.raises(ProjectionCacheError, match="copy changed"):
        cache.reuse()
    assert _sha(cache.projection) == original_sha
    assert not cache.output.with_name(cache.output.name + ".reuse.json").exists()


@pytest.mark.parametrize("target", ["receipt", "projection", "output_parent", "source_leaf"])
def test_rejects_symbolic_links(cache: CacheFixture, target: str) -> None:
    if target == "output_parent":
        original = cache.output.parent
    elif target == "source_leaf":
        original = cache.source / "candidate_pairs" / "part-00000.parquet"
    else:
        original = cache.receipt if target == "receipt" else cache.projection
    moved = original.with_name(original.name + "-real")
    original.rename(moved)
    try:
        original.symlink_to(moved, target_is_directory=moved.is_dir())
    except OSError as exc:
        moved.rename(original)
        pytest.skip(f"creating symbolic links is unavailable: {exc}")
    with pytest.raises(ProjectionCacheError):
        cache.reuse()
