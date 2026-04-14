from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from healscrape.engine.service import ScrapeResult

console = Console(stderr=True)


def print_run_footer(res: ScrapeResult, *, verb: str = "Extract") -> None:
    """Short human-readable line after JSON (stderr, safe for piping stdout)."""
    if res.exit_code == 0:
        console.print(f"[green]✓[/green] {verb} OK", end="")
    else:
        console.print(f"[red]✗[/red] {verb} failed (exit {res.exit_code})", end="")
    if res.run_public_id:
        console.print(f"  ·  run id: [cyan]{res.run_public_id}[/cyan]")
    else:
        console.print()


def print_quick_table(data: dict[str, Any]) -> None:
    """Readable table for `scrape quick` when not using raw JSON."""
    t = Table(show_header=True, header_style="bold", title="Page fields")
    t.add_column("Field")
    t.add_column("Value")
    for k, v in data.items():
        t.add_row(k, "" if v is None else str(v))
    console.print(t)


def resolve_config_arg(
    config: Path | None,
    schema: Path | None,
    profile: Path | None,
) -> tuple[Path | None, Path | None]:
    """If positional config path is given, map to schema or profile; enforce exclusivity."""
    if config is not None:
        if schema is not None or profile is not None:
            raise typer.BadParameter("Use either the positional CONFIG file or --schema / --profile, not both.")
        suf = config.suffix.lower()
        if suf in (".yaml", ".yml"):
            return None, config
        if suf == ".json":
            return config, None
        raise typer.BadParameter("CONFIG must end with .json (schema) or .yaml / .yml (profile).")
    return schema, profile
