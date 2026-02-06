"""Shared pytest fixtures — sample data used across the test suite."""

import pytest


@pytest.fixture(autouse=True, scope="session")
def _register_extractors():
    """Register file-type extractors once before the test session starts."""
    from src.bootstrapper import register_extractors

    register_extractors()


@pytest.fixture
def sample_extracted_data():
    """Minimal extracted_text.json structure with 5 sections and 100 pages."""
    sections = [
        {"title": "Financial Highlights", "start_page": 10, "end_page": 14, "level": 1},
        {"title": "Revenue Breakdown", "start_page": 11, "end_page": 12, "level": 2},
        {"title": "Cost Structure", "start_page": 13, "end_page": 14, "level": 2},
        {"title": "Sustainability", "start_page": 40, "end_page": 60, "level": 1},
        {"title": "Risk Management", "start_page": 70, "end_page": 85, "level": 1},
    ]
    pages = [{"page_number": i, "text": f"Content for page {i}"} for i in range(1, 101)]
    return {
        "metadata": {
            "filename": "test.pdf",
            "total_pages": 100,
            "extracted_at": "2025-01-01T00:00:00Z",
            "extraction_strategy": "toc",
            "version": "1.0",
        },
        "sections": sections,
        "pages": pages,
    }


@pytest.fixture
def sample_sections_config():
    """Typical config.json sections list."""
    return [
        {"name": "Financial Highlights", "page_override": None},
        {"name": "Sustainability", "page_override": "50-55"},
    ]


@pytest.fixture
def sample_script():
    return (
        "Alex: Welcome back everyone. Today we're diving into the annual report.\n"
        "Jordan: That's right Alex. Revenue grew 12% year-on-year.\n"
        "Alex: [laughs] Fair point Jordan. Actually I'd push back — 12% needs context.\n"
        "Jordan: You're right. The key takeaway is solid growth trajectory.\n"
        "Alex: Absolutely. Thanks for listening everyone.\n"
    )


@pytest.fixture
def sample_verification_report():
    return {
        "claims": [
            {
                "claim_text": "Revenue grew 12% year-on-year.",
                "status": "TRACED",
                "source_page": 10,
                "source_section": "Financial Highlights",
            },
            {
                "claim_text": "Company entered 3 new markets.",
                "status": "NOT_TRACED",
                "source_page": None,
                "source_section": None,
            },
            {
                "claim_text": "Employee engagement rose.",
                "status": "PARTIALLY_TRACED",
                "source_page": 42,
                "source_section": "Sustainability",
            },
        ],
        "coverage": [
            {
                "section": "Financial Highlights",
                "status": "COVERED",
                "key_points_total": 5,
                "key_points_covered": 5,
                "omitted_points": [],
            },
            {
                "section": "Sustainability",
                "status": "PARTIAL",
                "key_points_total": 8,
                "key_points_covered": 5,
                "omitted_points": ["Water targets", "Biodiversity", "Supply-chain audits"],
            },
        ],
        "summary": {
            "total_claims": 3,
            "traced": 1,
            "partially_traced": 1,
            "not_traced": 1,
            "total_key_points": 13,
            "key_points_covered": 10,
            "coverage_percentage": 76.9,
        },
    }
