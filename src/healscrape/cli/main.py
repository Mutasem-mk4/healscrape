from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import structlog
import typer
from rich.console import Console
from rich.panel import Panel

from healscrape import __version__
from healscrape.cli.quick_runner import looks_like_http_url, run_quick
from healscrape.cli.setup_wizard import run_setup
from healscrape.cli.starters import STARTER_PROFILE, STARTER_SCHEMA
from healscrape.cli.ux import print_quick_table, print_run_footer, resolve_config_arg
from healscrape.config import load_settings
from healscrape.engine.service import inspect_page, run_scrape
from healscrape.exit_codes import CONFIG_ERROR, NOT_FOUND, SUCCESS
from healscrape.logging_setup import configure_logging
from healscrape.output.sinks import emit_structured_result
from healscrape.persistence.bootstrap import upgrade_database
from healscrape.persistence.db import make_engine, make_session_factory
from healscrape.persistence.repositories import ProfileRepository, RunRepository, SelectorRepository, SiteRepository
from healscrape.providers.fetch import HttpFetcher
from healscrape.providers.llm.gemini import GeminiProvider
from healscrape.spec.loaders import load_extract_spec_from_schema_file, load_profile_yaml

console = Console(stderr=True)
log = structlog.get_logger(__name__)

APP_HELP = """\
[bold]healscrape[/bold] — scrape pages into structured JSON (deterministic first, optional AI repair).

[bold]Fastest start[/bold]
  [cyan]scrape[/cyan] https://example.com               [dim]# same as: scrape quick URL[/dim]
  [cyan]scrape setup[/cyan]                             [dim]# interactive wizard (.env + starters)[/dim]
  [cyan]scrape quick[/cyan] https://example.com         [dim]# explicit quick mode[/dim]
  [cyan]scrape init[/cyan]                              [dim]# starter schema files only[/dim]
  [cyan]scrape extract[/cyan] URL page.schema.json     [dim]# your own schema[/dim]

[bold]More[/bold]  [cyan]scrape inspect[/cyan], [cyan]scrape heal[/cyan], [cyan]scrape doctor[/cyan], [cyan]scrape --help[/cyan]
"""

app = typer.Typer(
    name="scrape",
    help=APP_HELP,
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=True,
    rich_markup_mode="rich",
    add_completion=False,
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
        raise typer.BadParameter(
            "Missing schema or profile. Try:  scrape https://…  |  scrape init  |  scrape setup  |  "
            "scrape extract YOUR_URL page.schema.json"
        )


def _register_profile_if_needed(settings, profile_path: Path | None, site_slug: str, body: str) -> None:
    if profile_path is None or not body:
        return
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    with session_scope(sf) as session:
        ProfileRepository(session).upsert(site_slug, body)


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
    version: bool = typer.Option(False, "--version", "-V", help="Print version and exit."),
) -> None:
    """Global options apply to all subcommands."""
    if version:
        console.print(f"healscrape {__version__}")
        raise typer.Exit(SUCCESS)
    if data_dir is not None:
        os.environ["HEALSCRAPE_DATA_DIR"] = str(data_dir.expanduser().resolve())
    configure_logging(json_logs=json_logs, level=log_level)

    if ctx.invoked_subcommand is not None:
        return

    extras = list(ctx.args or ())
    if not extras:
        console.print(ctx.get_help())
        raise typer.Exit(0)

    first = extras[0].strip()
    if looks_like_http_url(first):
        if len(extras) > 1:
            console.print("[yellow]Note:[/yellow] ignoring extra arguments after the URL.")
        code = run_quick(
            first,
            save=False,
            table=False,
            no_heal=True,
            output="json",
            llm_factory=_llm_factory,
            session_scope=session_scope,
            console=console,
            print_quick_table=print_quick_table,
            print_run_footer=print_run_footer,
        )
        raise typer.Exit(code)

    console.print(f"[red]Unknown:[/red] {first!r} — expected a URL starting with http:// or https://")
    console.print("[dim]Try:[/dim] scrape --help  |  scrape setup  |  scrape init")
    raise typer.Exit(CONFIG_ERROR)


