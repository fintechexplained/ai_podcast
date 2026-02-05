"""Central configuration — every tuneable constant lives here.

Each value reads from the environment first so that a .env file or a shell
export can override it without touching code.  Logging is configured by
``utility.logging_helper.setup_logging()``, called from
``bootstrapper.bootstrap()``.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
OUTPUT_DIR: Path = BASE_DIR / "output"
PROMPTS_DIR: Path = BASE_DIR / "prompts"
LOGS_DIR: Path = BASE_DIR / "logs"

DEFAULT_PDF: Path = DATA_DIR / "Vestas Annual Report 2024.pdf"
CONFIG_PATH: Path = BASE_DIR / "config.json"

# ── LLM / Agent ────────────────────────────────────────────────────────────
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o")
MAX_AGENT_ITERATIONS: int = int(os.getenv("MAX_AGENT_ITERATIONS", "5"))
SCORE_THRESHOLD: int = int(os.getenv("SCORE_THRESHOLD", "8"))
MAX_LLM_CALLS: int = int(os.getenv("MAX_LLM_CALLS", "30"))

# ── Podcast ────────────────────────────────────────────────────────────────
TARGET_WORD_COUNT: int = int(os.getenv("TARGET_WORD_COUNT", "2000"))

# ── Extraction ─────────────────────────────────────────────────────────────
# Lines appearing on more than this many pages are treated as nav bars.
# 0 means "auto: floor(total_pages / 2)" — calculated at runtime.
MAX_PAGE_APPEARANCES: int = int(os.getenv("MAX_PAGE_APPEARANCES", "0"))
HEADING_FONT_SIZE: float = float(os.getenv("HEADING_FONT_SIZE", "18"))
MAJOR_SECTION_FONT_SIZE: float = float(os.getenv("MAJOR_SECTION_FONT_SIZE", "26"))
MIN_HEADING_CHARS: int = int(os.getenv("MIN_HEADING_CHARS", "3"))

# ── Logging ────────────────────────────────────────────────────────────────
LOG_FILE: Path = LOGS_DIR / "app.log"
LLM_LOG_FILE: Path = OUTPUT_DIR / "llm_log.json"

