"""Shared LLM utilities — budget tracking, retry logic, call logging, and
source-text formatting.

These helpers are consumed by both ``generate.py`` and ``verify.py``.  Keeping
them here avoids a circular dependency between those two modules.
"""

import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from pydantic_ai import Agent

from src.app_config import LLM_LOG_FILE, MAX_LLM_CALLS, MODEL_NAME, OUTPUT_DIR

logger = logging.getLogger(__name__)


# ── exceptions ─────────────────────────────────────────────────────────────


class LLMCallError(Exception):
    """Raised when all retries for an LLM call are exhausted."""


# ── shared budget counter ──────────────────────────────────────────────────
# Mutable dict so that the same object is shared across every module that
# imports it — mutations in one place are visible everywhere.

_llm_call_budget: dict = {"remaining": MAX_LLM_CALLS}


# ── public helpers ─────────────────────────────────────────────────────────


def log_llm_call(agent_name: str, iteration: int, prompt: str, result, scores=None) -> None:
    """Append one structured entry to ``llm_log.json``.

    Also decrements the global LLM-call budget and logs a warning when it
    hits zero.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    usage = result.usage()
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": agent_name,
        "iteration": iteration,
        "model": MODEL_NAME,
        "prompt_length_chars": len(prompt),
        "response_length_chars": len(str(result.output)),
        "usage": {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
        },
        "scores": scores,
    }
    with open(LLM_LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    _llm_call_budget["remaining"] -= 1
    if _llm_call_budget["remaining"] <= 0:
        logger.warning("LLM call budget exhausted (%d calls).", MAX_LLM_CALLS)


def _check_budget() -> None:
    """Raise if the shared LLM-call budget is exhausted."""
    if _llm_call_budget["remaining"] <= 0:
        raise LLMCallError(f"Exceeded maximum allowed LLM calls ({MAX_LLM_CALLS}).")


def format_source_passages(source_passages: OrderedDict) -> str:
    """Turn the ordered-dict from ``filter.resolve()`` into a single readable
    string with section and page markers."""
    parts: list[str] = []
    for section_name, data in source_passages.items():
        parts.append(
            f"\n=== Section: {section_name} "
            f"(Pages {data['start_page']}-{data['end_page']}) ===\n"
        )
        parts.append(data["text"])
    return "\n".join(parts)


def _run_with_retry(agent: Agent, prompt: str, max_retries: int = 3):
    """Run a PydanticAI agent with exponential back-off on failure."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return agent.run_sync(prompt)
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries - 1:
                break
            wait = 2 ** attempt  # 1 s, 2 s, 4 s
            logger.error(
                "LLM call failed (attempt %d/%d): %s. Retrying in %ds…",
                attempt + 1, max_retries, exc, wait,
            )
            time.sleep(wait)
    raise LLMCallError(f"LLM call failed after {max_retries} retries") from last_exc
