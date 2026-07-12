"""Milestone 1 governance artifact tests."""

import csv
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCUMENTS = [
    "AGENTS.md",
    "CLAUDE.md",
    "docs/research-charter.md",
    "docs/corpus-scope.md",
    "docs/data-sources.md",
    "docs/data-licensing.md",
    "docs/benchmark-design.md",
    "docs/tier1-quotation-curation.md",
    "docs/canonical-token-schema.md",
    "docs/normalization.md",
    "docs/novelty-review.md",
    "docs/prior-projects.md",
    "docs/decisions/README.md",
    "docs/decisions/0001-primary-corpus-boundary.md",
    "docs/decisions/0002-layered-corpus-strategy.md",
    "docs/decisions/0003-no-llm-primary-discovery.md",
    "docs/decisions/0004-local-first-architecture.md",
    "docs/decisions/0005-macula-hebrew-source-selection.md",
    "docs/decisions/0006-canonical-token-identifiers.md",
    "docs/decisions/0007-hebrew-normalization-policy.md",
    "docs/decisions/0008-methodology-amendments.md",
    "docs/decisions/0009-oshb-ketiv-qere-supplementation.md",
    "docs/decisions/0010-macula-greek-source-selection.md",
    "outputs/reports/milestone-2-hebrew-ingestion-report.md",
    "data/review/literature_matrix.csv",
    "data/benchmarks/tier1_quotations.csv",
]

LITERATURE_COLUMNS = {
    "citation_id",
    "citation",
    "year",
    "research_field",
    "corpus",
    "languages",
    "phenomenon",
    "textual_unit",
    "method",
    "supervised_or_unsupervised",
    "training_data",
    "benchmark",
    "evaluation_method",
    "expert_review",
    "code_available",
    "data_available",
    "claimed_novelty",
    "limitations",
    "relevance_to_project_echoes",
    "review_status",
    "notes",
}


@pytest.mark.parametrize("relative_path", REQUIRED_DOCUMENTS)
def test_required_governance_document_exists(relative_path: str) -> None:
    path = PROJECT_ROOT / relative_path

    assert path.is_file()
    assert path.stat().st_size > 0


def test_literature_matrix_has_required_columns_and_verified_seeds() -> None:
    matrix = PROJECT_ROOT / "data" / "review" / "literature_matrix.csv"
    with matrix.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert set(reader.fieldnames or []) == LITERATURE_COLUMNS
    assert len(rows) == 5
    assert {row["review_status"] for row in rows} == {"verified_primary_source"}
