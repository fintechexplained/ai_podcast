"""Integration tests — real PDF extraction with per-section assertions.

Emirates (tests/data/2024-2025.pdf):
    Single-column TOC, page-number-first layout (number on one line,
    title on the next).  All entries are flat (level 1).

Vestas (data/Vestas Annual Report 2024.pdf):
    Two-column TOC, dot-leader format, three heading levels.
"""

import pytest
from pathlib import Path

from src.register import Registry

# ── PDF paths ──────────────────────────────────────────────────────────────

TESTS_DIR = Path(__file__).resolve().parent
EMIRATES_PDF = TESTS_DIR / "data" / "2024-2025.pdf"
VESTAS_PDF = TESTS_DIR.parent / "data" / "Vestas Annual Report 2024.pdf"

# ── Emirates expected sections (title + start_page only; flat TOC) ─────────

EMIRATES_EXPECTED = [
    {"title": "Foreword from the Ruler of Dubai", "start_page": 4},
    {"title": "Financial highlights", "start_page": 6},
    {"title": "Chairman\u2019s statement", "start_page": 8},
    {"title": "Leadership", "start_page": 14},
    {"title": "Emirates highlights", "start_page": 16},
    {"title": "dnata highlights", "start_page": 42},
    {"title": "Group sustainability", "start_page": 56},
    {"title": "Our planet", "start_page": 62},
    {"title": "Our people", "start_page": 80},
    {"title": "Our communities", "start_page": 90},
    {"title": "Our business", "start_page": 98},
    {"title": "GRI reference table", "start_page": 108},
    {"title": "Our network", "start_page": 110},
    {"title": "Emirates financial commentary", "start_page": 114},
    {"title": "dnata financial commentary", "start_page": 124},
    {"title": "Emirates independent auditor\u2019s report", "start_page": 132},
    {"title": "Emirates consolidated financial statements", "start_page": 138},
    {"title": "dnata independent auditor\u2019s report", "start_page": 188},
    {"title": "dnata consolidated financial statements", "start_page": 192},
    {"title": "Emirates ten-year overview", "start_page": 236},
    {"title": "dnata ten-year overview", "start_page": 238},
    {"title": "Group ten-year overview", "start_page": 240},
    {"title": "Group companies of Emirates", "start_page": 241},
    {"title": "Group companies of dnata", "start_page": 242},
    {"title": "Glossary", "start_page": 244},
]

# ── Vestas expected sections (full schema: title, start_page, end_page, level) ─

