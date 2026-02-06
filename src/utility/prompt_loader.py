"""Utility for loading prompt templates from the prompts/ directory."""

from pathlib import Path

from src.app_config import PROMPTS_DIR


def load_prompt(name: str) -> str:
    """Load a prompt file by name (without the .md extension).

    Args:
        name: e.g. "generate", "evaluate"

    Returns:
        The full text of the prompt file.

    Raises:
        FileNotFoundError: if the .md file does not exist in prompts/.
    """
    path: Path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
