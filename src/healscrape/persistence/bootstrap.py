from __future__ import annotations

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from healscrape.config import Settings
from healscrape.paths import project_root
from healscrape.persistence.models import Base

log = structlog.get_logger(__name__)


def upgrade_database(settings: Settings) -> None:
    """Apply Alembic migrations when the alembic directory is available; else create_all."""
    url = settings.resolved_database_url()
    root = project_root()
    alembic_dir = root / "alembic"
    ini_path = root / "alembic.ini"
    if alembic_dir.is_dir() and ini_path.is_file():
        cfg = Config(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", url)
        log.info("db_migrate", url=url.split("@")[-1] if "@" in url else url)
        command.upgrade(cfg, "head")
        return
    log.warning("alembic_missing_using_create_all")
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
