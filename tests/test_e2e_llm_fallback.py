from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select

from healscrape.config import load_settings
from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec
from healscrape.engine.service import run_scrape
from healscrape.exit_codes import SUCCESS
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.providers.fetch import HttpFetcher
from healscrape.providers.llm.mock import MockLlmProvider
from tests.fake_fetcher import FakeFetcher


def test_llm_extracted_value_when_selectors_still_broken(isolated_env, monkeypatch):
    """
    Model returns a correct visible-text value but CSS that does not match the DOM.
    Final output must still succeed via evidence-grounded LLM merge; selectors must NOT promote.
    """
    html = "<html><body><p class='x'>The Secret Title</p></body></html>"
    monkeypatch.setattr(HttpFetcher, "get", lambda self, url: FakeFetcher(html).get(url))

    spec = ExtractSpec(
        site_slug="fallback-only",
        fields=[
            ExtractFieldSpec(
                name="title",
                json_path="title",
                json_type="string",
                required=True,
                selector="h1.wrong",
            ),
        ],
        json_schema={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )

    def factory():
        return MockLlmProvider(
            {
                "extracted": {"title": "The Secret Title"},
                "selectors": {"title": {"css": "span.never-exists", "attr": None}},
                "notes": "no stable selector",
            }
        )

    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    session = sf()
    try:
        fetcher = HttpFetcher(settings)
        res = run_scrape(
            settings=settings,
            session=session,
            url="https://example.test/p",
            spec=spec,
            command_name="extract",
            fetcher=fetcher,
            llm_factory=factory,
            allow_healing=True,
        )
        session.commit()
    finally:
        session.close()
        fetcher.close()

    assert res.exit_code == SUCCESS
    assert res.data["title"] == "The Secret Title"
    trace = json.loads((settings.data_dir / "traces" / f"{res.run_public_id}.json").read_text(encoding="utf-8"))
    post = next(s for s in trace["steps"] if s.get("step") == "post_heal_validation")
    assert "title" in post.get("llm_fallback_fields", [])
    assert post["vr_dom"]["ok"] is False
    assert post["vr_merged"]["ok"] is True

    from healscrape.persistence.models import HealingEvent, ScrapeRun

    session = sf()
    try:
        run = session.scalars(select(ScrapeRun).where(ScrapeRun.public_id == UUID(res.run_public_id))).one()
        ev = session.scalars(select(HealingEvent).where(HealingEvent.run_id == run.id)).one()
        assert ev.promoted_selector_version_id is None
        assert ev.promotion_blocked_reason == "promotion_blocked_dom_extraction_invalid"
    finally:
        session.close()
