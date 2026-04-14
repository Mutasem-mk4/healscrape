from __future__ import annotations

import json

from healscrape.config import load_settings
from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec
from healscrape.engine.service import run_scrape
from healscrape.exit_codes import SUCCESS
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.providers.fetch import HttpFetcher
from healscrape.providers.llm.mock import MockLlmProvider
from tests.fake_fetcher import FakeFetcher


def test_e2e_healing_promotes_selectors(isolated_env, monkeypatch):
    """Selector drift: mock LLM proposes working CSS; selectors promote after DOM + replay checks."""
    html = "<html><body><h1 id='real-title'>Healed Title</h1></body></html>"
    monkeypatch.setattr(HttpFetcher, "get", lambda self, url: FakeFetcher(html).get(url))

    spec = ExtractSpec(
        site_slug="drift-demo",
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
                "extracted": {"title": "Healed Title"},
                "selectors": {"title": {"css": "#real-title", "attr": None}},
                "notes": "fixed drift",
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
    assert res.data["title"] == "Healed Title"
    assert res.run_public_id
    trace = json.loads((settings.data_dir / "traces" / f"{res.run_public_id}.json").read_text(encoding="utf-8"))
    assert any(s.get("step") == "llm_response" for s in trace["steps"])
    post = next(s for s in trace["steps"] if s.get("step") == "post_heal_validation")
    assert post.get("replay_ok") is True
    assert post.get("llm_fallback_fields") == []


def test_e2e_second_run_uses_promoted_selectors_without_llm(isolated_env, monkeypatch):
    """After promotion, a second extract succeeds with healing off using DB selectors only."""
    html = "<html><body><h1 id='real-title'>Second Run</h1></body></html>"
    monkeypatch.setattr(HttpFetcher, "get", lambda self, url: FakeFetcher(html).get(url))

    spec = ExtractSpec(
        site_slug="reuse-site",
        fields=[
            ExtractFieldSpec(
                name="title",
                json_path="title",
                json_type="string",
                required=True,
                selector="h1.broken",
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
                "extracted": {"title": "Second Run"},
                "selectors": {"title": {"css": "#real-title", "attr": None}},
                "notes": "repair",
            }
        )

    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)

    session = sf()
    try:
        fetcher = HttpFetcher(settings)
        r1 = run_scrape(
            settings=settings,
            session=session,
            url="https://example.test/a",
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

    assert r1.exit_code == SUCCESS

    session = sf()
    try:
        fetcher = HttpFetcher(settings)
        r2 = run_scrape(
            settings=settings,
            session=session,
            url="https://example.test/b",
            spec=spec,
            command_name="extract",
            fetcher=fetcher,
            llm_factory=None,
            allow_healing=False,
        )
        session.commit()
    finally:
        session.close()
        fetcher.close()

    assert r2.exit_code == SUCCESS
    assert r2.data["title"] == "Second Run"
    trace2 = json.loads((settings.data_dir / "traces" / f"{r2.run_public_id}.json").read_text(encoding="utf-8"))
    assert not any(s.get("step") == "llm_response" for s in trace2["steps"])
