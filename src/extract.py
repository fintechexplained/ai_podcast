"""Layer 1 — PDF extraction.

Combines pdfplumber (accurate page text) and fitz/PyMuPDF (TOC, font details,
hyperlinks) to produce the canonical ``extracted_text.json`` cache that every
downstream step reads from.

Public entry-point
------------------
    run_extraction(file_path, output_path=None) → dict

The module also registers ``PDFExtractor`` in the IoC ``Registry`` at load time
so that callers can resolve it generically via ``Registry.get_extractor("pdf")``.
"""

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from math import floor
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber

from src.app_config import (
    HEADING_FONT_SIZE,
    MAJOR_SECTION_FONT_SIZE,
    MAX_PAGE_APPEARANCES,
    MIN_HEADING_CHARS,
    OUTPUT_DIR,
)
from src.register import BaseExtractor, Registry

logger = logging.getLogger(__name__)

# Regex: captures (title)(dots/dashes)(page_number) on a TOC line.
_TOC_LINE_RE = re.compile(r"^(.+?)\s*[.\-\u2013\u2014]+\s*(\d+)\s*$")

# Regex: captures (page_number)(whitespace)(title) — page-number-first style.
_TOC_LINE_PAGE_FIRST_RE = re.compile(r"^\s*(\d+)\s+(.+)\s*$")

# Regex: a line that contains only a page number (optional surrounding whitespace/tabs).
_NUMBER_ONLY_RE = re.compile(r"^\s*(\d+)\s*$")

# Keywords that identify a Contents page (case-insensitive, checked against
# the leading lines of every page).
_CONTENTS_KEYWORDS = ("table of contents", "contents", "table des matières")

# Characters whose presence at the start of a line marks it as a nav arrow.
_ARROW_CHARS = {"→", "▶", "▸", "►"}

# Indentation threshold (points) used when assigning heading levels from a
# Contents page.
_INDENT_THRESHOLD_PT = 10

# Translation table that drops all C0 control characters (U+0000–U+001F).
# PDF text extraction frequently leaves \x08 (backspace) in heading titles.
_STRIP_CONTROL = str.maketrans({i: None for i in range(0x20)})


class ExtractionError(Exception):
    """User-facing extraction failure."""


# ── Tier helpers (module-level pure functions for testability) ─────────────


def _sections_from_toc(toc: list) -> list[dict]:
    """Convert a fitz TOC list into the section-dict format.

    Each fitz entry is ``[level, title, page_number]`` (1-based page).
    """
    return [{"title": title.strip(), "start_page": page, "level": level} for level, title, page in toc]


def _find_contents_page_index(raw_pages: list[dict]) -> Optional[int]:
    """Return the 0-based index of the first page whose *top* text matches
    a Contents keyword, or ``None``.

    Only the first 15 lines are scanned so that footer occurrences of the
    keyword (e.g. a repeated section label at the bottom of a preceding page)
    cannot produce a false match.
    """
    for idx, page in enumerate(raw_pages):
        top_lines = (page["text"] or "").strip().split("\n")[:15]
        for line in top_lines:
            if any(kw in line.lower() for kw in _CONTENTS_KEYWORDS):
                return idx
    return None


