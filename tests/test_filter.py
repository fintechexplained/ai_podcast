"""Tests for filter.py — section resolution logic."""

import pytest

from src.filter import SectionNotFoundError, resolve


@pytest.fixture
def extracted(sample_extracted_data):
    """Alias that keeps tests short."""
    return sample_extracted_data


class TestExactAndFuzzyMatch:
    def test_exact_name_match(self, extracted):
        """Config name that exactly equals an extracted section title."""
        sections = [{"name": "Financial Highlights", "page_override": None}]
        result = resolve(extracted, sections)
        assert "Financial Highlights" in result
        assert result["Financial Highlights"]["start_page"] == 10
        assert result["Financial Highlights"]["end_page"] == 14

    def test_fuzzy_substring_match(self, extracted):
        """'Financial' is a substring of 'Financial Highlights' → matches."""
        sections = [{"name": "Financial", "page_override": None}]
        result = resolve(extracted, sections)
        assert "Financial" in result
        assert result["Financial"]["start_page"] == 10

    def test_reverse_substring_match(self, extracted):
        """Extracted title 'Risk Management' is a substring check against
        config name 'Risk Management Plan' — the extracted title IS a
        substring of the config name, so it matches."""
        sections = [{"name": "Risk Management Plan", "page_override": None}]
        result = resolve(extracted, sections)
        assert "Risk Management Plan" in result
        assert result["Risk Management Plan"]["start_page"] == 70


class TestPageOverrides:
    def test_page_override_takes_priority(self, extracted):
        """Explicit page range overrides detected section boundaries."""
        sections = [{"name": "Financial Highlights", "page_override": "12-13"}]
        result = resolve(extracted, sections)
        assert result["Financial Highlights"]["start_page"] == 12
        assert result["Financial Highlights"]["end_page"] == 13

    def test_single_page_override(self, extracted):
        """'42' resolves to pages 42–42."""
        sections = [{"name": "Sustainability", "page_override": "42"}]
        result = resolve(extracted, sections)
        assert result["Sustainability"]["start_page"] == 42
        assert result["Sustainability"]["end_page"] == 42


class TestErrorCases:
    def test_no_match_raises(self, extracted):
        """A name with zero overlap raises SectionNotFoundError."""
        sections = [{"name": "Completely Made Up Section", "page_override": None}]
        with pytest.raises(SectionNotFoundError, match="Completely Made Up Section"):
            resolve(extracted, sections)

    def test_empty_section_list(self, extracted):
        """Empty input list returns empty result without error."""
        result = resolve(extracted, [])
        assert len(result) == 0


class TestTextCollection:
    def test_text_includes_page_markers(self, extracted):
        """Collected text has '--- Page N ---' markers for each page."""
        sections = [{"name": "Financial Highlights", "page_override": "10-11"}]
        result = resolve(extracted, sections)
        text = result["Financial Highlights"]["text"]
        assert "--- Page 10 ---" in text
        assert "--- Page 11 ---" in text
        assert "Content for page 10" in text
        assert "Content for page 11" in text

    def test_best_match_picks_greatest_overlap(self, extracted):
        """When multiple sections partially match, greatest overlap wins.

        'Revenue' matches both 'Revenue Breakdown' (overlap=7) and
        potentially nothing else — it should pick Revenue Breakdown.
        """
        sections = [{"name": "Revenue", "page_override": None}]
        result = resolve(extracted, sections)
        # 'Revenue' is substring of 'Revenue Breakdown' → match
        assert result["Revenue"]["start_page"] == 11
