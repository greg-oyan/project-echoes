#!/usr/bin/env python3
"""Resume final-discovery input preparation after a 1 GiB knownness OOM.

The completed passage cache is authenticated and reused. The M6 OpenBible
knownness projection is generated with a 4 GiB DuckDB ceiling, then the normal
preparation script reauthenticates both caches and writes its canonical receipt.
This script never provisions infrastructure, accesses Backblaze, or launches
the scientific campaign.
"""

from __future__ import annotations

import argparse
import json
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
from echoes.final_discovery.passages import read_passage_records_jsonl
from echoes.manifest import sha256_file

KNOWNNESS_MEMORY_LIMIT_BYTES: Final = 4 * 1024**3
MINIMUM_FREE_DISK_BYTES: Final = 20 * 1024**3
PASSAGES_NAME: Final = "passages.jsonl"
KNOWNNESS_NAME: Final = "known-relationships.jsonl"
KNOWNNESS_RECEIPT_NAME: Final = "known-relationships.receipt.json"
PREPARATION_RECEIPT_NAME: Final = "preparation-receipt.json"
BENCHMARK_MANIFEST_RELATIVE: Final = Path(
    "data/processed/benchmarks/schema-v1/table-hashes.json"
)
EXPECTED_BENCHMARK_MANIFEST_SHA256: Final = (
    "1cfaab5de2904e283b466044b2cd38d0acdc6f6fef929bc397e720ce6d3838fd"
)
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


class RetryError(RuntimeError):
    """Raised when the bounded retry cannot preserve the frozen contract."""


def _run_git(root: Path, *arguments: str) -> str:
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
        raise RetryError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _validate_repository(root: Path, expected_commit: str) -> None:
    if not root.is_dir() or root.is_symlink() or not (root / ".git").is_dir():
        raise RetryError(f"repository root is absent or unsafe: {root}")
    observed = _run_git(root, "rev-parse", "HEAD")
    if observed != expected_commit:
        raise RetryError(
            f"repository commit differs: expected={expected_commit}, observed={observed}"
        )
    if _run_git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RetryError("repository must be completely clean, including untracked files")


def _validate_passages(path: Path) -> int:
    if not path.is_file() or path.is_symlink():
        raise RetryError(f"prepared passage cache is absent or unsafe: {path}")
    counts: Counter[tuple[str, str, str]] = Counter()
    row_count = 0
    for passage in read_passage_records_jsonl(path):
        counts[(passage.corpus, passage.analysis_profile, passage.analysis_reading)] += 1
        row_count += 1
    if dict(counts) != EXPECTED_STREAM_COUNTS:
        raise RetryError(
            f"prepared passage stream counts differ: expected={EXPECTED_STREAM_COUNTS}, "
            f"observed={dict(counts)}"
        )
    return row_count


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
        raise RetryError(
            f"knownness projection differs: expected={EXPECTED_KNOWNNESS}, observed={observed}"
        )
    return observed


def _validate_paths(root: Path, output_root: Path) -> tuple[Path, Path, Path, Path]:
    if not output_root.is_dir() or output_root.is_symlink():
        raise RetryError(f"output root is absent or unsafe: {output_root}")
    passages = output_root / PASSAGES_NAME
    knownness = output_root / KNOWNNESS_NAME
    receipt = output_root / KNOWNNESS_RECEIPT_NAME
    preparation_receipt = output_root / PREPARATION_RECEIPT_NAME
    _validate_passages(passages)

    knownness_state = (knownness.exists(), receipt.exists())
    if knownness_state in {(True, False), (False, True)}:
        raise RetryError("knownness JSONL and receipt must be both absent or both present")
    for path in (knownness, receipt, preparation_receipt):
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise RetryError(f"existing output is not a safe regular file: {path}")

    benchmark_manifest = root / BENCHMARK_MANIFEST_RELATIVE
    if not benchmark_manifest.is_file() or benchmark_manifest.is_symlink():
        raise RetryError("governed benchmark manifest is absent or unsafe")
    observed_manifest = sha256_file(benchmark_manifest)
    if observed_manifest != EXPECTED_BENCHMARK_MANIFEST_SHA256:
        raise RetryError(
            "governed benchmark manifest differs: "
            f"expected={EXPECTED_BENCHMARK_MANIFEST_SHA256}, observed={observed_manifest}"
        )
    if shutil.disk_usage(output_root).free < MINIMUM_FREE_DISK_BYTES:
        raise RetryError("less than 20 GiB free disk remains for the bounded retry")
    return passages, knownness, receipt, preparation_receipt


