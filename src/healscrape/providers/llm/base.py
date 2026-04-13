from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LlmProvider(Protocol):
    """Pluggable LLM for healing / fallback extraction."""

    def complete_json(self, system: str, user: str) -> str:
        """Return raw JSON string from the model (no markdown fences)."""
        ...
