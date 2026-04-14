from __future__ import annotations

import copy
from typing import Any

from healscrape.domain.schema_spec import ExtractFieldSpec
from healscrape.engine.heal_context import visible_text
from healscrape.engine.json_path_util import get_at_path, set_at_path


def value_supported_by_visible_text(value: str, html: str, *, max_chars: int = 200_000) -> bool:
    """Reject LLM-filled strings that do not appear in collapsed visible text (anti-hallucination)."""
    v = value.strip()
    if not v:
        return False
    vt = visible_text(html, max_chars)
    return v in vt


def merge_llm_fallback(
    dom: dict[str, Any],
    llm: dict[str, Any],
    fields: list[ExtractFieldSpec],
    html: str,
) -> tuple[dict[str, Any], list[str]]:
    """
    Fill missing DOM-extracted values from LLM `extracted` when evidence-backed.
    Keys in `llm` must match field `name` (schema property id).
    """
    out = copy.deepcopy(dom)
    applied: list[str] = []
    for f in fields:
        cur = get_at_path(out, f.json_path)
        if _nonempty_scalar(cur):
            continue
        raw = llm.get(f.name)
        if raw is None:
            continue
        if f.json_type == "string":
            s = str(raw).strip()
            if not s:
                continue
            if not value_supported_by_visible_text(s, html):
                continue
            set_at_path(out, f.json_path, s)
            applied.append(f.name)
        elif f.json_type in ("number", "integer"):
            # Only accept if string form appears in page (e.g. price digits)
            s = str(raw).strip()
            if not s:
                continue
            if not value_supported_by_visible_text(s, html):
                continue
            try:
                coerced: float | int = int(s) if f.json_type == "integer" else float(s)
            except ValueError:
                continue
            set_at_path(out, f.json_path, coerced)
            applied.append(f.name)
    return out, applied


def _nonempty_scalar(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (dict, list)):
        return len(v) > 0
    return True
