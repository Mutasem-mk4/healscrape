from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from selectolax.parser import HTMLParser


def visible_text(html: str, max_chars: int) -> str:
    tree = HTMLParser(html)
    body = tree.body
    if body is None:
        text = tree.text(deep=True, separator="\n", strip=True)
    else:
        text = body.text(deep=True, separator="\n", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def snippet_around_selector(html: str, css: str, max_len: int = 400) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first(css)
    if node is None:
        return None
    raw = node.html
    if len(raw) > max_len:
        return raw[:max_len] + "…"
    return raw


def build_healing_user_prompt(
    *,
    url: str,
    fields: list[dict[str, Any]],
    current_selectors: dict[str, dict[str, Any]],
    deterministic_payload: dict[str, Any],
    html: str,
    max_chars: int,
) -> str:
    text = visible_text(html, max_chars // 2)
    snippets: dict[str, str | None] = {}
    for name, sel in current_selectors.items():
        css = sel.get("css")
        if css:
            snippets[name] = snippet_around_selector(html, str(css))

    return (
        f"Target URL: {url}\n"
        f"Visible text (truncated):\n{text}\n\n"
        f"Fields to extract (JSON metadata):\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n\n"
        f"Current CSS selectors (may be broken):\n"
        f"{json.dumps(current_selectors, ensure_ascii=False, indent=2)}\n\n"
        f"Deterministic extraction attempt produced:\n"
        f"{json.dumps(deterministic_payload, ensure_ascii=False, indent=2)}\n\n"
        f"Optional DOM snippets for current selectors:\n{json.dumps(snippets, ensure_ascii=False, indent=2)}\n"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
