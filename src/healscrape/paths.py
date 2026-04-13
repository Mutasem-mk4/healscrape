from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Repository root when running from source; may be wrong in some wheel installs."""
    return Path(__file__).resolve().parents[2]
