"""Renders chat messages from the API to the terminal."""

from __future__ import annotations

import base64
import json
import re

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_VERDICT_COLOR = {
    "malicious": "red",
    "risky": "yellow",
    "undetected": "green",
}


def _unwrap_content(content: str) -> str:
    """
    The API sometimes stores content as a JSON object {"text": "...", "provider": "..."}.
    Extract the actual text string in that case.
    """
    if content and content.strip().startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "text" in data:
                return data["text"]
        except Exception:
            pass
    return content


def render_message(msg: dict, model: str = "") -> None:
    """Dispatch a stored message dict to the correct renderer."""
    component_type = msg.get("component_type", "assistant")
    content = _unwrap_content(msg.get("content", ""))

    if component_type == "user":
        _render_user(content)
    elif component_type in ("assistant", "report"):
        _render_assistant(content, model=model)
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


def _render_assistant(content: str, model: str = "") -> None:
    model_hint = f" [dim]({model})[/dim]" if model else ""
    console.print()
    console.print(f"[bold blue]Omnia[/bold blue]{model_hint}")
    if _has_custom_tags(content):
        pos = 0
        for m in _RE_TAGS.finditer(content):
            plain = content[pos : m.start()].strip()
            if plain:
                try:
                    console.print(Markdown(plain))
                except Exception:
                    console.print(plain)
            if m.group(1) is not None:
                tag, attrs_str, inner = m.group(1), m.group(2) or "", m.group(3) or ""
            else:
                tag, attrs_str, inner = m.group(4), m.group(5) or "", ""
            _render_custom_tag(tag, attrs_str, inner)
            pos = m.end()
        tail = content[pos:].strip()
        if tail:
            try:
                console.print(Markdown(tail))
            except Exception:
                console.print(tail)
    else:
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
    console.print(
        Panel(body, title="[bold]Analysis Result[/bold]", border_style=color, expand=False)
    )


def _render_workflow(msg: dict, component_type: str) -> None:
    icon = "▶" if component_type == "workflow_launch" else "■"
    name = msg.get("workflow_name") or msg.get("content", "workflow")
    style = "bold cyan" if component_type == "workflow_launch" else "dim"
    console.print(f"[{style}]{icon} {name}[/{style}]")


def _render_agent_launch(msg: dict) -> None:
    name = msg.get("agent_name") or msg.get("content", "agent")
    console.print(f"[bold magenta]◆ Launching agent: {name}[/bold magenta]")


def _render_error(content: str) -> None:
    console.print(
        Panel(
            content,
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
        )
    )


# ---------------------------------------------------------------------------
# Custom XML tag rendering
# ---------------------------------------------------------------------------

_KNOWN_TAGS = (
    "tool",
    "agent",
    "think",
    "error",
    "grounding",
    "groundings",
    "html_chart",
    "html_chart_no_download",
    "workflow_draft",
    "memories",
    "info",
    "report",
)
_TAG_PAT = "|".join(_KNOWN_TAGS)

# Matches full tags (<tag ...>content</tag>) and self-closing (<tag .../>)
_RE_TAGS = re.compile(
    rf"<({_TAG_PAT})\b([^>]*)>(.*?)</\1>|<({_TAG_PAT})\b([^>]*?)/>",
    re.DOTALL,
)
_RE_ATTR = re.compile(r'(\w+)="([^"]*)"')

_TOOL_ICONS: dict[str, str] = {
    "code_execution": ">_",
    "chart_generation": "📊",
    "google_web_search": "🔍",
    "web_search": "🔍",
    "read_file": "📄",
    "write_file": "✏",
    "bash": ">_",
    "python": ">_",
}


def _decode_b64(value: str) -> str | None:
    """Decode a base64 string (with stripped padding). Returns None on failure."""
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(padded).decode("utf-8")
    except Exception:
        return None


