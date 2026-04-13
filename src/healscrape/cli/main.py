from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import typer
import structlog
from rich.console import Console
from healscrape.config import load_settings
from healscrape.engine.service import inspect_page, run_scrape
from healscrape.exit_codes import CONFIG_ERROR, NOT_FOUND, SUCCESS
from healscrape.logging_setup import configure_logging
from healscrape.output.sinks import format_output
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.persistence.repositories import ProfileRepository, RunRepository, SelectorRepository, SiteRepository
from healscrape.providers.fetch import HttpFetcher
from healscrape.providers.llm.gemini import GeminiProvider
from healscrape.spec.loaders import load_extract_spec_from_schema_file, load_profile_yaml

console = Console(stderr=True)
log = structlog.get_logger(__name__)

app = typer.Typer(
    name="scrape",
    help="healscrape — deterministic-first, self-healing structured extraction CLI.",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)


@contextmanager
def session_scope(session_factory):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _llm_factory():
    s = load_settings()
    return GeminiProvider(s)


def _one_of_schema_profile(schema: Optional[Path], profile: Optional[Path]) -> None:
    if (schema is None) == (profile is None):
        raise typer.BadParameter("Provide exactly one of --schema or --profile.")


@app.callback()
def main(
    ctx: typer.Context,
    json_logs: bool = typer.Option(False, "--json-logs", help="Emit structured JSON logs."),
    log_level: str = typer.Option("INFO", "--log-level", help="Python log level name."),
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        help="Override HEALSCRAPE_DATA_DIR for this invocation.",
    ),
) -> None:
    """Global options apply to all subcommands."""
    if data_dir is not None:
        os.environ["HEALSCRAPE_DATA_DIR"] = str(data_dir.expanduser().resolve())
    configure_logging(json_logs=json_logs, level=log_level)
    if ctx.invoked_subcommand is None:
        return


@app.command("extract")
def extract_cmd(
    url: Annotated[str, typer.Argument(help="Target page URL.")],
    schema: Annotated[Optional[Path], typer.Option("--schema", help="JSON Schema with x-healscrape hints.")] = None,
    profile: Annotated[Optional[Path], typer.Option("--profile", help="Site profile YAML.")] = None,
    render: Annotated[bool, typer.Option("--render", help="Render with Playwright (requires browser extra).")] = False,
    no_heal: Annotated[bool, typer.Option("--no-heal", help="Disable LLM healing on validation failure.")] = False,
    output: Annotated[str, typer.Option("--output", help="json | ndjson | csv")] = "json",
) -> None:
    """Fetch a page, extract deterministically, validate, heal if needed, persist audit trail."""
    _one_of_schema_profile(schema, profile)
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings)

    if schema:
        spec = load_extract_spec_from_schema_file(schema)
    else:
        spec = load_profile_yaml(profile)  # type: ignore[arg-type]
        if profile is not None:
            body = profile.read_text(encoding="utf-8")
            engine = make_engine(settings)
            sf = make_session_factory(engine)
            with session_scope(sf) as session:
                ProfileRepository(session).upsert(spec.site_slug, body)

    if render:
        spec.render = True

    engine = make_engine(settings)
    sf = make_session_factory(engine)
    fetcher = HttpFetcher(settings)
    try:
        with session_scope(sf) as session:
            llm_factory = None if no_heal else _llm_factory
            res = run_scrape(
                settings=settings,
                session=session,
                url=url,
                spec=spec,
                command_name="extract",
                fetcher=fetcher,
                llm_factory=llm_factory,
                allow_healing=not no_heal,
                force_healing=False,
                output_format=output,
            )
        if res.data is not None:
            console.print(format_output(res.data, output))
        if res.error:
            console.print(f"[red]{res.error}[/red]")
        if res.validation and not res.validation.ok:
            console.print(f"[yellow]validation:[/yellow] {res.validation.to_json()}")
        if res.run_public_id:
            log.info("run_complete", run_id=res.run_public_id, exit=res.exit_code)
        raise typer.Exit(code=res.exit_code)
    finally:
        fetcher.close()


@app.command("inspect")
def inspect_cmd(
    url: Annotated[str, typer.Argument(help="Target page URL.")],
    render: Annotated[bool, typer.Option("--render", help="Render with Playwright.")] = False,
) -> None:
    """Lightweight page inspection (no persistence)."""
    settings = load_settings()
    fetcher = HttpFetcher(settings)
    try:
        info = inspect_page(url, settings, fetcher, render=render)
        console.print(json.dumps(info, indent=2, ensure_ascii=False))
        raise typer.Exit(SUCCESS)
    finally:
        fetcher.close()


