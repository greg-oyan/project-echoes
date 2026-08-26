"""Static contracts for the production input-preparation script."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_final_discovery_inputs.py"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_is_valid_python_and_has_separate_modes() -> None:
    script = _text()

    ast.parse(script)
    assert "--preflight-only" in script
    assert "--execute" in script
    assert "PREFLIGHT_COMPLETE" in script
    assert "INPUT_PREPARATION_COMPLETE" in script


def test_script_pins_exact_passage_stream_counts() -> None:
    script = _text()

    for fragment in (
        '("hebrew", "edition_complete", "qere"): 23_213',
        '("greek", "edition_complete", "source"): 7_943',
        '("hebrew", "edition_complete", "ketiv"): 23_213',
        '("greek", "critical_core", "source"): 7_918',
    ):
        assert fragment in script
    assert "include_greek_critical_core=True" in script
    assert "include_hebrew_ketiv=True" in script


def test_script_pins_exact_knownness_contract() -> None:
    script = _text()

    for fragment in (
        '"eligible_source_relationship_count": 344_799',
        '"mapped_endpoint_target_count": 954_614',
        '"expanded_edge_count": 608_600',
        '"excluded_self_edge_count": 67',
        '"row_count": 608_533',
        '"represented_source_relationship_count": 341_926',
        '"unique_unordered_pair_count": 550_333',
        '"multi_pair_relationship_count": 87_436',
        '"maximum_pairs_per_relationship": 182',
    ):
        assert fragment in script
    assert "memory_limit_bytes=1024**3" in script


def test_script_pins_all_five_governed_manifests() -> None:
    script = _text()

    required = {
        "b7741f800932a623e1ce7a53d79628ce2429b6626370ef5a6c4a11161832f7cf",
        "54b9b41dc939fe7e526fcb62c4772e86b9f053f829e2a2d556fb16049311f093",
        "2f521b87cb7b74cb9f032e41deff3b21c15db1d2f6f2b480c2324a7bb799d876",
        "810e7426e5fa3b10b12affc3d338bf0a031bd7b66d112176a4c12bc27ccc0573",
        "1cfaab5de2904e283b466044b2cd38d0acdc6f6fef929bc397e720ce6d3838fd",
    }
    assert all(value in script for value in required)


def test_script_never_manages_cloud_or_launches_campaign() -> None:
    script = _text()
    operational = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    for forbidden in (
        "scw instance",
        "hcloud server",
        "systemd-run",
        "launch_final_discovery",
        "run-final-discovery",
        "B2_APPLICATION_KEY",
        "rclone",
    ):
        assert forbidden not in operational
    assert not re.search(r"^\s*(sleep|watch)\b", operational, flags=re.MULTILINE)


def test_script_requires_clean_exact_commit_and_atomic_receipt() -> None:
    script = _text()

    assert '"status", "--porcelain=v1", "--untracked-files=all"' in script
    assert "repository commit differs" in script
    assert 'with staging.open("xb")' in script
    assert "os.replace(staging, path)" in script
    assert '"passed": True' in script
