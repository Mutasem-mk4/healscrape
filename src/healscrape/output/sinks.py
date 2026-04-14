from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any


def format_output(payload: dict[str, Any], fmt: str) -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if fmt == "ndjson":
        return json.dumps(payload, ensure_ascii=False) + "\n"
    if fmt == "csv":
        return _to_csv_row(payload)
    raise ValueError(f"unsupported_format:{fmt}")


def _to_csv_row(obj: dict[str, Any]) -> str:
    buf = io.StringIO()
    flat = {k: v for k, v in obj.items() if not isinstance(v, (dict, list))}
    w = csv.DictWriter(buf, fieldnames=list(flat.keys()))
    w.writeheader()
    w.writerow({k: "" if flat[k] is None else str(flat[k]) for k in flat})
    return buf.getvalue()


def emit_structured_result(payload: dict[str, Any], fmt: str) -> None:
    """Write machine-readable output to stdout (so `> out.json` and pipes work)."""
    s = format_output(payload, fmt)
    if fmt.lower() == "ndjson":
        sys.stdout.write(s)
        return
    if not s.endswith("\n"):
        s += "\n"
    sys.stdout.write(s)
