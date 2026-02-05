### Process Overview

* **Problem understanding & planning**

  * I began by clearly explaining the problem to Claude and asked it to produce a **high-level planning document** before writing any code.
  * The goal was to align on architecture, responsibilities, and execution steps upfront rather than jumping straight into implementation.
  * The resulting [planning.md](design\planning.md) captured:

    * Overall system flow
    * Major components (PDF extraction, agents, evaluation)
    * Testing strategy
    * Assumptions and constraints
  * The prompt used to generate this planning document is stored at:
    *[Planning Prompt](design\prompts_used\prompt_for_planning.txt)*

* **Separation of planning and implementation**

  * After reviewing and validating [planning.md](design\planning.md), I intentionally started a **new session** to avoid planning bias or accidental drift.
  * In the new session, I asked **Cursor Code (VS Code)** to strictly follow [planning.md](design\planning.md) and implement the solution step by step.
  * This ensured the implementation stayed grounded in the agreed design rather than evolving ad-hoc.
  * The implementation prompt is stored at:
    *[Implementation Prompt](design\prompts_used\prompt_for_planning.txt)*

* **Iterative implementation & debugging**

  * The initial implementation required several iterations:

    * Fixing unit test failures
    * Reviewing generated code for correctness and clarity
    * Refining logic until the application could run end-to-end
  * When attempting to extract a PDF and generate a podcast script, the application failed due to:

    * Usage of class properties that did not exist
    * Incorrect assumptions about object structures
  * I pasted the runtime errors directly into the IDE and asked the model to:

    * Fix the underlying issues
    * Add **integration tests** to ensure similar problems would be caught earlier in the future

* **Code quality & architectural refactoring**

  * After functionality was working, I evaluated the code from a **maintainability and design** perspective.
  * I found the implementation overly complex for the use case:

    * It was difficult to trace where agents and extractors were registered
    * Responsibilities were scattered across files
  * To address this, I refactored the design to better follow **SOLID principles**, with the goal of:

    * Allowing new extractors to be added without modifying core logic
    * Making it easy to swap agent models or configurations
    * Improving discoverability and extensibility
    * Ensuring responsibility of each component is clear
  * Key structural changes:

    * Introduced a **bootstrapper file** to explicitly register agents and extractors
    * Moved shared and repetitive logic into a **utilities module**
  * The full prompt and refactoring history is documented at:
    *[Refactor Prompt](design\prompts_used\refactor_prompt.txt)*

* **Validation with unseen data**

  * To ensure robustness, I tested the system using a **completely new PDF** located in:

    * `tests/data/2024-2025`
  * I asked the agent to generate an **integration test** that validates whether the contents page is extracted correctly from this unseen file.
  * This helped verify the system generalises beyond the initial development inputs.

* **Evaluation metrics & prompt refinement**

  * Initial evaluation results showed:

    * **High accuracy**
    * **Low coverage**
  * I identified this imbalance as a weakness and updated the evaluation strategy.
  * I asked the agent to:

    * Add **coverage** as an explicit evaluation metric
    * Update the prompts to optimise for both accuracy and coverage
    

* **Final scoring methodology**

  * The final evaluation score is a weighted aggregate of multiple dimensions:

    * Accuracy — **30%**
    * Coverage — **25%**
    * Teachability — **15%**
    * Conversational feel — **10%**
    * Friction & disagreement handling — **10%**
    * Takeaway clarity — **10%**
  * The final score is rounded to **one decimal place**


