"""
Tests for Reciprocal Rank Fusion (RRF) logic in HybridRetriever.
Run: python -m pytest tests/test_rrf_fusion.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from ai.rag.retriever import HybridRetriever


class TestRRFFusion:
    """HybridRetriever._rrf takes list[list[int]] → dict[int, float]"""

    def test_item_in_both_lists_scores_higher(self):
        # ID 1 appears rank-1 in both lists; ID 2 only in first
        scores = HybridRetriever._rrf([[1, 2, 3], [1, 4, 5]])
        assert scores[1] > scores[2], "ID appearing in both lists should score higher"

    def test_all_ids_present_in_output(self):
        scores = HybridRetriever._rrf([[1, 2], [3, 4]])
        assert set(scores.keys()) == {1, 2, 3, 4}

    def test_empty_lists_return_empty_dict(self):
        scores = HybridRetriever._rrf([])
        assert scores == {}

    def test_single_list_scores_decrease_with_rank(self):
        scores = HybridRetriever._rrf([[10, 20, 30]])
        assert scores[10] > scores[20] > scores[30]

    def test_score_is_sum_of_reciprocal_ranks(self):
        # ID 5 is rank-1 in list A (1/(60+1)) and rank-2 in list B (1/(60+2))
        scores = HybridRetriever._rrf([[5, 6], [7, 5]])
        expected = 1 / (60 + 1) + 1 / (60 + 2)
        assert abs(scores[5] - expected) < 1e-9

    def test_rank1_beats_rank2_single_list(self):
        scores = HybridRetriever._rrf([[100, 200]])
        assert scores[100] > scores[200]

    def test_handles_duplicate_ids_across_lists(self):
        scores = HybridRetriever._rrf([[1, 2], [1, 2], [1, 2]])
        # All three lists rank 1 first — score should be 3 * 1/(60+1)
        expected = 3 * (1 / 61)
        assert abs(scores[1] - expected) < 1e-9
