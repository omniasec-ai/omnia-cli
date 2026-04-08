"""Reusable Rich table builders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def _fmt_date(value: Any) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def projects_table(projects: list[dict]) -> Table:
    t = Table(title="Chats", show_lines=False, highlight=True)
    t.add_column("ID", style="dim cyan", no_wrap=True, max_width=36)
    t.add_column("Name", style="bold white")
    t.add_column("Unread", style="yellow", justify="right")
    t.add_column("Updated", style="dim")
    for p in projects:
        t.add_row(
            p.get("id", ""),
            p.get("name", ""),
            str(p.get("unread_messages", 0) or 0),
            _fmt_date(p.get("updated_at")),
        )
    return t


def chats_table(chats: list[dict]) -> Table:
    t = Table(title="Chats", show_lines=False, highlight=True)
    t.add_column("ID", style="dim cyan", no_wrap=True, max_width=36)
    t.add_column("Name", style="bold white")
    t.add_column("Project", style="blue")
    t.add_column("Updated", style="dim")
    for c in chats:
        t.add_row(
            c.get("id", ""),
            c.get("name", ""),
            c.get("project_name", ""),
            _fmt_date(c.get("updated_at")),
        )
    return t


def analyses_table(analyses: list[dict]) -> Table:
    _VERDICT_STYLE = {
        "malicious": "bold red",
        "risky": "bold yellow",
        "undetected": "green",
        "pending": "dim",
    }
    t = Table(title="Analyses", show_lines=False, highlight=True)
    t.add_column("Hash", style="dim cyan", no_wrap=True, max_width=16)
    t.add_column("Filename", style="white")
    t.add_column("Status", style="dim")
    t.add_column("Verdict", no_wrap=True)
    t.add_column("Risk", justify="right")
    t.add_column("Date", style="dim")
    for a in analyses:
        verdict = (a.get("verdict") or "pending").lower()
        t.add_row(
            a.get("file_id", "")[:16] + "…",
            a.get("filename", ""),
            a.get("status", ""),
            f"[{_VERDICT_STYLE.get(verdict, 'white')}]{verdict}[/]",
            str(a.get("risk_score", "-")),
            _fmt_date(a.get("created_at")),
        )
    return t


def templates_table(templates: list[dict]) -> Table:
    t = Table(title="Templates", show_lines=False, highlight=True)
    t.add_column("ID", style="dim cyan", no_wrap=True, max_width=36)
    t.add_column("Name", style="bold white")
    t.add_column("Type", style="magenta")
    t.add_column("Status", style="dim")
    t.add_column("Level", style="dim")
    for tmpl in templates:
        t.add_row(
            tmpl.get("id", ""),
            tmpl.get("name", ""),
            tmpl.get("template_type", ""),
            tmpl.get("status", ""),
            tmpl.get("confidence_level", ""),
        )
    return t


def agents_table(agents: list[dict]) -> Table:
    t = Table(title="Available Agents", show_lines=False, highlight=True)
    t.add_column("ID", style="cyan")
    t.add_column("Name", style="bold white")
    t.add_column("Description", style="dim")
    for a in agents:
        t.add_row(
            a.get("id", ""),
            a.get("name", ""),
            a.get("description", ""),
        )
    return t


def resources_table(resources: list[dict]) -> Table:
    t = Table(title="Resources", show_lines=False, highlight=True)
    t.add_column("ID", style="dim cyan", no_wrap=True, max_width=36)
    t.add_column("Name", style="white")
    t.add_column("Type", style="dim")
    t.add_column("Size", justify="right", style="dim")
    for r in resources:
        size = r.get("size", 0) or 0
        size_str = f"{size // 1024} KB" if size >= 1024 else f"{size} B"
        t.add_row(
            r.get("id", ""),
            r.get("name", r.get("filename", "")),
            r.get("type", ""),
            size_str,
        )
    return t
