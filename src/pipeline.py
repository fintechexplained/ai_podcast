"""Pipeline orchestrator — the single entry-point shared by the UI and CLI.

Wires together filter → generate → verify and writes all output artefacts.
"""

import json
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from src import filter as section_filter
from src import generate
from src import verify
from src.app_config import OUTPUT_DIR

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    script: str
    verification: dict
    word_count: int


def run_pipeline(
    extracted_data: dict,
    selected_sections: list[dict],
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> PipelineResult:
    """Run the full generation + verification pipeline.

    Args:
        extracted_data:      The cached extraction output (dict).
        selected_sections:   List of section dicts with 'name' and optional
                             'page_override'.
        progress_callback:   If provided, called as ``(message, fraction)`` at
                             each stage so the UI can show live status.
                             ``fraction`` ranges 0.0 → 1.0.

    Returns:
        ``PipelineResult`` with the final script, verification report, and
        word count.
    """

    def _progress(msg: str, frac: float) -> None:
        if progress_callback:
            progress_callback(msg, frac)

    # 1. Resolve sections ───────────────────────────────────────────────
    _progress("Resolving sections …", 0.0)
    source_passages = section_filter.resolve(extracted_data, selected_sections)

    # 2. Run generation + eval/improve loop ─────────────────────────────
    _progress("Generating podcast script …", 0.15)
    script = generate.run_generation(source_passages, progress_callback=_progress)

    # 3. Run verification ───────────────────────────────────────────────
    _progress("Verifying claims and coverage …", 0.75)
    verification = verify.run_verification(script, source_passages, selected_sections)

    # 4. Write output files ─────────────────────────────────────────────
    _progress("Writing output files …", 0.9)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUTPUT_DIR / "podcast_script.txt").write_text(script, encoding="utf-8")
    (OUTPUT_DIR / "verification_report.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    word_count = len(script.split())
    _progress("Done.", 1.0)
    logger.info("Pipeline complete — %d words, script + report written.", word_count)

    return PipelineResult(script=script, verification=verification, word_count=word_count)
