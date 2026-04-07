"""
omnia template  — list / fork templates
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from omnia.client.auth import get_me
from omnia.client.base import OmniaAPIError, NotConfiguredError
from omnia.client.templates import fork_template, get_template, list_templates
from omnia.ui.tables import templates_table

app = typer.Typer(help="Manage templates.")
console = Console()


def _user_id() -> str:
    return get_me()["user_info"]["user_id"]


@app.command("list")
def list_cmd(
    search: str = typer.Option("", "--search", "-s"),
) -> None:
    """List available templates."""
    try:
        uid = _user_id()
        tmpls = list_templates(uid, search=search)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not tmpls:
        console.print("[yellow]No templates found.[/yellow]")
        return
    console.print(templates_table(tmpls))


@app.command("show")
def show(template_id: str = typer.Argument(...)) -> None:
    """Show details of a template."""
    try:
        uid = _user_id()
        tmpl = get_template(uid, template_id)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]ID[/dim]", tmpl.get("id", ""))
    t.add_row("[dim]Name[/dim]", tmpl.get("name", ""))
    t.add_row("[dim]Type[/dim]", tmpl.get("template_type", ""))
    t.add_row("[dim]Status[/dim]", tmpl.get("status", ""))
    t.add_row("[dim]Level[/dim]", tmpl.get("confidence_level", ""))
    desc = tmpl.get("description", "")
    if desc:
        t.add_row("[dim]Description[/dim]", desc)

    console.print(Panel(t, title=f"[bold]{tmpl.get('name', template_id)}[/bold]", expand=False))


@app.command("fork")
def fork(template_id: str = typer.Argument(..., help="Template ID to fork")) -> None:
    """Fork (clone) a template to your account."""
    try:
        uid = _user_id()
        result = fork_template(uid, template_id)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    new_id = result.get("id", "")
    console.print(f"[green]Forked.[/green] New template ID: [cyan]{new_id}[/cyan]")
