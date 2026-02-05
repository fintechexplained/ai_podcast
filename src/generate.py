"""Layer 2 — Podcast generation with PydanticAI agents.

Contains the Generator, Evaluator, and Improver agent definitions (via the
``EvaluationScores`` model) and the ``run_generation()`` function that
orchestrates the eval/improve loop.  Agents are resolved at call time from the
``Registry``; shared LLM helpers live in ``utility.llm_utility``.
"""

import json
import logging
from collections import OrderedDict
from typing import Callable, Optional

from pydantic import BaseModel

from src.app_config import (
    MAX_AGENT_ITERATIONS,
    SCORE_THRESHOLD,
    TARGET_WORD_COUNT,
)
from src.register import Registry
from src.utility.llm_utility import (
    _check_budget,
    _run_with_retry,
    format_source_passages,
    log_llm_call,
)
from src.utility.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


# ── custom exceptions ──────────────────────────────────────────────────────


class ParseError(Exception):
    """Raised when an LLM response cannot be parsed into the expected shape."""


# ── result models ──────────────────────────────────────────────────────────


class SectionKeyPoints(BaseModel):
    section: str
    points: list[str]


class KeyPointsOutput(BaseModel):
    sections: list[SectionKeyPoints]


class EvaluationScores(BaseModel):
    teachability: int
    conversational_feel: int
    friction_disagreement: int
    takeaway_clarity: int
    accuracy: int
    coverage: int
    overall: float
    feedback: str


# ── helpers ────────────────────────────────────────────────────────────────


def _format_key_points_checklist(key_points: KeyPointsOutput) -> str:
    """Format extracted key points as a scannable checklist string."""
    lines: list[str] = []
    for section in key_points.sections:
        lines.append(f"\n{section.section}:")
        for point in section.points:
            lines.append(f"  - {point}")
    return "\n".join(lines)


# ── public entry-point ─────────────────────────────────────────────────────


def run_generation(
    source_passages: OrderedDict,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """Run Generator → Evaluator → Improver loop and return the final script.

    Args:
        source_passages:   Resolved section passages from ``filter.resolve()``.
        progress_callback: Optional ``(message, fraction)`` hook for UI updates.

    Returns:
        The final podcast script text.
    """

    def _progress(msg: str, frac: float) -> None:
        if progress_callback:
            progress_callback(msg, frac)

    source_text = format_source_passages(source_passages)

    # ── 0. Key-points extraction ──────────────────────────────────────
    _check_budget()
    _progress("Extracting key points …", 0.05)

    kp_prompt = load_prompt("extract_key_points")
    kp_prompt = kp_prompt.replace("{{source_text}}", source_text)

    kp_result = _run_with_retry(Registry.get_agent("key_points"), kp_prompt)
    key_points: KeyPointsOutput = kp_result.output
    key_points_checklist = _format_key_points_checklist(key_points)
    log_llm_call("key_points", 0, kp_prompt, kp_result)
    logger.info("Extracted key points for %d sections.", len(key_points.sections))

    # ── 1. Generator ───────────────────────────────────────────────────
    _check_budget()
    _progress("Generating initial script …", 0.15)

    gen_prompt = load_prompt("generate")
    gen_prompt = gen_prompt.replace("{{source_text}}", source_text)
    gen_prompt = gen_prompt.replace("{{target_word_count}}", str(TARGET_WORD_COUNT))
    gen_prompt = gen_prompt.replace("{{key_points_checklist}}", key_points_checklist)

    result = _run_with_retry(Registry.get_agent("generator"), gen_prompt)
    script: str = result.output
    log_llm_call("generator", 0, gen_prompt, result)
    logger.info("Generator produced %d words.", len(script.split()))

    # ── 2. Eval / Improve loop ─────────────────────────────────────────
    for iteration in range(MAX_AGENT_ITERATIONS):
        _check_budget()
        _progress(
            f"Evaluating (iteration {iteration + 1}/{MAX_AGENT_ITERATIONS}) …",
            0.2 + iteration * 0.08,
        )

        eval_prompt = load_prompt("evaluate")
        eval_prompt = eval_prompt.replace("{{script}}", script)
        eval_prompt = eval_prompt.replace("{{source_text}}", source_text)

        eval_result = _run_with_retry(Registry.get_agent("evaluator"), eval_prompt)
        scores: EvaluationScores = eval_result.output
        scores_dict = scores.model_dump()
        log_llm_call("evaluator", iteration, eval_prompt, eval_result, scores=scores_dict)
        logger.info("Iteration %d — overall score: %.1f", iteration, scores.overall)

        if scores.overall >= SCORE_THRESHOLD:
            logger.info("Score threshold met (%.1f ≥ %d). Stopping loop.", scores.overall, SCORE_THRESHOLD)
            break

        # Score below threshold → improve
        _check_budget()
        _progress(f"Improving script (iteration {iteration + 1}) …", 0.3 + iteration * 0.08)

        imp_prompt = load_prompt("improve")
        imp_prompt = imp_prompt.replace("{{script}}", script)
        imp_prompt = imp_prompt.replace("{{scores}}", json.dumps(scores_dict, indent=2))
        imp_prompt = imp_prompt.replace("{{source_text}}", source_text)
        imp_prompt = imp_prompt.replace("{{key_points_checklist}}", key_points_checklist)

        imp_result = _run_with_retry(Registry.get_agent("improver"), imp_prompt)
        script = imp_result.output
        log_llm_call("improver", iteration, imp_prompt, imp_result)
        logger.info("Improver produced %d words.", len(script.split()))

    return script
