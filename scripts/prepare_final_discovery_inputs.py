#!/usr/bin/env python3
"""Prepare the two governed local caches required by ``final-discovery-v1``.

This script does not provision infrastructure, access Backblaze, or launch the
scientific campaign. It projects the already-authenticated M5/M6 artifacts into
an external input directory, validates the exact accepted stream/cardinality
contracts, and writes one deterministic preparation receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Final

from echoes.final_discovery.knownness_projection import (
    KnownnessProjectionReceipt,
    authenticate_knownness_jsonl,
    project_openbible_knownness,
)
from echoes.final_discovery.passages import (
    PassageParquetSources,
    PassageProjectionScope,
    iter_passage_records_from_parquet,
    read_passage_records_jsonl,
    write_passage_records_jsonl,
)
from echoes.manifest import sha256_file

EXPERIMENT_ID: Final = "final-discovery-v1"
DEFAULT_OUTPUT_ROOT: Final = Path("/srv/project-echoes/inputs/final-discovery")
PASSAGES_NAME: Final = "passages.jsonl"
KNOWNNESS_NAME: Final = "known-relationships.jsonl"
KNOWNNESS_RECEIPT_NAME: Final = "known-relationships.receipt.json"
PREPARATION_RECEIPT_NAME: Final = "preparation-receipt.json"

EXPECTED_MANIFESTS: Final = {
    "data/processed/passages/schema-v1/table-hashes.json": (
        "b7741f800932a623e1ce7a53d79628ce2429b6626370ef5a6c4a11161832f7cf"
    ),
    "data/processed/macula-hebrew/25.08.11/table-hashes.json": (
        "54b9b41dc939fe7e526fcb62c4772e86b9f053f829e2a2d556fb16049311f093"
    ),
    "data/processed/macula-greek/24.06.17/table-hashes.json": (
        "2f521b87cb7b74cb9f032e41deff3b21c15db1d2f6f2b480c2324a7bb799d876"
    ),
    "data/processed/oshb-morphhb/master-3d15126/table-hashes.json": (
        "810e7426e5fa3b10b12affc3d338bf0a031bd7b66d112176a4c12bc27ccc0573"
    ),
    "data/processed/benchmarks/schema-v1/table-hashes.json": (
        "1cfaab5de2904e283b466044b2cd38d0acdc6f6fef929bc397e720ce6d3838fd"
    ),
}
EXPECTED_STREAM_COUNTS: Final = {
    ("hebrew", "edition_complete", "qere"): 23_213,
    ("greek", "edition_complete", "source"): 7_943,
    ("hebrew", "edition_complete", "ketiv"): 23_213,
    ("greek", "critical_core", "source"): 7_918,
}
EXPECTED_KNOWNNESS: Final = {
    "eligible_source_relationship_count": 344_799,
    "mapped_endpoint_target_count": 954_614,
    "expanded_edge_count": 608_600,
    "excluded_self_edge_count": 67,
    "row_count": 608_533,
    "represented_source_relationship_count": 341_926,
    "unique_unordered_pair_count": 550_333,
    "multi_pair_relationship_count": 87_436,
    "maximum_pairs_per_relationship": 182,
}


class PreparationError(RuntimeError):
    """Raised when input preparation cannot honor the frozen contract."""


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:1000]
        raise PreparationError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _validate_repository(root: Path, expected_commit: str) -> None:
    if not root.is_dir() or root.is_symlink() or not (root / ".git").is_dir():
        raise PreparationError(f"repository root is absent or unsafe: {root}")
    observed = _git(root, "rev-parse", "HEAD")
    if observed != expected_commit:
        raise PreparationError(
            f"repository commit differs: expected={expected_commit}, observed={observed}"
        )
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise PreparationError("repository must be completely clean, including untracked files")


def _verify_manifest_inventory(root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in EXPECTED_MANIFESTS.items():
        path = root.joinpath(*relative.split("/"))
        if not path.is_file() or path.is_symlink():
            raise PreparationError(f"governed manifest is absent or unsafe: {relative}")
        digest = sha256_file(path)
        if digest != expected:
            raise PreparationError(
                f"governed manifest differs: {relative}: expected={expected}, observed={digest}"
            )
        observed[relative] = digest
    return observed


def _passage_sources(root: Path) -> PassageParquetSources:
    processed = root / "data" / "processed"
    sources = PassageParquetSources(
        passage_root=processed / "passages" / "schema-v1",
        hebrew_tokens_path=processed / "macula-hebrew" / "25.08.11" / "tokens.parquet",
        greek_tokens_path=processed / "macula-greek" / "24.06.17" / "tokens.parquet",
        hebrew_ketiv_tokens_path=(
            processed / "oshb-morphhb" / "master-3d15126" / "kq_ketiv_tokens.parquet"
        ),
        benchmark_config_path=root / "config" / "benchmark.yaml",
    )
    required = (
        sources.hebrew_tokens_path,
        sources.greek_tokens_path,
        sources.hebrew_ketiv_tokens_path,
        sources.resolved_passage_hash_manifest_path,
        sources.resolved_hebrew_hash_manifest_path,
        sources.resolved_greek_hash_manifest_path,
        sources.resolved_hebrew_ketiv_hash_manifest_path,
    )
    for path in required:
        if path is None or not path.is_file() or path.is_symlink():
            raise PreparationError(f"required passage input is absent or unsafe: {path}")
    return sources


def _validate_output_root(output_root: Path) -> None:
    if output_root.exists() and (not output_root.is_dir() or output_root.is_symlink()):
        raise PreparationError(f"output root is not a safe directory: {output_root}")
    if output_root.resolve() == Path("/"):
        raise PreparationError("output root cannot be the filesystem root")


def _validate_partial_state(output_root: Path) -> None:
    passages = output_root / PASSAGES_NAME
    knownness = output_root / KNOWNNESS_NAME
    knownness_receipt = output_root / KNOWNNESS_RECEIPT_NAME
    knownness_present = (knownness.exists(), knownness_receipt.exists())
    if knownness_present in {(True, False), (False, True)}:
        raise PreparationError("knownness JSONL and receipt must be both absent or both present")
    for path in (passages, knownness, knownness_receipt):
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise PreparationError(f"existing output is not a safe regular file: {path}")


def _validate_passages(path: Path) -> tuple[int, dict[str, int]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    row_count = 0
    for passage in read_passage_records_jsonl(path):
        counts[(passage.corpus, passage.analysis_profile, passage.analysis_reading)] += 1
        row_count += 1
    if dict(counts) != EXPECTED_STREAM_COUNTS:
        raise PreparationError(
            f"prepared passage stream counts differ: expected={EXPECTED_STREAM_COUNTS}, "
            f"observed={dict(counts)}"
        )
    serialized = {"/".join(key): value for key, value in sorted(counts.items())}
    return row_count, serialized


def _knownness_summary(receipt: KnownnessProjectionReceipt) -> dict[str, int]:
    observed = {
        "eligible_source_relationship_count": receipt.eligible_source_relationship_count,
        "mapped_endpoint_target_count": receipt.mapped_endpoint_target_count,
        "expanded_edge_count": receipt.expanded_edge_count,
        "excluded_self_edge_count": receipt.excluded_self_edge_count,
        "row_count": receipt.row_count,
        "represented_source_relationship_count": receipt.represented_source_relationship_count,
        "unique_unordered_pair_count": receipt.unique_unordered_pair_count,
        "multi_pair_relationship_count": receipt.multi_pair_relationship_count,
        "maximum_pairs_per_relationship": receipt.maximum_pairs_per_relationship,
    }
    if observed != EXPECTED_KNOWNNESS:
        raise PreparationError(
            f"knownness projection differs: expected={EXPECTED_KNOWNNESS}, observed={observed}"
        )
    return observed


def _write_deterministic_receipt(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise PreparationError(f"existing preparation receipt differs or is unsafe: {path}")
        return
    staging = path.with_name(f".{path.name}.writing-{os.getpid()}")
    try:
        with staging.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _prepare(root: Path, output_root: Path, expected_commit: str) -> dict[str, object]:
    _validate_repository(root, expected_commit)
    manifests = _verify_manifest_inventory(root)
    sources = _passage_sources(root)
    _validate_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    _validate_partial_state(output_root)

    passages_path = output_root / PASSAGES_NAME
    if not passages_path.exists():
        passage_receipt = write_passage_records_jsonl(
            iter_passage_records_from_parquet(
                sources,
                scope=PassageProjectionScope(
                    include_greek_critical_core=True,
                    include_hebrew_ketiv=True,
                ),
            ),
            passages_path,
        )
        if passage_receipt.row_count != sum(EXPECTED_STREAM_COUNTS.values()):
            raise PreparationError(
                f"generated passage row count differs: {passage_receipt.row_count}"
            )
    passage_count, stream_counts = _validate_passages(passages_path)

    knownness_path = output_root / KNOWNNESS_NAME
    knownness_receipt_path = output_root / KNOWNNESS_RECEIPT_NAME
    expected_knownness_manifest = EXPECTED_MANIFESTS[
        "data/processed/benchmarks/schema-v1/table-hashes.json"
    ]
    if not knownness_path.exists():
        temp_directory = output_root / ".knownness-duckdb-temp"
        try:
            knownness_receipt = project_openbible_knownness(
                root / "data" / "processed" / "benchmarks" / "schema-v1",
                knownness_path,
                knownness_receipt_path,
                expected_manifest_sha256=expected_knownness_manifest,
                memory_limit_bytes=1024**3,
                temp_directory=temp_directory,
            )
        finally:
            shutil.rmtree(temp_directory, ignore_errors=True)
    else:
        knownness_receipt = authenticate_knownness_jsonl(
            knownness_path,
            knownness_receipt_path,
            expected_manifest_sha256=expected_knownness_manifest,
        )
    knownness_summary = _knownness_summary(knownness_receipt)

    payload: dict[str, object] = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "git_commit": expected_commit,
        "governed_manifests": manifests,
        "prepared_passages": {
            "path": str(passages_path),
            "sha256": sha256_file(passages_path),
            "row_count": passage_count,
            "stream_counts": stream_counts,
        },
        "knownness_projection": {
            "path": str(knownness_path),
            "receipt_path": str(knownness_receipt_path),
            "jsonl_sha256": knownness_receipt.jsonl_sha256,
            "logical_sha256": knownness_receipt.logical_sha256,
            **knownness_summary,
        },
        "passed": True,
    }
    _write_deterministic_receipt(output_root / PREPARATION_RECEIPT_NAME, payload)
    return payload


def _preflight(root: Path, output_root: Path, expected_commit: str) -> dict[str, object]:
    _validate_repository(root, expected_commit)
    manifests = _verify_manifest_inventory(root)
    _passage_sources(root)
    _validate_output_root(output_root)
    _validate_partial_state(output_root)
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "git_commit": expected_commit,
        "governed_manifest_count": len(manifests),
        "output_root": str(output_root),
        "preflight_passed": True,
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    expected_commit = str(arguments.expected_commit).lower()
    if len(expected_commit) != 40 or any(value not in "0123456789abcdef" for value in expected_commit):
        raise PreparationError("expected commit must be one full lowercase Git SHA")
    root = arguments.repo_root.resolve()
    output_root = arguments.output_root.resolve()
    payload = (
        _preflight(root, output_root, expected_commit)
        if arguments.preflight_only
        else _prepare(root, output_root, expected_commit)
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
    print("PREFLIGHT_COMPLETE" if arguments.preflight_only else "INPUT_PREPARATION_COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreparationError, OSError, ValueError, RuntimeError) as exc:
        print(f"INPUT PREPARATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
