"""
Interactive REPL for the Omnia CLI.

COMMANDS AVAILABLE WITHOUT LOGIN
─────────────────────────────────
  /version                          Check API version and connectivity
  /market search <query>            Search packages in market intelligence
  /market show <market> <id>        Show package details
  /market versions <market> <id>    List package versions
  /share <token>                    View a shared chat by token

COMMANDS THAT REQUIRE LOGIN
────────────────────────────
  /login [--url URL] [--key KEY]    Authenticate with the API
  /logout                           Clear credentials
  /me                               Show current user

  /new <name>                       Create a new chat
  /chats  /resume                   Pick a recent chat with arrow keys and enter it
  /delete                           Delete the current chat
  /leave  /back                     Leave the current chat (keeps CLI open)
  /history                          Show this chat's message history

  /analysis                         List your file analyses
  /analysis upload <file>           Upload a file for analysis
  /analysis show <id>               Show analysis detail (public or private)

  /templates                        List available templates
  /template show <id>               Show template detail
  /template fork <id>               Fork a template to your account

  /resources                        List resources in current chat
  /upload <file>                    Upload a file as a resource

  /agents                           List available agents
  /model [name]                     Show / change LLM model

  /config                           Show current configuration
  /config set <key> <value>         Set default_model or default_provider

  /help                             Show this help
  /clear                            Clear the screen
  /exit                             Quit

Any plain text (no leading /) is sent as a message to the current chat.
"""

from __future__ import annotations

import base64
import os
import select
import shlex
import sys
import termios
import tty
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from omnia.client import analysis as analysis_client
from omnia.client import auth as auth_client
from omnia.client import messages as messages_client
from omnia.client import projects as projects_client
from omnia.client import public as public_client
from omnia.client import resources as resources_client
from omnia.client import templates as templates_client
from omnia.client.base import NotConfiguredError, OmniaAPIError
from omnia.config.settings import CONFIG_DIR, settings
from omnia.ui.messages import render_message
from omnia.ui.stream import run_stream
from omnia.ui.tables import (
    agents_table,
    analyses_table,
    projects_table,
    resources_table,
    templates_table,
)

console = Console()

_BANNER = """\
[bold cyan]
  ██████╗ ███╗   ███╗███╗   ██╗██╗  █████╗
 ██╔═══██╗████╗ ████║████╗  ██║██║ ██╔══██╗
 ██║   ██║██╔████╔██║██╔██╗ ██║██║ ███████║
 ██║   ██║██║╚██╔╝██║██║╚██╗██║██║ ██╔══██║
 ╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██║ ██║  ██║
  ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝ ╚═╝  ╚═╝[/bold cyan]
[dim]  Type [bold cyan]/help[/bold cyan] for commands · [bold cyan]/login[/bold cyan] to authenticate[/dim]
"""

_HELP = __doc__  # Reuse the module docstring

_COMPLETIONS = [
    "/version",
    "/market search",
    "/market show",
    "/market versions",
    "/share",
    "/login",
    "/logout",
    "/me",
    "/new",
    "/delete",
    "/chats",
    "/resume",
    "/leave",
    "/back",
    "/history",
    "/analysis",
    "/analysis upload",
    "/analysis show",
    "/templates",
    "/template show",
    "/template fork",
    "/resources",
    "/upload",
    "/agents",
    "/model",
    "/config",
    "/config set",
    "/help",
    "/clear",
    "/exit",
]

_PT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})

_VERDICT_COLOR = {"malicious": "red", "risky": "yellow", "undetected": "green"}

# ---------------------------------------------------------------------------
# Model helpers  (mirrors omnia-frontend ModelDropdown / SettingsContext)
# ---------------------------------------------------------------------------


def _models_from_settings(user_settings: dict) -> list[dict]:
    """
    Build the selectable model list from the user's last_settings payload,
    replicating the frontend logic:
      - only providers that have a non-empty api_key var (or don't require one)
      - only models flagged as enabled
    Returns a list of {"label", "model", "provider"} dicts.
    """
    result: list[dict] = []
    for provider in user_settings.get("llm_providers", []):
        has_key = any(
            v.get("var_name") == "api_key"
            and ((v.get("required") and v.get("var_value")) or not v.get("required"))
            for v in provider.get("vars", [])
        )
        if not has_key:
            continue
        for model in provider.get("models", []):
            if model.get("enabled"):
                result.append(
                    {
                        "label": model.get("title") or model["internal_name"],
                        "model": model["internal_name"],
                        "provider": provider["internal_name"],
                    }
                )
    return result