@app.command("heal")
def heal_cmd(
    url: Annotated[str, typer.Argument(help="Target page URL.")],
    schema: Annotated[Optional[Path], typer.Option("--schema", help="JSON Schema path.")] = None,
    profile: Annotated[Optional[Path], typer.Option("--profile", help="Site profile YAML.")] = None,
    render: Annotated[bool, typer.Option("--render", help="Render with Playwright.")] = False,
    output: Annotated[str, typer.Option("--output", help="json | ndjson | csv")] = "json",
) -> None:
    """Run extraction and allow healing when validation fails (same pipeline as extract with healing on)."""
    _one_of_schema_profile(schema, profile)
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings)

    if schema:
        spec = load_extract_spec_from_schema_file(schema)
    else:
        spec = load_profile_yaml(profile)  # type: ignore[arg-type]
        if profile is not None:
            body = profile.read_text(encoding="utf-8")
            engine = make_engine(settings)
            sf = make_session_factory(engine)
            with session_scope(sf) as session:
                ProfileRepository(session).upsert(spec.site_slug, body)

    if render:
        spec.render = True

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
                command_name="heal",
                fetcher=fetcher,
                llm_factory=_llm_factory,
                allow_healing=True,
                force_healing=False,
                output_format=output,
            )
        if res.data is not None:
            console.print(format_output(res.data, output))
        if res.error:
            console.print(f"[red]{res.error}[/red]")
        raise typer.Exit(code=res.exit_code)
    finally:
        fetcher.close()


profiles_app = typer.Typer(help="Manage stored site profiles.")
app.add_typer(profiles_app, name="profiles")


@profiles_app.command("list")
def profiles_list() -> None:
    """List profile names persisted in the database."""
    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    with session_scope(sf) as session:
        names = ProfileRepository(session).list_names()
    for n in names:
        console.print(n)
    raise typer.Exit(SUCCESS)


selectors_app = typer.Typer(help="Inspect selector versions.")
app.add_typer(selectors_app, name="selectors")


@selectors_app.command("show")
def selectors_show(
    site: Annotated[str, typer.Argument(help="Site slug.")],
) -> None:
    """Show the latest promoted selector set for a site."""
    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    with session_scope(sf) as session:
        site_row = SiteRepository(session).get_by_slug(site)
        if not site_row:
            console.print(f"site_not_found:{site}")
            raise typer.Exit(NOT_FOUND)
        sel = SelectorRepository(session).latest_promoted(site_row.id)
        if not sel:
            console.print("no_promoted_selectors")
            raise typer.Exit(NOT_FOUND)
        console.print(sel.selectors_json)
    raise typer.Exit(SUCCESS)


runs_app = typer.Typer(help="Inspect persisted runs.")
app.add_typer(runs_app, name="runs")


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run public UUID.")],
) -> None:
    """Show run metadata, validation summary, and healing events."""
    settings = load_settings()
    upgrade_database(settings)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    with session_scope(sf) as session:
        run = RunRepository(session).get_by_public_id(run_id)
        if not run:
            console.print("run_not_found")
            raise typer.Exit(NOT_FOUND)
        healing = list(run.healing_events)
        payload = {
            "public_id": str(run.public_id),
            "url": run.url,
            "command": run.command,
            "outcome": run.outcome.value,
            "exit_code": run.exit_code,
            "confidence": run.confidence,
            "validation_report": json.loads(run.validation_report_json)
            if run.validation_report_json
            else None,
            "result": json.loads(run.result_json) if run.result_json else None,
            "trace_path": run.trace_path,
            "healing_events": [
                {
                    "sequence": h.sequence,
                    "failure_reason": h.failure_reason,
                    "validation_pass_1_ok": h.validation_pass_1_ok,
                    "validation_pass_2_ok": h.validation_pass_2_ok,
                    "promotion_blocked_reason": h.promotion_blocked_reason,
                    "promoted_selector_version_id": h.promoted_selector_version_id,
                    "llm_raw_response": h.llm_raw_response,
                    "candidate_selectors": json.loads(h.candidate_selectors_json)
                    if h.candidate_selectors_json
                    else None,
                }
                for h in healing
            ],
        }
        console.print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise typer.Exit(SUCCESS)


def run() -> None:
    try:
        app()
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(CONFIG_ERROR) from e


if __name__ == "__main__":
    run()
