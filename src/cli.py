"""CLI entry-point — two sub-commands that delegate to the same functions
the Streamlit UI uses.

Usage
-----
    python -m src.cli extract  --input <pdf>  [--output <json>]
    python -m src.cli generate [--config <config.json>] [--extracted <json>]
"""

import argparse
import json
import sys

from dotenv import load_dotenv

# Bootstrap .env before touching anything else, then initialise the app.
load_dotenv()

from src.bootstrapper import bootstrap  # noqa: E402
from src.app_config import CONFIG_PATH, OUTPUT_DIR  # noqa: E402
from src.extract import run_extraction  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

bootstrap()


def cmd_extract(args: argparse.Namespace) -> None:
    """Handle the ``extract`` sub-command."""
    output_path = args.output or str(OUTPUT_DIR / "extracted_text.json")
    run_extraction(file_path=args.input, output_path=output_path)
    print(f"Extraction complete → {output_path}")


def cmd_generate(args: argparse.Namespace) -> None:
    """Handle the ``generate`` sub-command."""
    with open(args.extracted, encoding="utf-8") as fh:
        extracted_data = json.load(fh)
    with open(args.config, encoding="utf-8") as fh:
        config = json.load(fh)

    def progress(msg: str, frac: float) -> None:
        print(f"  [{frac * 100:5.1f}%] {msg}")

    result = run_pipeline(extracted_data, config["sections"], progress_callback=progress)
    print(f"Script written  → {OUTPUT_DIR / 'podcast_script.txt'}")
    print(f"Report written  → {OUTPUT_DIR / 'verification_report.json'}")
    print(f"Word count: {result.word_count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Podcast Generator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # extract ────────────────────────────────────────────────────────────
    ext = sub.add_parser("extract", help="Extract text and sections from a PDF")
    ext.add_argument("--input", required=True, help="Path to the PDF file")
    ext.add_argument("--output", default=None, help="Output JSON path (optional)")

    # generate ───────────────────────────────────────────────────────────
    gen = sub.add_parser("generate", help="Run the podcast generation pipeline")
    gen.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    gen.add_argument(
        "--extracted",
        default=str(OUTPUT_DIR / "extracted_text.json"),
        help="Path to the cached extraction JSON",
    )

    args = parser.parse_args()
    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "generate":
        cmd_generate(args)


if __name__ == "__main__":  # pragma: no cover
    main()
