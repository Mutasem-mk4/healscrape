from __future__ import annotations

import json


class MockLlmProvider:
    """Deterministic LLM stub for tests."""

    def __init__(self, response: dict) -> None:
        self.response = response

    def complete_json(self, system: str, user: str) -> str:
        return json.dumps(self.response, ensure_ascii=False)
