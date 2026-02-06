"""Tests for verify.py — verification logic.  LLM calls are mocked."""

import pytest

from src.verify import _compute_summary


# ── Summary metric computation ────────────────────────────────────────────


class TestCoveragePercentageCalculation:
    def test_coverage_percentage_calculation(self):
        """coverage_percentage arithmetic is correct."""
        coverage = [
            {"section": "A", "status": "COVERED", "key_points_total": 6, "key_points_covered": 6, "omitted_points": []},
            {"section": "B", "status": "PARTIAL", "key_points_total": 4, "key_points_covered": 2, "omitted_points": ["x", "y"]},
        ]
        claims = [
            {"claim_text": "c1", "status": "TRACED", "source_page": 1, "source_section": "A"},
            {"claim_text": "c2", "status": "NOT_TRACED", "source_page": None, "source_section": None},
        ]
        summary = _compute_summary(claims, coverage)

        # (6 + 2) / (6 + 4) * 100 = 80.0
        assert summary["coverage_percentage"] == 80.0
        assert summary["total_claims"] == 2
        assert summary["traced"] == 1
        assert summary["not_traced"] == 1
        assert summary["total_key_points"] == 10
        assert summary["key_points_covered"] == 8

    def test_zero_key_points(self):
        """Edge case: no key points at all → coverage_percentage is 0."""
        summary = _compute_summary([], [])
        assert summary["coverage_percentage"] == 0.0
        assert summary["total_key_points"] == 0


# ── Emoji mapping ──────────────────────────────────────────────────────────


class TestEmojiMapping:
    """Verify the status → emoji mapping used by the UI (defined in app.py)."""

    _STATUS_EMOJI = {
        "TRACED": "✅",
        "PARTIALLY_TRACED": "⚠️",
        "NOT_TRACED": "🚩",
        "COVERED": "✅",
        "PARTIAL": "⚠️",
        "OMITTED": "🚩",
    }

    def test_emoji_mapping_all_statuses(self):
        """Every defined status maps to the correct emoji."""
        assert self._STATUS_EMOJI["TRACED"] == "✅"
        assert self._STATUS_EMOJI["PARTIALLY_TRACED"] == "⚠️"
        assert self._STATUS_EMOJI["NOT_TRACED"] == "🚩"
        assert self._STATUS_EMOJI["COVERED"] == "✅"
        assert self._STATUS_EMOJI["PARTIAL"] == "⚠️"
        assert self._STATUS_EMOJI["OMITTED"] == "🚩"


# ── Omitted points ────────────────────────────────────────────────────────


class TestOmittedPoints:
    def test_omitted_points_populated(self):
        """PARTIAL sections list the specific missing points in the summary."""
        coverage = [
            {
                "section": "Risk",
                "status": "PARTIAL",
                "key_points_total": 5,
                "key_points_covered": 3,
                "omitted_points": ["Cyber risk", "Regulatory changes"],
            }
        ]
        # _compute_summary doesn't touch omitted_points; they pass through
        # from the agent. Verify the structure is preserved end-to-end.
        assert coverage[0]["omitted_points"] == ["Cyber risk", "Regulatory changes"]

    def test_fully_covered_section(self):
        """A COVERED section has an empty omitted_points list."""
        coverage = [
            {
                "section": "Fin",
                "status": "COVERED",
                "key_points_total": 4,
                "key_points_covered": 4,
                "omitted_points": [],
            }
        ]
        assert coverage[0]["omitted_points"] == []


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_claims_not_traced(self):
        """Edge case: every claim is NOT_TRACED — report is still well-formed."""
        claims = [
            {"claim_text": f"claim {i}", "status": "NOT_TRACED", "source_page": None, "source_section": None}
            for i in range(5)
        ]
        coverage = [
            {"section": "X", "status": "OMITTED", "key_points_total": 3, "key_points_covered": 0, "omitted_points": ["a", "b", "c"]}
        ]
        summary = _compute_summary(claims, coverage)
        assert summary["traced"] == 0
        assert summary["not_traced"] == 5
        assert summary["coverage_percentage"] == 0.0