def _model_picker(models: list[dict], current_model: str) -> dict | None:
    """
    Interactive arrow-key model selector rendered directly to the terminal.
    Returns the chosen model dict, or None if the user cancelled (Ctrl-C / q).
    """
    # ── Build display structure ──────────────────────────────────────────
    providers_order: list[str] = []
    by_provider: dict[str, list[tuple[int, dict]]] = {}
    for i, m in enumerate(models):
        p = m["provider"]
        if p not in by_provider:
            providers_order.append(p)
            by_provider[p] = []
        by_provider[p].append((i, m))

    # flat list of (model_index | None, display_text)
    lines: list[tuple[int | None, str]] = []
    for p in providers_order:
        lines.append((None, p.upper()))
        for model_idx, m in by_provider[p]:
            lines.append((model_idx, m["label"]))

    # indices into `lines` that correspond to selectable models
    selectable: list[int] = [i for i, (midx, _) in enumerate(lines) if midx is not None]

    # position within `selectable`
    cur_idx = next(
        (
            si
            for si, li in enumerate(selectable)
            if lines[li][0]
            == next((i for i, m in enumerate(models) if m["model"] == current_model), 0)
        ),
        0,
    )

    def _line_str(line_i: int) -> str:
        midx, label = lines[line_i]
        if midx is None:
            # provider header
            return f"\x1b[2m  {label}\x1b[0m"
        if line_i == selectable[cur_idx]:
            return f"\x1b[1;36m❯ {label}\x1b[0m"
        return f"  {label}"

    def _render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{len(lines)}A")
        for i in range(len(lines)):
            sys.stdout.write(f"\x1b[2K\r{_line_str(i)}\n")
        sys.stdout.flush()

    sys.stdout.write("\n")
    _render(first=True)

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            # Use os.read to bypass Python's TextIOWrapper buffer so that
            # select() reliably sees pending bytes after reading \x1b.
            ch = os.read(fd, 1)

            if ch in (b"\x03", b"q"):  # Ctrl-C or q → cancel
                return None
            elif ch in (b"\r", b"\n"):  # Enter → confirm
                model_idx = lines[selectable[cur_idx]][0]
                return models[model_idx]  # type: ignore[index]
            elif ch == b"\x1b":  # possible escape sequence
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    return None  # lone Escape → cancel
                rest = os.read(fd, 2)
                if rest == b"[A":  # ↑
                    cur_idx = (cur_idx - 1) % len(selectable)
                    _render()
                elif rest == b"[B":  # ↓
                    cur_idx = (cur_idx + 1) % len(selectable)
                    _render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\n")
        sys.stdout.flush()


def _chat_picker(projects: list[dict], window: int = 5) -> dict | None:
    """
    Arrow-key picker with a scrolling window of `window` visible items.
    Returns the chosen project dict, or None if cancelled.
    """
    from datetime import datetime

    def _fmt(p: dict) -> str:
        name = p.get("name", "(unnamed)")
        updated = p.get("updated_at") or p.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = ""
        unread = p.get("unread_messages") or 0
        badge = f" [{unread}]" if unread else ""
        suffix = f"  \x1b[2m{date_str}{badge}\x1b[0m" if date_str else ""
        return f"{name}{suffix}"

    n = len(projects)
    visible = min(window, n)
    cur_idx = 0  # index into projects (absolute)
    win_start = 0  # first visible index

    def _render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{visible}A")
        for row, i in enumerate(range(win_start, win_start + visible)):
            sys.stdout.write("\x1b[2K\r")
            label = _fmt(projects[i])
            if i == cur_idx:
                sys.stdout.write(f"\x1b[1;36m❯ {label}\x1b[0m\n")
            else:
                sys.stdout.write(f"  {label}\n")
        sys.stdout.flush()

    sys.stdout.write("\n")
    _render(first=True)

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = os.read(fd, 1)
            if ch in (b"\x03", b"q"):
                return None
            elif ch in (b"\r", b"\n"):
                return projects[cur_idx]
            elif ch == b"\x1b":
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    return None
                rest = os.read(fd, 2)
                if rest == b"[A":  # ↑
                    cur_idx = (cur_idx - 1) % n
                    if cur_idx < win_start:
                        win_start = cur_idx
                    elif cur_idx == n - 1:  # wrapped to bottom
                        win_start = n - visible
                    _render()
                elif rest == b"[B":  # ↓
                    cur_idx = (cur_idx + 1) % n
                    if cur_idx >= win_start + visible:
                        win_start = cur_idx - visible + 1
                    elif cur_idx == 0:  # wrapped to top
                        win_start = 0
                    _render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\n")
        sys.stdout.flush()