VESTAS_EXPECTED = [
    {"title": "Letter from the Chair & CEO", "start_page": 3, "end_page": 4, "level": 1},
    {"title": "Our business", "start_page": 5, "end_page": 5, "level": 1},
    {"title": "In brief", "start_page": 6, "end_page": 14, "level": 1},
    {"title": "Highlights for the year", "start_page": 7, "end_page": 9, "level": 2},
    {"title": "Financial and operational key figures", "start_page": 10, "end_page": 10, "level": 2},
    {"title": "Sustainability key figures", "start_page": 11, "end_page": 11, "level": 2},
    {"title": "In focus: Five years of Vestas\u2019 Sustainability Strategy", "start_page": 12, "end_page": 12, "level": 2},
    {"title": "Outlook", "start_page": 13, "end_page": 14, "level": 2},
    {"title": "Strategy and ambitions", "start_page": 15, "end_page": 24, "level": 1},
    {"title": "Business model", "start_page": 16, "end_page": 16, "level": 2},
    {"title": "Market outlook", "start_page": 17, "end_page": 18, "level": 2},
    {"title": "Corporate strategy", "start_page": 19, "end_page": 21, "level": 2},
    {"title": "Business area strategy", "start_page": 22, "end_page": 23, "level": 2},
    {"title": "Capital structure strategy", "start_page": 24, "end_page": 24, "level": 2},
    {"title": "Business area progress", "start_page": 25, "end_page": 34, "level": 1},
    {"title": "Our people, our strength", "start_page": 26, "end_page": 27, "level": 2},
    {"title": "Onshore", "start_page": 28, "end_page": 28, "level": 2},
    {"title": "Offshore", "start_page": 29, "end_page": 29, "level": 2},
    {"title": "In focus: Repowering and lifetime extensions", "start_page": 30, "end_page": 30, "level": 2},
    {"title": "Service", "start_page": 31, "end_page": 31, "level": 2},
    {"title": "Development", "start_page": 32, "end_page": 32, "level": 2},
    {"title": "Customer partnerships", "start_page": 33, "end_page": 33, "level": 2},
    {"title": "Our footprint", "start_page": 34, "end_page": 34, "level": 2},
    {"title": "Corporate governance", "start_page": 35, "end_page": 221, "level": 1},
    {"title": "Corporate governance and governance principles", "start_page": 36, "end_page": 36, "level": 2},
    {"title": "Shareholders", "start_page": 37, "end_page": 37, "level": 2},
    {"title": "Board of Directors", "start_page": 38, "end_page": 41, "level": 2},
    {"title": "Day-to-day management", "start_page": 42, "end_page": 45, "level": 2},
    {"title": "Remuneration", "start_page": 46, "end_page": 46, "level": 2},
    {"title": "Sustainability governance", "start_page": 47, "end_page": 48, "level": 2},
    {"title": "Risk management", "start_page": 49, "end_page": 221, "level": 2},
    {"title": "Sustainability statement", "start_page": 51, "end_page": 51, "level": 3},
    {"title": "General information", "start_page": 52, "end_page": 52, "level": 3},
    {"title": "Progressing on our sustainability journey", "start_page": 53, "end_page": 55, "level": 3},
    {"title": "Vestas\u2019 inaugural Sustainability statement", "start_page": 56, "end_page": 56, "level": 3},
    {"title": "The result of the double materiality assessment", "start_page": 57, "end_page": 61, "level": 3},
    {"title": "Our value chain", "start_page": 62, "end_page": 62, "level": 3},
    {"title": "Sustainability risk management", "start_page": 63, "end_page": 63, "level": 3},
    {"title": "The double materiality assessment process", "start_page": 64, "end_page": 68, "level": 3},
    {"title": "Basis for preparation", "start_page": 69, "end_page": 70, "level": 3},
    {"title": "Environmental information", "start_page": 71, "end_page": 71, "level": 3},
    {"title": "E1 Climate change", "start_page": 72, "end_page": 80, "level": 3},
    {"title": "E3 Water and marine resources", "start_page": 81, "end_page": 82, "level": 3},
    {"title": "E4 Biodiversity and ecosystems", "start_page": 83, "end_page": 85, "level": 3},
    {"title": "E5 Circular economy and resource use", "start_page": 86, "end_page": 92, "level": 3},
    {"title": "EU Taxonomy", "start_page": 93, "end_page": 97, "level": 3},
    {"title": "Social information", "start_page": 98, "end_page": 98, "level": 3},
    {"title": "S1 Own workforce \u2013 Working conditions: Health and safety", "start_page": 99, "end_page": 101, "level": 3},
    {"title": "S1 Own workforce \u2013 Working conditions: Secure employment", "start_page": 102, "end_page": 106, "level": 3},
    {"title": "S1 Own workforce \u2013 Equal treatment and opportunities for all", "start_page": 107, "end_page": 110, "level": 3},
    {"title": "Statutory diversity reporting under Danish law", "start_page": 111, "end_page": 111, "level": 3},
    {"title": "S2 Workers in the value chain", "start_page": 112, "end_page": 116, "level": 3},
    {"title": "S3 Affected communities", "start_page": 117, "end_page": 122, "level": 3},
    {"title": "Governance information", "start_page": 123, "end_page": 123, "level": 3},
    {"title": "G1 Business conduct", "start_page": 124, "end_page": 127, "level": 3},
    {"title": "Entity-specific disclosures: Transparent tax", "start_page": 128, "end_page": 129, "level": 3},
    {"title": "Entity-specific disclosures: Cyber security risks", "start_page": 130, "end_page": 132, "level": 3},
    {"title": "Financial statements", "start_page": 133, "end_page": 133, "level": 3},
    {"title": "Consolidated financial statements, Financial performance, and Notes", "start_page": 134, "end_page": 188, "level": 3},
    {"title": "Parent company financial statements and Notes", "start_page": 189, "end_page": 198, "level": 3},
    {"title": "Auditor and management statements", "start_page": 199, "end_page": 205, "level": 3},
    {"title": "Additional information", "start_page": 206, "end_page": 221, "level": 3},
]

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def emirates_result():
    """Run extraction once for the Emirates PDF; skip if file is missing."""
    if not EMIRATES_PDF.exists():
        pytest.skip(f"{EMIRATES_PDF} not present")
    extractor = Registry.get_extractor("pdf")
    return extractor.extract(str(EMIRATES_PDF))


