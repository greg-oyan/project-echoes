"""Governance gates for Milestone 4 closure and the Milestone 5 handoff."""

from __future__ import annotations

from pathlib import Path

from echoes.manifests.sources import SourceStatus, load_source_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _milestone_block(number: int, next_number: int) -> str:
    plan = (PROJECT_ROOT / "docs" / "master-plan.md").read_text(encoding="utf-8")
    start = plan.index(f"## Milestone {number}:")
    end = plan.index(f"## Milestone {next_number}:", start)
    return plan[start:end]


def test_stepbible_deferral_adr_is_accepted_and_owner_authorized() -> None:
    adr = (PROJECT_ROOT / "docs" / "decisions" / "0012-defer-stepbible-activation.md").read_text(
        encoding="utf-8"
    )
    normalized_adr = " ".join(adr.split())

    assert "- Status: Accepted" in adr
    assert "- executing_agent: Codex" in adr
    assert "project owner authorized this deferral before execution" in normalized_adr
    assert "does not constitute rejection" in normalized_adr
    assert "licensing determination" in normalized_adr
    for required in (
        "A specific missing field or capability",
        "The exact STEPBible files required",
        "A measurable benefit",
        "Completed file-level licensing and provenance review",
        "A conflict-preserving integration design",
    ):
        assert required in adr


def test_stepbible_manifest_remains_inactive_with_seven_open_questions() -> None:
    source = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml").find(
        "stepbible-data"
    )

    assert source is not None
    assert source.status is SourceStatus.UNDER_REVIEW
    assert source.version_or_commit is None
    assert source.download_date is None
    assert source.expected_files == []
    assert source.file_hashes == {}
    assert source.ingest_adapter is None
    assert source.acquisition is None
    assert len(source.unresolved_questions) == 7
    assert any("ADR 0012" in note and "deferred" in note for note in source.notes)


def test_milestone_four_gate_uses_completed_generic_infrastructure() -> None:
    milestone = _milestone_block(4, 5)

    assert "* STEPBible adapter" not in milestone
    assert "Status: **Complete as of 2026-07-12**" in milestone
    for required in (
        "OSHB Ketiv/Qere supplementary tokens",
        "Supplementary annotation-alignment tables",
        "Conflict-preservation and uncertainty-query logic",
        "Ketiv structural-alignment mappings",
        "Separate versification-crosswalk mapping layer",
        "Source-native identity preservation",
        "Explicit unresolved-alignment reporting",
        "Deferred optional STEPBible activation governed by ADR 0012",
        "Supplementary data never overwrites primary annotations",
        "Primary Hebrew and Greek identity, surface/lemma, and analytical digests remain unchanged",
        "Any future supplementary source requires a demonstrated downstream need",
    ):
        assert required in milestone


def test_milestone_five_handoff_preserves_structural_uncertainty() -> None:
    milestone = _milestone_block(5, 6)
    normalized_milestone = " ".join(milestone.lower().split())
    segmentation = (PROJECT_ROOT / "docs" / "segmentation.md").read_text(encoding="utf-8")

    for required in (
        "default qere stream retains complete primary macula",
        "verse-level ketiv analysis includes every ketiv token",
        "sentence-level ketiv analysis may use the completed sentence mappings",
        "never fabricate membership for unresolved mappings",
        "ketiv_structural_uncertainty",
        "tokens remain visible in the corpus and verse-level analysis",
        "adr 0011 remains binding",
        "mrk 16:20",
        "mrk 16:99",
    ):
        assert required in normalized_milestone
    assert "no multi-verse passage at any granularity contains both" in normalized_milestone
    assert "no passage generation is implemented" in segmentation.lower()


def test_execution_plan_keeps_stepbible_questions_open() -> None:
    execution = (PROJECT_ROOT / "docs" / "milestone-4-execution-plan.md").read_text(
        encoding="utf-8"
    )

    assert "Status: **Complete" in execution
    assert "## Completed OSHB work" in execution
    assert "## Completed generic alignment infrastructure" in execution
    assert "## Deferred STEPBible work" in execution
    assert "## Future activation criteria" in execution
    assert "## Unresolved STEPBible subset-audit questions" in execution
    assert "none is resolvable by automation" in execution
    assert "None of the seven STEPBible questions is answered by deferral" in execution