@app.command("quick")
def quick_cmd(
    url: Annotated[str, typer.Argument(help="Page URL.")],
    table: Annotated[bool, typer.Option("--table", "-t", help="Show a table instead of JSON.")] = False,
    save: Annotated[bool, typer.Option("--save", help="Persist run / snapshot / trace (needs DB).")] = False,
    no_heal: Annotated[bool, typer.Option("--no-heal", help="With --save: disable Gemini healing.")] = False,
    output: Annotated[str, typer.Option("--output", "-o", help="json | ndjson | csv")] = "json",
) -> None:
    """Grab common page fields with zero config (no schema file). Use --save for full audit trail."""
    code = run_quick(
        url,
        save=save,
        table=table,
        no_heal=no_heal,
        output=output,
        llm_factory=None if no_heal else _llm_factory,
        session_scope=session_scope,
        console=console,
        print_quick_table=print_quick_table,
        print_run_footer=print_run_footer,
    )
    raise typer.Exit(code)


@app.command("setup")
def setup_cmd(
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Print setup hints only (no prompts)."),
    ] = False,
    env_file: Annotated[Path, typer.Option("--env-file", help="Where to write .env.")] = Path(".env"),
    starters: Annotated[bool, typer.Option("--starters/--no-starters", help="Offer starter schema files.")] = True,
    starters_dir: Annotated[
        Path,
        typer.Option("--starters-dir", help="Directory for page.schema.json + site.yaml."),
    ] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing starter files.")] = False,
) -> None:
    """Interactive first-run wizard: .env, data dir, optional Gemini key, starter files."""
    raise typer.Exit(
        run_setup(
            env_file=env_file,
            non_interactive=non_interactive,
            with_starters=starters,
            starters_dir=starters_dir,
            force_starters=force,
        )
    )