def _parse_contents_page(fitz_page) -> list[dict]:
    """Parse a single fitz page identified as a Contents page.

    Supports three TOC-line formats:
      1. ``title … dots … page_number``  (classic dot-leader style)
      2. Bare ``page_number`` on one line followed by ``title`` on the next
         line within the same block (common when PDF renderers split a
         tab-separated number+title into two lines).
      3. ``page_number  title`` on a single line (page-number-first style).

    Levels are assigned in a second pass using x-indentation relative to the
    leftmost *matched* entry in each column, so sidebar / nav blocks that
    contain no valid TOC entries cannot skew the baseline.
    """
    text_dict = fitz_page.get_text("dict")
    blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
    if not blocks:
        return []

    # ── column detection ───────────────────────────────────────────────
    widths = [b["bbox"][2] - b["bbox"][0] for b in blocks]
    avg_width = sum(widths) / len(widths) if widths else 1.0

    # Collect unique left-edge positions, sorted.
    x_lefts = sorted({round(b["bbox"][0], 1) for b in blocks})

    # Cluster x-positions: a gap > avg_width starts a new column.
    columns_ranges: list[tuple[float, float]] = []
    if x_lefts:
        start = end = x_lefts[0]
        for x in x_lefts[1:]:
            if x - end > avg_width:
                columns_ranges.append((start, end))
                start = x
            end = x
        columns_ranges.append((start, end))

    # Assign blocks to columns.
    columns: list[list] = [[] for _ in columns_ranges]
    for block in blocks:
        bx = round(block["bbox"][0], 1)
        for i, (cs, ce) in enumerate(columns_ranges):
            if cs - avg_width / 4 <= bx <= ce + avg_width / 4:
                columns[i].append(block)
                break

    # Sort each column top-to-bottom by y0.
    for col in columns:
        col.sort(key=lambda b: b["bbox"][1])

    # Titles that are just a contents-page keyword are noise.
    skip_titles = {kw.lower() for kw in _CONTENTS_KEYWORDS}

    # ── pass 1: extract raw (title, page_num, x) per column ───────────
    # Each entry: (title, page_num, line_x)
    column_entries: list[list[tuple[str, int, float]]] = [[] for _ in columns]

    for col_idx, col in enumerate(columns):
        if not col:
            continue

        for block in col:
            # Collect (text, x) for every non-empty line in this block.
            lines_data: list[tuple[str, float]] = []
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(sp["text"] for sp in spans).strip()
                line_x = min(sp["bbox"][0] for sp in spans)
                if line_text:
                    lines_data.append((line_text, line_x))

            # Lines that match no pattern are held as a pending prefix;
            # when the very next line *does* match, the prefix is prepended
            # to its title.  This handles TOC entries whose title wraps
            # across two (or more) lines before the dot-leader + page number.
            pending_prefix = ""
            pending_x = 0.0
            i = 0
            while i < len(lines_data):
                line_text, line_x = lines_data[i]

                # Pattern 1 — "title … dots … page_number"
                match = _TOC_LINE_RE.match(line_text)
                if match:
                    title = match.group(1).strip()
                    page_num = int(match.group(2))
                    # Only prepend prefix when the base title is itself a
                    # plausible heading fragment.  A base title of all-digits
                    # (e.g. "2024" from a "2024–2025" artifact) must not be
                    # inflated by a preceding line.
                    if pending_prefix and sum(1 for c in title if c.isalpha()) >= MIN_HEADING_CHARS:
                        title = pending_prefix + " " + title
                        line_x = pending_x
                    pending_prefix = ""  # always clear on a pattern match
                    if (
                        title.lower() not in skip_titles
                        and sum(1 for c in title if c.isalpha()) >= MIN_HEADING_CHARS
                    ):
                        column_entries[col_idx].append((title, page_num, line_x))
                    i += 1
                    continue

                # Pattern 2 — bare page number; title on the next line
                num_match = _NUMBER_ONLY_RE.match(line_text)
                if num_match and i + 1 < len(lines_data):
                    next_text, _ = lines_data[i + 1]
                    if (
                        not _NUMBER_ONLY_RE.match(next_text)
                        and next_text.lower() not in skip_titles
                        and sum(1 for c in next_text if c.isalpha()) >= MIN_HEADING_CHARS
                    ):
                        page_num = int(num_match.group(1))
                        title = next_text
                        if pending_prefix:
                            title = pending_prefix + " " + title
                            line_x = pending_x
                            pending_prefix = ""
                        column_entries[col_idx].append((title, page_num, line_x))
                        i += 2
                        continue

                # Pattern 3 — "page_number  title" on one line
                match = _TOC_LINE_PAGE_FIRST_RE.match(line_text)
                if match:
                    page_num = int(match.group(1))
                    title = match.group(2).strip()
                    if pending_prefix and sum(1 for c in title if c.isalpha()) >= MIN_HEADING_CHARS:
                        title = pending_prefix + " " + title
                        line_x = pending_x
                    pending_prefix = ""  # always clear on a pattern match
                    if (
                        title.lower() not in skip_titles
                        and sum(1 for c in title if c.isalpha()) >= MIN_HEADING_CHARS
                    ):
                        column_entries[col_idx].append((title, page_num, line_x))
                    i += 1
                    continue

                # No pattern matched — accumulate as title prefix if it
                # contains enough alphabetic characters; otherwise reset.
                if sum(1 for c in line_text if c.isalpha()) >= MIN_HEADING_CHARS:
                    if not pending_prefix:
                        pending_x = line_x
                    pending_prefix = (pending_prefix + " " + line_text).strip() if pending_prefix else line_text
                else:
                    pending_prefix = ""
                i += 1

    # ── pass 2: assign levels from per-column x-indentation ────────────
    sections: list[dict] = []
    for col_entries in column_entries:
        if not col_entries:
            continue
        col_min_x = min(x for _, _, x in col_entries)
        for title, page_num, x_pos in col_entries:
            indent = x_pos - col_min_x
            level = 1
            if indent > _INDENT_THRESHOLD_PT:
                level = 2
            if indent > _INDENT_THRESHOLD_PT * 2:
                level = 3
            sections.append({"title": title, "start_page": page_num, "level": level})

    sections.sort(key=lambda s: s["start_page"])
    return sections


