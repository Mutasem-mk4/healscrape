"""Shared implementation for `scrape quick` and bare `scrape <url>`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from healscrape.cli.quick_spec import load_quick_spec
from healscrape.config import load_settings
from healscrape.engine.extract import extract_from_spec_fields
from healscrape.engine.service import fetch_html, run_scrape
from healscrape.engine.validate import validate_extraction
from healscrape.exit_codes import SUCCESS
from healscrape.output.sinks import emit_structured_result
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.providers.fetch import HttpFetcher
from healscrape.spec.loaders import selectors_dict_from_spec


def looks_like_http_url(s: str) -> bool:
    t = s.strip()
    return t.startswith("http://") or t.startswith("https://")


def run_quick(
    url: str,
    *,
    save: bool,
    table: bool,
    no_heal: bool,
    output: str,
    llm_factory: Callable[[], Any] | None,
    session_scope: Any,
    console: Any,
    print_quick_table: Any,
    print_run_footer: Any,
) -> int:
    """
    Run quick scrape. Returns exit code.
    When save=False, llm_factory/session_scope may be unused.
    """
    spec = load_quick_spec()
    settings = load_settings()

    if not save:
        fetcher = HttpFetcher(settings)
        try:
            html, _mode = fetch_html(url, render=False, settings=settings, fetcher=fetcher)
            sel = selectors_dict_from_spec(spec)
            data = extract_from_spec_fields(html, sel, spec.fields)
            report = validate_extraction(data, spec)
        except Exception as e:
            console.print(f"[red]Fetch failed:[/red] {e}")
            return 20
        finally:
            fetcher.close()

        if table:
            print_quick_table(data)
        else:
            emit_structured_result(data, output)
        if not report.ok:
            console.print(f"[yellow]Note:[/yellow] {report.to_json()}")
        console.print("[dim]Tip: scrape extract URL schema.json  |  scrape quick URL --save  |  scrape setup[/dim]")
        return SUCCESS

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    fetcher = HttpFetcher(settings)
    try:
        with session_scope(sf) as session:
            res = run_scrape(
                settings=settings,
                session=session,
                url=url,
                spec=spec,
                command_name="quick",
                fetcher=fetcher,
                llm_factory=llm_factory,
                allow_healing=not no_heal,
                output_format=output,
            )
        if res.data is not None and not table:
            emit_structured_result(res.data, output)
        elif res.data is not None and table:
            print_quick_table(res.data)
        print_run_footer(res, verb="Quick")
        if res.error:
            console.print(f"[red]{res.error}[/red]")
        return int(res.exit_code)
    finally:
        fetcher.close()