def _finalize_with_normal_preparer(root: Path, output_root: Path, expected_commit: str) -> None:
    normal_script = root / "scripts" / "prepare_final_discovery_inputs.py"
    if not normal_script.is_file() or normal_script.is_symlink():
        raise RetryError("normal input-preparation script is absent or unsafe")
    completed = subprocess.run(
        [
            sys.executable,
            str(normal_script),
            "--execute",
            "--repo-root",
            str(root),
            "--output-root",
            str(output_root),
            "--expected-commit",
            expected_commit,
        ],
        cwd=root,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RetryError("normal input-preparation finalization failed")


def _preflight(root: Path, output_root: Path, expected_commit: str) -> dict[str, object]:
    _validate_repository(root, expected_commit)
    passages, knownness, receipt, preparation_receipt = _validate_paths(root, output_root)
    return {
        "schema_version": 1,
        "experiment_id": "final-discovery-v1",
        "git_commit": expected_commit,
        "passages_path": str(passages),
        "passage_row_count": sum(EXPECTED_STREAM_COUNTS.values()),
        "knownness_state": "complete" if knownness.exists() and receipt.exists() else "absent",
        "preparation_receipt_present": preparation_receipt.exists(),
        "duckdb_memory_limit_bytes": KNOWNNESS_MEMORY_LIMIT_BYTES,
        "preflight_passed": True,
    }


def _execute(root: Path, output_root: Path, expected_commit: str) -> dict[str, object]:
    preflight = _preflight(root, output_root, expected_commit)
    _, knownness, receipt, _ = _validate_paths(root, output_root)
    benchmark_root = root / "data" / "processed" / "benchmarks" / "schema-v1"

    if knownness.exists():
        knownness_receipt = authenticate_knownness_jsonl(
            knownness,
            receipt,
            expected_manifest_sha256=EXPECTED_BENCHMARK_MANIFEST_SHA256,
        )
        action = "verified_existing"
    else:
        temp_directory = output_root / ".knownness-duckdb-temp-4g"
        try:
            knownness_receipt = project_openbible_knownness(
                benchmark_root,
                knownness,
                receipt,
                expected_manifest_sha256=EXPECTED_BENCHMARK_MANIFEST_SHA256,
                memory_limit_bytes=KNOWNNESS_MEMORY_LIMIT_BYTES,
                temp_directory=temp_directory,
            )
        finally:
            shutil.rmtree(temp_directory, ignore_errors=True)
        action = "generated"

    summary = _knownness_summary(knownness_receipt)
    _finalize_with_normal_preparer(root, output_root, expected_commit)
    preparation_receipt = output_root / PREPARATION_RECEIPT_NAME
    if not preparation_receipt.is_file() or preparation_receipt.is_symlink():
        raise RetryError("normal preparation receipt was not committed")

    return {
        **preflight,
        "knownness_action": action,
        "knownness_jsonl_sha256": knownness_receipt.jsonl_sha256,
        "knownness_logical_sha256": knownness_receipt.logical_sha256,
        "knownness_summary": summary,
        "preparation_receipt_path": str(preparation_receipt),
        "passed": True,
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    expected_commit = str(arguments.expected_commit).lower()
    invalid_commit = len(expected_commit) != 40 or any(
        character not in "0123456789abcdef" for character in expected_commit
    )
    if invalid_commit:
        raise RetryError("expected commit must be one full lowercase Git SHA")
    root = arguments.repo_root.resolve()
    output_root = arguments.output_root.resolve()
    payload = (
        _preflight(root, output_root, expected_commit)
        if arguments.preflight_only
        else _execute(root, output_root, expected_commit)
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
    print("PREFLIGHT_COMPLETE" if arguments.preflight_only else "KNOWNNESS_RETRY_COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RetryError, OSError, ValueError, RuntimeError) as exc:
        print(f"KNOWNNESS RETRY FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