class OmniaREPL:
    def __init__(self) -> None:
        self.user_info: Optional[dict] = None
        self.project: Optional[dict] = None
        self.chat: Optional[dict] = None
        self.model: str = settings.default_model
        self.provider: str = settings.default_provider
        self.user_settings: dict = {}

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._session: PromptSession = PromptSession(
            history=FileHistory(str(CONFIG_DIR / "history")),
            auto_suggest=AutoSuggestFromHistory(),
            completer=WordCompleter(_COMPLETIONS, sentence=True),
            style=_PT_STYLE,
            complete_while_typing=False,
        )

    # ------------------------------------------------------------------
    # Properties / helpers
    # ------------------------------------------------------------------

    @property
    def user_id(self) -> Optional[str]:
        return self.user_info.get("user_id") if self.user_info else None

    def _prompt_text(self) -> str:
        if self.project:
            label = self.project.get("name", "chat")
        elif self.user_info:
            label = self.user_info.get("email", "omnia").split("@")[0]
        else:
            label = "omnia"
        auth = "" if self.user_info else " [dim](not logged in)[/dim]"
        # prompt_toolkit doesn't render Rich markup — keep it plain
        auth_plain = "" if self.user_info else " (?)"
        return f"{label}{auth_plain} >> "

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        console.print(_BANNER)

        console.print(f"[dim]Endpoint:[/dim] [cyan]{settings.api_url}[/cyan]\n")

        if settings.is_configured():
            self._try_auto_login()
        else:
            console.print(
                "[yellow]Not logged in.[/yellow]  "
                "Run [bold cyan]/login[/bold cyan] to authenticate.\n"
                "[dim]Some commands (/version, /market, /share) work without login.[/dim]\n"
            )

        while True:
            try:
                raw = self._session.prompt(self._prompt_text()).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not raw:
                continue

            if raw.startswith("/"):
                if self._dispatch(raw):
                    break
            else:
                self._send_message(raw)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, raw: str) -> bool:
        """Returns True to signal exit."""
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()

        cmd = tokens[0].lower()
        args = tokens[1:]

        try:
            # ── No auth required ──────────────────────────────────────
            if cmd == "/exit":
                console.print("[dim]Goodbye.[/dim]")
                return True
            elif cmd == "/help":
                console.print(_HELP)
            elif cmd == "/clear":
                os.system("clear")
            elif cmd == "/version":
                self._cmd_version()
            elif cmd == "/market":
                self._cmd_market(args)
            elif cmd == "/share":
                self._cmd_share(args)

            # ── Auth required ─────────────────────────────────────────
            elif cmd == "/login":
                self._cmd_login(args)
            elif cmd == "/logout":
                self._cmd_logout()
            elif cmd == "/me":
                self._require_auth()
                self._cmd_me()
            elif cmd == "/agents":
                self._require_auth()
                self._cmd_agents()
            elif cmd == "/new":
                self._require_auth()
                self._cmd_new(args)
            elif cmd in ("/chats", "/resume"):
                self._require_auth()
                self._cmd_chats()
            elif cmd == "/delete":
                self._require_auth()
                self._cmd_delete()
            elif cmd in ("/leave", "/back"):
                self._cmd_leave()
            elif cmd == "/history":
                self._require_auth()
                self._require_chat()
                self._cmd_history()
            elif cmd == "/analysis":
                self._cmd_analysis(args)  # has internal public/private split
            elif cmd == "/templates":
                self._require_auth()
                self._cmd_templates([])
            elif cmd == "/template":
                self._require_auth()
                self._cmd_templates(args)
            elif cmd == "/resources":
                self._require_auth()
                self._require_chat()
                self._cmd_resources()
            elif cmd == "/upload":
                self._require_auth()
                self._require_chat()
                self._cmd_upload(args)
            elif cmd == "/model":
                self._cmd_model(args)
            elif cmd == "/config":
                self._cmd_config(args)
            else:
                console.print(f"[red]Unknown command:[/red] {cmd}  (type [cyan]/help[/cyan])")
        except NotConfiguredError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
        except OmniaAPIError as exc:
            console.print(f"[bold red]API error {exc.status_code}:[/bold red] {exc.detail}")
        except Exception as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")

        return False

    # ------------------------------------------------------------------
    # ── PUBLIC commands (no login needed) ────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_version(self) -> None:
        data = public_client.get_api_version()
        msg = data.get("message", "")
        version = data.get("core_version", "")
        console.print(f"[bold]{msg}[/bold]  [dim]v{version}[/dim]")

    def _cmd_market(self, args: list[str]) -> None:
        sub = args[0].lower() if args else "search"
        rest = args[1:]

        if sub == "search":
            query = " ".join(rest) if rest else _prompt_default("Search query")
            if not query:
                console.print("[red]Usage: /market search <query>[/red]")
                return
            with console.status(f"[dim]Searching for [cyan]{query}[/cyan]…[/dim]"):
                data = public_client.search_market(query)
            _print_market_results(data)

        elif sub == "show":
            if len(rest) < 2:
                console.print("[red]Usage: /market show <market> <id>[/red]")
                return
            market, mid = rest[0], rest[1]
            version = rest[2] if len(rest) > 2 else ""
            with console.status("[dim]Loading…[/dim]"):
                data = public_client.get_market_package(market, mid, version)
            _print_market_package(data)

        elif sub == "versions":
            if len(rest) < 2:
                console.print("[red]Usage: /market versions <market> <id>[/red]")
                return
            market, mid = rest[0], rest[1]
            with console.status("[dim]Loading versions…[/dim]"):
                data = public_client.get_market_package_versions(market, mid)
            _print_market_versions(data)

        else:
            console.print(
                "[dim]Usage:[/dim]  "
                "/market search <query>  |  "
                "/market show <market> <id>  |  "
                "/market versions <market> <id>"
            )

    def _cmd_share(self, args: list[str]) -> None:
        if not args:
            console.print("[red]Usage: /share <token>[/red]")
            return
        token = args[0]
        with console.status("[dim]Loading shared chat…[/dim]"):
            data = public_client.get_shared_chat(token)
        _print_shared_chat(data)

    # ------------------------------------------------------------------
    # ── AUTH commands ─────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _try_auto_login(self) -> None:
        try:
            data = auth_client.get_me()
            self.user_info = data.get("user_info", {})
            email = self.user_info.get("email", "unknown")
            try:
                self.user_settings = auth_client.get_last_user_settings(self.user_id)
            except Exception:
                self.user_settings = {}
            console.print(f"[dim]Logged in as[/dim] [bold cyan]{email}[/bold cyan]\n")
        except Exception:
            console.print(
                "[yellow]Credentials found but could not verify.[/yellow]  "
                "Run [cyan]/login[/cyan] to re-authenticate.\n"
            )

    def _cmd_login(self, args: list[str]) -> None:
        key = _flag(args, "--key")
        if not key:
            user_id = Prompt.ask("User ID (UUID)")
            api_key = _prompt_secret("API Key")
            raw = f"{user_id}:{api_key}".encode()
            key = f"Basic {base64.b64encode(raw).decode()}"

        settings.api_key = key

        console.print(f"[dim]Connecting to[/dim] [cyan]{settings.api_url}[/cyan][dim]…[/dim]")
        with console.status("[dim]Verifying credentials…[/dim]"):
            data = auth_client.get_me()

        self.user_info = data.get("user_info", {})
        try:
            self.user_settings = auth_client.get_last_user_settings(self.user_id)
        except Exception:
            self.user_settings = {}
        settings.save()

        console.print(
            Panel(
                f"[bold green]Authenticated[/bold green] as "
                f"[cyan]{self.user_info.get('email')}[/cyan]\n"
                f"[dim]User ID:[/dim] {self.user_info.get('user_id')}\n"
                f"[dim]Roles:[/dim]   {', '.join(self.user_info.get('roles', []))}",
                title="Login successful",
                border_style="green",
                expand=False,
            )
        )

    def _cmd_logout(self) -> None:
        settings.api_url = ""
        settings.api_key = ""
        settings.save()
        self.user_info = None
        self.project = None
        self.chat = None
        console.print("[green]Logged out.[/green]")

    def _cmd_me(self) -> None:
        # Refresh from API to get latest state
        data = auth_client.get_me()
        self.user_info = data.get("user_info", {})
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_row("[dim]User ID[/dim]", self.user_info.get("user_id", ""))
        t.add_row("[dim]Email[/dim]", self.user_info.get("email", ""))
        t.add_row("[dim]Auth type[/dim]", self.user_info.get("auth_type", ""))
        t.add_row("[dim]Roles[/dim]", ", ".join(self.user_info.get("roles", [])))
        t.add_row("[dim]Groups[/dim]", ", ".join(self.user_info.get("groups", [])))
        console.print(Panel(t, title="[bold]Current user[/bold]", expand=False))

    # ------------------------------------------------------------------
    # ── Projects / chats ──────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_agents(self) -> None:
        agents = auth_client.get_agents()
        if agents:
            console.print(agents_table(agents))
        else:
            console.print("[yellow]No agents found.[/yellow]")

    def _cmd_new(self, args: list[str]) -> None:
        name = " ".join(args) if args else _prompt_default("Chat name", "New chat")
        with console.status(f"[dim]Creating [cyan]{name}[/cyan]…[/dim]"):
            project, chat = projects_client.create_project_with_chat(self.user_id, name)
        self.project = project
        self.chat = chat
        console.print(
            f"[green]Created:[/green] [bold]{name}[/bold]  "
            "[dim]Start typing to send a message.[/dim]"
        )

    def _cmd_delete(self) -> None:
        if not self.project:
            console.print("[red]No active chat to delete.[/red]")
            return
        name = self.project.get("name", "")
        pid = self.project["id"]
        confirm = _prompt_default(f"Delete chat {name!r}? [y/N]", "n")
        if confirm.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled.[/dim]")
            return
        projects_client.delete_project(self.user_id, pid)
        self.project = None
        self.chat = None
        console.print(f"[green]Deleted[/green] [bold]{name}[/bold]")

    def _cmd_leave(self) -> None:
        if not self.project:
            console.print("[dim]No active chat.[/dim]")
            return
        name = self.project.get("name", "")
        self.project = None
        self.chat = None
        console.print(
            f"[dim]Left[/dim] [bold]{name}[/bold][dim]. "
            "Use [bold cyan]/chats[/bold cyan] or [bold cyan]/new[/bold cyan] to start another.[/dim]"
        )

    def _cmd_chats(self) -> None:
        with console.status("[dim]Loading chats…[/dim]"):
            projects = projects_client.list_projects(self.user_id, limit=50)

        if not projects:
            console.print("[yellow]No chats found.[/yellow]")
            return

        # Sort by most recently updated
        projects.sort(
            key=lambda p: p.get("updated_at") or p.get("created_at") or "",
            reverse=True,
        )

        chosen = _chat_picker(projects)
        if not chosen:
            console.print("[dim]Cancelled.[/dim]")
            return

        project_id = chosen["id"]
        with console.status("[dim]Loading…[/dim]"):
            chat = projects_client.get_or_create_chat(self.user_id, project_id)

        self.project = chosen
        self.chat = chat

        # Show full history
        with console.status("[dim]Loading history…[/dim]"):
            msgs = messages_client.list_messages(self.user_id, project_id, chat["id"])

        if msgs:
            console.print()
            for msg in msgs:
                render_message(msg)
            console.print()
        else:
            console.print(
                f"\n[green]Entered:[/green] [bold]{chosen.get('name')}[/bold]  "
                "[dim]No messages yet. Start typing.[/dim]\n"
            )

    def _cmd_history(self) -> None:
        with console.status("[dim]Loading messages…[/dim]"):
            msgs = messages_client.list_messages(self.user_id, self.project["id"], self.chat["id"])
        if not msgs:
            console.print("[dim]No messages yet.[/dim]")
            return
        for msg in msgs:
            render_message(msg)

    # ------------------------------------------------------------------
    # ── Analysis ──────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_analysis(self, args: list[str]) -> None:
        sub = args[0].lower() if args else ""
        rest = args[1:]

        if sub == "upload":
            self._require_auth()
            if not rest:
                console.print("[red]Usage: /analysis upload <file>[/red]")
                return
            file_path = Path(rest[0]).expanduser()
            if not file_path.exists():
                console.print(f"[red]File not found: {rest[0]}[/red]")
                return
            with console.status(f"[dim]Uploading [cyan]{file_path.name}[/cyan]…[/dim]"):
                result = analysis_client.upload_file(self.user_id, file_path)
            aid = result.get("id", "")
            console.print(
                f"[green]Uploaded.[/green] Analysis ID: [cyan]{aid}[/cyan]\n"
                f"[dim]Use [bold]/analysis show {aid}[/bold] to check results.[/dim]"
            )

        elif sub == "show":
            if not rest:
                console.print("[red]Usage: /analysis show <id>[/red]")
                return
            # Try private first (if logged in), then public
            analysis = None
            if self.user_id:
                try:
                    analysis = analysis_client.get_analysis(rest[0])
                except OmniaAPIError as exc:
                    if exc.status_code not in (401, 403):
                        raise
            if analysis is None:
                # Fallback to public endpoint
                analysis = public_client.get_public_analysis(rest[0])
            _print_analysis_detail(analysis)

        else:
            # List: requires auth
            self._require_auth()
            with console.status("[dim]Loading…[/dim]"):
                analyses = analysis_client.list_analyses(self.user_id)
            if analyses:
                console.print(analyses_table(analyses))
            else:
                console.print("[yellow]No analyses yet.[/yellow]")

    # ------------------------------------------------------------------
    # ── Templates ─────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_templates(self, args: list[str]) -> None:
        sub = args[0].lower() if args else ""
        rest = args[1:]

        if sub == "show":
            if not rest:
                console.print("[red]Usage: /template show <id>[/red]")
                return
            tmpl = templates_client.get_template(self.user_id, rest[0])
            _print_template_detail(tmpl)

        elif sub == "fork":
            if not rest:
                console.print("[red]Usage: /template fork <id>[/red]")
                return
            result = templates_client.fork_template(self.user_id, rest[0])
            console.print(f"[green]Forked.[/green] New ID: [cyan]{result.get('id')}[/cyan]")

        else:
            with console.status("[dim]Loading…[/dim]"):
                tmpls = templates_client.list_templates(self.user_id)
            if tmpls:
                console.print(templates_table(tmpls))
            else:
                console.print("[yellow]No templates found.[/yellow]")

    # ------------------------------------------------------------------
    # ── Resources ─────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_resources(self) -> None:
        resources = resources_client.list_resources(self.user_id, self.project["id"])
        if resources:
            console.print(resources_table(resources))
        else:
            console.print("[dim]No resources in this chat.[/dim]")

    def _cmd_upload(self, args: list[str]) -> None:
        if not args:
            console.print("[red]Usage: /upload <file>[/red]")
            return
        file_path = Path(args[0]).expanduser()
        if not file_path.exists():
            console.print(f"[red]File not found: {args[0]}[/red]")
            return
        with console.status(f"[dim]Uploading [cyan]{file_path.name}[/cyan]…[/dim]"):
            resource = resources_client.upload_resource(self.user_id, self.project["id"], file_path)
        console.print(f"[green]Uploaded.[/green] Resource ID: [cyan]{resource.get('id')}[/cyan]")

    # ------------------------------------------------------------------
    # ── Model / provider / config ─────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_model(self, args: list[str]) -> None:
        if args:
            # Direct set: /model <name>
            self.model = args[0]
            console.print(f"[green]Model:[/green] [bold]{self.model}[/bold]")
            return

        models = _models_from_settings(self.user_settings)
        if not models:
            console.print(
                "[yellow]No models available.[/yellow]  "
                "Make sure you are logged in and have at least one provider configured."
            )
            return

        selected = _model_picker(models, self.model)
        if selected:
            self.model = selected["model"]
            self.provider = selected["provider"]
            console.print(
                f"[green]✓ Model:[/green] [bold]{selected['label']}[/bold]  "
                f"[dim]({selected['provider']})[/dim]"
            )
        else:
            console.print(f"[dim]Cancelled — model unchanged:[/dim] [bold]{self.model}[/bold]")

    def _cmd_config(self, args: list[str]) -> None:
        if args and args[0].lower() == "set":
            rest = args[1:]
            if len(rest) < 2:
                console.print("[red]Usage: /config set <key> <value>[/red]")
                return
            try:
                settings.set(rest[0], rest[1])
                settings.save()
                console.print(f"[green]Set[/green] {rest[0]} = {rest[1]!r}")
            except KeyError as exc:
                console.print(f"[bold red]Error:[/bold red] {exc}")
        else:
            t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            t.add_column("Key")
            t.add_column("Value")
            for k, v in settings.as_dict().items():
                display = "***" if k == "api_key" and v else str(v)
                t.add_row(f"[cyan]{k}[/cyan]", display)
            console.print(t)

    # ------------------------------------------------------------------
    # ── Message sending ───────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _send_message(self, text: str) -> None:
        if not self.user_info:
            console.print("[yellow]Not logged in.[/yellow]  Run [cyan]/login[/cyan] first.")
            return
        if not self.project or not self.chat:
            console.print(
                "[yellow]No active chat.[/yellow]  "
                "Run [cyan]/chats[/cyan] or [cyan]/new <name>[/cyan] to start one."
            )
            return

        console.print(f"\n[bold green]You[/bold green]  {text}")
        try:
            events = messages_client.stream_message(
                self.user_id,
                self.project["id"],
                self.chat["id"],
                text,
                model=self.model,
                provider=self.provider,
                user_settings=self.user_settings,
            )
            run_stream(events)
        except OmniaAPIError as exc:
            console.print(f"[bold red]API error {exc.status_code}:[/bold red] {exc.detail}")

    # ------------------------------------------------------------------
    # ── Guards ────────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if not self.user_info:
            raise NotConfiguredError("This command requires login. Run [cyan]/login[/cyan] first.")

    def _require_chat(self) -> None:
        if not self.project or not self.chat:
            raise NotConfiguredError(
                "No active chat. Run [cyan]/chat[/cyan] or [cyan]/new <name>[/cyan] first."
            )


