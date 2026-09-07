"""Regression coverage for canonical zero-based M7 evidence positions."""

from __future__ import annotations

import pytest

from echoes.final_discovery.m7_adapter import (
    M7AdapterError,
    _validate_shared_evidence_rows,
)
from echoes.lexical.models import LEXICAL_ARTIFACT_COLUMNS


def _shared_evidence_row(
    *,
    passage_a_positions_json: str = "[0]",
    passage_b_positions_json: str = "[0,2]",
) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": "M7EVID-0001",
        "candidate_pair_id": "M7PAIR-0001",
        "evidence_family": "lemma",
        "feature_id": "LF-0001",
        "feature_value": "say",
        "passage_a_positions_json": passage_a_positions_json,
        "passage_b_positions_json": passage_b_positions_json,
        "corpus_frequency": 2,
        "document_frequency": 2,
        "passage_a_local_frequency": 1,
        "passage_b_local_frequency": 2,
        "association_score": 0.5,
        "pmi": None,
        "log_likelihood": None,
        "frequency_control": None,
        "score_formula": "inverse_corpus_frequency_evidence_weight",
        "detector_contributions_json": '{"rare_lemma_root":0.5}',
        "independence_expected_count": 0.25,
        "contains_primary_rare_item": True,
        "counts_as_independent_co_signal": False,
        "english_derived": False,
        "notes": "zero-based position regression fixture",
    }
    assert set(row) == set(LEXICAL_ARTIFACT_COLUMNS["shared_evidence"])
    return row


def test_m7_adapter_accepts_canonical_zero_based_positions() -> None:
    row = _shared_evidence_row()

    ordered, digest = _validate_shared_evidence_rows(
        [row],
        candidate_pair_id_value="M7PAIR-0001",
        expected_count=1,
    )

    assert ordered == (row,)
    assert ordered[0]["passage_a_positions_json"] == "[0]"
    assert ordered[0]["passage_b_positions_json"] == "[0,2]"
    assert len(digest) == 64


@pytest.mark.parametrize("positions", ("[-1]", "[true]", "[]", "[0.5]"))
def test_m7_adapter_rejects_non_index_positions(positions: str) -> None:
    row = _shared_evidence_row(passage_a_positions_json=positions)

    with pytest.raises(M7AdapterError, match="invalid passage_a_positions_json"):
        _validate_shared_evidence_rows(
            [row],
            candidate_pair_id_value="M7PAIR-0001",
            expected_count=1,
        )
