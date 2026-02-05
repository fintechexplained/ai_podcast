"""Integration tests for generate.py using pydantic-ai TestModel.

These tests exercise the real Agent.run_sync → AgentRunResult.output path
without hitting the OpenAI API.  They catch breakage caused by pydantic-ai
version upgrades (e.g. the 0.x → 1.x rename of .data → .output).
"""

from collections import OrderedDict
from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from src.generate import (
    EvaluationScores,
    KeyPointsOutput,
    run_generation,
)
from src.register import Registry
from src.utility.llm_utility import _llm_call_budget


# ── shared helpers ─────────────────────────────────────────────────────────


def _sample_passages() -> OrderedDict:
    return OrderedDict(
        [
            (
                "Financials",
                {"start_page": 1, "end_page": 3, "text": "Revenue was $10 B."},
            ),
            (
                "Strategy",
                {"start_page": 4, "end_page": 6, "text": "We plan to expand into Asia."},
            ),
        ]
    )


def _passing_scores_dict() -> dict:
    """Args for TestModel(custom_output_args=…) that produce an EvaluationScores
    with overall ≥ SCORE_THRESHOLD (default 8)."""
    return {
        "teachability": 9,
        "conversational_feel": 9,
        "friction_disagreement": 8,
        "takeaway_clarity": 9,
        "accuracy": 9,
        "coverage": 9,
        "overall": 9.0,
        "feedback": "Solid draft.",
    }


def _low_scores_dict() -> dict:
    return {
        "teachability": 4,
        "conversational_feel": 4,
        "friction_disagreement": 3,
        "takeaway_clarity": 4,
        "accuracy": 5,
        "coverage": 3,
        "overall": 4.0,
        "feedback": "Needs work.",
    }


def _key_points_dict() -> dict:
    """Args for TestModel that produce a valid KeyPointsOutput."""
    return {
        "sections": [
            {"section": "Financials", "points": ["Revenue was $10 B.", "Growth was positive."]},
            {"section": "Strategy", "points": ["Plan to expand into Asia."]},
        ],
    }


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_agent_cache():
    """Clear the agent registry before every test so each test can
    inject fresh agents with the desired TestModel."""
    Registry._agents.clear()
    yield
    Registry._agents.clear()


@pytest.fixture(autouse=True)
def _reset_budget():
    from src.app_config import MAX_LLM_CALLS

    _llm_call_budget["remaining"] = MAX_LLM_CALLS
    yield


@pytest.fixture(autouse=True)
def _patch_prompts():
    """Stub prompt templates so the tests don't depend on prompts/ files."""

    def _loader(name: str) -> str:
        return {
            "extract_key_points": "Extract: {{source_text}}",
            "generate": "Generate: {{source_text}} words={{target_word_count}} checklist={{key_points_checklist}}",
            "evaluate": "Evaluate: {{script}} src={{source_text}}",
            "improve": "Improve: {{script}} scores={{scores}} src={{source_text}} checklist={{key_points_checklist}}",
        }.get(name, "")

    with patch("src.generate.load_prompt", side_effect=_loader):
        yield


# ── tests ──────────────────────────────────────────────────────────────────


class TestGeneratorAgent:
    """Generator agent returns its output via AgentRunResult.output (str)."""

    def test_generator_output_is_str(self):
        """run_generation returns a string when the score passes immediately."""
        gen_text = "Alex: Let's talk about revenue. Jordan: Sure."
        Registry.register_agent("key_points", _make_agent(
            TestModel(custom_output_args=_key_points_dict()),
            output_type=KeyPointsOutput,
        ))
        Registry.register_agent("generator", _make_agent(TestModel(custom_output_text=gen_text)))
        Registry.register_agent("evaluator", _make_agent(
            TestModel(custom_output_args=_passing_scores_dict()),
            output_type=EvaluationScores,
        ))

        with patch("src.generate.log_llm_call"):
            script = run_generation(_sample_passages())

        assert script == gen_text

    def test_generator_output_contains_source_content(self):
        """The generator prompt receives source text; verify the agent is actually
        invoked (output is not empty)."""
        Registry.register_agent("key_points", _make_agent(
            TestModel(custom_output_args=_key_points_dict()),
            output_type=KeyPointsOutput,
        ))
        Registry.register_agent("generator", _make_agent(
            TestModel(custom_output_text="Revenue discussion here.")
        ))
        Registry.register_agent("evaluator", _make_agent(
            TestModel(custom_output_args=_passing_scores_dict()),
            output_type=EvaluationScores,
        ))

        with patch("src.generate.log_llm_call"):
            script = run_generation(_sample_passages())

        assert len(script) > 0


