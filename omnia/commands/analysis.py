"""
omnia analysis  — upload files and inspect results
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from omnia.client.analysis import (
    get_analysis,
    get_analysis_children,
    list_analyses,
    upload_file,
)
from omnia.client.auth import get_me
from omnia.client.base import OmniaAPIError, NotConfiguredError
from omnia.ui.tables import analyses_table

app = typer.Typer(help="File analysis.")
console = Console()

_VERDICT_COLOR = {
    "malicious": "red",
    "risky": "yellow",
    "undetected": "green",
}


def _user_id() -> str:
    return get_me()["user_info"]["user_id"]


@app.command("list")
def list_cmd(
    shared: bool = typer.Option(False, "--shared", help="Show shared analyses"),
) -> None:
    """List analyses (yours or shared)."""
    try:
        uid = _user_id()
        analyses = list_analyses(uid, shared=shared)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not analyses:
        console.print("[yellow]No analyses found.[/yellow]")
        return
    console.print(analyses_table(analyses))


@app.command("upload")
def upload(
    file: Path = typer.Argument(..., help="File to analyse", exists=True),
    watch: bool = typer.Option(False, "--watch", "-w", help="Poll until analysis completes"),
) -> None:
    """Upload a file for analysis."""
    try:
        uid = _user_id()
        with console.status(f"Uploading [cyan]{file.name}[/cyan]…"):
            result = upload_file(uid, file)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    analysis_id = result.get("id", "")
    console.print(f"[green]Uploaded.[/green] Analysis ID: [cyan]{analysis_id}[/cyan]")

    if watch and analysis_id:
        _poll_analysis(analysis_id)


def _poll_analysis(analysis_id: str, interval: int = 5, max_wait: int = 300) -> None:
    elapsed = 0
    with console.status("[dim]Waiting for analysis to complete…[/dim]"):
        while elapsed < max_wait:
            try:
                analysis = get_analysis(analysis_id)
            except OmniaAPIError as exc:
                console.print(f"[bold red]Error polling:[/bold red] {exc}")
                return

            status = (analysis.get("status") or "").upper()
            if status in ("COMPLETED", "FAILED"):
                break
            time.sleep(interval)
            elapsed += interval

    _print_analysis_detail(analysis)


@app.command("show")
def show(
    analysis_id: str = typer.Argument(..., help="Analysis ID"),
    children: bool = typer.Option(False, "--children", "-c", help="Also show child analyses"),
) -> None:
    """Show detail for a single analysis."""
    try:
        analysis = get_analysis(analysis_id)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    _print_analysis_detail(analysis)

    if children:
        try:
            child_list = get_analysis_children(analysis_id)
        except OmniaAPIError:
            child_list = []
        if child_list:
            console.print()
            console.print(analyses_table(child_list))


def _print_analysis_detail(analysis: dict) -> None:
    verdict = (analysis.get("verdict") or "pending").lower()
    color = _VERDICT_COLOR.get(verdict, "white")
    risk = analysis.get("risk_score", "-")

    body = Text()
    body.append(f"File: ", style="dim")
    body.append(f"{analysis.get('filename', '')}\n")
    body.append(f"Status: ", style="dim")
    body.append(f"{analysis.get('status', '')}\n")
    body.append(f"Verdict: ", style="dim")
    body.append(f"{verdict.upper()}", style=f"bold {color}")
    body.append(f"\nRisk score: ", style="dim")
    body.append(f"{risk}/10\n")

    summary = analysis.get("summary") or analysis.get("overview", "")
    if summary:
        body.append(f"\n{summary}")

    # Analyzer results
    analyzer_results = analysis.get("analyzer_results", [])
    if analyzer_results:
        body.append("\n\n[bold]Analyzer Results[/bold]")
        for ar in analyzer_results:
            name = ar.get("name", "")
            status = ar.get("status", "")
            body.append(f"\n  • {name}: {status}", style="dim")

    console.print(
        Panel(
            body,
            title=f"[bold]Analysis — {analysis.get('id', '')}[/bold]",
            border_style=color,
            expand=False,
        )
    )
