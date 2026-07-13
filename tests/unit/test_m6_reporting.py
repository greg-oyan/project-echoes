"""Fail-closed Milestone 6 report and spot-check contracts."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from echoes.benchmarks.models import BENCHMARK_ARTIFACT_NAMES
from echoes.benchmarks.tier1 import Tier1ValidationError


def _script(name: str) -> ModuleType:
    scripts = str(Path("scripts").resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module(name)


def _hash_manifest(value: str) -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "table_counts": {name: 1 for name in BENCHMARK_ARTIFACT_NAMES},
        "table_logical_sha256": {name: value * 64 for name in BENCHMARK_ARTIFACT_NAMES},
        "table_physical_sha256": {name: value * 64 for name in BENCHMARK_ARTIFACT_NAMES},
    }


def test_two_run_determinism_requires_logical_and_expected_physical_hashes(
    tmp_path: Path,
) -> None:
    report = _script("generate_m6_report")
    first = _hash_manifest("a")
    first_path = tmp_path / "first.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    current = _hash_manifest("a")
    current_physical = current["table_physical_sha256"]
    assert isinstance(current_physical, dict)
    current_physical["benchmark_metadata"] = "b" * 64

    status, _ = report._determinism(current, first_path)
    current_physical["benchmark_relationships"] = "b" * 64
    failed, _ = report._determinism(current, first_path)

    assert status == "passed"
    assert failed == "failed"


def test_spot_check_config_covers_every_required_criterion(tmp_path: Path) -> None:
    spot = _script("generate_m6_spot_check_evidence")
    canonical = Path("outputs/reports/m6-spot-check-config.json")
    criteria = spot._load_criteria(canonical)
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    payload["criteria"] = payload["criteria"][:-1]
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(payload), encoding="utf-8")

    assert len(criteria) == 21
    with pytest.raises(ValueError, match="omits required criteria"):
        spot._load_criteria(incomplete)


def test_spot_check_tier1_evidence_uses_strict_placeholder_validator(tmp_path: Path) -> None:
    spot = _script("generate_m6_spot_check_evidence")
    invalid = tmp_path / "tier1.csv"
    invalid.write_text("quotation_id\n   \n", encoding="utf-8")

    with pytest.raises(Tier1ValidationError):
        spot._tier1_evidence(invalid, "0" * 64)


def test_spot_check_manual_review_is_fail_closed_and_dated() -> None:
    spot = _script("generate_m6_spot_check_evidence")

    assert (
        "`PENDING`"
        in spot._manual_review_lines(
            reviewer=None,
            review_date=None,
            verdict="pending",
        )[0]
    )
    passed = spot._manual_review_lines(
        reviewer="Codex",
        review_date="2026-07-12",
        verdict="passed",
    )
    assert any("`PASS`" in line for line in passed)
    assert any("`Codex`" in line for line in passed)
    with pytest.raises(ValueError, match="requires a reviewer"):
        spot._manual_review_lines(
            reviewer=None,
            review_date="2026-07-12",
            verdict="passed",
        )
    with pytest.raises(ValueError, match="ISO"):
        spot._manual_review_lines(
            reviewer="Codex",
            review_date="July 12",
            verdict="passed",
        )


@pytest.mark.parametrize(
    "forbidden",
    (
        "- Biblical text: forbidden",
        "- Surface: forbidden",
        "- Lemma: forbidden",
        "| Source text | forbidden |",
    ),
)
def test_spot_check_evidence_rejects_text_bearing_fields(forbidden: str) -> None:
    spot = _script("generate_m6_spot_check_evidence")

    with pytest.raises(ValueError, match="prohibited text-bearing fields"):
        spot._assert_content_boundary(forbidden)
    spot._assert_content_boundary(
        "- Original source references: `Gen.1.1` / `John.1.1`\n"
        "- Content boundary: no biblical quotation text is reproduced.\n"
    )


def test_report_tracks_reference_level_risks_and_inline_distributions() -> None:
    source = Path("scripts/generate_m6_report.py").read_text(encoding="utf-8")

    assert "m6-versification-risk-references.csv" in source
    assert "### Corpus-pair distribution" in source
    assert '"Strategy", "Partition", "Eligibility"' in source
    assert '"Negative strategy", "Split strategy", "Partition", "Count"' in source
    assert "GitHub Actions evidence is absent or not passed" in source
