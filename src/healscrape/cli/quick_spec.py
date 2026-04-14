"""Built-in schema for `scrape quick` — no files required."""

from __future__ import annotations

from healscrape.domain.schema_spec import ExtractSpec
from healscrape.spec.loaders import schema_to_extract_spec

# Sensible defaults for arbitrary pages; all fields optional so quick mode usually succeeds.
QUICK_PAGE_SCHEMA: dict = {
    "title": "QuickPage",
    "type": "object",
    "properties": {
        "page_title": {
            "type": "string",
            "description": "Document title",
            "x-healscrape": {"selector": "title"},
        },
        "heading": {
            "type": "string",
            "description": "Main h1 text",
            "x-healscrape": {"selector": "h1"},
        },
        "description": {
            "type": "string",
            "description": "Meta description",
            "x-healscrape": {"selector": "meta[name=description]", "attr": "content"},
        },
        "canonical": {
            "type": "string",
            "description": "Canonical URL if present",
            "x-healscrape": {"selector": "link[rel=canonical]", "attr": "href"},
        },
    },
}


def load_quick_spec() -> ExtractSpec:
    return schema_to_extract_spec(QUICK_PAGE_SCHEMA, "quick-page")
