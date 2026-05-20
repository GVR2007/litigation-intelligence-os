"""
Tests for the two-stage AO order fact extractor.
Run: python -m pytest tests/test_case_extractor.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from utils.case_extractor import detect_ao_structure, _extract_additions_regex


# Minimal synthetic AO order text for unit testing (no LLM call needed)
_SAMPLE_AO_TEXT = """
ORDER

BRIEF FACTS OF THE CASE

The assessee is engaged in the business of civil construction. During the year under
consideration, the assessee received cash loans from family members.

ASSESSEE SUBMISSIONS

The assessee submitted bank statements, confirmation letters, and PAN details of lenders.
The affidavit from lenders was also submitted.

AO FINDINGS

The AO was not satisfied with the explanation. The lenders were not produced for examination.
Accordingly, an addition of Rs. 15,00,000 under section 269SS was made.
Further, an addition of Rs. 8,50,000 was made under section 68 for unexplained cash credits.

The total demand raised amounts to Rs. 23,50,000.
"""


class TestDetectAOStructure:
    def test_returns_dict(self):
        result = detect_ao_structure(_SAMPLE_AO_TEXT)
        assert isinstance(result, dict)

    def test_detects_brief_facts(self):
        result = detect_ao_structure(_SAMPLE_AO_TEXT)
        assert "brief_facts" in result
        assert len(result["brief_facts"]) > 20

    def test_detects_additions(self):
        result = detect_ao_structure(_SAMPLE_AO_TEXT)
        assert "additions" in result

    def test_detects_assessee_submissions(self):
        result = detect_ao_structure(_SAMPLE_AO_TEXT)
        assert "assessee_submissions" in result

    def test_empty_text_returns_empty_dict(self):
        result = detect_ao_structure("")
        assert isinstance(result, dict)

    def test_short_text_does_not_crash(self):
        result = detect_ao_structure("ORDER\nThe assessee.")
        assert isinstance(result, dict)


class TestExtractAdditionsRegex:
    def test_finds_section_269ss_addition(self):
        additions = _extract_additions_regex(_SAMPLE_AO_TEXT)
        sections = [a["section"] for a in additions]
        assert "269SS" in sections

    def test_finds_section_68_addition(self):
        additions = _extract_additions_regex(_SAMPLE_AO_TEXT)
        sections = [a["section"] for a in additions]
        assert "68" in sections

    def test_extracts_amount(self):
        additions = _extract_additions_regex(_SAMPLE_AO_TEXT)
        amounts = [a["amount"] for a in additions]
        assert any(a > 0 for a in amounts)

    def test_returns_list(self):
        result = _extract_additions_regex(_SAMPLE_AO_TEXT)
        assert isinstance(result, list)

    def test_empty_text_returns_empty_list(self):
        result = _extract_additions_regex("")
        assert result == []

    def test_no_additions_text(self):
        result = _extract_additions_regex("The appeal is allowed. No additions made.")
        assert isinstance(result, list)
