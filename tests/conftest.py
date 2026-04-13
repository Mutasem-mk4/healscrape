from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path):
    db = tmp_path / "t.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("HEALSCRAPE_DATA_DIR", str(data))
    monkeypatch.chdir(project_root)
    yield tmp_path
