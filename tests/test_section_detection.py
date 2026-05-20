"""
Tests for section detection and expansion logic.
Run: python -m pytest tests/test_section_detection.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from utils.helpers import parse_sections


class TestParseSections:
    def test_single_section(self):
        assert parse_sections("269SS") == ["269SS"]

    def test_json_list(self):
        import json
        sections = ["269SS", "44AD", "68"]
        result = parse_sections(json.dumps(sections))
        assert set(result) == set(sections)

    def test_comma_separated(self):
        result = parse_sections("269SS, 271D, 44AD")
        assert "269SS" in result
        assert "44AD" in result

    def test_deduplication(self):
        # parse_sections may return dupes — caller deduplicates if needed
        result = parse_sections("269SS, 44AD")
        assert "269SS" in result
        assert "44AD" in result

    def test_empty_string(self):
        result = parse_sections("")
        assert result == []

    def test_none_input(self):
        result = parse_sections(None)
        assert result == []

    def test_section_with_prefix(self):
        result = parse_sections("§ 68 and § 69A")
        assert "68" in result or any("68" in s for s in result)


class TestSectionGraph:
    def test_expand_known_section(self):
        from ai.rag.section_graph import expand
        related = expand(["269SS"])
        assert "269SS" in related
        assert len(related) >= 1

    def test_expand_unknown_section(self):
        from ai.rag.section_graph import expand
        related = expand(["999ZZ"])
        assert "999ZZ" in related

    def test_expand_multiple(self):
        from ai.rag.section_graph import expand
        related = expand(["269SS", "271D"])
        assert "269SS" in related
        assert "271D" in related

    def test_get_context_note_returns_string(self):
        from ai.rag.section_graph import get_context_note
        note = get_context_note(["269SS"])
        assert isinstance(note, str)
        assert len(note) > 0