def _font_heuristic_sections(fitz_doc, total_pages: int) -> list[dict]:
    """Tier 3 — scan every page for large / bold text and classify headings.

    Applies the candidate-filtering rules specified in §7.2 Tier 3.
    """
    # Effective nav-bar threshold.
    max_appearances = MAX_PAGE_APPEARANCES if MAX_PAGE_APPEARANCES > 0 else floor(total_pages / 2)

    candidates: list[dict] = []  # {title, start_page, level}

    for page_idx in range(len(fitz_doc)):
        page = fitz_doc[page_idx]
        page_number = page_idx + 1
        text_dict = page.get_text("dict")

        prev_level: Optional[int] = None
        prev_title: Optional[str] = None

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if not text:
                        continue

                    # Must contain at least MIN_HEADING_CHARS alphabetic chars.
                    alpha_count = sum(1 for ch in text if ch.isalpha())
                    if alpha_count < MIN_HEADING_CHARS:
                        continue

                    size = span.get("size", 0)
                    is_bold = "bold" in span.get("font", "").lower()

                    level: Optional[int] = None
                    if size >= MAJOR_SECTION_FONT_SIZE:
                        level = 1
                    elif size >= HEADING_FONT_SIZE:
                        level = 2
                    elif is_bold and size >= 14:
                        level = 2

                    if level is None:
                        # Not a heading candidate; reset merge state.
                        prev_level = None
                        prev_title = None
                        continue

                    # Merge consecutive candidates on the same page.
                    if prev_level == level and prev_title is not None:
                        # Update the last candidate's title.
                        candidates[-1]["title"] += " " + text
                        prev_title = candidates[-1]["title"]
                    else:
                        candidates.append({"title": text, "start_page": page_number, "level": level})
                        prev_level = level
                        prev_title = text

    # Drop titles that appear on too many pages (nav-bar fragments).
    title_page_counts: Counter = Counter()
    for c in candidates:
        title_page_counts[c["title"]] += 1

    # Deduplicate: keep only the first occurrence of each title.
    seen: set[str] = set()
    filtered: list[dict] = []
    for c in candidates:
        if title_page_counts[c["title"]] > max_appearances:
            continue
        if c["title"] in seen:
            continue
        seen.add(c["title"])
        filtered.append(c)

    return filtered


def compute_end_pages(sections: list[dict], total_pages: int) -> list[dict]:
    """Derive ``end_page`` for every section in a single pass.

    For section *i*, ``end_page`` is ``start_page[j] − 1`` where *j* is the
    next section whose level ≤ level *i*.  If no such *j* exists,
    ``end_page`` equals ``total_pages``.
    """
    result = [dict(s) for s in sections]  # shallow copy each dict

    for i, sec in enumerate(result):
        end = total_pages  # default: extends to end of document
        for j in range(i + 1, len(result)):
            if result[j]["level"] <= sec["level"]:
                end = result[j]["start_page"] - 1
                break
        result[i]["end_page"] = end

    return result


# ── Cleaning helpers ───────────────────────────────────────────────────────


def _effective_max_appearances(total_pages: int) -> int:
    return MAX_PAGE_APPEARANCES if MAX_PAGE_APPEARANCES > 0 else floor(total_pages / 2)


def _build_nav_bar_lines(raw_pages: list[dict], total_pages: int) -> set[str]:
    """Scan the top 5 lines of every page; return lines whose frequency
    exceeds the nav-bar threshold."""
    threshold = _effective_max_appearances(total_pages)
    freq: Counter = Counter()
    for page in raw_pages:
        top_lines = (page["text"] or "").split("\n")[:5]
        # Use a *set* per page so a line repeated within the same page
        # only counts once toward the page-frequency.
        for line in set(top_lines):
            stripped = line.strip()
            if stripped:
                freq[stripped] += 1
    return {line for line, count in freq.items() if count > threshold}


