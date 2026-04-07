"""
omnia config  — view and edit persisted configuration
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from omnia.config.settings import settings, CONFIG_FILE

app = typer.Typer(help="View and edit CLI configuration.")
console = Console()


@app.command("show")
def show() -> None:
    """Print current configuration."""
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    t.add_column("Key")
    t.add_column("Value")
    cfg = settings.as_dict()
    for k, v in cfg.items():
        display = "***" if k == "api_key" and v else str(v)
        t.add_row(f"[cyan]{k}[/cyan]", display)
    console.print(t)
    console.print(f"\n[dim]Config file: {CONFIG_FILE}[/dim]")


@app.command("set")
def set_value(
    key: str = typer.Argument(..., help="Config key"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a config value and save it."""
    try:
        settings.set(key, value)
        settings.save()
        console.print(f"[green]Set[/green] {key} = {value!r}")
    except KeyError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