def _decode_args(args_b64: str) -> str:
    """Decode base64-encoded args JSON into a compact readable string."""
    raw = _decode_b64(args_b64)
    if raw is None:
        return ""
    try:
        data = json.loads(raw)
        return json.dumps(data, ensure_ascii=False, separators=(", ", ": "))
    except Exception:
        return raw


def _render_custom_tag(tag: str, attrs_str: str, content: str) -> None:
    """Dispatch a parsed custom tag to the appropriate renderer."""
    attrs: dict[str, str] = dict(_RE_ATTR.findall(attrs_str))
    # temp=True tags print a plain one-liner; everything else goes through
    # _build_tag_renderable so the same logic works nested inside agents too.
    temp = attrs.get("temp", "False") == "True"
    if temp:
        name = attrs.get("name", tag)
        if tag == "agent":
            console.print(f"[dim]◆ Running agent [bold]{name}[/bold]…[/dim]")
        elif tag != "info":
            icon = _TOOL_ICONS.get(name, "⚙")
            console.print(f"[dim]{icon} Running [bold]{name}[/bold]…[/dim]")
        return

    r = _build_tag_renderable(tag, attrs_str, content)
    if r is not None:
        console.print(r)


def _build_renderables(text: str) -> list[RenderableType]:
    """
    Convert text (which may contain custom XML tags) into a list of Rich
    renderables. Used to build nested panel contents without printing.
    """
    renderables: list[RenderableType] = []
    if not _has_custom_tags(text):
        stripped = text.strip()
        if stripped:
            renderables.append(Text(stripped, style="dim white"))
        return renderables

    pos = 0
    for m in _RE_TAGS.finditer(text):
        plain = text[pos : m.start()].strip("\n\r")
        if plain.strip():
            renderables.append(Text(plain, style="dim white"))
        if m.group(1) is not None:
            tag, attrs_str, inner = m.group(1), m.group(2) or "", m.group(3) or ""
        else:
            tag, attrs_str, inner = m.group(4), m.group(5) or "", ""
        r = _build_tag_renderable(tag, attrs_str, inner)
        if r is not None:
            renderables.append(r)
        pos = m.end()

    tail = text[pos:].strip("\n\r")
    if tail.strip():
        renderables.append(Text(tail, style="dim white"))

    return renderables