def _remove_nav_bars(pages_text: list[str], nav_lines: set[str]) -> list[str]:
    """Strip nav-bar lines from every page."""
    cleaned: list[str] = []
    for text in pages_text:
        lines = text.split("\n")
        cleaned.append("\n".join(ln for ln in lines if ln.strip() not in nav_lines))
    return cleaned


def _remove_arrow_links(pages_text: list[str]) -> list[str]:
    """Remove lines whose first non-whitespace character is an arrow."""
    cleaned: list[str] = []
    for text in pages_text:
        lines = text.split("\n")
        filtered: list[str] = []
        for ln in lines:
            stripped = ln.lstrip()
            if stripped and stripped[0] in _ARROW_CHARS:
                continue
            filtered.append(ln)
        cleaned.append("\n".join(filtered))
    return cleaned


def _get_top_hyperlink_texts(fitz_doc, total_pages: int) -> dict[int, set[str]]:
    """For each page, collect text snippets that belong to hyperlinks in the
    top 15 % of the page.  Keyed by 1-based page number."""
    top_texts: dict[int, set[str]] = {}
    for page_idx in range(min(len(fitz_doc), total_pages)):
        page = fitz_doc[page_idx]
        page_height = page.rect.height
        top_limit = 0.15 * page_height

        links = page.get_links()
        link_rects = []
        for link in links:
            rect = fitz.Rect(link["from"])
            if rect.y0 < top_limit:
                link_rects.append(rect)

        if not link_rects:
            continue

        # Find spans whose bounding boxes overlap with the link rects.
        snippets: set[str] = set()
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_rect = fitz.Rect(span["bbox"])
                    for lr in link_rects:
                        if span_rect.intersects(lr):
                            t = span["text"].strip()
                            if t:
                                snippets.add(t)
                            break

        if snippets:
            top_texts[page_idx + 1] = snippets  # 1-based key
    return top_texts


def _remove_top_hyperlinks(raw_pages: list[dict], top_hyperlink_map: dict[int, set[str]]) -> list[str]:
    """For each page, remove lines that consist entirely of top-hyperlink
    text snippets."""
    cleaned: list[str] = []
    for page in raw_pages:
        pn = page["page_number"]
        snippets = top_hyperlink_map.get(pn, set())
        if not snippets:
            cleaned.append(page["text"] or "")
            continue

        lines = (page["text"] or "").split("\n")
        filtered: list[str] = []
        for ln in lines:
            # A line is a hyperlink line if *all* its non-whitespace tokens
            # are contained in the snippets set.
            tokens = ln.split()
            if tokens and all(any(tok in sn for sn in snippets) for tok in tokens):
                continue
            filtered.append(ln)
        cleaned.append("\n".join(filtered))
    return cleaned


def _encoding_cleanup(pages_text: list[str], raw_pages: list[dict]) -> list[str]:
    """Drop any character that cannot be encoded as UTF-8, remove empty lines
    that result, and log a warning per affected page."""
    cleaned: list[str] = []
    for text, page in zip(pages_text, raw_pages):
        new_chars: list[str] = []
        dropped = False
        for ch in text:
            try:
                ch.encode("utf-8")
                new_chars.append(ch)
            except UnicodeEncodeError:
                dropped = True
        if dropped:
            logger.warning(
                "Encoding cleanup: characters dropped on page %d",
                page["page_number"],
            )
        # Remove lines that became empty after stripping.
        lines = "".join(new_chars).split("\n")
        cleaned.append("\n".join(ln for ln in lines if ln.strip()))
    return cleaned


# ── Main extractor class ───────────────────────────────────────────────────


