"""Tests for pipeline.py — end-to-end orchestration.  LLM calls are mocked;
file I/O uses a temporary directory.
"""

import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import PipelineResult, run_pipeline


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def mock_resolved_passages():
    return OrderedDict(
        [
            ("Section A", {"start_page": 1, "end_page": 3, "text": "--- Page 1 ---\nSample text."}),
        ]
    )


@pytest.fixture
def mock_verification():
    return {
        "claims": [{"claim_text": "Fact.", "status": "TRACED", "source_page": 1, "source_section": "Section A"}],
        "coverage": [{"section": "Section A", "status": "COVERED", "key_points_total": 2, "key_points_covered": 2, "omitted_points": []}],
        "summary": {"total_claims": 1, "traced": 1, "partially_traced": 0, "not_traced": 0, "total_key_points": 2, "key_points_covered": 2, "coverage_percentage": 100.0},
    }


@pytest.fixture
def sample_extracted(sample_extracted_data):
    return sample_extracted_data


# ── tests ──────────────────────────────────────────────────────────────────


class TestFullPipeline:
    @patch("src.pipeline.verify.run_verification")
    @patch("src.pipeline.generate.run_generation")
    @patch("src.pipeline.section_filter.resolve")
    def test_full_pipeline_writes_all_outputs(
        self, mock_resolve, mock_generate, mock_verify, tmp_path, sample_extracted, mock_resolved_passages, mock_verification
    ):
        """podcast_script.txt, verification_report.json are written."""
        mock_resolve.return_value = mock_resolved_passages
        mock_generate.return_value = "Alex: Hello everyone. Jordan: Great show."
        mock_verify.return_value = mock_verification

        with patch("src.pipeline.OUTPUT_DIR", tmp_path):
            result = run_pipeline(
                sample_extracted,
                [{"name": "Section A", "page_override": None}],
            )

        assert (tmp_path / "podcast_script.txt").exists()
        assert (tmp_path / "verification_report.json").exists()

        script_on_disk = (tmp_path / "podcast_script.txt").read_text()
        assert script_on_disk == "Alex: Hello everyone. Jordan: Great show."

        report_on_disk = json.loads((tmp_path / "verification_report.json").read_text())
        assert report_on_disk == mock_verification

    @patch("src.pipeline.verify.run_verification")
    @patch("src.pipeline.generate.run_generation")
    @patch("src.pipeline.section_filter.resolve")
    def test_pipeline_result_fields(
        self, mock_resolve, mock_generate, mock_verify, tmp_path, sample_extracted, mock_resolved_passages, mock_verification
    ):
        """PipelineResult contains script, verification dict, and correct word_count."""
        mock_resolve.return_value = mock_resolved_passages
        script_text = "one two three four five"
        mock_generate.return_value = script_text
        mock_verify.return_value = mock_verification

        with patch("src.pipeline.OUTPUT_DIR", tmp_path):
            result = run_pipeline(
                sample_extracted,
                [{"name": "Section A", "page_override": None}],
            )

        assert isinstance(result, PipelineResult)
        assert result.script == script_text
        assert result.verification == mock_verification
        assert result.word_count == 5

    @patch("src.pipeline.verify.run_verification")
    @patch("src.pipeline.generate.run_generation")
    @patch("src.pipeline.section_filter.resolve")
    def test_progress_callback_called(
        self, mock_resolve, mock_generate, mock_verify, tmp_path, sample_extracted, mock_resolved_passages, mock_verification
    ):
        """The optional callback is invoked with increasing fractions."""
        mock_resolve.return_value = mock_resolved_passages
        mock_generate.return_value = "Script text here."
        mock_verify.return_value = mock_verification

        calls: list[tuple[str, float]] = []

        def cb(msg, frac):
            calls.append((msg, frac))

        with patch("src.pipeline.OUTPUT_DIR", tmp_path):
            run_pipeline(
                sample_extracted,
                [{"name": "Section A", "page_override": None}],
                progress_callback=cb,
            )

        # At minimum we expect the pipeline's own progress calls
        # (0.0, 0.15, 0.75, 0.9, 1.0) plus any from generate.
        fracs = [frac for _, frac in calls]
        assert fracs[0] == 0.0   # "Resolving sections"
        assert fracs[-1] == 1.0  # "Done."
        # Fractions should be non-decreasing (pipeline-level calls).
        pipeline_fracs = [f for f in fracs if f in (0.0, 0.15, 0.75, 0.9, 1.0)]
        assert pipeline_fracs == sorted(pipeline_fracs)