def _build_tag_renderable(tag: str, attrs_str: str, content: str) -> RenderableType | None:
    """Return a Rich renderable for a custom tag (without printing it)."""
    attrs: dict[str, str] = dict(_RE_ATTR.findall(attrs_str))

    if tag == "tool":
        name = attrs.get("name", "tool")
        temp = attrs.get("temp", "False") == "True"
        if temp:
            return Text(f"⚙ Running {name}…", style="dim")
        icon = _TOOL_ICONS.get(name, "⚙")
        args_decoded = _decode_args(attrs.get("args", ""))
        body = Text()
        if args_decoded:
            body.append("Args  ", style="dim")
            body.append(args_decoded + "\n", style="cyan")
        output = content.strip()
        if output:
            if body:
                body.append("\n")
            body.append(output, style="dim white")
        return Panel(
            body,
            title=f"[bold cyan]{icon} {name}[/bold cyan]",
            border_style="cyan",
            expand=False,
            padding=(0, 1),
        )

    if tag == "agent":
        name = attrs.get("name", "agent")
        temp = attrs.get("temp", "False") == "True"
        if temp:
            return Text(f"◆ Running agent {name}…", style="dim")
        inner_renderables = _build_renderables(content.strip())
        inner = Group(*inner_renderables) if inner_renderables else Text("")
        return Panel(
            inner,
            title=f"[bold magenta]◆ {name}[/bold magenta]",
            border_style="magenta",
            expand=False,
            padding=(0, 1),
        )

    if tag == "think":
        stripped = content.strip()
        return Text(f"  ↳ {stripped}", style="dim italic") if stripped else None

    if tag == "error":
        return Panel(
            content.strip(),
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
        )

    if tag in ("grounding", "groundings"):
        uri = attrs.get("uri", "")
        text_val = content.strip()
        if uri and text_val:
            return Text(f"{text_val} ({uri})", style="dim")
        return Text(text_val, style="dim") if text_val else None

    if tag in ("html_chart", "html_chart_no_download"):
        code = attrs.get("code", "")
        chart_type, title = "chart", ""
        raw = _decode_b64(code)
        if raw:
            try:
                cfg = json.loads(raw)
                chart_type = cfg.get("type", "chart")
                title = (
                    cfg.get("options", {}).get("plugins", {}).get("title", {}).get("text")
                    or cfg.get("data", {}).get("datasets", [{}])[0].get("label", "")
                    or ""
                )
            except Exception:
                pass
        label = f"{title} ({chart_type})" if title else chart_type
        return Panel(
            Text("Chart cannot be rendered in the terminal.", style="dim"),
            title=f"[bold yellow]📊 {label}[/bold yellow]",
            border_style="yellow",
            expand=False,
            padding=(0, 1),
        )

    if tag == "workflow_draft":
        struct_b64 = attrs.get("struct", "")
        name, description = "Workflow", ""
        raw = _decode_b64(struct_b64)
        if raw:
            try:
                data = json.loads(raw)
                name = data.get("name") or data.get("title") or name
                description = data.get("description", "")
            except Exception:
                pass
        body = Text()
        body.append(name, style="bold white")
        if description:
            body.append(f"\n{description}", style="dim")
        return Panel(
            body,
            title="[bold green]▶ Workflow Draft[/bold green]",
            border_style="green",
            expand=False,
            padding=(0, 1),
        )

    if tag == "memories":
        output = content.strip()
        return (
            Panel(
                output,
                title="[dim]Memories[/dim]",
                border_style="dim",
                expand=False,
                padding=(0, 1),
            )
            if output
            else None
        )

    if tag == "report":
        report_id = attrs.get("report_id", "")
        timestamp = attrs.get("report_timestamp", "")
        info = Text()
        info.append(f"ID: {report_id}", style="cyan")
        if timestamp:
            info.append(f"  •  {timestamp}", style="dim")
        return Panel(
            info,
            title="[bold]📋 Report[/bold]",
            border_style="dim",
            expand=False,
            padding=(0, 1),
        )

    return None


def _has_custom_tags(text: str) -> bool:
    return any(f"<{t}" in text for t in _KNOWN_TAGS)


def _render_text_with_tags(text: str, *, inline: bool = False) -> bool:
    """
    Scan `text` for custom XML tags, render them as panels.
    Plain text between tags is printed normally (inline=True → no trailing newline).
    Returns True if at least one tag was found.
    """
    if not _has_custom_tags(text):
        return False

    pos = 0
    found = False
    for m in _RE_TAGS.finditer(text):
        plain = text[pos : m.start()].strip("\n\r")
        if plain.strip():
            console.print(plain, end="", highlight=False)
        # Group 1/2/3 → full form; Group 4/5 → self-closing
        if m.group(1) is not None:
            tag, attrs_str, content = m.group(1), m.group(2) or "", m.group(3) or ""
        else:
            tag, attrs_str, content = m.group(4), m.group(5) or "", ""
        _render_custom_tag(tag, attrs_str, content)
        pos = m.end()
        found = True

    tail = text[pos:].strip("\n\r") if found else text[pos:]
    if tail.strip() if found else tail:
        end = "" if inline else None
        if end is not None:
            console.print(tail, end=end, highlight=False)
        else:
            console.print(tail, highlight=False)

    return found


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
        if not _render_text_with_tags(delta, inline=True):
            # Skip deltas that are only whitespace — they're usually padding
            # around tool tags and would produce blank lines
            if delta.strip():
                console.print(delta, end="", highlight=False)

    buffer.append(delta)
