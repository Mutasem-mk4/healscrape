from __future__ import annotations

import json

from healscrape.config import load_settings
from healscrape.domain.schema_spec import ExtractFieldSpec, ExtractSpec
from healscrape.engine.service import run_scrape
from healscrape.exit_codes import SUCCESS
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.providers.fetch import HttpFetcher
from tests.fake_fetcher import FakeFetcher


def test_e2e_deterministic_success(isolated_env, monkeypatch):
    html = "<html><body><h1 id='title'>Product A</h1><span data-price='12'>$12</span></body></html>"
    monkeypatch.setattr(HttpFetcher, "get", lambda self, url: FakeFetcher(html).get(url))

    spec = ExtractSpec(
        site_slug="fixture-shop",
        fields=[
            ExtractFieldSpec(name="title", json_path="title", json_type="string", required=True, selector="#title"),
            ExtractFieldSpec(name="price", json_path="price", json_type="string", required=True, selector="span"),
        ],
        json_schema={
            "type": "object",
            "required": ["title", "price"],
            "properties": {
                "title": {"type": "string"},
                "price": {"type": "string"},
            },
        },
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
            url="https://example.test/item",
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

    assert res.exit_code == SUCCESS
    assert res.data["title"] == "Product A"
    assert res.data["price"] == "$12"


def test_e2e_healing_promotes_selectors(isolated_env, monkeypatch):
    """Simulate selector drift: wrong selector in spec, mock LLM proposes correct CSS."""
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

    from healscrape.providers.llm.mock import MockLlmProvider

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
