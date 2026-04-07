"""
omnia project  — list / create / delete projects
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from omnia.client.auth import get_me
from omnia.client.base import OmniaAPIError, NotConfiguredError
from omnia.client.projects import (
    create_project_with_chat,
    delete_project,
    list_projects,
)
from omnia.ui.tables import projects_table

app = typer.Typer(help="Manage projects.")
console = Console()


def _user_id() -> str:
    data = get_me()
    return data["user_info"]["user_id"]


@app.command("list")
def list_cmd(
    search: str = typer.Option("", "--search", "-s", help="Filter by name"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List all projects."""
    try:
        uid = _user_id()
        projects = list_projects(uid, search=search, limit=limit)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return
    console.print(projects_table(projects))


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Project name"),
    description: str = typer.Option("", "--description", "-d"),
) -> None:
    """Create a new project (also creates its first chat)."""
    try:
        uid = _user_id()
        project, chat = create_project_with_chat(uid, name)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold white]{name}[/bold white]\n"
            f"Project ID: [cyan]{project.get('id')}[/cyan]\n"
            f"Chat ID:    [cyan]{chat.get('id')}[/cyan]",
            title="[green]Project created[/green]",
            border_style="green",
            expand=False,
        )
    )


@app.command("delete")
def delete(
    project_id: str = typer.Argument(..., help="Project ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a project and all its chats."""
    if not yes:
        typer.confirm(f"Delete project {project_id!r} and all its data?", abort=True)
    try:
        uid = _user_id()
        delete_project(uid, project_id)
        console.print(f"[green]Deleted project {project_id}[/green]")
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
