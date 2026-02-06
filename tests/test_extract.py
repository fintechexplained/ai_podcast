"""Tests for extract.py — section detection, end-page computation, and text
cleaning.  All fitz / pdfplumber calls are mocked; no real PDFs are read.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.extract import (
    ExtractionError,
    PDFExtractor,
    _sections_from_toc,
    _find_contents_page_index,
    _parse_contents_page,
    _font_heuristic_sections,
    compute_end_pages,
    _build_nav_bar_lines,
    _remove_nav_bars,
    _remove_arrow_links,
    _encoding_cleanup,
)


# ── Tier 1 — TOC ──────────────────────────────────────────────────────────


class TestTocExtraction:
    def test_toc_extraction(self):
        """TOC entries are converted to the correct section-dict shape."""
        toc = [
            [1, "Financial Highlights", 10],
            [2, "Revenue Breakdown", 11],
            [1, "Sustainability", 40],
        ]
        result = _sections_from_toc(toc)
        assert len(result) == 3
        assert result[0] == {"title": "Financial Highlights", "start_page": 10, "level": 1}
        assert result[1] == {"title": "Revenue Breakdown", "start_page": 11, "level": 2}
        assert result[2] == {"title": "Sustainability", "start_page": 40, "level": 1}

    def test_toc_whitespace_stripped(self):
        toc = [[1, "  Title With Spaces  ", 5]]
        result = _sections_from_toc(toc)
        assert result[0]["title"] == "Title With Spaces"


# ── Tier 2 — Contents page ────────────────────────────────────────────────


class TestContentsPage:
    def test_contents_page_single_column(self):
        """A single-column Contents page is parsed correctly."""
        raw_pages = [
            {"page_number": 1, "text": "Some intro text"},
            {"page_number": 2, "text": "Table of Contents\nFinancial Highlights"},
            {"page_number": 3, "text": "Chapter one"},
        ]
        idx = _find_contents_page_index(raw_pages)
        assert idx == 1

    def test_contents_page_multi_column(self):
        """Multi-column detection: if blocks are spread across x-ranges
        with gaps > avg width, multiple columns are found."""
        # We test _parse_contents_page with a mock fitz page that has
        # two columns of text blocks.
        mock_page = MagicMock()
        # Two columns: left at x=50, right at x=400 (gap=350, avg_width~100)
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "bbox": (50, 50, 150, 70),
                    "lines": [
                        {
                            "spans": [
                                {"text": "Section A.........10", "bbox": (50, 50, 150, 70)}
                            ]
                        }
                    ],
                },
                {
                    "type": 0,
                    "bbox": (400, 50, 500, 70),
                    "lines": [
                        {
                            "spans": [
                                {"text": "Section B.........20", "bbox": (400, 50, 500, 70)}
                            ]
                        }
                    ],
                },
            ]
        }
        sections = _parse_contents_page(mock_page)
        titles = [s["title"] for s in sections]
        assert "Section A" in titles
        assert "Section B" in titles

    def test_two_line_title_merged(self):
        """A TOC title that wraps across two lines (first line has no
        dot-leader / page number) is merged into a single section."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "bbox": (50, 50, 300, 110),
                    "lines": [
                        # Normal single-line entry
                        {"spans": [{"text": "Section A.........10", "bbox": (50, 50, 300, 60)}]},
                        # First line of a wrapped title — no dots, no page number
                        {"spans": [{"text": "Long title that wraps", "bbox": (50, 62, 250, 72)}]},
                        # Second line — carries the dot-leader and page number
                        {"spans": [{"text": "onto the next line.........20", "bbox": (50, 74, 300, 84)}]},
                        # Another normal entry (should NOT pick up stale prefix)
                        {"spans": [{"text": "Section C.........30", "bbox": (50, 86, 300, 96)}]},
                    ],
                }
            ]
        }
        sections = _parse_contents_page(mock_page)
        titles = [s["title"] for s in sections]
        assert titles == [
            "Section A",
            "Long title that wraps onto the next line",
            "Section C",
        ]

    def test_contents_page_no_match(self):
        """Pages with no Contents keyword return None."""
        raw_pages = [
            {"page_number": 1, "text": "Introduction"},
            {"page_number": 2, "text": "Chapter 1 — Overview"},
        ]
        assert _find_contents_page_index(raw_pages) is None


