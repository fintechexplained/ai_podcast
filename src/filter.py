"""Section resolution — bridges user section selection and extracted data.

Reads ``config.json``-style section entries and maps each one to the actual
pages and text discovered by the extractor.  Returns an ``OrderedDict``
preserving the caller's requested order.
"""

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class SectionNotFoundError(Exception):
    """Raised when a requested section name has no match in the extraction."""


# ── public API ─────────────────────────────────────────────────────────────


def resolve(extracted_data: dict, selected_sections: list[dict]) -> OrderedDict:
    """Resolve each section entry to its page range and concatenated text.

    Args:
        extracted_data:    The full extraction dict (from ``extracted_text.json``).
        selected_sections: List of ``{"name": str, "page_override": str | None}``.

    Returns:
        ``OrderedDict`` mapping each requested section name to
        ``{"start_page": int, "end_page": int, "text": str}``.

    Raises:
        SectionNotFoundError: if a name cannot be matched and has no override.
    """
    if not selected_sections:
        return OrderedDict()

    sections_db = extracted_data.get("sections", [])
    pages_db = extracted_data.get("pages", [])

    # Build a quick page-number → text lookup.
    page_text: dict[int, str] = {p["page_number"]: p.get("text", "") for p in pages_db}

    result: OrderedDict = OrderedDict()

    for entry in selected_sections:
        name = entry["name"]
        override = entry.get("page_override")

        if override:
            start, end = _parse_page_override(override)
        else:
            matched = _find_best_match(name, sections_db)
            if matched is None:
                available = [s["title"] for s in sections_db]
                raise SectionNotFoundError(
                    f"Section '{name}' not found.  Available sections: {available}"
                )
            start = matched["start_page"]
            end = matched["end_page"]

        text = _collect_text(page_text, start, end)
        result[name] = {"start_page": start, "end_page": end, "text": text}
        logger.info("Resolved section '%s' → pages %d–%d", name, start, end)

    return result


# ── internal helpers ───────────────────────────────────────────────────────


def _parse_page_override(override: str) -> tuple[int, int]:
    """Parse ``"42"`` or ``"50-65"`` into ``(start, end)``."""
    parts = override.strip().split("-")
    if len(parts) == 1:
        page = int(parts[0])
        return page, page
    return int(parts[0]), int(parts[1])


def _find_best_match(name: str, sections_db: list[dict]) -> Optional[dict]:
    """Case-insensitive substring match.  Accepts A⊂B or B⊂A.
    If multiple sections match, the one with the greatest character overlap
    (length of the shorter string) wins."""
    name_lower = name.lower()
    best: Optional[dict] = None
    best_overlap = -1

    for sec in sections_db:
        title_lower = sec["title"].lower()
        if name_lower in title_lower or title_lower in name_lower:
            overlap = min(len(name_lower), len(title_lower))
            if overlap > best_overlap:
                best = sec
                best_overlap = overlap

    return best


def _collect_text(page_text: dict[int, str], start: int, end: int) -> str:
    """Concatenate page texts with page-number markers so downstream agents
    can reference specific pages."""
    parts: list[str] = []
    for pn in range(start, end + 1):
        text = page_text.get(pn, "")
        parts.append(f"--- Page {pn} ---\n{text}")
    return "\n".join(parts)
