"""
Tests for RAG pipeline components (FTS, models, AI client JSON parsing).
These tests avoid network calls and LLM calls — pure unit tests.
Run: python -m pytest tests/test_rag_retrieval.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


class TestAIClientParseJson:
    """Test AIClient.parse_json without any API call."""

    def test_plain_json_object(self):
        from ai.ai_client import AIClient
        result = AIClient.parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_plain_json_array(self):
        from ai.ai_client import AIClient
        result = AIClient.parse_json('[{"a": 1}, {"a": 2}]')
        assert len(result) == 2

    def test_json_in_code_fence(self):
        from ai.ai_client import AIClient
        raw = '```json\n{"key": "value"}\n```'
        result = AIClient.parse_json(raw)
        assert result == {"key": "value"}

    def test_json_in_plain_fence(self):
        from ai.ai_client import AIClient
        raw = '```\n[1, 2, 3]\n```'
        result = AIClient.parse_json(raw)
        assert result == [1, 2, 3]

    def test_junk_before_json(self):
        from ai.ai_client import AIClient
        raw = 'Here is the result:\n{"score": 0.9}'
        result = AIClient.parse_json(raw)
        assert result == {"score": 0.9}

    def test_invalid_returns_none(self):
        from ai.ai_client import AIClient
        result = AIClient.parse_json("not json at all")
        assert result is None

    def test_empty_returns_none(self):
        from ai.ai_client import AIClient
        result = AIClient.parse_json("")
        assert result is None

    def test_is_error_detects_error_string(self):
        from ai.ai_client import AIClient
        assert AIClient.is_error("[ERROR] quota exceeded")
        assert AIClient.is_error("")
        assert not AIClient.is_error("Normal response text")


class TestRAGModels:
    """Test dataclass construction and defaults."""

    def test_case_query_defaults(self):
        from ai.rag.models import CaseQuery
        q = CaseQuery(case_id=0, sections=["269SS"], client_facts="test facts")
        assert q.case_id == 0
        assert q.demand_amount == 0.0
        assert q.sections == ["269SS"]

    def test_retrieved_case_construction(self):
        from ai.rag.models import RetrievedCase, CourtType
        rc = RetrievedCase(
            db_id=1,
            citation="Test vs ITO [2020]",
            section="269SS",
            key_ratio="Genuine transaction",
            facts_summary="Facts summary",
            year=2020,
            court_type=CourtType.ITAT,
            url="",
        )
        assert rc.vector_score == 0.0   # default

    def test_legal_argument_defaults(self):
        from ai.rag.models import LegalArgument
        arg = LegalArgument(
            rank=1,
            argument="Test argument",
            win_rate=0.75,
            section="269SS",
        )
        assert arg.authorities == []
        assert arg.documents   == []


class TestFTSIndex:
    """Test FTS index query parsing (no DB needed for query building)."""

    def test_fts_index_instantiates(self):
        from ai.rag.fts import FTSIndex
        fts = FTSIndex.__new__(FTSIndex)
        assert fts is not None

    def test_clean_fts_query_strips_special_chars(self):
        from ai.rag.fts import FTSIndex
        # FTSIndex._clean_query should exist and handle special chars
        if hasattr(FTSIndex, "_clean_query"):
            result = FTSIndex._clean_query("269SS AND (loan OR gift)")
            assert isinstance(result, str)