# ---------------------------------------------------------------------------
# Rich renderers for public data
# ---------------------------------------------------------------------------


def _print_market_results(data: dict) -> None:
    items = data.get("results", data.get("packages", []))
    if not items:
        console.print("[yellow]No results.[/yellow]")
        return
    t = Table(title="Market Intelligence", show_lines=False, highlight=True)
    t.add_column("Market", style="dim")
    t.add_column("ID", style="cyan")
    t.add_column("Name / Version", style="bold white")
    t.add_column("Latest analysis", style="dim")
    for item in items:
        pkg = item.get("package", item)
        analysis = item.get("latest_analysis", {}) or {}
        verdict = (analysis.get("verdict") or "").lower()
        _VERDICT_COLOR = {"malicious": "red", "risky": "yellow", "undetected": "green"}
        color = _VERDICT_COLOR.get(verdict, "dim")
        verdict_str = f"[{color}]{verdict}[/{color}]" if verdict else "[dim]-[/dim]"
        t.add_row(
            pkg.get("market", ""),
            pkg.get("market_id", ""),
            f"{pkg.get('name', '')}  [dim]{pkg.get('version', '')}[/dim]",
            verdict_str,
        )
    console.print(t)


def _print_market_package(data: dict) -> None:
    pkg = data.get("package", data)
    analysis = data.get("latest_analysis", {}) or {}
    t = Table(show_header=False, box=None, padding=(0, 2))
    for k, v in [
        ("Market", pkg.get("market", "")),
        ("ID", pkg.get("market_id", "")),
        ("Name", pkg.get("name", "")),
        ("Version", pkg.get("version", "")),
        ("Author", pkg.get("author", "")),
        ("Description", (pkg.get("description") or "")[:120]),
    ]:
        if v:
            t.add_row(f"[dim]{k}[/dim]", str(v))
    if analysis:
        verdict = (analysis.get("verdict") or "").lower()
        _VERDICT_COLOR = {"malicious": "red", "risky": "yellow", "undetected": "green"}
        color = _VERDICT_COLOR.get(verdict, "white")
        t.add_row(
            "[dim]Latest verdict[/dim]",
            f"[bold {color}]{verdict.upper()}[/bold {color}]"
            f"  risk {analysis.get('risk_score', '-')}/10",
        )
    console.print(Panel(t, title=f"[bold]{pkg.get('name', 'Package')}[/bold]", expand=False))


