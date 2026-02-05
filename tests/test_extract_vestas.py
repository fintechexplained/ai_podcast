"""Integration test — runs real extraction on data/Vestas Annual Report 2024.pdf.

The unit tests in test_extract.py mock all fitz / pdfplumber I/O.  This module
exercises the full pipeline against the actual PDF to validate schema
correctness, section detection, and text-cleaning end-to-end.
"""

import pytest

from src.app_config import DEFAULT_PDF
from src.register import Registry


@pytest.fixture(scope="module")
def vestas_result():
    """Run extraction once; share the result across every test in this module."""
    if not DEFAULT_PDF.exists():
        pytest.skip("data/Vestas Annual Report 2024.pdf not present")
    extractor = Registry.get_extractor("pdf")
    return extractor.extract(str(DEFAULT_PDF))


# ── metadata ──────────────────────────────────────────────────────────────────


class TestVestasMetadata:
    def test_filename(self, vestas_result):
        assert vestas_result["metadata"]["filename"] == "Vestas Annual Report 2024.pdf"

    def test_total_pages_positive(self, vestas_result):
        assert vestas_result["metadata"]["total_pages"] > 0

    def test_strategy_is_valid(self, vestas_result):
        assert vestas_result["metadata"]["extraction_strategy"] in {
            "toc",
            "contents_page",
            "font_heuristic",
        }

    def test_version(self, vestas_result):
        assert vestas_result["metadata"]["version"] == "1.0"

    def test_extracted_at_present(self, vestas_result):
        assert "extracted_at" in vestas_result["metadata"]


# ── pages ─────────────────────────────────────────────────────────────────────


class TestVestasPages:
    def test_page_count_matches_metadata(self, vestas_result):
        assert len(vestas_result["pages"]) == vestas_result["metadata"]["total_pages"]

    def test_pages_numbered_sequentially(self, vestas_result):
        numbers = [p["page_number"] for p in vestas_result["pages"]]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_majority_of_pages_have_text(self, vestas_result):
        """Some pages may be image-only; expect > 50 % to contain extracted text."""
        non_empty = sum(1 for p in vestas_result["pages"] if p["text"].strip())
        total = len(vestas_result["pages"])
        assert non_empty / total > 0.5, f"Only {non_empty}/{total} pages have text"


# ── sections ──────────────────────────────────────────────────────────────────


class TestVestasSections:
    def test_sections_detected(self, vestas_result):
        assert len(vestas_result["sections"]) > 0

    def test_section_schema(self, vestas_result):
        total = vestas_result["metadata"]["total_pages"]
        for sec in vestas_result["sections"]:
            assert isinstance(sec["title"], str) and sec["title"].strip()
            assert 1 <= sec["start_page"] <= total
            assert sec["start_page"] <= sec["end_page"] <= total
            assert sec["level"] in {1, 2, 3}

    def test_sections_ordered_by_start_page(self, vestas_result):
        starts = [s["start_page"] for s in vestas_result["sections"]]
        assert starts == sorted(starts)
