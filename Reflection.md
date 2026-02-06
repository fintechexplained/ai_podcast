## 1. Why did you choose this architecture / framework?

I chose this architecture to balance **real-world PDF variability**, **LLM flexibility**, and **long-term maintainability**, rather than optimising only for a happy-path demo.

### Architecture Rationale

The system is intentionally modular and layered, with each decision addressing a concrete failure mode I encountered while working with real documents.

| Decision                                       | Rationale                                                                                                                                                                                                                                |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Two-library extraction (pdfplumber + fitz)** | No single PDF library is sufficient in practice. `pdfplumber` produces the most reliable plain-text layout, while `fitz` exposes outlines, font metadata, and links. Combining them gives better recall and precision than either alone. |
| **Three-tier section detection**               | PDFs vary widely: some have outlines, some only printed TOCs, and some neither. Falling through tiers allows the system to degrade gracefully instead of failing outright.                                                               |
| **Extraction cache (`extracted_text.json`)**   | PDF extraction is the slowest step. Caching ensures the expensive work runs once, while downstream LLM iterations remain fast and inexpensive.                                                                                           |
| **PydanticAI agents with typed outputs**       | Typed schemas create explicit contracts between agents and code. This allows me to swap models (Claude, GPT, or local) or providers without touching application logic, reduces vendor lock-in, and makes refactoring safer.             |
| **Eval / Improve loop**                        | Separating generation from evaluation avoids trusting a single LLM pass. A bounded loop converges quality while keeping costs predictable.                                                                                               |
| **Shared pipeline function**                   | Both CLI and Streamlit UI call the same `run_pipeline()` function, preventing interface drift and simplifying testing.                                                                                                                   |
| **Markdown prompt files**                      | Prompts change more often than code. Keeping them as `.md` files allows iteration without redeploying or modifying Python source.                                                                                                        |
| **Bootstrap + IoC pattern**                    | Central registration of extractors and agents avoids circular imports, clarifies system composition, and makes extension straightforward.                                                                                                |
| **Utility package extraction**                 | Pulling shared logic into utilities keeps modules focused, reduces duplication, and improves testability.                                                                                                                                |

### Why Python and Streamlit

* **Python** has best-in-class ecosystem support for PDFs, LLM tooling, testing, and data processing.
* It enables fast iteration, strong typing via Pydantic, and easy integration with multiple AI providers.
* **Streamlit** allows rapid UI development directly on top of Python logic, making it ideal for AI workflows where the UI is a thin layer over an evolving pipeline.
* Using Streamlit also made it easy to expose internal state (intermediate outputs, logs, errors) during development and debugging.

---

## 2. What’s the weakest part of your system?

The weakest part of the system is **PDF extraction robustness**, and I was very deliberate about acknowledging that tradeoff.

* **Brittle PDF parsing**

  * Despite three-tier section detection, the system still struggles with edge cases like:

    * Sidebar artifacts
    * Multi-line or wrapped titles
    * Dot-leader vs page-first layouts
  * PDFs without outlines or usable TOCs may fail entirely.

* **Hard LLM call budget limits**

  * The `MAX_LLM_CALLS` cap prevents runaway costs but can cause failures on complex documents.
  * There’s no graceful degradation if quality doesn’t converge before hitting the limit.

* **Cache invalidation blind spot**

  * Cached extraction results improve performance but lack versioning or invalidation.
  * If extraction logic improves or produces incorrect output, stale data persists until manually cleared.

* **Script-only output**

  * Despite the name “AI Podcast Generator,” the system currently outputs text scripts only.
  * Audio generation is intentionally out of scope but is an obvious missing end-to-end feature.

* **No prompt versioning**

  * Prompt evolution isn’t tracked, which makes regression analysis and reproducibility harder.

Overall, the system favors **clarity and iteration speed** over maximum robustness, which was a conscious choice given the scope.

---

## 3. If you had another 4 hours, what would you improve first?

With another four hours, I would focus on **quality, robustness, and observability**.

### Highest-Impact Improvements

1. **Validate and clean extracted PDF text**

   * Remove headers, footers, repeated artifacts, and special characters.
   * Add sanity checks so bad extraction fails early instead of polluting downstream steps.

2. **Introduce golden evaluation datasets**

   * Evaluate each agent against known-good documents.
   * Track accuracy and coverage regressions as prompts and models evolve.

3. **Prompt and cache versioning**

   * Version prompts explicitly.
   * Tie cache entries to extractor and prompt versions to prevent stale data issues.

4. **Graceful degradation for LLM budgets**

   * Allow partial results or fallback behavior if the eval/improve loop hits call limits.

5. **Model specialization**

   * Test different models for different stages (extraction assist, evaluation, generation).
   * Choose based on accuracy vs cost tradeoffs per task.

### If time allowed beyond that

* Parallelize extraction for large PDFs.
* Add document-specific instruction prompts.
* Test across multiple, diverse PDFs.
* Add natural-language filtering over extracted sections.
* Store sessions to reload historical podcasts.
* Generate audio directly from scripts.
* Load secrets from a vault instead of environment variables.
