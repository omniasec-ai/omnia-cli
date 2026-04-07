"""Renders chat messages from the API to the terminal."""
from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_VERDICT_COLOR = {
    "malicious": "red",
    "risky": "yellow",
    "undetected": "green",
}


def render_message(msg: dict) -> None:
    """Dispatch a stored message dict to the correct renderer."""
    component_type = msg.get("component_type", "assistant")
    content = msg.get("content", "")

    if component_type == "user":
        _render_user(content)
    elif component_type in ("assistant", "report"):
        _render_assistant(content)
    elif component_type == "thinking":
        _render_thinking(content)
    elif component_type in ("file", "context_file"):
        _render_file(msg)
    elif component_type == "analysis":
        _render_analysis(msg)
    elif component_type in ("workflow_launch", "workflow_end"):
        _render_workflow(msg, component_type)
    elif component_type == "agent_launch":
        _render_agent_launch(msg)
    elif component_type == "error":
        _render_error(content)
    elif component_type == "loading":
        pass  # skip persisted loading indicators
    else:
        # Generic fallback
        if content:
            console.print(f"[dim][{component_type}][/dim] {content}")


def _render_user(content: str) -> None:
    console.print(f"\n[bold green]You[/bold green]  {content}")


def _render_assistant(content: str) -> None:
    console.print()
    console.print("[bold blue]Omnia[/bold blue]")
    try:
        console.print(Markdown(content))
    except Exception:
        console.print(content)


def _render_thinking(content: str) -> None:
    console.print(f"[dim italic]  ↳ {content}[/dim italic]")


def _render_file(msg: dict) -> None:
    name = msg.get("filename") or msg.get("content", "file")
    file_type = msg.get("file_type", "")
    console.print(
        Panel(
            f"[cyan]{name}[/cyan]  [dim]{file_type}[/dim]",
            title="[bold]File[/bold]",
            border_style="dim",
            expand=False,
        )
    )


def _render_analysis(msg: dict) -> None:
    verdict = (msg.get("verdict") or "").lower()
    color = _VERDICT_COLOR.get(verdict, "white")
    risk = msg.get("risk_score", "")
    filename = msg.get("filename", "")
    summary = msg.get("summary") or msg.get("content", "")
    body = Text()
    if filename:
        body.append(f"File: {filename}\n", style="dim")
    if verdict:
        body.append("Verdict: ")
        body.append(verdict.upper(), style=f"bold {color}")
        body.append("\n")
    if risk:
        body.append(f"Risk score: {risk}/10\n", style="dim")
    if summary:
        body.append(f"\n{summary}")
    console.print(Panel(body, title="[bold]Analysis Result[/bold]", border_style=color, expand=False))


def _render_workflow(msg: dict, component_type: str) -> None:
    icon = "▶" if component_type == "workflow_launch" else "■"
    name = msg.get("workflow_name") or msg.get("content", "workflow")
    style = "bold cyan" if component_type == "workflow_launch" else "dim"
    console.print(f"[{style}]{icon} {name}[/{style}]")


def _render_agent_launch(msg: dict) -> None:
    name = msg.get("agent_name") or msg.get("content", "agent")
    console.print(f"[bold magenta]◆ Launching agent: {name}[/bold magenta]")


def _render_error(content: str) -> None:
    console.print(Panel(content, title="[bold red]Error[/bold red]", border_style="red", expand=False))


def render_streaming_chunk(chunk: dict, buffer: list[str]) -> None:
    """
    Called during live SSE streaming.
    Accumulates content in `buffer` and prints deltas.
    """
    delta = chunk.get("content", "")
    if isinstance(delta, dict):
        delta = delta.get("text", "")
    
    is_partial = chunk.get("partial", True)
    accumulated = "".join(buffer)
    # Skip the final chunk if it's non-partial OR if it duplicates what we've already streamed
    if buffer and (not is_partial or delta == accumulated):
        buffer.append(delta)
        return
        
    component_type = chunk.get("component_type", "assistant")

    if component_type in ("thinking",):
        console.print(f"[dim italic]{delta}[/dim italic]", end="")
    elif component_type == "error":
        _render_error(delta)
    else:
        console.print(delta, end="", highlight=False)
    
    buffer.append(delta)