@pytest.fixture(scope="module")
def vestas_result():
    """Run extraction once for the Vestas PDF; skip if file is missing."""
    if not VESTAS_PDF.exists():
        pytest.skip(f"{VESTAS_PDF} not present")
    extractor = Registry.get_extractor("pdf")
    return extractor.extract(str(VESTAS_PDF))


# ── Emirates tests ─────────────────────────────────────────────────────────


class TestEmiratesMetadata:
    def test_strategy_is_contents_page(self, emirates_result):
        assert emirates_result["metadata"]["extraction_strategy"] == "contents_page"

    def test_total_pages_positive(self, emirates_result):
        assert emirates_result["metadata"]["total_pages"] > 0


class TestEmiratessections:
    def test_section_count(self, emirates_result):
        """Extracted section count matches the expected TOC."""
        assert len(emirates_result["sections"]) == len(EMIRATES_EXPECTED), (
            f"Got {len(emirates_result['sections'])} sections, "
            f"expected {len(EMIRATES_EXPECTED)}.\n"
            f"Extracted titles: {[s['title'] for s in emirates_result['sections']]}"
        )

    def test_section_titles_and_pages(self, emirates_result):
        """Every expected (title, start_page) pair is present exactly once."""
        for exp in EMIRATES_EXPECTED:
            matching = [
                s for s in emirates_result["sections"]
                if s["title"] == exp["title"] and s["start_page"] == exp["start_page"]
            ]
            assert len(matching) == 1, (
                f"Section '{exp['title']}' at page {exp['start_page']} "
                f"found {len(matching)} times"
            )

    def test_all_sections_level_1(self, emirates_result):
        """Emirates TOC is flat — every entry should be level 1."""
        for sec in emirates_result["sections"]:
            assert sec["level"] == 1, (
                f"Section '{sec['title']}' has level {sec['level']}, expected 1"
            )

    def test_end_pages_present(self, emirates_result):
        """Every section has an end_page key."""
        for sec in emirates_result["sections"]:
            assert "end_page" in sec

    def test_sections_ordered_by_start_page(self, emirates_result):
        starts = [s["start_page"] for s in emirates_result["sections"]]
        assert starts == sorted(starts)


# ── Vestas tests ───────────────────────────────────────────────────────────


class TestVestasMetadata:
    def test_strategy_is_contents_page(self, vestas_result):
        assert vestas_result["metadata"]["extraction_strategy"] == "contents_page"

    def test_total_pages(self, vestas_result):
        assert vestas_result["metadata"]["total_pages"] == 221


class TestVestasExtraction:
    def test_section_count(self, vestas_result):
        """Extracted section count matches the expected list."""
        assert len(vestas_result["sections"]) == len(VESTAS_EXPECTED), (
            f"Got {len(vestas_result['sections'])} sections, "
            f"expected {len(VESTAS_EXPECTED)}.\n"
            f"Extracted: {[(s['title'], s['start_page']) for s in vestas_result['sections']]}"
        )

    @pytest.mark.parametrize("idx", range(len(VESTAS_EXPECTED)))
    def test_section(self, vestas_result, idx):
        """Each section matches title, start_page, end_page, and level."""
        expected = VESTAS_EXPECTED[idx]
        sections = vestas_result["sections"]
        assert idx < len(sections), f"Section index {idx} out of range (only {len(sections)} extracted)"
        actual = sections[idx]

        assert actual["title"] == expected["title"], (
            f"Section {idx}: title mismatch\n  got:      {actual['title']!r}\n  expected: {expected['title']!r}"
        )
        assert actual["start_page"] == expected["start_page"], (
            f"Section {idx} '{expected['title']}': start_page {actual['start_page']} != {expected['start_page']}"
        )
        assert actual["end_page"] == expected["end_page"], (
            f"Section {idx} '{expected['title']}': end_page {actual['end_page']} != {expected['end_page']}"
        )
        assert actual["level"] == expected["level"], (
            f"Section {idx} '{expected['title']}': level {actual['level']} != {expected['level']}"
        )

    def test_sections_ordered_by_start_page(self, vestas_result):
        starts = [s["start_page"] for s in vestas_result["sections"]]
        assert starts == sorted(starts)