def _print_market_versions(data: dict) -> None:
    versions = data.get("versions", [])
    if not versions:
        console.print("[yellow]No versions found.[/yellow]")
        return
    t = Table(title="Versions", show_lines=False)
    t.add_column("Version", style="cyan")
    t.add_column("Published", style="dim")
    for v in versions:
        t.add_row(
            str(v.get("version", v) if isinstance(v, dict) else v),
            str(v.get("published_at", "") if isinstance(v, dict) else ""),
        )
    console.print(t)


def _print_shared_chat(data: dict) -> None:
    project = data.get("project", {})
    messages = data.get("chat_messages", [])
    console.print(
        Panel(
            f"[bold white]{project.get('name', 'Shared Chat')}[/bold white]\n"
            f"[dim]{len(messages)} messages[/dim]",
            title="[bold]Shared Chat[/bold]",
            border_style="cyan",
            expand=False,
        )
    )
    for msg in messages:
        render_message(msg)


def _print_analysis_detail(analysis: dict) -> None:
    verdict = (analysis.get("verdict") or "pending").lower()
    color = _VERDICT_COLOR.get(verdict, "white")
    body = Text()
    body.append("File:        ", style="dim")
    body.append(f"{analysis.get('filename', '')}\n")
    body.append("Status:      ", style="dim")
    body.append(f"{analysis.get('status', '')}\n")
    body.append("Verdict:     ", style="dim")
    body.append(f"{verdict.upper()}", style=f"bold {color}")
    body.append("\nRisk score:  ", style="dim")
    body.append(f"{analysis.get('risk_score', '-')}/10\n")
    summary = analysis.get("summary") or analysis.get("overview", "")
    if summary:
        body.append(f"\n{summary}")
    for ar in analysis.get("analyzer_results", []):
        body.append(f"\n  • {ar.get('name')}: {ar.get('status')}", style="dim")
    console.print(
        Panel(
            body,
            title=f"[bold]Analysis {analysis.get('id', '')}[/bold]",
            border_style=color,
            expand=False,
        )
    )


def _print_template_detail(tmpl: dict) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    for k, v in [
        ("ID", tmpl.get("id", "")),
        ("Name", tmpl.get("name", "")),
        ("Type", tmpl.get("template_type", "")),
        ("Status", tmpl.get("status", "")),
        ("Level", tmpl.get("confidence_level", "")),
        ("Description", tmpl.get("description", "")),
    ]:
        if v:
            t.add_row(f"[dim]{k}[/dim]", str(v))
    console.print(Panel(t, title=f"[bold]{tmpl.get('name', '')}[/bold]", expand=False))


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _flag(args: list[str], flag: str) -> Optional[str]:
    try:
        idx = args.index(flag)
        return args[idx + 1]
    except (ValueError, IndexError):
        return None


def _prompt_default(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_secret(label: str) -> str:
    import getpass

    return getpass.getpass(f"{label}: ")
