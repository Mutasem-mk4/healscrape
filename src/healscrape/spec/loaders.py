from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec


def load_json_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_to_extract_spec(schema: dict[str, Any], site_slug: str) -> ExtractSpec:
    props = schema.get("properties") or {}
    required_root = set(schema.get("required") or [])
    fields: list[ExtractFieldSpec] = []
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        hx = sub.get("x-healscrape") or {}
        sel = hx.get("selector")
        attr = hx.get("attr")
        json_path = str(hx.get("json_path") or name)
        req = bool(hx.get("required")) or name in required_root
        jt = sub.get("type")
        if isinstance(jt, list):
            jt = next((t for t in jt if t != "null"), "string")
        if not isinstance(jt, str):
            jt = "string"
        fields.append(
            ExtractFieldSpec(
                name=name,
                json_path=json_path,
                json_type=jt,
                selector=sel,
                attr=attr,
                required=req,
                description=sub.get("description"),
            )
        )
    return ExtractSpec(site_slug=site_slug, fields=fields, json_schema=schema, render=False)


def load_extract_spec_from_schema_file(path: Path, site_slug: str | None = None) -> ExtractSpec:
    schema = load_json_schema(path)
    slug = site_slug or path.stem
    return schema_to_extract_spec(schema, slug)


def load_profile_yaml(path: Path) -> ExtractSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Profile YAML must be a mapping")
    site_slug = str(raw.get("site") or path.stem)
    render = bool(raw.get("render", False))
    selectors = raw.get("selectors") or {}
    schema = raw.get("schema")
    if schema is None:
        raise ValueError("Profile must include a 'schema' block (JSON Schema object)")
    if not isinstance(schema, dict):
        raise ValueError("Profile 'schema' must be a mapping")
    props = schema.get("properties") or {}
    required_root = set(schema.get("required") or [])
    fields: list[ExtractFieldSpec] = []
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        hx = sub.get("x-healscrape") or {}
        sel = hx.get("selector") or selectors.get(name)
        attr = hx.get("attr")
        json_path = str(hx.get("json_path") or name)
        req = bool(hx.get("required")) or name in required_root
        jt = sub.get("type")
        if isinstance(jt, list):
            jt = next((t for t in jt if t != "null"), "string")
        if not isinstance(jt, str):
            jt = "string"
        fields.append(
            ExtractFieldSpec(
                name=name,
                json_path=json_path,
                json_type=jt,
                selector=sel,
                attr=attr,
                required=req,
                description=sub.get("description"),
            )
        )
    return ExtractSpec(site_slug=site_slug, fields=fields, json_schema=schema, render=render)


def selectors_dict_from_spec(spec: ExtractSpec) -> dict[str, dict[str, str | None]]:
    out: dict[str, dict[str, str | None]] = {}
    for f in spec.fields:
        out[f.name] = {"css": f.selector, "attr": f.attr}
    return out