# ── Tier 3 — font heuristic ───────────────────────────────────────────────


class TestFontHeuristic:
    def _make_span(self, text, size, font="Arial"):
        return {"text": text, "size": size, "font": font, "bbox": (0, 0, 100, 20)}

    def _make_fitz_doc(self, pages_data):
        """pages_data: list of list-of-spans-per-page."""
        doc = MagicMock()
        doc.__len__ = lambda self: len(pages_data)
        pages = []
        for spans in pages_data:
            page = MagicMock()
            page.get_text.return_value = {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [{"spans": [s]} for s in spans],
                    }
                ]
            }
            pages.append(page)
        doc.__getitem__ = lambda self, idx: pages[idx]
        return doc

    @patch("src.extract.MAX_PAGE_APPEARANCES", 0)
    def test_font_heuristic_levels(self):
        """Font sizes ≥ 26 → level 1; ≥ 18 → level 2."""
        spans = [
            self._make_span("Major Title", 28),
            self._make_span("Sub Heading", 20),
            self._make_span("Normal text is here", 12),
        ]
        doc = self._make_fitz_doc([spans])
        sections = _font_heuristic_sections(doc, total_pages=2)
        assert sections[0]["level"] == 1
        assert sections[0]["title"] == "Major Title"
        assert sections[1]["level"] == 2
        assert sections[1]["title"] == "Sub Heading"

    @patch("src.extract.MAX_PAGE_APPEARANCES", 0)
    def test_level_detection_bold(self):
        """Bold text at ≥ 14 pt is classified as level 2 even below HEADING_FONT_SIZE."""
        spans = [self._make_span("Bold Heading", 15, font="Arial-Bold")]
        doc = self._make_fitz_doc([spans])
        sections = _font_heuristic_sections(doc, total_pages=2)
        assert len(sections) == 1
        assert sections[0]["level"] == 2

    @patch("src.extract.MAX_PAGE_APPEARANCES", 0)
    def test_consecutive_heading_merge(self):
        """Two heading spans on the same page at the same level merge into one title."""
        spans = [
            self._make_span("Long", 28),
            self._make_span("Title", 28),
        ]
        doc = self._make_fitz_doc([spans])
        sections = _font_heuristic_sections(doc, total_pages=2)
        assert len(sections) == 1
        assert sections[0]["title"] == "Long Title"

    @patch("src.extract.MAX_PAGE_APPEARANCES", 0)
    def test_min_char_filter(self):
        """Candidates with fewer than 3 alphabetic chars are rejected."""
        spans = [
            self._make_span("12", 28),       # 0 alpha → rejected
            self._make_span("→", 28),        # 0 alpha → rejected
            self._make_span("OK", 28),       # 2 alpha → rejected (< 3)
            self._make_span("Real Title", 28),  # passes
        ]
        doc = self._make_fitz_doc([spans])
        sections = _font_heuristic_sections(doc, total_pages=2)
        titles = [s["title"] for s in sections]
        assert "Real Title" in titles
        assert "12" not in titles
        assert "OK" not in titles


# ── End-page computation ──────────────────────────────────────────────────


class TestEndPageComputation:
    def test_end_page_computation(self):
        sections = [
            {"title": "A", "start_page": 1, "level": 1},
            {"title": "A1", "start_page": 3, "level": 2},
            {"title": "A2", "start_page": 5, "level": 2},
            {"title": "B", "start_page": 8, "level": 1},
        ]
        result = compute_end_pages(sections, total_pages=20)

        # A ends where B starts − 1
        assert result[0]["end_page"] == 7
        # A1 ends where A2 starts − 1
        assert result[1]["end_page"] == 4
        # A2 ends where B starts − 1 (next section with level ≤ 2 is B at level 1)
        assert result[2]["end_page"] == 7
        # B is last → extends to total_pages
        assert result[3]["end_page"] == 20

    def test_single_section(self):
        sections = [{"title": "Only", "start_page": 1, "level": 1}]
        result = compute_end_pages(sections, total_pages=50)
        assert result[0]["end_page"] == 50


# ── Cleaning: nav-bar removal ─────────────────────────────────────────────


