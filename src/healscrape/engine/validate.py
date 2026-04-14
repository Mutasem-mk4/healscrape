from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec
from healscrape.engine.json_path_util import get_at_path


@dataclass
class ValidationReport:
    ok: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "confidence": self.confidence,
                "reasons": self.reasons,
                "schema_errors": self.schema_errors,
            },
            ensure_ascii=False,
        )


def field_level_checks(data: dict[str, Any], fields: list[ExtractFieldSpec]) -> list[str]:
    reasons: list[str] = []
    for f in fields:
        val = get_at_path(data, f.json_path)
        if f.required and (val is None or (isinstance(val, str) and val.strip() == "")):
            reasons.append(f"required_field_empty:{f.name}")
            continue
        if val is None:
            continue
        if f.json_type == "string" and not isinstance(val, str):
            reasons.append(f"type_mismatch:{f.name}:expected_string")
        if f.json_type == "number" and not isinstance(val, (int, float)):
            reasons.append(f"type_mismatch:{f.name}:expected_number")
        if f.json_type == "integer" and not isinstance(val, int):
            reasons.append(f"type_mismatch:{f.name}:expected_integer")
    return reasons


def compute_confidence(data: dict[str, Any], fields: list[ExtractFieldSpec]) -> float:
    required = [f for f in fields if f.required]
    if not required:
        if not fields:
            return 1.0
        filled = sum(1 for f in fields if _nonempty(get_at_path(data, f.json_path)))
        return filled / max(len(fields), 1)
    filled = sum(1 for f in required if _nonempty(get_at_path(data, f.json_path)))
    return filled / len(required)


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    return True


def validate_extraction(data: dict[str, Any], spec: ExtractSpec) -> ValidationReport:
    schema_errors: list[str] = []
    if spec.json_schema:
        try:
            validator = Draft202012Validator(spec.json_schema)
            for e in sorted(validator.iter_errors(data), key=lambda x: x.path):
                schema_errors.append(f"{list(e.path)}: {e.message}")
        except jsonschema.SchemaError as e:
            schema_errors.append(f"invalid_schema:{e.message}")

    fl = field_level_checks(data, spec.fields)
    reasons = list(fl)
    reasons.extend([f"json_schema:{s}" for s in schema_errors])

    conf = compute_confidence(data, spec.fields)
    required_missing = any(r.startswith("required_field_empty") for r in fl)
    ok = (len(schema_errors) == 0) and (not required_missing) and (len([r for r in fl if r.startswith("type_mismatch")]) == 0)

    return ValidationReport(ok=ok, confidence=conf, reasons=reasons, schema_errors=schema_errors)
