"""Hard-bound tests for the registered whole-canon candidate universe."""

from __future__ import annotations

import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.scale import (
    EXPECTED_PRIMARY_PASSAGE_COUNT,
    CampaignScaleError,
    campaign_scale_contract,
    directional_top_k_pair_bound,
)


def test_frozen_whole_canon_scale_contract_has_exact_conservative_caps() -> None:
    contract = campaign_scale_contract(
        load_final_discovery_config(),
        primary_passage_count=EXPECTED_PRIMARY_PASSAGE_COUNT,
    )

    assert contract.maximum_pairs_per_sparse_retrieval == 498_496
    assert contract.maximum_pairs_per_embedding_retrieval == 498_496
    assert contract.maximum_stage_two_semantic_pairs == 1_495_488
    assert contract.maximum_stage_three_pairs == 1_595_488
    assert contract.maximum_stage_four_pairs == 498_496
    assert contract.maximum_stage_five_pairs == 498_496
    assert contract.maximum_retained_candidate_pairs == 2_592_480
    assert contract.maximum_stage_three_raw_evidence_rows == 7_630_731
    assert contract.maximum_stage_four_raw_evidence_rows == 996_992
    assert contract.maximum_stage_five_raw_evidence_rows == 498_496
    assert contract.maximum_stage_six_raw_evidence_rows == 2_592_480
    assert contract.maximum_total_raw_evidence_rows == 11_718_699
    assert contract.maximum_calibration_pair_strata == 6_633
    assert contract.maximum_calibration_detector_strata == 59_697
    assert contract.maximum_permutation_like_calibration_rows == 10_123_211
    assert contract.maximum_bootstrap_calibration_rows == 1_595_488
    assert contract.maximum_evidence_rows_per_pair == 9


def test_directional_pair_bound_caps_at_the_complete_pair_space() -> None:
    assert directional_top_k_pair_bound(4, 1) == 4
    assert directional_top_k_pair_bound(4, 99) == 6
    with pytest.raises(CampaignScaleError, match="at least two passages"):
        directional_top_k_pair_bound(1, 1)
