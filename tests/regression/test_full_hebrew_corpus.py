"""Optional regression gate for a locally acquired full MACULA Hebrew corpus."""

from __future__ import annotations

import os

import pytest

from echoes.corpus.hebrew import validate_existing_hebrew_corpus


@pytest.mark.full_corpus
@pytest.mark.skipif(
    os.environ.get("ECHOES_RUN_FULL_CORPUS") != "1",
    reason="set ECHOES_RUN_FULL_CORPUS=1 after local governed acquisition and ingestion",
)
def test_full_hebrew_corpus_passes_milestone_two_gate() -> None:
    report = validate_existing_hebrew_corpus()

    assert report.passed
    assert report.error_count == 0
    assert report.total_source_records == 475_911
    assert report.total_tokens == 475_911
    assert report.book_count == 39
    assert report.chapter_count == 929
