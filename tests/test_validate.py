from __future__ import annotations

from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec
from healscrape.engine.validate import validate_extraction


def test_validate_success():
    spec = ExtractSpec(
        site_slug="t",
        fields=[
            ExtractFieldSpec(name="title", json_path="title", json_type="string", required=True, selector="h1"),
        ],
        json_schema={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )
    r = validate_extraction({"title": "Hello"}, spec)
    assert r.ok
    assert r.confidence == 1.0


def test_validate_required_missing():
    spec = ExtractSpec(
        site_slug="t",
        fields=[
            ExtractFieldSpec(name="title", json_path="title", json_type="string", required=True, selector="h1"),
        ],
        json_schema={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )
    r = validate_extraction({"title": ""}, spec)
    assert not r.ok
    assert any("required_field_empty" in x for x in r.reasons)
