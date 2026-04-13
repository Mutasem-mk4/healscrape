from __future__ import annotations

import json

import google.generativeai as genai
import structlog

from healscrape.config import Settings

log = structlog.get_logger(__name__)


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel(
            settings.gemini_model,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )

    def complete_json(self, system: str, user: str) -> str:
        log.info("llm_gemini_request", chars=len(user))
        # Gemini prefers single prompt; combine roles for reliability.
        prompt = f"{system.strip()}\n\n---\n\n{user.strip()}"
        resp = self._model.generate_content(prompt)
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError("Empty LLM response")
        # Validate JSON early for clearer errors
        json.loads(text)
        return text