class TestNavBarRemoval:
    def test_nav_bar_removal(self):
        """A line appearing on more than half the pages is stripped everywhere."""
        # 10 pages; threshold = floor(10/2) = 5; line appears on 6 pages.
        raw_pages = []
        for i in range(1, 11):
            text = f"Content page {i}"
            if i <= 6:
                text = "Home  About  Investors\n" + text
            raw_pages.append({"page_number": i, "text": text})

        with patch("src.extract.MAX_PAGE_APPEARANCES", 0):
            nav_lines = _build_nav_bar_lines(raw_pages, total_pages=10)

        assert "Home  About  Investors" in nav_lines

        texts = [p["text"] for p in raw_pages]
        cleaned = _remove_nav_bars(texts, nav_lines)
        for t in cleaned:
            assert "Home  About  Investors" not in t


# ── Cleaning: arrow-link removal ──────────────────────────────────────────


class TestArrowLinkRemoval:
    def test_arrow_link_removal(self):
        texts = [
            "Normal line\n→ Click here\n▶ Another nav\nKeep this",
            "▸ Sub link\n► More nav\nReal content",
        ]
        cleaned = _remove_arrow_links(texts)
        assert "→ Click here" not in cleaned[0]
        assert "▶ Another nav" not in cleaned[0]
        assert "Keep this" in cleaned[0]
        assert "▸ Sub link" not in cleaned[1]
        assert "Real content" in cleaned[1]


# ── Cleaning: encoding cleanup ────────────────────────────────────────────


class TestEncodingCleanup:
    def test_unsupported_encoding(self):
        """Characters that fail UTF-8 encoding are silently dropped."""
        # All standard Python str chars encode to UTF-8 fine; to trigger the
        # except branch we'd need surrogate chars.  Use a surrogate:
        bad_char = "\ud800"  # lone surrogate — encode("utf-8") raises
        text = f"Hello{bad_char} World"
        pages = [{"page_number": 1, "text": text}]
        result = _encoding_cleanup([text], pages)
        assert "\ud800" not in result[0]
        assert "Hello" in result[0]
        assert "World" in result[0]


# ── Negative / error cases ────────────────────────────────────────────────


class TestExtractionErrors:
    @patch("src.extract.fitz.open")
    def test_password_protected_pdf(self, mock_fitz_open):
        """Encrypted PDFs raise ExtractionError with a clear message."""
        mock_doc = MagicMock()
        mock_doc.is_encrypted = True
        mock_fitz_open.return_value = mock_doc

        extractor = PDFExtractor()
        with pytest.raises(ExtractionError, match="password-protected"):
            extractor.extract("some/path.pdf")

    @patch("src.extract.pdfplumber.open")
    @patch("src.extract.fitz.open")
    def test_empty_pdf(self, mock_fitz_open, mock_plumber_open):
        """A PDF with no extractable text raises ExtractionError."""
        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.get_toc.return_value = []
        mock_doc.__len__ = lambda self: 3
        mock_fitz_open.return_value = mock_doc

        # pdfplumber pages all return empty text
        mock_pages = [MagicMock() for _ in range(3)]
        for p in mock_pages:
            p.extract_text.return_value = ""
        mock_pdf = MagicMock()
        mock_pdf.pages = mock_pages
        mock_pdf.close = MagicMock()
        mock_plumber_open.return_value = mock_pdf

        extractor = PDFExtractor()
        with pytest.raises(ExtractionError, match="no extractable text"):
            extractor.extract("empty.pdf")


# ── Hyperlink removal (integration-style with mocked fitz) ────────────────


class TestHyperlinkRemoval:
    def test_hyperlink_removal(self):
        """Top-of-page hyperlink text is removed from the cleaned output."""
        from src.extract import _get_top_hyperlink_texts, _remove_top_hyperlinks

        # Mock a single fitz page with one link in the top 15% and one span
        # whose bbox overlaps.
        mock_page = MagicMock()
        mock_page.rect.height = 800
        mock_page.get_links.return_value = [
            {"from": (10, 10, 200, 40), "type": 0}  # y0=10 < 0.15*800=120 → top
        ]
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "Home",
                                    "bbox": (10, 10, 60, 40),  # overlaps link rect
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        top_map = _get_top_hyperlink_texts(mock_doc, total_pages=1)
        assert 1 in top_map
        assert "Home" in top_map[1]

        raw = [{"page_number": 1, "text": "Home\nReal content here"}]
        cleaned = _remove_top_hyperlinks(raw, top_map)
        assert "Home" not in cleaned[0]
        assert "Real content here" in cleaned[0]
