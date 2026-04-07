"""
omnia auth  — login / logout / whoami
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from omnia.client.auth import get_me
from omnia.client.base import OmniaAPIError, NotConfiguredError
from omnia.config.settings import settings

app = typer.Typer(help="Manage authentication credentials.")
console = Console()


@app.command("login")
def login(
    api_url: str = typer.Option(None, "--url", "-u", help="Omnia API base URL"),
    api_key: str = typer.Option(None, "--key", "-k", help="API key / token"),
) -> None:
    """Configure API credentials and verify they work."""
    if not api_url:
        api_url = typer.prompt("API URL", default=settings.api_url or "")
    if not api_key:
        api_key = typer.prompt("API key", hide_input=True)

    settings.api_url = api_url.rstrip("/")
    settings.api_key = api_key

    console.print("[dim]Verifying credentials…[/dim]")
    try:
        data = get_me()
        info = data.get("user_info", {})
        settings.save()
        console.print(
            Panel(
                f"[bold green]Authenticated[/bold green] as "
                f"[cyan]{info.get('email', 'unknown')}[/cyan]\n"
                f"User ID: [dim]{info.get('user_id', '')}[/dim]\n"
                f"Roles: [dim]{', '.join(info.get('roles', []))}[/dim]",
                title="Login successful",
                border_style="green",
                expand=False,
            )
        )
    except (OmniaAPIError, NotConfiguredError, Exception) as exc:
        console.print(f"[bold red]Login failed:[/bold red] {exc}")
        raise typer.Exit(code=1)


@app.command("logout")
def logout() -> None:
    """Clear stored credentials."""
    settings.api_url = ""
    settings.api_key = ""
    settings.save()
    console.print("[green]Credentials cleared.[/green]")


@app.command("whoami")
def whoami() -> None:
    """Show the currently authenticated user."""
    try:
        data = get_me()
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    info = data.get("user_info", {})
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]User ID[/dim]", info.get("user_id", ""))
    t.add_row("[dim]Email[/dim]", info.get("email", ""))
    t.add_row("[dim]Auth type[/dim]", info.get("auth_type", ""))
    t.add_row("[dim]Roles[/dim]", ", ".join(info.get("roles", [])))
    t.add_row("[dim]Groups[/dim]", ", ".join(info.get("groups", [])))
    console.print(Panel(t, title="[bold]Current user[/bold]", expand=False))