class TestEvaluatorAgent:
    """Evaluator returns EvaluationScores via AgentRunResult.output (BaseModel)."""

    def test_evaluator_scores_parsed_correctly(self):
        """When the evaluator returns a passing score the loop exits after one
        evaluation — confirming the Pydantic model was correctly deserialised
        from AgentRunResult.output."""
        Registry.register_agent("key_points", _make_agent(
            TestModel(custom_output_args=_key_points_dict()),
            output_type=KeyPointsOutput,
        ))
        Registry.register_agent("generator", _make_agent(
            TestModel(custom_output_text="Draft.")
        ))
        Registry.register_agent("evaluator", _make_agent(
            TestModel(custom_output_args=_passing_scores_dict()),
            output_type=EvaluationScores,
        ))

        with patch("src.generate.log_llm_call"):
            # If .output parsing were broken this would raise
            script = run_generation(_sample_passages())

        assert script == "Draft."


class TestImproverAgent:
    """Improver is invoked when the evaluator score is below threshold and
    returns the updated script via AgentRunResult.output (str)."""

    def test_improver_produces_updated_script(self):
        improved_text = "Improved: Revenue grew 12 percent."

        Registry.register_agent("key_points", _make_agent(
            TestModel(custom_output_args=_key_points_dict()),
            output_type=KeyPointsOutput,
        ))
        Registry.register_agent("generator", _make_agent(
            TestModel(custom_output_text="Original draft.")
        ))

        # Evaluator will be called twice: first low, then passing.
        # TestModel is stateless so we need to swap it between calls.
        # We achieve this by letting _run_with_retry hit the real agents
        # but controlling the evaluator via side-effect on Registry.get_agent.
        eval_call_count = {"n": 0}
        low_eval_agent = _make_agent(
            TestModel(custom_output_args=_low_scores_dict()),
            output_type=EvaluationScores,
        )
        pass_eval_agent = _make_agent(
            TestModel(custom_output_args=_passing_scores_dict()),
            output_type=EvaluationScores,
        )
        Registry.register_agent("evaluator", low_eval_agent)
        Registry.register_agent("improver", _make_agent(
            TestModel(custom_output_text=improved_text)
        ))

        def _cycling_get_agent(name: str):
            if name == "evaluator":
                eval_call_count["n"] += 1
                # Second call onwards → passing score
                if eval_call_count["n"] >= 2:
                    Registry.register_agent("evaluator", pass_eval_agent)
                return Registry._agents["evaluator"]
            return Registry._agents[name]

        with patch("src.generate.log_llm_call"), \
             patch.object(Registry, "get_agent", side_effect=_cycling_get_agent), \
             patch("src.generate.MAX_AGENT_ITERATIONS", 3), \
             patch("src.generate.SCORE_THRESHOLD", 8):
            script = run_generation(_sample_passages())

        assert script == improved_text


class TestUsageTracking:
    """log_llm_call receives a real AgentRunResult — verify .usage() works."""

    def test_log_llm_call_receives_valid_usage(self, tmp_path):
        """Pass a real AgentRunResult (from TestModel) into log_llm_call and
        confirm it reads input_tokens / output_tokens without error."""
        from pydantic_ai import Agent as RealAgent
        from src.utility.llm_utility import log_llm_call

        model = TestModel(custom_output_text="hello")
        agent = RealAgent("test")

        with agent.override(model=model):
            result = agent.run_sync("prompt")

        log_file = tmp_path / "llm_log.json"
        with patch("src.utility.llm_utility.LLM_LOG_FILE", log_file), \
             patch("src.utility.llm_utility.OUTPUT_DIR", tmp_path):
            log_llm_call("generator", 0, "prompt", result)

        import json

        entry = json.loads(log_file.read_text().strip())
        assert entry["usage"]["prompt_tokens"] >= 0
        assert entry["usage"]["completion_tokens"] >= 0
        assert entry["response_length_chars"] == len("hello")


# ── private helpers ────────────────────────────────────────────────────────


def _make_agent(model: TestModel, output_type=None):
    """Create an Agent wired to a TestModel, optionally with a typed output."""
    from pydantic_ai import Agent as RealAgent

    kwargs = {"output_type": output_type} if output_type is not None else {}
    agent = RealAgent("test", **kwargs)
    # Permanently override the model on this agent instance via override context
    # — but we need a non-context-manager approach.  Agent stores the model
    # override internally; we simply re-create with the test model directly.
    agent = RealAgent(model, **kwargs)
    return agent
