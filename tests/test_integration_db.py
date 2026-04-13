from __future__ import annotations

from healscrape.config import load_settings
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.persistence.repositories import SiteRepository


def test_site_roundtrip(isolated_env):
    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    session = sf()
    try:
        s = SiteRepository(session).get_or_create("acme")
        session.commit()
        sid = s.id
    finally:
        session.close()

    session = sf()
    try:
        s2 = SiteRepository(session).get_by_slug("acme")
        assert s2 is not None
        assert s2.id == sid
    finally:
        session.close()
