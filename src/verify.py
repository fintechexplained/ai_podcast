"""Verification — final quality gate.

Two independent PydanticAI agents answer complementary questions:
  1. *Claims agent*   — is every factual statement supported by the source?
  2. *Coverage agent* — did the script actually cover the key information
                        from each selected section?
"""

import logging
from collections import OrderedDict
from typing import Literal, Optional

from pydantic import BaseModel

from src.register import Registry
from src.utility.llm_utility import (
    _check_budget,
    _run_with_retry,
    format_source_passages,
    log_llm_call,
)
from src.utility.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


# ── result models ──────────────────────────────────────────────────────────


class ClaimResult(BaseModel):
    claim_text: str
    status: Literal["TRACED", "PARTIALLY_TRACED", "NOT_TRACED"]
    source_page: Optional[int] = None
    source_section: Optional[str] = None


class CoverageResult(BaseModel):
    section: str
    status: Literal["COVERED", "PARTIAL", "OMITTED"]
    key_points_total: int
    key_points_covered: int
    omitted_points: list[str]


class ClaimsOutput(BaseModel):
    """Wrapper so OpenAI structured-output sees a top-level object."""
    claims: list[ClaimResult]



# ── public entry-point ─────────────────────────────────────────────────────


def run_verification(
    script: str,
    source_passages: OrderedDict,
    selected_sections: list[dict],
) -> dict:
    """Run claims + coverage verification and return the full report dict.

    Args:
        script:            The final podcast script text.
        source_passages:   Resolved passages from ``filter.resolve()``.
        selected_sections: The original section-selection list (for names).

    Returns:
        A dict conforming to the ``verification_report.json`` schema.
    """
    source_text = format_source_passages(source_passages)

    # ── Claims ─────────────────────────────────────────────────────────
    _check_budget()
    logger.info("Running claims verification …")

    claims_prompt = load_prompt("verify_claims")
    claims_prompt = claims_prompt.replace("{{script}}", script)
    claims_prompt = claims_prompt.replace("{{source_text}}", source_text)

    claims_result = _run_with_retry(Registry.get_agent("claims"), claims_prompt)
    log_llm_call("claims_agent", 0, claims_prompt, claims_result)

    claims: list[dict] = [c.model_dump() for c in claims_result.output.claims]
    logger.info("Claims agent returned %d claims.", len(claims))

    # ── Coverage (one call per section) ────────────────────────────────
    logger.info("Running coverage verification …")
    coverage: list[dict] = []

    for idx, (section_name, section_data) in enumerate(source_passages.items()):
        _check_budget()

        cov_prompt = load_prompt("verify_coverage")
        cov_prompt = cov_prompt.replace("{{section_name}}", section_name)
        cov_prompt = cov_prompt.replace("{{section_text}}", section_data["text"])
        cov_prompt = cov_prompt.replace("{{script}}", script)

        cov_result = _run_with_retry(Registry.get_agent("coverage"), cov_prompt)
        log_llm_call("coverage_agent", idx, cov_prompt, cov_result)

        coverage.append(cov_result.output.model_dump())

    logger.info("Coverage verification returned %d sections.", len(coverage))

    # ── Summary ────────────────────────────────────────────────────────
    summary = _compute_summary(claims, coverage)

    return {"claims": claims, "coverage": coverage, "summary": summary}


# ── helpers ────────────────────────────────────────────────────────────────


def _compute_summary(claims: list[dict], coverage: list[dict]) -> dict:
    """Derive the summary metrics from the raw agent outputs."""
    total_claims = len(claims)
    traced = sum(1 for c in claims if c["status"] == "TRACED")
    partially_traced = sum(1 for c in claims if c["status"] == "PARTIALLY_TRACED")
    not_traced = sum(1 for c in claims if c["status"] == "NOT_TRACED")

    total_key_points = sum(c["key_points_total"] for c in coverage)
    key_points_covered = sum(c["key_points_covered"] for c in coverage)

    coverage_pct = (
        round((key_points_covered / total_key_points) * 100, 1)
        if total_key_points > 0
        else 0.0
    )

    return {
        "total_claims": total_claims,
        "traced": traced,
        "partially_traced": partially_traced,
        "not_traced": not_traced,
        "total_key_points": total_key_points,
        "key_points_covered": key_points_covered,
        "coverage_percentage": coverage_pct,
    }
