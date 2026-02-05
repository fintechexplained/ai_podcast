"""IoC container for file-type extractors and PydanticAI agents.

A new file type (DOCX, EPUB, …) can be supported later by writing one class
that inherits ``BaseExtractor`` and calling ``Registry.register(…)``.
New agents are added via ``Registry.register_agent(…)`` in ``bootstrapper.py``.
Nothing else in the codebase needs to change.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Type


class BaseExtractor(ABC):
    """Interface every file-type extractor must implement."""

    @abstractmethod
    def extract(self, file_path: str) -> dict:
        """Return the canonical extracted-text dict.

        The returned dict must conform to the schema defined in §7.4 of the
        design document (metadata, sections, pages).
        """
        ...


class Registry:
    """Singleton IoC container.  Extractors and agents are registered once
    during bootstrap; consumers resolve them by key at call time."""

    _extractors: Dict[str, Type[BaseExtractor]] = {}
    _agents: Dict[str, Any] = {}

    # ── extractors ─────────────────────────────────────────────────────

    @classmethod
    def register(cls, extension: str, extractor_class: Type[BaseExtractor]) -> None:
        """Register an extractor class for a given file extension (e.g. 'pdf')."""
        cls._extractors[extension.lower().lstrip(".")] = extractor_class

    @classmethod
    def get_extractor(cls, extension: str) -> BaseExtractor:
        """Instantiate and return the extractor for the given extension.

        Raises:
            ValueError: if no extractor is registered for the extension.
        """
        key = extension.lower().lstrip(".")
        if key not in cls._extractors:
            raise ValueError(f"No extractor registered for '.{key}'")
        return cls._extractors[key]()

    # ── agents ─────────────────────────────────────────────────────────

    @classmethod
    def register_agent(cls, name: str, agent) -> None:
        """Register a PydanticAI Agent instance by logical name."""
        cls._agents[name] = agent

    @classmethod
    def get_agent(cls, name: str):
        """Return the registered Agent instance for the given name.

        Raises:
            ValueError: if no agent is registered with that name.
        """
        if name not in cls._agents:
            raise ValueError(f"No agent registered with name '{name}'")
        return cls._agents[name]
