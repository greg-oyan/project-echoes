"""Static contracts for the bounded final-discovery knownness retry."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "retry_final_discovery_knownness.py"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_retry_script_is_valid_python_and_has_separate_modes() -> None:
    script = _text()

    ast.parse(script)
    assert "--preflight-only" in script
    assert "--execute" in script
    assert "PREFLIGHT_COMPLETE" in script
    assert "KNOWNNESS_RETRY_COMPLETE" in script


def test_retry_uses_four_gib_duckdb_ceiling() -> None:
    script = _text()

    assert "KNOWNNESS_MEMORY_LIMIT_BYTES: Final = 4 * 1024**3" in script
    assert "memory_limit_bytes=KNOWNNESS_MEMORY_LIMIT_BYTES" in script
    assert "1 * 1024**3" not in script
    assert "memory_limit_bytes=1024**3" not in script


def test_retry_reuses_exact_passage_cache_and_pins_knownness_contract() -> None:
    script = _text()

    for fragment in (
        '("hebrew", "edition_complete", "qere"): 23_213',
        '("greek", "edition_complete", "source"): 7_943',
        '("hebrew", "edition_complete", "ketiv"): 23_213',
        '("greek", "critical_core", "source"): 7_918',
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
    assert "read_passage_records_jsonl" in script
    assert "authenticate_knownness_jsonl" in script


def test_retry_finalizes_through_normal_preparation_script() -> None:
    script = _text()

    assert 'normal_script = root / "scripts" / "prepare_final_discovery_inputs.py"' in script
    assert '"--execute"' in script
    assert "normal preparation receipt was not committed" in script


def test_retry_never_manages_cloud_or_launches_campaign() -> None:
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


def test_retry_requires_clean_exact_commit_and_safe_pair_state() -> None:
    script = _text()

    assert '"status", "--porcelain=v1", "--untracked-files=all"' in script
    assert "repository commit differs" in script
    assert "knownness JSONL and receipt must be both absent or both present" in script
    assert "less than 20 GiB free disk" in script
