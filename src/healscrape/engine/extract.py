from __future__ import annotations

from typing import Any

import structlog
from selectolax.parser import HTMLParser

from healscrape.domain.schema_spec import ExtractFieldSpec

log = structlog.get_logger(__name__)


def _set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: dict[str, Any] = target
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def extract_with_selectors(html: str, fields: list[tuple[str, str | None, str | None]]) -> dict[str, Any]:
    """
    fields: list of (json_path, css_selector_or_none, attr_or_none)
    attr_or_none: None means text content; otherwise attribute name.
    """
    tree = HTMLParser(html)
    out: dict[str, Any] = {}
    for json_path, css, attr in fields:
        if not css:
            _set_path(out, json_path, None)
            continue
        node = tree.css_first(css)
        if node is None:
            val = None
        elif attr:
            val = node.attributes.get(attr)
        else:
            val = node.text(deep=True, separator=" ", strip=True)
        _set_path(out, json_path, val)
    return out


def extract_from_spec_fields(
    html: str,
    selectors_by_field_name: dict[str, dict[str, Any]],
    spec_fields: list[ExtractFieldSpec],
) -> dict[str, Any]:
    """Run CSS extraction; selector map is keyed by field `name`, values written at `json_path`."""
    tuples: list[tuple[str, str | None, str | None]] = []
    for f in spec_fields:
        sel = selectors_by_field_name.get(f.name) or {}
        css = sel.get("css")
        tuples.append(
            (
                f.json_path,
                str(css) if css else None,
                str(sel["attr"]) if sel.get("attr") else None,
            )
        )
    return extract_with_selectors(html, tuples)


def extract_from_spec_map(html: str, selectors: dict[str, dict[str, Any]], field_order: list[str]) -> dict[str, Any]:
    """Backward-compatible: field_order entries are field names; json_path defaults to name."""
    tuples: list[tuple[str, str | None, str | None]] = []
    for name in field_order:
        spec = selectors.get(name) or {}
        css = spec.get("css")
        tuples.append((name, str(css) if css else None, str(spec["attr"]) if spec.get("attr") else None))
    return extract_with_selectors(html, tuples)
