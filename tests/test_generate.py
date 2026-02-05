"""Tests for generate.py — agent loop logic.  All LLM calls are mocked."""

import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from src.generate import (
    EvaluationScores,
    KeyPointsOutput,
    SectionKeyPoints,
    run_generation,
)
from src.utility.llm_utility import (
    _llm_call_budget,
    log_llm_call,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _mock_result(data, usage_req=100, usage_res=200):
    """Create a minimal mock RunResult."""
    result = MagicMock()
    result.output = data
    usage = MagicMock()
    usage.input_tokens = usage_req
    usage.output_tokens = usage_res
    result.usage.return_value = usage
    return result


def _passing_scores():
    return EvaluationScores(
        teachability=9,
        conversational_feel=9,
        friction_disagreement=8,
        takeaway_clarity=9,
        accuracy=9,
        coverage=9,
        overall=8.9,
        feedback="Looks great.",
    )


def _low_scores():
    return EvaluationScores(
        teachability=5,
        conversational_feel=5,
        friction_disagreement=4,
        takeaway_clarity=5,
        accuracy=6,
        coverage=4,
        overall=5.0,
        feedback="Needs improvement.",
    )


def _sample_passages():
    return OrderedDict(
        [
            (
                "Section A",
                {"start_page": 1, "end_page": 5, "text": "--- Page 1 ---\nSample content."},
            )
        ]
    )


def _mock_key_points():
    return KeyPointsOutput(sections=[
        SectionKeyPoints(section="Section A", points=["Sample content point."]),
    ])


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_budget():
    """Reset the LLM call budget before every test."""
    from src.app_config import MAX_LLM_CALLS

    _llm_call_budget["remaining"] = MAX_LLM_CALLS
    yield


@pytest.fixture(autouse=True)
def _patch_prompts():
    """Make load_prompt return a simple template for all prompt names."""

    def _loader(name):
        templates = {
            "extract_key_points": "Extract: {{source_text}}",
            "generate": "Generate podcast from: {{source_text}} target: {{target_word_count}} checklist: {{key_points_checklist}}",
            "evaluate": "Evaluate: {{script}} source: {{source_text}}",
            "improve": "Improve: {{script}} scores: {{scores}} source: {{source_text}} checklist: {{key_points_checklist}}",
        }
        return templates.get(name, "")

    with patch("src.generate.load_prompt", side_effect=_loader):
        yield


# ── tests ──────────────────────────────────────────────────────────────────


@patch("src.generate.Registry.get_agent")  # prevent real Agent / OpenAI init
class TestAgentLoop:
    @patch("src.generate.log_llm_call")
    @patch("src.generate._run_with_retry")
    def test_loop_stops_when_score_meets_threshold(self, mock_run, mock_log, _mock_agent):
        """Loop exits after evaluation returns overall ≥ SCORE_THRESHOLD."""
        mock_run.side_effect = [
            _mock_result(_mock_key_points()),       # key_points
            _mock_result("Draft script"),           # generator
            _mock_result(_passing_scores()),        # evaluator → passes
        ]

        with patch("src.generate.SCORE_THRESHOLD", 8):
            script = run_generation(_sample_passages())

        assert script == "Draft script"
        # key_points + generator + evaluator = 3 calls; improver never called
        assert mock_run.call_count == 3

    @patch("src.generate.log_llm_call")
    @patch("src.generate._run_with_retry")
    def test_loop_stops_at_max_iterations(self, mock_run, mock_log, _mock_agent):
        """Loop exits after MAX_AGENT_ITERATIONS even if score stays low."""
        max_iter = 2
        side_effects = [_mock_result(_mock_key_points()), _mock_result("Draft")]  # key_points + generator
        for _ in range(max_iter):
            side_effects.append(_mock_result(_low_scores()))   # evaluator
            side_effects.append(_mock_result("Improved draft"))  # improver
        mock_run.side_effect = side_effects

        with patch("src.generate.MAX_AGENT_ITERATIONS", max_iter), \
             patch("src.generate.SCORE_THRESHOLD", 100):  # threshold unreachable
            script = run_generation(_sample_passages())

        assert script == "Improved draft"
        # 1 (key_points) + 1 (gen) + 2*(eval+improve) = 6
        assert mock_run.call_count == 2 + max_iter * 2

    @patch("src.generate.log_llm_call")
    @patch("src.generate._run_with_retry")
    def test_improver_not_called_when_score_sufficient(self, mock_run, mock_log, _mock_agent):
        """If first evaluation passes, Improver is never invoked."""
        mock_run.side_effect = [
            _mock_result(_mock_key_points()),       # key_points
            _mock_result("Good script"),
            _mock_result(_passing_scores()),
        ]

        with patch("src.generate.SCORE_THRESHOLD", 8):
            run_generation(_sample_passages())

        # key_points + generator + evaluator
        assert mock_run.call_count == 3

    @patch("src.generate.log_llm_call")
    @patch("src.generate._run_with_retry")
    def test_generator_called_exactly_once(self, mock_run, mock_log, _mock_agent):
        """Generator runs only at the start, not inside the loop."""
        mock_run.side_effect = [
            _mock_result(_mock_key_points()),       # key_points
            _mock_result("Draft"),
            _mock_result(_low_scores()),
            _mock_result("Improved"),
            _mock_result(_passing_scores()),
        ]

        with patch("src.generate.MAX_AGENT_ITERATIONS", 5), \
             patch("src.generate.SCORE_THRESHOLD", 8):
            run_generation(_sample_passages())

        # Call sequence: key_points, gen, eval, improve, eval → 5 total
        # key_points and generator are each called once only.
        assert mock_run.call_count == 5


class TestLLMLog:
    def test_llm_log_entries_written(self, tmp_path):
        """Each log_llm_call produces a valid JSON line."""
        log_file = tmp_path / "llm_log.json"

        with patch("src.utility.llm_utility.LLM_LOG_FILE", log_file), \
             patch("src.utility.llm_utility.OUTPUT_DIR", tmp_path):
            result = _mock_result("test output")
            log_llm_call("generator", 0, "prompt text", result)

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["agent"] == "generator"
        assert entry["iteration"] == 0
        assert entry["prompt_length_chars"] == len("prompt text")
        assert entry["response_length_chars"] == len("test output")
        assert "usage" in entry
        assert entry["scores"] is None
