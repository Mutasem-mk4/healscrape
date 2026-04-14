from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FieldSelectorHint(BaseModel):
    """Per-field extraction hint stored in JSON Schema x-healscrape."""

    selector: str | None = None
    attr: str | None = Field(
        default=None,
        description="HTML attribute to read (default: text content). Use 'href' for links.",
    )
    required: bool = False


class ExtractFieldSpec(BaseModel):
    name: str
    json_path: str  # dotted path in output object; LLM keys still use `name`
    json_type: str = "string"
    selector: str | None = None
    attr: str | None = None
    required: bool = False
    description: str | None = None


class ExtractSpec(BaseModel):
    """Normalized extraction specification from schema and/or profile."""

    site_slug: str
    fields: list[ExtractFieldSpec]
    render: bool = False
    json_schema: dict[str, Any] = Field(default_factory=dict)