class PDFExtractor(BaseExtractor):
    """Extracts text and section structure from a PDF file."""

    def extract(self, file_path: str) -> dict:
        logger.info("Starting PDF extraction — %s", os.path.basename(file_path))

        # ── open documents ─────────────────────────────────────────────
        try:
            fitz_doc = fitz.open(file_path)
        except Exception as exc:
            raise ExtractionError(f"Could not open PDF with fitz: {exc}") from exc

        if fitz_doc.is_encrypted:
            fitz_doc.close()
            raise ExtractionError("PDF is password-protected. Cannot extract text.")

        try:
            plumber_pdf = pdfplumber.open(file_path)
        except Exception as exc:
            fitz_doc.close()
            raise ExtractionError(f"Could not open PDF with pdfplumber: {exc}") from exc

        try:
            total_pages = len(plumber_pdf.pages)

            # ── raw text extraction (pdfplumber) ───────────────────────
            raw_pages: list[dict] = []
            for i, page in enumerate(plumber_pdf.pages):
                text = page.extract_text() or ""
                raw_pages.append({"page_number": i + 1, "text": text})

            if all(p["text"].strip() == "" for p in raw_pages):
                logger.error("No extractable text found in %s", file_path)
                raise ExtractionError("PDF contains no extractable text.")

            # ── section detection (3-tier) ─────────────────────────────
            sections, strategy = self._detect_sections(fitz_doc, raw_pages, total_pages)
            for sec in sections:
                sec["title"] = sec["title"].translate(_STRIP_CONTROL).strip()
            sections = compute_end_pages(sections, total_pages)

            # ── text cleaning ──────────────────────────────────────────
            pages = self._clean_pages(raw_pages, fitz_doc, total_pages)

            # ── assemble output ────────────────────────────────────────
            result = {
                "metadata": {
                    "filename": os.path.basename(file_path),
                    "total_pages": total_pages,
                    "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "extraction_strategy": strategy,
                    "version": "1.0",
                },
                "sections": sections,
                "pages": pages,
            }

            logger.info("Extraction complete — %d pages, %d sections (%s)", total_pages, len(sections), strategy)
            return result

        finally:
            plumber_pdf.close()
            fitz_doc.close()

    # ── section detection ──────────────────────────────────────────────

    def _detect_sections(self, fitz_doc, raw_pages: list[dict], total_pages: int) -> tuple[list[dict], str]:
        """Try Tier 1 → 2 → 3 and return (sections, strategy_name)."""
        # Tier 1 — PDF outline
        toc = fitz_doc.get_toc()
        if toc:
            logger.info("Section detection: using PDF outline (TOC)")
            return _sections_from_toc(toc), "toc"

        # Tier 2 — Contents page
        contents_idx = _find_contents_page_index(raw_pages)
        if contents_idx is not None:
            logger.info("Section detection: using Contents page (page %d)", contents_idx + 1)
            sections = _parse_contents_page(fitz_doc[contents_idx])
            if sections:
                return sections, "contents_page"

        # Tier 3 — font-size heuristic
        logger.info("Section detection: using font-size heuristic")
        return _font_heuristic_sections(fitz_doc, total_pages), "font_heuristic"

    # ── cleaning pipeline (steps run in order) ─────────────────────────

    def _clean_pages(self, raw_pages: list[dict], fitz_doc, total_pages: int) -> list[dict]:
        # Step 1 — Nav-bar removal
        nav_lines = _build_nav_bar_lines(raw_pages, total_pages)
        texts = _remove_nav_bars([p["text"] or "" for p in raw_pages], nav_lines)
        if nav_lines:
            logger.warning("Nav-bar lines removed (%d distinct): %s", len(nav_lines), list(nav_lines)[:3])

        # Step 2 — Arrow-link removal
        texts = _remove_arrow_links(texts)

        # Step 3 — Top hyperlink removal
        top_map = _get_top_hyperlink_texts(fitz_doc, total_pages)
        # Re-build raw_pages-like list with current texts for the helper.
        interim = [{"page_number": p["page_number"], "text": t} for p, t in zip(raw_pages, texts)]
        texts = _remove_top_hyperlinks(interim, top_map)

        # Step 4 — Encoding cleanup
        interim = [{"page_number": p["page_number"], "text": t} for p, t in zip(raw_pages, texts)]
        texts = _encoding_cleanup(texts, interim)

        return [{"page_number": p["page_number"], "text": t} for p, t in zip(raw_pages, texts)]


# ── Public entry-point ─────────────────────────────────────────────────────


def run_extraction(file_path: str, output_path: Optional[str] = None) -> dict:
    """Extract text and sections from a PDF and persist the cache.

    Args:
        file_path:   Path to the source PDF.
        output_path: Where to write the JSON cache (defaults to
                     ``output/extracted_text.json``).

    Returns:
        The extraction result dict (same content that was written to disk).
    """
    extractor = Registry.get_extractor("pdf")
    result = extractor.extract(file_path)

    out = Path(output_path) if output_path else OUTPUT_DIR / "extracted_text.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Extraction cache written → %s", out)

    return result


# ── Standalone CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Extract text and sections from a PDF")
    parser.add_argument("--input", required=True, help="Path to the PDF file")
    parser.add_argument("--output", default=None, help="Output JSON path (optional)")
    args = parser.parse_args()

    run_extraction(file_path=args.input, output_path=args.output)