@app.command("init")
def init_cmd(
    directory: Annotated[Path, typer.Option("--dir", help="Folder to write starter files.", show_default=True)] = Path(
        "."
    ),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Create page.schema.json and site.yaml you can edit and pass to scrape extract."""
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    schema_path = directory / "page.schema.json"
    yaml_path = directory / "site.yaml"
    for p, content in ((schema_path, STARTER_SCHEMA), (yaml_path, STARTER_PROFILE)):
        if p.exists() and not force:
            console.print(f"[yellow]Skip[/yellow] (exists): {p}")
            continue
        p.write_text(content.strip() + "\n", encoding="utf-8")
        console.print(f"[green]Wrote[/green] {p}")
    console.print(
        Panel.fit(
            "[bold]Next[/bold]\n"
            f"  scrape extract YOUR_URL [cyan]{schema_path.name}[/cyan]\n"
            f"  scrape extract YOUR_URL [cyan]{yaml_path.name}[/cyan]\n"
            "  [cyan]scrape setup[/cyan]  [dim](if you have not configured .env yet)[/dim]",
            title="healscrape",
        )
    )
    raise typer.Exit(SUCCESS)


@app.command("doctor")
def doctor_cmd() -> None:
    """Check your environment (Python, API key, optional Playwright)."""
    console.print(f"[bold]healscrape[/bold] {__version__}")
    console.print(f"Python {sys.version.split()[0]}")
    key = load_settings().gemini_api_key
    console.print("GEMINI_API_KEY: [green]set[/green]" if key else "[yellow]not set[/yellow] (healing disabled)")
    try:
        import playwright  # noqa: F401

        console.print("Playwright: [green]installed[/green]")
    except ImportError:
        console.print("Playwright: [dim]not installed[/dim] (pip install healscrape[browser])")
    console.print("[dim]First time? Run[/dim] [cyan]scrape setup[/cyan] [dim]for a guided .env and starter files.[/dim]")
    raise typer.Exit(SUCCESS)


@app.command("extract")
def extract_cmd(
    url: Annotated[str, typer.Argument(help="Target page URL.")],
    config: Annotated[
        Optional[Path],
        typer.Argument(
            help="Schema (.json) or profile (.yaml). Same as --schema / --profile.",
            show_default=False,
        ),
    ] = None,
    schema: Annotated[Optional[Path], typer.Option("--schema", help="JSON Schema with x-healscrape hints.")] = None,
    profile: Annotated[Optional[Path], typer.Option("--profile", help="Site profile YAML.")] = None,
    render: Annotated[bool, typer.Option("--render", help="Render with Playwright (requires browser extra).")] = False,
    no_heal: Annotated[bool, typer.Option("--no-heal", help="Disable LLM healing on validation failure.")] = False,
    output: Annotated[str, typer.Option("--output", "-o", help="json | ndjson | csv")] = "json",
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Less chatter on stderr.")] = False,
) -> None:
    """Fetch a page, extract, validate, heal if needed, persist audit trail."""
    try:
        schema, profile = resolve_config_arg(config, schema, profile)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(CONFIG_ERROR) from e
    _one_of_schema_profile(schema, profile)
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings)

    profile_body = ""
    if schema:
        spec = load_extract_spec_from_schema_file(schema)
    else:
        spec = load_profile_yaml(profile)  # type: ignore[arg-type]
        profile_body = profile.read_text(encoding="utf-8") if profile is not None else ""

    if profile is not None and profile_body:
        _register_profile_if_needed(settings, profile, spec.site_slug, profile_body)

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
            emit_structured_result(res.data, output)
        if res.error:
            console.print(f"[red]{res.error}[/red]")
        if res.validation and not res.validation.ok:
            console.print(f"[yellow]validation:[/yellow] {res.validation.to_json()}")
        if not quiet:
            print_run_footer(res, verb="Extract")
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
        sys.stdout.write(json.dumps(info, indent=2, ensure_ascii=False) + "\n")
        raise typer.Exit(SUCCESS)
    finally:
        fetcher.close()


@app.command("heal")
def heal_cmd(
    url: Annotated[str, typer.Argument(help="Target page URL.")],
    config: Annotated[
        Optional[Path],
        typer.Argument(help="Schema (.json) or profile (.yaml).", show_default=False),
    ] = None,
    schema: Annotated[Optional[Path], typer.Option("--schema", help="JSON Schema path.")] = None,
    profile: Annotated[Optional[Path], typer.Option("--profile", help="Site profile YAML.")] = None,
    render: Annotated[bool, typer.Option("--render", help="Render with Playwright.")] = False,
    output: Annotated[str, typer.Option("--output", "-o", help="json | ndjson | csv")] = "json",
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Less chatter on stderr.")] = False,
) -> None:
    """Same as extract with healing enabled (explicit command for operators)."""
    try:
        schema, profile = resolve_config_arg(config, schema, profile)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(CONFIG_ERROR) from e
    _one_of_schema_profile(schema, profile)
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings)

    profile_body = ""
    if schema:
        spec = load_extract_spec_from_schema_file(schema)
    else:
        spec = load_profile_yaml(profile)  # type: ignore[arg-type]
        profile_body = profile.read_text(encoding="utf-8") if profile is not None else ""

    if profile is not None and profile_body:
        _register_profile_if_needed(settings, profile, spec.site_slug, profile_body)

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
            emit_structured_result(res.data, output)
        if res.error:
            console.print(f"[red]{res.error}[/red]")
        if not quiet:
            print_run_footer(res, verb="Heal")
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
        sys.stdout.write(n + "\n")
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
        sys.stdout.write(sel.selectors_json + "\n")
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
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    raise typer.Exit(SUCCESS)


def run() -> None:
    try:
        app()
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(CONFIG_ERROR) from e


if __name__ == "__main__":
    run()
