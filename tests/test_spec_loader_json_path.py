from __future__ import annotations

from pathlib import Path

from healscrape.spec.loaders import schema_to_extract_spec


def test_x_healscrape_json_path(tmp_path: Path):
    schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "x-healscrape": {"selector": "h1", "json_path": "meta.title"},
            }
        },
    }
    spec = schema_to_extract_spec(schema, "s")
    assert spec.fields[0].name == "title"
    assert spec.fields[0].json_path == "meta.title"
