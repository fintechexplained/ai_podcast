"""Application bootstrapper — single initialisation entry-point.

Call ``bootstrap()`` once at startup (from ``cli.py`` or ``app.py``).
It wires up logging, registers all extractors, and pre-creates every
PydanticAI agent so that the rest of the code can resolve them via the
``Registry`` without knowing concrete types.
"""

from pydantic_ai import Agent

from src.app_config import MODEL_NAME
from src.register import Registry
from src.utility.logging_helper import setup_logging


def register_extractors() -> None:
    """Register all file-type extractors in the IoC container."""
    from src.extract import PDFExtractor  # local import avoids circular deps

    Registry.register("pdf", PDFExtractor)


def register_agents() -> None:
    """Create and register every PydanticAI agent used by the pipeline."""
    from src.generate import EvaluationScores, KeyPointsOutput  # local import avoids circular deps
    from src.verify import ClaimsOutput, CoverageResult

    Registry.register_agent("key_points", Agent(f"openai:{MODEL_NAME}", output_type=KeyPointsOutput))
    Registry.register_agent("generator", Agent(f"openai:{MODEL_NAME}"))
    Registry.register_agent("evaluator", Agent(f"openai:{MODEL_NAME}", output_type=EvaluationScores))
    Registry.register_agent("improver", Agent(f"openai:{MODEL_NAME}"))
    Registry.register_agent("claims", Agent(f"openai:{MODEL_NAME}", output_type=ClaimsOutput))
    Registry.register_agent("coverage", Agent(f"openai:{MODEL_NAME}", output_type=CoverageResult))


def bootstrap() -> None:
    """Initialise the application: logging, extractors, and agents."""
    setup_logging()
    register_extractors()
    register_agents()
