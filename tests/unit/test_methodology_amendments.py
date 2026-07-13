"""Governance gates for the approved pre-Milestone-3 amendments."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from echoes.manifests.sources import (
    LicenseReviewStatus,
    RedistributionStatus,
    SourceRole,
    SourceStatus,
    load_source_catalog,
)
from echoes.settings import ScoringConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIER1_COLUMNS = [
    "quotation_id",
    "nt_reference",
    "ot_reference",
    "ot_source_tradition",
    "relationship_class",
    "quotation_marker",
    "curation_source",
    "source_public_domain_status",
    "curator",
    "review_status",
    "notes",
]


def test_master_plan_keeps_milestone_numbers_and_blank_time_budgets() -> None:
    plan = (PROJECT_ROOT / "docs" / "master-plan.md").read_text(encoding="utf-8")
    sections = re.findall(
        r"(?ms)^## Milestone (\d+):.*?(?=^## Milestone |^---\n\n# 35\.)",
        plan,
    )

    assert [int(number) for number in sections] == list(range(17))
    milestone_blocks = re.findall(
        r"(?ms)^## Milestone \d+:.*?(?=^## Milestone |^---\n\n# 35\.)",
        plan,
    )
    assert len(milestone_blocks) == 17
    assert all(len(re.findall(r"(?m)^time_budget:\s*$", block)) == 1 for block in milestone_blocks)


def test_master_plan_contains_the_approved_methodological_gates() -> None:
    plan = (PROJECT_ROOT / "docs" / "master-plan.md").read_text(encoding="utf-8").lower()

    for required in (
        "source-edition-only token-id generation",
        "analysis_position_in_corpus",
        "openbible cross-reference source as a tier 3 resource",
        "frequency-preserving synthetic-passage null",
        "expected_cooccurrence_independence",
        "token-level hebrew-septuagint alignment is explicitly out of scope",
        "english-feature ablation",
        "pauline letters predate the written canonical gospels",
        "output j: milestone 8 top-100 review and false-positive taxonomy",
    ):
        assert required in plan


def test_agent_handoffs_are_identical_thin_master_plan_pointers() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert agents == claude
    assert "docs/master-plan.md" in agents
    assert "acceptance gate" in agents
    assert "restricted source data" in agents
    assert "docs/decisions/" in agents and "CHANGELOG.md" in agents
    assert len(agents.splitlines()) <= 8


def test_decision_template_and_amendment_record_executing_agent() -> None:
    template = (PROJECT_ROOT / "docs" / "decisions" / "README.md").read_text(encoding="utf-8")
    amendment = (PROJECT_ROOT / "docs" / "decisions" / "0008-methodology-amendments.md").read_text(
        encoding="utf-8"
    )

    assert "- executing_agent: Codex | Claude | ChatGPT | Human | Mixed" in template
    assert "- executing_agent: Codex" in amendment


def test_tier1_benchmark_is_header_only_with_the_governed_schema() -> None:
    path = PROJECT_ROOT / "data" / "benchmarks" / "tier1_quotations.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert rows == [TIER1_COLUMNS]


def test_amended_benchmark_source_governance_is_explicit() -> None:
    catalog = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml")
    openbible = catalog.find("openbible-cross-references")
    tier1 = catalog.find("project-echoes-tier1-quotations")

    assert openbible is not None and tier1 is not None
    assert openbible.role is SourceRole.BENCHMARK
    assert openbible.status in {SourceStatus.APPROVED, SourceStatus.VALIDATED}
    assert openbible.license_review_status is LicenseReviewStatus.COMPLETE
    assert openbible.redistribution_status is RedistributionStatus.PERMITTED
    assert "Tier 3" in openbible.research_purpose
    assert "not scholarly" in openbible.research_purpose
    assert tier1.role is SourceRole.BENCHMARK
    assert tier1.status is SourceStatus.PLANNED
    assert tier1.repository_or_location == "data/benchmarks/tier1_quotations.csv"
    assert any("header" in limitation for limitation in tier1.known_limitations)


def test_scoring_amendments_are_strict_disabled_placeholders() -> None:
    loaded = load_config(PROJECT_ROOT / "config" / "scoring.yaml")

    assert isinstance(loaded, ScoringConfig)
    assert not loaded.null_models.enabled
    assert loaded.null_models.repetitions is None
    assert {family.name for family in loaded.null_models.families} == {
        "within_book_reassignment",
        "frequency_preserving_synthetic_passages",
    }
    assert not loaded.rare_evidence.enabled
    assert loaded.rare_evidence.total_corpus_frequency_max == 3
    assert loaded.rare_evidence.require_independent_co_signal
    assert set(loaded.rare_evidence.planned_evidence_fields) == {
        "expected_cooccurrence_independence",
        "hypergeometric_p_value",
        "null_model_empirical_rate",
        "multiple_testing_adjustment",
    }
