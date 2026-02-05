# AI Podcast Generator — Technical Design Document

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Layout](#2-repository-layout)
3. [Architecture Diagram](#3-architecture-diagram)
4. [Configuration Layer](#4-configuration-layer-app_configpy)
5. [IoC Container](#5-ioc-container-registerpy)
6. [Prompt Management](#6-prompt-management)
7. [Layer 1 — PDF Extraction](#7-layer-1--pdf-extraction-extractpy)
8. [Section Resolution](#8-section-resolution-filterpy)
9. [Layer 2 — Podcast Generation](#9-layer-2--podcast-generation-generatepy)
10. [Verification](#10-verification-verifypy)
11. [Pipeline Orchestrator](#11-pipeline-orchestrator-pipelinepy)
12. [CLI Interface](#12-cli-interface-clipy)
13. [Streamlit UI](#13-streamlit-ui-apppy)
14. [Output Files](#14-output-files)
15. [Logging](#15-logging)
16. [Testing Strategy](#16-testing-strategy)
17. [Error Handling Guidelines](#17-error-handling-guidelines)
18. [User Guide](#18-user-guide)
19. [Dependencies](#19-dependencies)
20. [README Outline](#20-readmemd-outline)

---

## 1. Project Overview

The AI Podcast Generator takes any corporate PDF, extracts its text and section structure, and produces a two-host podcast script together with a full verification report that traces every factual claim back to the source.

**Key design constraints:**

- Extraction is expensive — it runs once and caches to `output/extracted_text.json`. Every downstream step reads from that cache.
- The Streamlit UI and the CLI share the exact same Python functions. No logic is duplicated.
- The default input is `data/Vestas Annual Report 2024.pdf` (221 pages), but the pipeline is generic and works on any corporate PDF.
- All LLM interaction goes through PydanticAI agents backed by the OpenAI provider. Agents are isolated so each can be tested, logged, and swapped independently.

---

## 2. Repository Layout

```
ai_podcast/
│
├── config.json                 # user-facing section selection config
├── requirements.txt            # Python dependencies
├── .env.example                # template for environment variables
├── README.md                   # project readme with architecture diagram
│
├── data/
│   ├── logo.png                # sidebar logo (Lunate branding)
│   └── Vestas Annual Report 2024.pdf
│
├── design/
│   ├── planning.md             # this file
│
├── logs/
│   └── app.log                 # application log (created at runtime)
│
├── output/                     # all generated artefacts (created at runtime)
│   ├── extracted_text.json
│   ├── podcast_script.txt
│   ├── verification_report.json
│   └── llm_log.json
│
├── prompts/                    # every LLM prompt as a Markdown file
│   ├── generate.md
│   ├── evaluate.md
│   ├── improve.md
│   ├── verify_claims.md
│   └── verify_coverage.md
│
├── src/
│   ├── __init__.py
│   ├── app.py                  # Streamlit UI entry-point
│   ├── app_config.py           # all tuneable constants (env-overridable)
│   ├── cli.py                  # CLI entry-point (two sub-commands)
│   ├── extract.py              # PDF → extracted_text.json
│   ├── filter.py               # config.json sections → resolved passages
│   ├── generate.py             # PydanticAI Generator / Evaluator / Improver agents
│   ├── verify.py               # PydanticAI Claims + Coverage verification agents
│   ├── pipeline.py             # single run_pipeline() shared by UI and CLI
│   ├── register.py             # IoC container for file-type extractors
│   └── prompt_loader.py        # utility: load a prompt .md by name
│
└── tests/
    ├── __init__.py
    ├── conftest.py             # shared fixtures (sample PDFs, mock data)
    ├── test_extract.py         # extraction + section detection + cleaning
    ├── test_filter.py          # section resolution logic
    ├── test_generate.py        # agent loop (LLM calls mocked)
    ├── test_verify.py          # verification logic (LLM calls mocked)
    └── test_pipeline.py        # end-to-end pipeline (LLM calls mocked)
```

---

## 3. Architecture Diagram

```
  PDF file (any corporate PDF)
       │
       ▼
  ┌─────────────┐   pdfplumber (text)
  │  extract.py │   fitz / PyMuPDF  (TOC, sections, hyperlinks)
  └──────┬──────┘
         │  writes
         ▼
  extracted_text.json          ◄── cached; all downstream steps read from here
         │
         ▼
  ┌─────────────┐   reads config.json  (section names + optional page overrides)
  │  filter.py  │
  └──────┬──────┘
         │  resolved source passages
         ▼
  ┌──────────────────────────────────────────────────┐
  │                  generate.py                      │
  │                                                  │
  │  ┌───────────┐    ┌───────────┐   ┌───────────┐ │
  │  │ Generator │───▶│ Evaluator │──▶│ Improver  │ │
  │  │   Agent   │    │   Agent   │   │   Agent   │ │
  │  └───────────┘    └───────────┘   └─────┬─────┘ │
  │        ▲           score < 8           │        │
  │        └───────────────────────────────┘        │
  │              loop: up to MAX_AGENT_ITERATIONS   │
  └──────────────────────┬───────────────────────────┘
                         │  final script
                         ▼
  ┌──────────────────────────────┐
  │          verify.py           │
  │  Claims Agent + Coverage Agent│
  └────────┬─────────┬───────────┘
           │         │
           ▼         ▼
  podcast_script.txt   verification_report.json
           │         │
           ▼         ▼
  ┌─────────────────────────────┐
  │  app.py  (Streamlit UI)     │
  │     OR                      │
  │  cli.py  (two-step CLI)     │
  └─────────────────────────────┘

  Cross-cutting:
    • register.py     — IoC container; resolves extractors by file extension
    • app_config.py   — single source of truth for every configurable constant
    • prompt_loader.py— loads prompts/*.md at call time
    • llm_log.json   — append-only log of every LLM round-trip
    • logs/app.log    — standard Python logging output
```

---

## 4. Configuration Layer (`app_config.py`)

Every tuneable value lives in `src/app_config.py`. Each constant reads from the environment first so that a `.env` file or a shell export can override it without touching code.

```python
# src/app_config.py
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
OUTPUT_DIR: Path = BASE_DIR / "output"
PROMPTS_DIR: Path = BASE_DIR / "prompts"
LOGS_DIR: Path = BASE_DIR / "logs"

DEFAULT_PDF: Path = DATA_DIR / "Vestas Annual Report 2024.pdf"
CONFIG_PATH: Path = BASE_DIR / "config.json"

# ── LLM / Agent ────────────────────────────────────────────────────
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o")
MAX_AGENT_ITERATIONS: int = int(os.getenv("MAX_AGENT_ITERATIONS", "5"))
SCORE_THRESHOLD: int = int(os.getenv("SCORE_THRESHOLD", "8"))
MAX_LLM_CALLS: int = int(os.getenv("MAX_LLM_CALLS", "30"))

# ── Podcast ────────────────────────────────────────────────────────
TARGET_WORD_COUNT: int = int(os.getenv("TARGET_WORD_COUNT", "2000"))

# ── Extraction ─────────────────────────────────────────────────────
# Lines appearing on more than this many pages are treated as nav bars.
# 0 means "auto: floor(total_pages / 2)" — calculated at runtime.
MAX_PAGE_APPEARANCES: int = int(os.getenv("MAX_PAGE_APPEARANCES", "0"))
HEADING_FONT_SIZE: float = float(os.getenv("HEADING_FONT_SIZE", "18"))
MAJOR_SECTION_FONT_SIZE: float = float(os.getenv("MAJOR_SECTION_FONT_SIZE", "26"))
MIN_HEADING_CHARS: int = int(os.getenv("MIN_HEADING_CHARS", "3"))

# ── Logging ────────────────────────────────────────────────────────
LOG_FILE: Path = LOGS_DIR / "app.log"
LLM_LOG_FILE: Path = OUTPUT_DIR / "llm_log.json"
```

**`.env.example`** ships with the repo so every developer sees the full list of overridable keys:

```ini
# .env.example
OPENAI_API_KEY=sk-…
MODEL_NAME=gpt-4o
MAX_AGENT_ITERATIONS=5
SCORE_THRESHOLD=8
MAX_LLM_CALLS=30
TARGET_WORD_COUNT=2000
MAX_PAGE_APPEARANCES=0
HEADING_FONT_SIZE=18
MAJOR_SECTION_FONT_SIZE=26
MIN_HEADING_CHARS=3
```

---

## 5. IoC Container (`register.py`)

The registry decouples the rest of the application from concrete extractor classes. A new file type (DOCX, EPUB, …) can be added later by writing one class and calling `Registry.register(...)` — nothing else changes.

```python
# src/register.py
from abc import ABC, abstractmethod
from typing import Dict, Type


class BaseExtractor(ABC):
    """Interface every file-type extractor must implement."""

    @abstractmethod
    def extract(self, file_path: str) -> dict:
        """Return the canonical extracted-text dict.

        The returned dict must conform to the schema defined in §7.4
        (metadata, sections, pages).
        """
        ...


class Registry:
    """Singleton IoC container.  Extractors register themselves at
    module-load time; consumers resolve them by file extension."""

    _extractors: Dict[str, Type[BaseExtractor]] = {}

    @classmethod
    def register(cls, extension: str, extractor_class: Type[BaseExtractor]) -> None:
        """Register an extractor class for a given file extension (e.g. 'pdf')."""
        cls._extractors[extension.lower().lstrip(".")] = extractor_class

    @classmethod
    def get_extractor(cls, extension: str) -> BaseExtractor:
        """Instantiate and return the extractor for the given extension.

        Raises ValueError if no extractor is registered.
        """
        key = extension.lower().lstrip(".")
        if key not in cls._extractors:
            raise ValueError(f"No extractor registered for '.{key}'")
        return cls._extractors[key]()
```

`extract.py` calls `Registry.register("pdf", PDFExtractor)` at module load time. Both the Streamlit upload handler and the CLI resolve the correct extractor via `Registry.get_extractor(suffix)`.

---

## 6. Prompt Management

All LLM prompts live as Markdown files in `prompts/`. This makes editing prompts a no-code task and keeps the source files clean.

### 6.1 Prompt Files

| File | Used by | Purpose |
|---|---|---|
| `generate.md` | Generator Agent | System instructions + user template for first-draft script creation |
| `evaluate.md` | Evaluator Agent | Scoring rubric and instructions for quality evaluation |
| `improve.md` | Improver Agent | Revision rules applied when score is below threshold |
| `verify_claims.md` | Claims Agent | Instructions for tracing individual facts back to source |
| `verify_coverage.md` | Coverage Agent | Instructions for checking section-level completeness |

### 6.2 Placeholder Convention

Each prompt file uses `{{placeholder}}` tokens that the calling code fills in before sending:

| Placeholder | Populated with |
|---|---|
| `{{source_text}}` | The resolved source passages for the selected sections |
| `{{script}}` | The current podcast script (for evaluate / improve / verify) |
| `{{scores}}` | The JSON evaluation scores (for improve) |
| `{{target_word_count}}` | Value of `TARGET_WORD_COUNT` from config |
| `{{section_list}}` | JSON list of selected section names (for coverage check) |

### 6.3 Loader Utility (`prompt_loader.py`)

```python
# src/prompt_loader.py
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
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
```

---

## 7. Layer 1 — PDF Extraction (`extract.py`)

This is the most complex single module. It combines two libraries for complementary tasks:

| Library | Role |
|---|---|
| **pdfplumber** | Extracts raw text, page by page, with accurate layout handling |
| **fitz (PyMuPDF)** | Reads the PDF outline (TOC), detects font sizes and bold spans for heuristic headings, and retrieves hyperlink annotations |

### 7.1 High-Level Flow

```
open PDF with pdfplumber          → raw page text
open PDF with fitz                → outline, font details, hyperlinks
       │
       ▼
detect_sections()                 → list of (title, start_page, level)
       │
       ▼
compute end_pages                 → fill in end_page for each section
       │
       ▼
clean_pages()                     → remove nav bars, arrows, hyperlinks, bad encoding
       │
       ▼
assemble & write extracted_text.json
```

### 7.2 Section Detection — Three-Tier Strategy

The extractor tries each tier in order and stops at the first one that produces results.

#### Tier 1 — PDF Outline (TOC)

```python
import fitz

doc = fitz.open(file_path)
toc = doc.get_toc()   # returns list of [level, title, page_number]
```

If `len(toc) > 0` the outline is used directly. Each entry already carries level, title, and 1-based page number. No further heuristics needed.

#### Tier 2 — Contents Page

If the outline is empty, the extractor searches every page for one whose leading text matches a known keyword (case-insensitive):

```
"contents"
"table of contents"
"table des matières"
```

Once the Contents page is identified, its text is parsed to extract `(title, page_number)` pairs:

1. **Column detection** — Cluster the x-coordinates of text blocks on the page. If two or more clusters are separated by a gap larger than the average block width, the page is multi-column. Parse each column independently, top to bottom.
2. **Line parsing** — Each line typically ends with a page number (possibly after a run of dots or dashes). A regex like `^(.+?)\s*[.\-–—]+\s*(\d+)\s*$` extracts the title and page number.
3. **Level from indentation** — Within each column, the leftmost text position is the baseline (level 1). Any line whose left edge is indented beyond the baseline by a configurable threshold (e.g., 10 pt) is level 2; a further indent is level 3.

#### Tier 3 — Font-Size Heuristic

If neither outline nor Contents page is available, the extractor scans every page using fitz's detailed text extraction (`get_text("dict")`). For each text span it checks:

| Condition | Assigned Level |
|---|---|
| font size ≥ `MAJOR_SECTION_FONT_SIZE` (default 26 pt) | 1 — major section |
| font size ≥ `HEADING_FONT_SIZE` (default 18 pt) | 2 — heading |
| bold flag set AND font size ≥ 14 pt | 2 — heading |

**Candidate filtering rules (applied in order):**

1. The text must contain at least `MIN_HEADING_CHARS` (default 3) alphabetic characters. This filters out decorative callouts like arrows, percentages, and single-digit page numbers.
2. Consecutive candidate lines on the **same page** are merged into one title (joined with a single space). This handles titles that wrap across two lines.
3. After all candidates are collected, count how many distinct pages each title appears on. Drop any title whose count exceeds `MAX_PAGE_APPEARANCES` (default `floor(total_pages / 2)`). These are navigation bar fragments, not real headings.

### 7.3 Computing `end_page`

Sections are initially detected with only a `start_page`. End pages are derived in a single pass:

```
For each section i (in order of start_page):
    Find the next section j whose level ≤ section i's level.
    end_page[i] = start_page[j] − 1

    If no such j exists (i is the last section at its level or deeper):
        end_page[i] = total_pages
```

### 7.4 Text Cleaning Pipeline

Applied to every page's text after extraction. Steps run in this exact order:

#### Step 1 — Nav-Bar Removal

Scan the first few lines (top 3–5 lines) of every page. Build a frequency map:

```
line_text  →  number of pages on which it appears
```

Any line whose frequency exceeds `MAX_PAGE_APPEARANCES` is deleted from **all** pages where it occurs. This catches repeated headers like `"Home  About  Investors  Contact"`.

#### Step 2 — Arrow-Link Removal

Any line whose first non-whitespace character is one of the nav-arrow characters below is removed entirely:

```
→   ▶   ▸   ►
```

These are clickable sub-links in the PDF that have no meaning as plain text.

#### Step 3 — Top Hyperlink Removal

Using fitz, retrieve the list of hyperlink annotations on each page. Identify which lines of extracted text correspond to those hyperlinks (by comparing bounding-box coordinates). If those lines appear at the **top** of the page (within the first ~15% of the page height), remove them.

#### Step 4 — Encoding Cleanup

Attempt to encode each character as UTF-8. Any character that fails is silently dropped. If the entire line becomes empty after stripping, remove the line. Log a warning with the page number whenever characters are dropped.

### 7.5 Output Schema — `extracted_text.json`

```json
{
  "metadata": {
    "filename": "Vestas Annual Report 2024.pdf",
    "total_pages": 221,
    "extracted_at": "2025-06-15T10:30:00Z",
    "extraction_strategy": "toc",
    "version": "1.0"
  },
  "sections": [
    {
      "title": "Financial Highlights",
      "start_page": 10,
      "end_page": 14,
      "level": 1
    },
    {
      "title": "Revenue Breakdown",
      "start_page": 11,
      "end_page": 12,
      "level": 2
    }
  ],
  "pages": [
    {
      "page_number": 1,
      "text": "Cleaned text for page 1 …"
    }
  ]
}
```

`extraction_strategy` records which tier was used (`"toc"`, `"contents_page"`, or `"font_heuristic"`) for transparency and debugging.

### 7.6 Public Interface

```python
# Importable function — used by pipeline.py and app.py
from src.extract import run_extraction

result: dict = run_extraction(file_path="data/Vestas Annual Report 2024.pdf")
# result conforms to the schema above; also written to output/extracted_text.json

# Standalone CLI
# python src/extract.py --input "data/Vestas Annual Report 2024.pdf" --output output/extracted_text.json
```

---

## 8. Section Resolution (`filter.py`)

`filter.py` bridges the gap between the user's section selection (from `config.json` or the UI) and the actual sections that the extractor discovered.

### 8.1 Input — `config.json`

```json
{
  "sections": [
    { "name": "Financial Highlights",  "page_override": null },
    { "name": "Sustainability",        "page_override": "50-65" },
    { "name": "Risk Management",       "page_override": null }
  ]
}
```

`page_override` is either `null` (use detected boundaries) or a string: a single page (`"42"`) or a range (`"50-65"`).

### 8.2 Resolution Algorithm

```
for each entry in the section list:

    if entry.page_override is set:
        parse the override into (start, end)
        collect text for pages [start .. end] from extracted_text.json
        ← page_override takes priority; section boundaries are ignored

    else:
        compare entry.name against every section title in extracted_text.json
        match rule:
            • case-insensitive
            • accept if  A is a substring of B  OR  B is a substring of A
        if multiple sections match:
            pick the one with the greatest character overlap
        collect text for pages [matched.start_page .. matched.end_page]

    if no match and no override:
        raise SectionNotFoundError(entry.name)
```

Return value: an ordered dict mapping each requested section name to its resolved page range and concatenated page text.

---

## 9. Layer 2 — Podcast Generation (`generate.py`)

### 9.1 Agent Architecture

Four PydanticAI agents, each backed by the OpenAI provider configured via `app_config.MODEL_NAME`. Every agent shares a common logging wrapper that writes to `llm_log.json` after each call.

```python
from pydantic_ai import Agent
from src.app_config import MODEL_NAME

# Each agent is a module-level instance.  System prompts are loaded from
# prompts/*.md at call time via load_prompt().

generator_agent = Agent(
    f"openai:{MODEL_NAME}",
    system_prompt=load_prompt("generate"),
)

evaluator_agent = Agent(
    f"openai:{MODEL_NAME}",
    system_prompt=load_prompt("evaluate"),
)

improver_agent = Agent(
    f"openai:{MODEL_NAME}",
    system_prompt=load_prompt("improve"),
)
```

> **Note:** `verify.py` defines its own two agents (`claims_agent`, `coverage_agent`) using the same pattern.

### 9.2 Generator Agent

**Prompt file:** `prompts/generate.md`

The system prompt instructs the model to produce a podcast script with these constraints:

- Two hosts: **Alex** and **Jordan**.
- Turns do **not** rigidly alternate — one host may speak several times in a row when the topic calls for it.
- At least **one genuine disagreement** moment between the hosts.
- Sparse emotion cues in square brackets: `[laughs]`, `[pauses]`, `[nods]`. Not on every line.
- A clear **takeaway** section at the end.
- Target length: `TARGET_WORD_COUNT` words (default 2000).
- Every fact must come from the source passages — the model must never invent data.
- Tone: lightweight, professional, conversational.

The user message template fills `{{source_text}}` and `{{target_word_count}}`.

### 9.3 Evaluator Agent

**Prompt file:** `prompts/evaluate.md`

Scores the script on five dimensions, each 1–10:

| Dimension | What is measured |
|---|---|
| **Teachability** | Does the listener learn something concrete and actionable? |
| **Conversational Feel** | Does it sound like a natural spoken exchange — not a monologue read aloud? |
| **Friction / Disagreement** | Is there a genuine point of debate or tension between the hosts? |
| **Takeaway Clarity** | Is the key message stated plainly at the end? |
| **Accuracy** | Are all stated facts directly traceable to the provided source text? |

**Strict scoring rules baked into `evaluate.md`:**

- Be strict. Do not inflate scores.
- Any hallucinated fact drops Accuracy to ≤ 3.
- Factual correctness is weighted above creativity.
- No new information may be introduced that is absent from the source.
- Language must be respectful, inclusive, and free from harmful or biased phrasing. Violations drop the relevant dimension to 1.

The agent returns a JSON object:

```json
{
  "teachability": 7,
  "conversational_feel": 8,
  "friction_disagreement": 6,
  "takeaway_clarity": 9,
  "accuracy": 8,
  "overall": 7.6,
  "feedback": "The disagreement moment felt forced …"
}
```

`overall` is the arithmetic mean of the five scores, rounded to one decimal place. This value drives the loop decision.

### 9.4 Improver Agent

**Prompt file:** `prompts/improve.md`

Only invoked when `overall < SCORE_THRESHOLD`. The system prompt instructs the model to revise the script by:

1. **Removing** any hallucinated facts entirely.
2. **Adding** missing key points from the source that the Evaluator flagged.
3. **Improving** spoken flow and transitions.
4. **Preserving** the original tone and target duration.
5. **Not introducing** any fact that is not present in the source passages.

The user message template fills `{{script}}`, `{{scores}}` (the full evaluator JSON), and `{{source_text}}`.

### 9.5 Agent Loop

Orchestrated inside `generate.py`, called by `pipeline.py`:

```
iteration = 0
script = generator_agent.run(source_passages)

while iteration < MAX_AGENT_ITERATIONS:
    scores = evaluator_agent.run(script, source_passages)
    log_llm_call("evaluator", iteration, scores)

    if scores.overall >= SCORE_THRESHOLD:
        break                              # quality bar met

    script = improver_agent.run(script, scores, source_passages)
    log_llm_call("improver", iteration, script)
    iteration += 1

# After loop exits (quality met OR max iterations reached):
#   script is the final version; pass it to verify.py
```

The loop will execute **at most** `MAX_AGENT_ITERATIONS` (default 5) full cycles. If the score never reaches the threshold, the best script produced so far is used.

### 9.6 LLM Call Logging

Every round-trip to the model appends one JSON object to `output/llm_log.json`:

```json
{
  "timestamp": "2025-06-15T10:45:00Z",
  "agent": "generator",
  "iteration": 0,
  "model": "gpt-4o",
  "prompt_length_chars": 3200,
  "response_length_chars": 8100,
  "usage": {
    "prompt_tokens": 812,
    "completion_tokens": 2040
  },
  "scores": null
}
```

For evaluator calls, the `scores` field is populated with the full score JSON. This log is append-only and is never truncated during a session.

---

## 10. Verification (`verify.py`)

Verification is the final quality gate. It answers two independent questions:

1. **Claims** — Is every factual statement in the script supported by the source?
2. **Coverage** — Did the script actually cover the key information from each selected section?

### 10.1 Claims Agent

**Prompt file:** `verify_claims.md`

The agent receives the final script and the source passages. It:

1. Extracts every discrete factual claim from the script.
2. Classifies each claim:

| Status | Meaning |
|---|---|
| `TRACED` | The claim is directly supported by a specific passage. The agent records the **page number** and **section name**. |
| `PARTIALLY_TRACED` | The claim is partially supported — some detail cannot be confirmed from the source. |
| `NOT_TRACED` | No supporting evidence in the provided source text. |

Example output (partial):

```json
[
  {
    "claim_text": "Vestas revenue grew 12 % year-on-year.",
    "status": "TRACED",
    "source_page": 42,
    "source_section": "Financial Highlights"
  },
  {
    "claim_text": "The company entered three new markets in Asia.",
    "status": "NOT_TRACED",
    "source_page": null,
    "source_section": null
  }
]
```

### 10.2 Coverage Agent

**Prompt file:** `verify_coverage.md`

A second agent checks the reverse direction. For each section that was fed into the pipeline, it determines whether the script covered the key information:

| Status | Meaning |
|---|---|
| `COVERED` | All key points from the section appear in the script. |
| `PARTIAL` | Some key points are present; others are missing. The agent lists the specific omitted points. |
| `OMITTED` | The section contributed no material to the final script. |

### 10.3 Summary Metrics

Calculated after both agents return:

```
coverage_percentage = (total key points covered across all sections)
                      ──────────────────────────────────────────────  × 100
                      (total key points across all sections)
```

### 10.4 Output Schema — `verification_report.json`

```json
{
  "claims": [
    {
      "claim_text": "Vestas revenue grew 12 % year-on-year.",
      "status": "TRACED",
      "source_page": 42,
      "source_section": "Financial Highlights"
    },
    {
      "claim_text": "The company entered three new markets in Asia.",
      "status": "NOT_TRACED",
      "source_page": null,
      "source_section": null
    }
  ],
  "coverage": [
    {
      "section": "Financial Highlights",
      "status": "COVERED",
      "key_points_total": 6,
      "key_points_covered": 6,
      "omitted_points": []
    },
    {
      "section": "Sustainability",
      "status": "PARTIAL",
      "key_points_total": 8,
      "key_points_covered": 5,
      "omitted_points": [
        "Water consumption reduction targets",
        "Biodiversity commitments",
        "Supply-chain audit results"
      ]
    }
  ],
  "summary": {
    "total_claims": 24,
    "traced": 20,
    "partially_traced": 2,
    "not_traced": 2,
    "total_key_points": 14,
    "key_points_covered": 11,
    "coverage_percentage": 78.6
  }
}
```

---

## 11. Pipeline Orchestrator (`pipeline.py`)

`pipeline.py` is the single entry-point shared by the Streamlit UI and the CLI. It wires together filter → generate → verify and writes all output files.

```python
# src/pipeline.py
import json
from typing import Callable, Optional
from dataclasses import dataclass

from src import filter as section_filter
from src import generate
from src import verify
from src.app_config import OUTPUT_DIR


@dataclass
class PipelineResult:
    script: str
    verification: dict
    word_count: int


def run_pipeline(
    extracted_data: dict,                                   # parsed extracted_text.json
    selected_sections: list[dict],                          # [{"name": ..., "page_override": ...}, ...]
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> PipelineResult:
    """Run the full generation + verification pipeline.

    Args:
        extracted_data:      The cached extraction output (dict).
        selected_sections:   List of section dicts with 'name' and optional 'page_override'.
        progress_callback:   If provided, called as (message, fraction) at each stage
                             so the UI can show live status.  fraction ranges 0.0 → 1.0.

    Returns:
        PipelineResult with the final script, verification report, and word count.
    """

    def _progress(msg: str, frac: float):
        if progress_callback:
            progress_callback(msg, frac)

    # 1. Resolve sections
    _progress("Resolving sections …", 0.0)
    source_passages = section_filter.resolve(extracted_data, selected_sections)

    # 2. Run generation + eval/improve loop
    _progress("Generating podcast script …", 0.15)
    script = generate.run_generation(source_passages, progress_callback=_progress)

    # 3. Run verification
    _progress("Verifying claims and coverage …", 0.75)
    verification = verify.run_verification(script, source_passages, selected_sections)

    # 4. Write output files
    _progress("Writing output files …", 0.9)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUTPUT_DIR / "podcast_script.txt").write_text(script, encoding="utf-8")
    (OUTPUT_DIR / "verification_report.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    word_count = len(script.split())
    _progress("Done.", 1.0)

    return PipelineResult(script=script, verification=verification, word_count=word_count)
```

---

## 12. CLI Interface (`cli.py`)

Two sub-commands, both delegating to the same functions the UI uses.

```bash
# Step 1 — Extract a PDF into the JSON cache
python -m src.cli extract --input "data/Vestas Annual Report 2024.pdf" [--output output/extracted_text.json]

# Step 2 — Generate the podcast (reads the cache; uses config.json for section selection)
python -m src.cli generate [--config config.json] [--extracted output/extracted_text.json]
```

### Implementation Sketch

```python
# src/cli.py
import argparse
import json
import sys

from src.extract import run_extraction
from src.pipeline import run_pipeline
from src.app_config import CONFIG_PATH, OUTPUT_DIR


def cmd_extract(args):
    result = run_extraction(file_path=args.input)
    output_path = args.output or str(OUTPUT_DIR / "extracted_text.json")
    # result is already written by run_extraction; also return it for chaining
    print(f"Extraction complete → {output_path}")


def cmd_generate(args):
    with open(args.extracted) as fh:
        extracted_data = json.load(fh)
    with open(args.config) as fh:
        config = json.load(fh)

    def progress(msg, frac):
        print(f"  [{frac * 100:5.1f}%] {msg}")

    result = run_pipeline(extracted_data, config["sections"], progress_callback=progress)
    print(f"Script written  → {OUTPUT_DIR / 'podcast_script.txt'}")
    print(f"Report written  → {OUTPUT_DIR / 'verification_report.json'}")
    print(f"Word count: {result.word_count}")


def main():
    parser = argparse.ArgumentParser(description="AI Podcast Generator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # extract
    ext = sub.add_parser("extract", help="Extract text and sections from a PDF")
    ext.add_argument("--input", required=True, help="Path to the PDF file")
    ext.add_argument("--output", default=None, help="Output JSON path (optional)")

    # generate
    gen = sub.add_parser("generate", help="Run the podcast generation pipeline")
    gen.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    gen.add_argument("--extracted", default=str(OUTPUT_DIR / "extracted_text.json"),
                     help="Path to the cached extraction JSON")

    args = parser.parse_args()
    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "generate":
        cmd_generate(args)


if __name__ == "__main__":
    main()
```

---

## 13. Streamlit UI (`app.py`)

### 13.1 Session State Keys

All persistent state lives in `st.session_state`. Switching tabs or clicking buttons never resets data that was already computed.

| Key | Type | Set by |
|---|---|---|
| `extracted_data` | `dict \| None` | Tab 1 — after extraction completes |
| `sections` | `list[dict] \| None` | Tab 1 — parsed from `extracted_data` |
| `selected_sections` | `list[str]` | Tab 2 — checkbox selections |
| `page_overrides` | `dict[str, str]` | Tab 2 — user-typed page ranges |
| `script` | `str \| None` | Tab 2 — after generation completes |
| `verification` | `dict \| None` | Tab 2 — after generation completes |
| `word_count` | `int \| None` | Derived from script |

### 13.2 Sidebar

```
┌─────────────────────────┐
│   [logo.png]            │   ← st.sidebar.image("data/logo.png")
│                         │
│   🔄  Reset             │   ← st.sidebar.button; clears all session_state keys
└─────────────────────────┘
```

- API key is loaded once at startup via `python-dotenv`: `load_dotenv()` → `os.getenv("OPENAI_API_KEY")`.

### 13.3 Tab 1 — Extract

**Layout:**

```
┌────────────────────────────────────────────┐
│  Upload a PDF                              │
│  [ Browse files … ]                        │
│                                            │
│  [ Extract ]   ← disabled until a file     │
│                  is uploaded               │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ Title              │ Pages  │ Level  │  │  ← st.dataframe; visible only after
│  ├────────────────────┼────────┼────────┤  │     extraction succeeds
│  │ Financial Highlights│ 10–14 │   1    │  │
│  │ Revenue Breakdown  │ 11–12  │   2    │  │
│  │ …                  │  …     │   …    │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

The **Extract** button wraps `run_extraction()` inside an `st.status()` context manager so the user sees live progress text while the (potentially slow) extraction runs.

### 13.4 Tab 2 — Generate

**Guard:** if `extracted_data` is `None`, display an info message ("Run extraction first") and return. Do not render anything else on this tab.

**Layout:**

```
┌────────────────────────────────────────────┐
│  Select sections                           │
│                                            │
│  ▾ Financial Highlights (pp 10–14)         │  ← st.expander
│      ☑ Financial Highlights                │     parent checkbox
│      ☑   Revenue Breakdown (pp 11–12)      │     child checkbox — auto-checked
│      ☐   Cost Structure    (pp 13–14)      │       when parent is checked
│  ▸ Sustainability          (pp 40–60)      │
│      ☐ Sustainability                      │
│  …                                         │
│                                            │
│  Page overrides (only for selected)        │
│  Financial Highlights: [          ]        │  ← st.text_input; e.g. "12-13"
│  Revenue Breakdown:    [          ]        │
│                                            │
│  [ Generate ]                              │
│  Status: Generating script … 40 %         │  ← live via progress_callback
└────────────────────────────────────────────┘
```

#### Tree Selection Behaviour

The section list is rendered as a hierarchy of `st.expander` + `st.checkbox` widgets:

1. Group the flat section list into a tree: each section at level N+1 is a child of the nearest preceding section at level N.
2. Render level-1 sections as expanders. Inside each expander, render a checkbox for the parent, then recursively render children.
3. When a parent checkbox is toggled **on**, set all its descendant checkboxes to checked. When toggled **off**, uncheck all descendants.
4. Page-override text inputs appear only for sections that are currently checked.

#### Generate Button

Calls `run_pipeline()` with a `progress_callback` that updates an `st.status()` widget in real time. On completion, stores `script`, `verification`, and `word_count` in session state.

### 13.5 Tab 3 — Podcast Script

```
┌────────────────────────────────────────────┐
│  Word Count                                │
│  ┌──────────┐                              │
│  │  2 043   │  ← st.metric                 │
│  └──────────┘                              │
│                                            │
│  **Alex:** Welcome back, everyone. Today   │  ← st.markdown
│  we're looking at …                        │     speaker names in bold
│                                            │
│  **Jordan:** Absolutely. And one thing I   │
│  found really interesting …                │
│                                            │
│  [ ⬇ Download Script ]                    │  ← st.download_button (.txt)
└────────────────────────────────────────────┘
```

Speaker labels (`Alex:`, `Jordan:`) are rendered in **bold** by the markdown renderer. The download button exports the raw plain-text script.

### 13.6 Tab 4 — Verification Report

```
┌────────────────────────────────────────────┐
│  Claims                                    │
│  ✅  Vestas revenue grew 12 % …            │  TRACED
│  ⚠️  Employee engagement rose …            │  PARTIALLY_TRACED
│  🚩  Company entered 3 new markets …       │  NOT_TRACED
│                                            │
│  Section Coverage                          │
│  ✅  Financial Highlights                  │  COVERED
│  ⚠️  Sustainability                        │  PARTIAL
│  🚩  Risk Management                       │  OMITTED
│                                            │
│  [ ⬇ Download Report (JSON) ]             │  ← st.download_button
└────────────────────────────────────────────┘
```

**Emoji mapping:**

| Status | Emoji |
|---|---|
| `TRACED` / `COVERED` | ✅ |
| `PARTIALLY_TRACED` / `PARTIAL` | ⚠️ |
| `NOT_TRACED` / `OMITTED` | 🚩 |

Both the claims table and the coverage table are rendered as `st.dataframe` with the emoji prepended to the status column.

---

## 14. Output Files

All generated artefacts are written to `output/`. The directory is created automatically if it does not exist.

| File | Written by | Contents |
|---|---|---|
| `extracted_text.json` | `extract.py` | Full extraction cache (metadata + sections + cleaned page text) |
| `podcast_script.txt` | `pipeline.py` | Final script, plain text |
| `verification_report.json` | `pipeline.py` | Full verification report (claims + coverage + summary) |
| `llm_log.json` | `generate.py` / `verify.py` | Append-only log — one JSON object per LLM round-trip |

---

## 15. Logging

### 15.1 Application Log

Standard Python `logging` module. Configured once at application startup (in `app_config.py` or a dedicated `logging_config.py`). Output goes to **both**:

- `logs/app.log` — file handler, persists across restarts
- stdout — stream handler, visible in the terminal / Streamlit logs

Format:

```
2025-06-15 10:30:45,123 [INFO]     extract  : Starting PDF extraction — Vestas Annual Report 2024.pdf
2025-06-15 10:31:02,456 [WARNING]  extract  : Nav-bar line removed (appeared on 180 pages): "Home  About  Investors"
2025-06-15 10:35:10,789 [ERROR]    generate : OpenAI API call failed — retrying (1/3)
```

### 15.2 LLM Call Log (`llm_log.json`)

Append-only JSON file in `output/`. One line per LLM call. See §9.6 for the full schema. This log is the primary debugging and auditing tool for the generation layer.

---

## 16. Testing Strategy

All tests live in `tests/` and use **pytest** as the runner. LLM calls are mocked with `unittest.mock` so tests are fast, deterministic, and free of API costs. TDD is followed: tests are written first, then the implementation.

### 16.1 `test_extract.py` — Section Detection & Cleaning

Section-and-page extraction accuracy is the **highest-priority** test target.

| Test | Positive / Negative | What it verifies |
|---|---|---|
| `test_toc_extraction` | Positive | TOC-based sections produce correct titles, pages, and levels |
| `test_contents_page_single_column` | Positive | Single-column Contents page is parsed correctly |
| `test_contents_page_multi_column` | Positive | Multi-column Contents page columns are detected and parsed |
| `test_font_heuristic_levels` | Positive | Font sizes map to the correct heading levels |
| `test_level_detection_bold` | Positive | Bold + 14 pt text is classified as level 2 |
| `test_consecutive_heading_merge` | Positive | Two heading lines on the same page merge into one title |
| `test_nav_bar_removal` | Positive | Lines appearing on > half of pages are stripped from all pages |
| `test_arrow_link_removal` | Positive | Lines starting with → ▶ ▸ ► are removed |
| `test_hyperlink_removal` | Positive | Top-of-page hyperlink text is removed |
| `test_end_page_computation` | Positive | `end_page` values are correct for nested sections |
| `test_min_char_filter` | Negative | Candidates with fewer than 3 alphabetic chars are rejected |
| `test_empty_pdf` | Negative | Graceful, logged error on a PDF with no extractable text |
| `test_unsupported_encoding` | Negative | Un-encodable characters are stripped; no crash occurs |
| `test_password_protected_pdf` | Negative | Raises a clear error for encrypted PDFs |

### 16.2 `test_filter.py` — Section Resolution

| Test | Positive / Negative | What it verifies |
|---|---|---|
| `test_exact_name_match` | Positive | Config name equals an extracted section title exactly |
| `test_fuzzy_substring_match` | Positive | `"Financial"` matches `"Financial Highlights"` |
| `test_reverse_substring_match` | Positive | `"Financial Highlights"` matches config entry `"Financial"` |
| `test_page_override_takes_priority` | Positive | Explicit page range overrides detected section boundaries |
| `test_single_page_override` | Positive | `"42"` resolves to pages 42–42 |
| `test_no_match_raises` | Negative | A name with zero overlap raises `SectionNotFoundError` |
| `test_empty_section_list` | Negative | Empty input list returns an empty result without error |

### 16.3 `test_generate.py` — Agent Loop

All LLM calls mocked. Tests verify:

| Test | What it verifies |
|---|---|
| `test_loop_stops_when_score_meets_threshold` | Loop exits after evaluation returns `overall >= SCORE_THRESHOLD` |
| `test_loop_stops_at_max_iterations` | Loop exits after `MAX_AGENT_ITERATIONS` even if score stays low |
| `test_improver_not_called_when_score_sufficient` | If first evaluation passes, Improver is never invoked |
| `test_llm_log_entries_written` | Each LLM call produces a valid `llm_log.json` entry |
| `test_generator_called_exactly_once` | The Generator Agent runs only at the start, not inside the loop |

### 16.4 `test_verify.py` — Verification Logic

All LLM calls mocked. Tests verify:

| Test | What it verifies |
|---|---|
| `test_coverage_percentage_calculation` | `coverage_percentage` arithmetic is correct |
| `test_emoji_mapping_all_statuses` | TRACED→✅, PARTIALLY_TRACED→⚠️, NOT_TRACED→🚩 (and coverage equivalents) |
| `test_omitted_points_populated` | `PARTIAL` sections list the specific missing points |
| `test_fully_covered_section` | A `COVERED` section has an empty `omitted_points` list |
| `test_all_claims_not_traced` | Edge case: every claim is `NOT_TRACED` — report still well-formed |

### 16.5 `test_pipeline.py` — End-to-End

LLM calls mocked; file I/O uses a temporary directory.

| Test | What it verifies |
|---|---|
| `test_full_pipeline_writes_all_outputs` | `podcast_script.txt`, `verification_report.json`, and `llm_log.json` are all written |
| `test_pipeline_result_fields` | `PipelineResult` contains script, verification dict, and correct word_count |
| `test_progress_callback_called` | The optional callback is invoked with increasing fractions |

---

## 17. Error Handling Guidelines

Every error is logged at `ERROR` level with a full stack trace before being surfaced to the user.

| Layer | Likely Error | Handling |
|---|---|---|
| **Extraction** | Corrupted or password-protected PDF | Catch the fitz / pdfplumber exception. Log it. Re-raise as a user-friendly `ExtractionError("Could not open PDF …")`. |
| **Extraction** | Un-encodable text in a page | Strip bad characters silently. Log a `WARNING` with the page number and a snippet. Continue processing. |
| **Filter** | No section matches the requested name | Raise `SectionNotFoundError(name)` immediately. The message includes the name and the list of available sections. |
| **Generation** | OpenAI API timeout or 5xx error | Retry up to 3 times with exponential back-off (1 s, 2 s, 4 s). If all retries fail, raise `LLMCallError` with the last exception. |
| **Generation** | Response body does not parse as expected JSON | Log the raw response text. Raise `ParseError("Evaluator response is not valid JSON …")`. |
| **Pipeline** | `output/` directory missing | `os.makedirs(OUTPUT_DIR, exist_ok=True)` before the first write. |
| **UI** | Extraction has not been run yet | Tabs 2–4 check `st.session_state.extracted_data`. If `None`, render an info banner and return. No crash. |
| **UI** | File upload is not a PDF | Check the suffix before calling the extractor. Show an error message if it is not `.pdf`. |

---

## 18. User Guide

### Prerequisites

- Python 3.10 or later
- An OpenAI API key (GPT-4o access)

### Setup

```bash
git clone <repo-url>
cd ai_podcast

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Open .env in a text editor and set:
#   OPENAI_API_KEY=sk-…
```

### Running via Streamlit UI

```bash
streamlit run src/app.py
```

A browser tab opens automatically. Follow these steps:

1. **Tab 1 — Extract**
   - Click *Browse files* and upload a PDF (or leave the default Vestas report).
   - Click **Extract**.
   - Wait for the status widget to finish. A table of detected sections appears below.

2. **Tab 2 — Generate**
   - Expand the section tree and check the sections you want in the podcast.
   - Checking a parent section automatically checks all of its child sections.
   - Optionally type a page range (e.g. `12-15`) into the override field for any section to narrow the source pages.
   - Click **Generate**. A live status bar shows progress through resolution → generation → evaluation → verification.

3. **Tab 3 — Podcast Script**
   - The word count is displayed as a metric at the top.
   - Read through the full script. Speaker names are in **bold**.
   - Click **Download Script** to save the plain-text file.

4. **Tab 4 — Verification Report**
   - The *Claims* table shows every factual statement the script makes, colour-coded by traceability (✅ ⚠️ 🚩).
   - The *Section Coverage* table shows how thoroughly each selected section was covered.
   - Click **Download Report (JSON)** to save the full report.

5. **Sidebar — Reset**
   - Click **Reset** at any time to clear all state and start over from scratch.

### Running via CLI

```bash
# Step 1 — extract text and sections from the PDF
python -m src.cli extract --input "data/Vestas Annual Report 2024.pdf"

# Step 2 — generate the podcast (reads config.json for section selection)
python -m src.cli generate
```

Output files appear in `output/`. Edit `config.json` to change which sections are included or to add page overrides before running Step 2.

---

## 19. Dependencies

```
# requirements.txt
pdfplumber>=0.11
pymupdf>=1.23              # provides the 'fitz' module
openai>=1.0
pydantic-ai>=0.0.30        # PydanticAI agent framework; wraps openai internally
streamlit>=1.30
python-dotenv>=1.0

# dev / test
pytest>=7.4
```

> `pydantic-ai` is listed explicitly because the design calls for PydanticAI agents. It pulls in `openai` and `pydantic` as transitive dependencies, so those do not need separate version pins — but `openai>=1.0` is kept for clarity.

---

## 20. `README.md` Outline

The `README.md` in the repo root will contain, in this order:

1. **Project title and one-paragraph description.**
2. **System architecture diagram** — the same ASCII diagram from §3.
3. **Architecture Decisions** - what design decisions were chosen and why
4. **Prerequisites** — Python version, API key.
5. **Setup instructions** — clone, venv, pip install, .env.
6. **How to run** — both Streamlit and CLI, with exact commands.
7. **Configuration reference** — table of every env var from `app_config.py` with its default.
8. **Output files** — what each file in `output/` contains.
9. **Project structure** — the directory tree from §2.
10. **Prompts Management** - where the prompts are and what their purpose is
11. **Evaluation/Verification** - how the problems are caught and coverage is computed
12. **Future Improvements** - areas to improve on
13. **License.**

---

*End of design document.*
