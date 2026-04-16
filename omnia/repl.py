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
  /login                            Authenticate (browser or API Key)
  /logout                           Clear credentials
  /me                               Show current user

  /new <name>                       Create a new chat
  /chats  /resume                   Pick a recent chat with arrow keys and enter it
  /delete                           Delete the current chat
  /leave  /back                     Leave the current chat (keeps CLI open)
  /history                          Show this chat's message history

  /agent                            Attach an agent recipe to next messages (@chip)
  /knowledge                        Attach a knowledge base to next messages (#chip)
  /skill                            Attach a skill to next messages (/chip)
  /prompt                           Browse prompts and insert one into the conversation
  /workflow                         Launch a workflow (with variable prompting)

  /analysis                         List your file analyses
  /analysis upload <file>           Upload a file for analysis
  /analysis show <id>               Show analysis detail (public or private)

  /templates                        List available templates
  /template show <id>               Show template detail
  /template fork <id>               Fork a template to your account

  /resources                        List resources in current chat
  /analyze <file>                   Upload a file as a resource

  /newprovider                      Configure API key for a provider (shows configured/pending)
  /model [name]                     Show / change LLM model

  /config                           Show current configuration


  /help                             Show this help
  /clear                            Clear the screen
  /exit                             Quit

Any plain text (no leading /) is sent as a message to the current chat.
"""

from __future__ import annotations

import copy
import getpass
import os
import select
import shlex
import socket
import sys
import termios
import tty
import webbrowser
from datetime import datetime
from pathlib import Path

from omnia_sdk import NotConfiguredError, OmniaAPIError, OmniaClient
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, PathCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from omnia.config.settings import CONFIG_DIR, settings
from omnia.ui.messages import render_message
from omnia.ui.stream import run_stream
from omnia.ui.tables import (
    analyses_table,
    resources_table,
    templates_table,
)

console = Console()


def _client() -> OmniaClient:
    """Return an OmniaClient configured from the current CLI settings."""
    return OmniaClient(
        api_key=settings.api_key,
        api_url=settings.api_url,
        default_model=settings.default_model,
        default_provider=settings.default_provider,
    )


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
    "/agent",
    "/knowledge",
    "/skill",
    "/prompt",
    "/workflow",
    "/analysis",
    "/analysis upload",
    "/analysis show",
    "/templates",
    "/template show",
    "/template fork",
    "/resources",
    "/analyze",
    "/newprovider",
    "/model",
    "/config",
    "/help",
    "/clear",
    "/exit",
]

_PT_STYLE = Style.from_dict({"prompt": "ansicyan bold"})

_PATH_COMMANDS = {"/analysis upload", "/analyze"}


class _OmniaCompleter(Completer):
    """Command completer with path completion for file arguments."""

    def __init__(self) -> None:
        self._word = WordCompleter(_COMPLETIONS, sentence=True)
        self._path = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        for cmd in _PATH_COMMANDS:
            prefix = cmd + " "
            if text.startswith(prefix):
                path_doc = document.text_before_cursor[len(prefix) :]
                from prompt_toolkit.document import Document

                yield from self._path.get_completions(
                    Document(path_doc, len(path_doc)), complete_event
                )
                return
        yield from self._word.get_completions(document, complete_event)


_VERDICT_COLOR: dict[str, str] = {"malicious": "red", "risky": "yellow", "undetected": "green"}

_TEMPLATE_LABELS: dict[str, tuple[str, str]] = {
    "AGENT_RECIPE": ("agent", "@"),
    "KNOWLEDGE": ("knowledge", "#"),
    "SKILL": ("skill", "/"),
    "PROMPT": ("prompt", "?"),
}

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


def _login_method_picker() -> str | None:
    """
    Two-option picker for login method.
    Returns 'web', 'apikey', or None if cancelled (Esc / Ctrl-C / q).
    """
    options = [
        ("web", "Login with Web Browser  [recommended]"),
        ("apikey", "Login with API Key"),
    ]
    cur = 0

    def _render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{len(options)}A")
        for i, (_, label) in enumerate(options):
            if i == cur:
                sys.stdout.write(f"\x1b[2K\r\x1b[1;36m❯ {label}\x1b[0m\n")
            else:
                sys.stdout.write(f"\x1b[2K\r  {label}\n")
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
                return options[cur][0]
            elif ch == b"\x1b":
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    return None  # lone Escape → cancel
                rest = os.read(fd, 2)
                if rest == b"[A":  # ↑
                    cur = (cur - 1) % len(options)
                    _render()
                elif rest == b"[B":  # ↓
                    cur = (cur + 1) % len(options)
                    _render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Template variable helpers
# ---------------------------------------------------------------------------


def _trunc(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _chip(s: str, n: int = 12) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _collect_vars(template: dict) -> dict | None:
    """
    Prompt the user to fill in each extracted_param of a template.
    Returns a {name: value} dict, or None if the user cancelled.
    """
    params = template.get("extracted_params") or []
    if not params:
        return {}

    console.print(f"\n[dim]This template has [bold]{len(params)}[/bold] variable(s):[/dim]")
    written: dict = {}
    for p in params:
        name = p.get("name", "")
        desc = p.get("description", "")
        default = p.get("value") or ""
        hint = f" [dim]({desc})[/dim]" if desc else ""
        prompt_str = f"  [cyan]{name}[/cyan]{hint}"
        if default:
            prompt_str += f" [dim](default: {default})[/dim]"
        prompt_str += ": "
        value = Prompt.ask(prompt_str, default=default or "").strip()
        if value == "" and not default:
            console.print("[dim]Cancelled.[/dim]")
            return None
        written[name] = value or default
    return written


def _apply_template_vars(template: dict) -> str:
    """
    Collect variables for a PROMPT template and return the substituted text.
    Shows a Prompt.ask for each variable. Returns "" on cancel.
    """
    text: str = template.get("prompt") or template.get("description") or ""
    if not text:
        return ""

    written = _collect_vars(template)
    if written is None:
        return ""

    for name, value in written.items():
        text = text.replace(f"${{{{{name}}}}}", value)
    return text


class OmniaREPL:
    def __init__(self) -> None:
        self.user_info: dict | None = None
        self.project: dict | None = None
        self.chat: dict | None = None
        self.model: str = settings.default_model
        self.provider: str = settings.default_provider
        self.user_settings: dict = {}
        # Active message "chips"
        self.selected_agent: dict | None = None  # AGENT_RECIPE template
        self.selected_knowledge: dict | None = None  # KNOWLEDGE template
        self.selected_skill: dict | None = None  # SKILL template
        self._pending_input: str = ""  # pre-filled text for next prompt

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Custom Ctrl+C binding: always raise KeyboardInterrupt immediately,
        # even if the buffer has text (prompt_toolkit default clears buffer first).
        _kb = KeyBindings()

        @_kb.add("c-c", eager=True)
        def _ctrl_c(event):
            event.app.exit(exception=KeyboardInterrupt())

        self._session: PromptSession = PromptSession(
            history=FileHistory(str(CONFIG_DIR / "history")),
            auto_suggest=AutoSuggestFromHistory(),
            completer=_OmniaCompleter(),
            style=_PT_STYLE,
            complete_while_typing=False,
            key_bindings=_kb,
        )

    # ------------------------------------------------------------------
    # Properties / helpers
    # ------------------------------------------------------------------

    @property
    def user_id(self) -> str | None:
        if not self.user_info:
            return None
        return self.user_info.get("user_id") or self.user_info.get("id")

    def _prompt_text(self) -> str:
        if self.project:
            chips = []
            if self.selected_agent:
                chips.append(f"@{_chip(self.selected_agent['title'])}")
            if self.selected_knowledge:
                chips.append(f"#{_chip(self.selected_knowledge['title'])}")
            if self.selected_skill:
                chips.append(f"/{_chip(self.selected_skill['title'])}")
            chip_str = "".join(f"[{c}]" for c in chips)
            if self.chat:
                return f"Chat {chip_str}>> "
            return f"{chip_str}>> " if chip_str else ">> "
        elif self.user_info:
            label = self.user_info.get("email", "omnia").split("@")[0]
        else:
            label = "omnia"
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
                pending, self._pending_input = self._pending_input, ""
                raw = self._session.prompt(self._prompt_text(), default=pending).strip()
            except KeyboardInterrupt:
                if self.project:
                    console.print()
                    self._cmd_leave()
                    continue
                console.print("\n[dim]Goodbye.[/dim]")
                break
            except EOFError:
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
                console.clear()
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
            elif cmd == "/agent":
                self._require_auth()
                self._cmd_pick_template("AGENT_RECIPE")
            elif cmd == "/knowledge":
                self._require_auth()
                self._cmd_pick_template("KNOWLEDGE")
            elif cmd == "/skill":
                self._require_auth()
                self._cmd_pick_template("SKILL")
            elif cmd == "/prompt":
                self._require_auth()
                self._cmd_pick_template("PROMPT")
            elif cmd == "/workflow":
                self._require_auth()
                self._require_chat()
                self._cmd_workflow()
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
            elif cmd == "/analyze":
                self._require_auth()
                self._cmd_upload(args)
            elif cmd == "/newprovider":
                self._require_auth()
                self._cmd_newprovider()
            elif cmd == "/model":
                self._cmd_model(args)
            elif cmd == "/config":
                self._cmd_config(args)
            else:
                console.print(f"[red]Unknown command:[/red] {cmd}  (type [cyan]/help[/cyan])")
        except NotConfiguredError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
        except OmniaAPIError as exc:
            if exc.status_code == 401:
                settings.api_key = ""
                settings.save()
                self.user_info = None
                console.print(
                    "\n[bold red]Session expired.[/bold red] "
                    "Your API key is no longer valid (it may have been deleted).\n"
                    "Run [bold cyan]/login[/bold cyan] to authenticate again."
                )
            else:
                console.print(f"[bold red]API error {exc.status_code}:[/bold red] {exc.detail}")
        except Exception as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")

        return False

    # ------------------------------------------------------------------
    # ── PUBLIC commands (no login needed) ────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_version(self) -> None:
        data = _client().public.get_api_version()
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
            console.print()
            with console.status(f"[dim]Searching for [cyan]{query}[/cyan]…[/dim]"):
                data = _client().public.search_market(query)
            _print_market_results(data)

        elif sub == "show":
            if len(rest) < 2:
                console.print("[red]Usage: /market show <market> <id>[/red]")
                return
            market, mid = rest[0], rest[1]
            version = rest[2] if len(rest) > 2 else ""
            console.print()
            with console.status("[dim]Loading…[/dim]"):
                data = _client().public.get_market_package(market, mid, version)
            _print_market_package(data)

        elif sub == "versions":
            if len(rest) < 2:
                console.print("[red]Usage: /market versions <market> <id>[/red]")
                return
            market, mid = rest[0], rest[1]
            console.print()
            with console.status("[dim]Loading versions…[/dim]"):
                data = _client().public.get_market_package_versions(market, mid)
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
        console.print()
        with console.status("[dim]Loading shared chat…[/dim]"):
            data = _client().public.get_shared_chat(token)
        _print_shared_chat(data)

    # ------------------------------------------------------------------
    # ── AUTH commands ─────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _try_auto_login(self) -> None:
        try:
            self.user_info = _client().auth.get_me().model_dump(mode="json")
            email = self.user_info.get("email", "unknown")
            try:
                self.user_settings = _client().auth.get_last_user_settings(self.user_id)
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
        if key:
            # Programmatic / scripted login — skip picker
            self._do_key_login(key)
            return

        console.print("[dim]Select login method:[/dim]")
        method = _login_method_picker()
        if method is None:
            console.print("[dim]Cancelled.[/dim]")
            return

        if method == "web":
            self._cmd_login_web()
        else:
            self._do_key_login(None)

    def _do_key_login(self, key: str | None) -> None:
        """Authenticate with an API Key."""
        if not key:
            key = _prompt_secret("API Key")

        settings.api_key = key

        console.print()
        with console.status("[dim]Verifying credentials…[/dim]"):
            self.user_info = _client().auth.get_me().model_dump(mode="json")

        try:
            self.user_settings = _client().auth.get_last_user_settings(self.user_id)
        except Exception:
            self.user_settings = {}
        settings.save()

        console.print(
            Panel(
                f"[bold green]Authenticated[/bold green] as "
                f"[cyan]{self.user_info.get('email')}[/cyan]\n"
                f"[dim]User ID:[/dim] {self.user_id}\n"
                f"[dim]Roles:[/dim]   {', '.join(self.user_info.get('roles', []))}",
                title="Login successful",
                border_style="green",
                expand=False,
            )
        )

    def _cmd_login_web(self) -> None:
        """Authenticate via browser — opens /cli-auth, user copies the generated key."""
        hostname = socket.gethostname()
        auth_url = f"{settings.frontend_url}/cli-auth?hostname={hostname}"

        console.print(
            Panel(
                f"[dim]Your browser will open automatically.[/dim]\n"
                f"[dim]If it doesn't, copy and paste this URL:[/dim]\n\n"
                f"  [cyan]{auth_url}[/cyan]\n\n"
                f"[dim]Device:[/dim] [bold]{hostname}[/bold]\n"
                f"[dim]Sign in and copy the CLI key shown in the browser.[/dim]",
                title="Web Authentication",
                border_style="cyan",
                expand=False,
            )
        )

        webbrowser.open(auth_url)

        try:
            key = _prompt_secret("Paste your CLI key here")
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
            return

        if not key:
            console.print("[dim]Cancelled.[/dim]")
            return

        settings.api_key = key.strip()

        console.print()
        with console.status("[dim]Verifying credentials…[/dim]"):
            self.user_info = _client().auth.get_me().model_dump(mode="json")

        try:
            self.user_settings = _client().auth.get_last_user_settings(self.user_id)
        except Exception:
            self.user_settings = {}
        settings.save()

        console.print(
            Panel(
                f"[bold green]Authenticated[/bold green] as "
                f"[cyan]{self.user_info.get('email')}[/cyan]\n"
                f"[dim]User ID:[/dim] {self.user_id}\n"
                f"[dim]Roles:[/dim]   {', '.join(self.user_info.get('roles', []))}",
                title="Login successful",
                border_style="green",
                expand=False,
            )
        )

    def _cmd_logout(self) -> None:
        settings.api_key = ""
        settings.save()
        self.user_info = None
        self.project = None
        self.chat = None
        console.print("[green]Logged out.[/green]")

    def _cmd_me(self) -> None:
        # Refresh from API to get latest state
        self.user_info = _client().auth.get_me().model_dump(mode="json")
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_row("[dim]User ID[/dim]", self.user_id or "")
        t.add_row("[dim]Email[/dim]", self.user_info.get("email", ""))
        t.add_row("[dim]Auth type[/dim]", self.user_info.get("auth_type", ""))
        t.add_row("[dim]Roles[/dim]", ", ".join(self.user_info.get("roles", [])))
        t.add_row("[dim]Groups[/dim]", ", ".join(self.user_info.get("groups", [])))
        console.print(Panel(t, title="[bold]Current user[/bold]", expand=False))

    # ------------------------------------------------------------------
    # ── Projects / chats ──────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_new(self, args: list[str]) -> None:
        name = " ".join(args) if args else "New Chat"
        console.print()
        with console.status("[dim]Creating chat…[/dim]"):
            p, c = _client().projects.create_project_with_chat(self.user_id, name)
        self.project = p.model_dump(mode="json")
        self.chat = c.model_dump(mode="json")
        console.print(
            "[green]New chat ready.[/green]  [dim]Start typing — it will be named automatically.[/dim]"
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
        _client().projects.delete_project(self.user_id, pid)
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
        console.print()
        with console.status("[dim]Loading chats…[/dim]"):
            projects = [
                p.model_dump(mode="json")
                for p in _client().projects.list_projects(self.user_id, limit=50)
            ]

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
        console.print()
        with console.status("[dim]Loading…[/dim]"):
            chat = (
                _client()
                .projects.get_or_create_chat(self.user_id, project_id)
                .model_dump(mode="json")
            )

        self.project = chosen
        self.chat = chat

        # Show full history
        console.print()
        with console.status("[dim]Loading history…[/dim]"):
            msgs = [
                m.model_dump(mode="json")
                for m in _client().messages.list_messages(self.user_id, project_id, chat["id"])
            ]

        if msgs:
            console.print()
            for msg in msgs:
                render_message(msg, model=self.model)
            console.print()
        else:
            console.print(
                f"\n[green]Entered:[/green] [bold]{chosen.get('name')}[/bold]  "
                "[dim]No messages yet. Start typing.[/dim]\n"
            )

    def _cmd_workflow(self) -> None:
        console.print()
        with console.status("[dim]Loading workflows…[/dim]"):
            all_templates = [
                t.model_dump(mode="json") for t in _client().templates.list_templates(self.user_id)
            ]

        workflows = [
            t
            for t in all_templates
            if t.get("template_type") == "AGENT_WORKFLOW"
            and t.get("status") in ("ENABLED", "PRODUCTION", None, "")
        ]
        if not workflows:
            console.print("[yellow]No workflows available.[/yellow]")
            return

        items = [{"name": _trunc(t.get("title", t.get("id", ""))), "_t": t} for t in workflows]
        console.print("[dim]Select workflow:[/dim]")
        chosen = _chat_picker(items, window=min(8, len(items)))
        if not chosen:
            console.print("[dim]Cancelled.[/dim]")
            return

        t = chosen["_t"]

        # Fetch full template detail — the list endpoint may omit extracted_params
        console.print()
        with console.status("[dim]Loading workflow…[/dim]"):
            t = _client().templates.get_template(self.user_id, t["id"]).model_dump(mode="json")

        written_params = _collect_vars(t)
        if written_params is None:
            return  # user cancelled during var collection

        # Resolve the agent endpoint (mirrors frontend selectedAgentFromSettings)
        agents = _client().auth.get_agents()
        agent = next(
            (a for a in agents if a.get("default_workflow_endpoint") and a.get("can_chat")),
            agents[0] if agents else None,
        )
        if not agent:
            console.print("[red]No agent available to run workflows.[/red]")
            return

        console.print(f"[dim]Launching[/dim] [bold]{t.get('title')}[/bold][dim]…[/dim]")
        try:
            console.print()
            with console.status("[dim]Launching…[/dim]"):
                _client().messages.launch_workflow(
                    agent_name=agent["name"],
                    workflow_endpoint=agent["default_workflow_endpoint"],
                    user_id=self.user_id,
                    project_id=self.project["id"],
                    chat_id=self.chat["id"],
                    workflow_template_id=t["id"],
                    written_params=written_params,
                    model=self.model,
                    provider=self.provider,
                    user_settings=self.user_settings,
                )
            console.print(
                "[green]Workflow launched.[/green]  "
                "[dim]Use [bold cyan]/history[/bold cyan] to check results as they arrive.[/dim]"
            )
        except OmniaAPIError as exc:
            console.print(f"[bold red]API error {exc.status_code}:[/bold red] {exc.detail}")

    def _cmd_pick_template(self, template_type: str) -> None:
        label, sigil = _TEMPLATE_LABELS.get(template_type, (template_type.lower(), ""))

        console.print()
        with console.status(f"[dim]Loading {label}s…[/dim]"):
            all_templates = [
                t.model_dump(mode="json") for t in _client().templates.list_templates(self.user_id)
            ]

        templates = [
            t
            for t in all_templates
            if t.get("template_type") == template_type
            and t.get("status") in ("ENABLED", "PRODUCTION", None, "")
        ]

        if not templates:
            console.print(f"[yellow]No {label}s available.[/yellow]")
            return

        # Build picker items: first entry clears the current selection
        _CURRENT = {
            "AGENT_RECIPE": self.selected_agent,
            "KNOWLEDGE": self.selected_knowledge,
            "SKILL": self.selected_skill,
            "PROMPT": None,
        }
        current = _CURRENT.get(template_type)

        items = [{"name": "─ none ─", "_t": None}]

        for t in templates:
            title = _trunc(t.get("title", t.get("id", "")))
            active = current and current.get("id") == t.get("id")
            marker = "✓ " if active else "  "
            items.append({"name": f"{marker}{sigil}{title}", "_t": t})

        console.print(f"[dim]Select {label} (none to clear):[/dim]")
        chosen = _chat_picker(items, window=min(8, len(items)))
        if chosen is None:
            console.print("[dim]Cancelled.[/dim]")
            return

        t = chosen["_t"]

        if template_type == "AGENT_RECIPE":
            self.selected_agent = t
        elif template_type == "KNOWLEDGE":
            self.selected_knowledge = t
        elif template_type == "SKILL":
            self.selected_skill = t
        elif template_type == "PROMPT":
            if t:
                # Fetch full detail so we have `prompt` text + `extracted_params`
                console.print()
                with console.status("[dim]Loading prompt…[/dim]"):
                    full = (
                        _client()
                        .templates.get_template(self.user_id, t["id"])
                        .model_dump(mode="json")
                    )
                self._pending_input = _apply_template_vars(full)
                if self._pending_input:
                    console.print(
                        "[dim]Prompt ready — edit if needed and press Enter to send.[/dim]"
                    )
            return

        if t:
            console.print(
                f"[green]✓ {label.capitalize()} attached:[/green] [bold]{t.get('title')}[/bold]"
            )
        else:
            console.print(f"[dim]{label.capitalize()} cleared.[/dim]")

    def _cmd_history(self) -> None:
        console.print()
        with console.status("[dim]Loading messages…[/dim]"):
            msgs = [
                m.model_dump(mode="json")
                for m in _client().messages.list_messages(
                    self.user_id, self.project["id"], self.chat["id"]
                )
            ]
        if not msgs:
            console.print("[dim]No messages yet.[/dim]")
            return
        for msg in msgs:
            render_message(msg, model=self.model)

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
            console.print()
            with console.status(f"[dim]Uploading [cyan]{file_path.name}[/cyan]…[/dim]"):
                result = (
                    _client().analysis.upload_file(self.user_id, file_path).model_dump(mode="json")
                )
            aid = result.get("analysis_id") or result.get("id", "")
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
                    analysis = _client().analysis.get_analysis(rest[0]).model_dump(mode="json")
                except OmniaAPIError as exc:
                    if exc.status_code not in (401, 403):
                        raise
            if analysis is None:
                # Fallback to public endpoint
                analysis = _client().public.get_public_analysis(rest[0])
            _print_analysis_detail(analysis)

        else:
            # List: requires auth
            self._require_auth()
            console.print()
            with console.status("[dim]Loading…[/dim]"):
                analyses = [
                    a.model_dump(mode="json")
                    for a in _client().analysis.list_analyses(self.user_id)
                ]
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
            tmpl = _client().templates.get_template(self.user_id, rest[0]).model_dump(mode="json")
            _print_template_detail(tmpl)

        elif sub == "fork":
            if not rest:
                console.print("[red]Usage: /template fork <id>[/red]")
                return
            result = (
                _client().templates.fork_template(self.user_id, rest[0]).model_dump(mode="json")
            )
            console.print(f"[green]Forked.[/green] New ID: [cyan]{result.get('id')}[/cyan]")

        else:
            console.print()
            with console.status("[dim]Loading…[/dim]"):
                tmpls = [
                    t.model_dump(mode="json")
                    for t in _client().templates.list_templates(self.user_id)
                ]
            if tmpls:
                console.print(templates_table(tmpls))
            else:
                console.print("[yellow]No templates found.[/yellow]")

    # ------------------------------------------------------------------
    # ── Resources ─────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_resources(self) -> None:
        resources = [
            r.model_dump(mode="json")
            for r in _client().resources.list_resources(self.user_id, self.project["id"])
        ]
        if resources:
            console.print(resources_table(resources))
        else:
            console.print("[dim]No resources in this chat.[/dim]")

    def _cmd_upload(self, args: list[str]) -> None:
        if not args:
            console.print("[red]Usage: /analyze <file>[/red]")
            return
        file_path = Path(args[0]).expanduser()
        if not file_path.exists():
            console.print(f"[red]File not found: {args[0]}[/red]")
            return

        if not self.project:
            # No active chat — fall back to standalone analysis upload
            console.print()
            with console.status(
                f"[dim]Uploading [cyan]{file_path.name}[/cyan] for analysis…[/dim]"
            ):
                result = (
                    _client().analysis.upload_file(self.user_id, file_path).model_dump(mode="json")
                )
            aid = result.get("analysis_id") or result.get("id", "")
            console.print(
                f"[green]Uploaded.[/green] Analysis ID: [cyan]{aid}[/cyan]\n"
                f"[dim]Use [bold]/analysis show {aid}[/bold] to check results.[/dim]"
            )
            return

        # In a chat: upload resource then run the FileAnalysisWorkflow
        console.print()
        with console.status(f"[dim]Uploading [cyan]{file_path.name}[/cyan]…[/dim]"):
            resource = (
                _client()
                .resources.upload_resource(self.user_id, self.project["id"], file_path)
                .model_dump(mode="json")
            )
        global_file_id = resource.get("global_file_id", "")
        chat_id = self.chat["id"] if self.chat else ""
        console.print()
        with console.status("[dim]Running analysis…[/dim]"):
            result = _client().workflows.run_file_analysis(
                self.user_id, self.project["id"], global_file_id, chat_id
            )
        aid = result.get("analysis_id", "")
        file_hash = result.get("file_hash", "")
        console.print(
            f"[green]Analysis started.[/green] ID: [cyan]{aid}[/cyan]"
            + (f"  Hash: [dim]{file_hash[:16]}…[/dim]" if file_hash else "")
            + f"\n[dim]Use [bold]/analysis show {aid}[/bold] to check results.[/dim]"
        )

    # ------------------------------------------------------------------
    # ── Model / provider / config ─────────────────────────────────────
    # ------------------------------------------------------------------

    def _cmd_newprovider(self) -> None:
        console.print(
            "\n[bold]Configure a model provider[/bold]\n"
            "[dim]Each provider (OpenAI, Anthropic, Google…) requires its own API key "
            "to unlock its models in Omnia.\n"
            "Select a provider below, paste your key, and it will be saved to your account.[/dim]\n"
        )

        providers = [
            p
            for p in self.user_settings.get("llm_providers", [])
            if p.get("internal_name") != "omnia"
        ]
        if not providers:
            console.print("[yellow]No providers available.[/yellow]")
            return

        def _has_key(p: dict) -> bool:
            return any(
                v.get("var_name") == "api_key" and v.get("var_value") for v in p.get("vars", [])
            )

        # Build picker items showing configured/pending status
        # Wrap as fake "project" dicts: name field drives _chat_picker label
        items = []
        for i, p in enumerate(providers):
            title = p.get("title", p["internal_name"])
            status = "\x1b[32m✓\x1b[0m" if _has_key(p) else "\x1b[2m○\x1b[0m"
            items.append({"name": f"{status}  {title}", "_idx": i})

        console.print("[dim]Select provider:[/dim]")
        chosen_item = _chat_picker(items, window=len(items))
        if not chosen_item:
            console.print("[dim]Cancelled.[/dim]")
            return

        provider = providers[chosen_item["_idx"]]

        # Show current key if any
        key_var = next(
            (v for v in provider.get("vars", []) if v.get("var_name") == "api_key"), None
        )
        current = (key_var or {}).get("var_value") or ""
        if current:
            masked = "*" * 8 + current[-4:]
            console.print(f"[dim]Current key:[/dim] [yellow]{masked}[/yellow]")
            console.print("[dim]Leave empty to clear the key, Ctrl-C to cancel.[/dim]")
            new_key = _prompt_secret("New API key (empty = clear)").strip()
        else:
            new_key = _prompt_secret("API key (Enter to cancel)").strip()
            if not new_key:
                console.print("[dim]Cancelled.[/dim]")
                return

        clearing = current and not new_key
        if clearing:
            confirm = _prompt_default("Remove API key? [y/N]", "n")
            if confirm.lower() not in ("y", "yes"):
                console.print("[dim]Cancelled.[/dim]")
                return

        # Deep-clone settings and update the matching provider's api_key var
        updated_settings = copy.deepcopy(self.user_settings)
        for p in updated_settings.get("llm_providers", []):
            if p.get("internal_name") == provider["internal_name"]:
                for v in p.get("vars", []):
                    if v.get("var_name") == "api_key":
                        v["var_value"] = new_key
                break

        console.print()
        with console.status("[dim]Saving…[/dim]"):
            self.user_settings = _client().auth.update_user_settings(self.user_id, updated_settings)

        provider_name = provider.get("title", provider["internal_name"])
        if clearing:
            console.print(f"[yellow]✓ API key removed[/yellow] for [bold]{provider_name}[/bold]")
        else:
            console.print(f"[green]✓ API key saved[/green] for [bold]{provider_name}[/bold]")

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
                "Use [bold cyan]/newprovider[/bold cyan] to add an API key for a provider."
            )
            return

        console.print(
            "[dim]Tip: use [bold cyan]/newprovider[/bold cyan] to add or update API keys for more providers.[/dim]"
        )
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
        import os

        def _row(t: Table, key: str, value: str) -> None:
            t.add_row(f"[dim]{key}[/dim]", value)

        # ── Connection ──────────────────────────────────────────────
        ct = Table(show_header=False, box=None, padding=(0, 2))
        ct.add_column(style="dim", no_wrap=True)
        ct.add_column()
        env_name = os.getenv("OMNIA_ENV", "dev")
        explicit_url = os.getenv("OMNIA_API_URL", "")
        url_source = (
            "[dim](OMNIA_API_URL)[/dim]" if explicit_url else f"[dim](OMNIA_ENV={env_name})[/dim]"
        )
        _row(ct, "api_url", f"[cyan]{settings.api_url}[/cyan]  {url_source}")
        if settings.is_configured():
            key_src = (
                "[dim](env)[/dim]" if os.getenv("OMNIA_API_TOKEN") else "[dim](config file)[/dim]"
            )
            _row(ct, "api_key", f"[green]set[/green]  {key_src}")
        else:
            _row(ct, "api_key", "[red]not set[/red]  — run [cyan]/login[/cyan]")
        console.print(Panel(ct, title="[bold]Connection[/bold]", expand=False))

        # ── Session ─────────────────────────────────────────────────
        st = Table(show_header=False, box=None, padding=(0, 2))
        st.add_column(style="dim", no_wrap=True)
        st.add_column()
        if self.user_info:
            email = self.user_info.get("email", self.user_id or "—")
            _row(st, "user", f"[green]{email}[/green]")
        else:
            _row(st, "user", "[dim]not logged in[/dim]")
        if self.project:
            _row(
                st,
                "project",
                f"[cyan]{self.project.get('name', '')}[/cyan]  [dim]{self.project['id']}[/dim]",
            )
        else:
            _row(st, "project", "[dim]none[/dim]")
        if self.chat:
            _row(
                st,
                "chat",
                f"[cyan]{self.chat.get('name', '')}[/cyan]  [dim]{self.chat['id']}[/dim]",
            )
        else:
            _row(st, "chat", "[dim]none[/dim]")
        if self.selected_agent:
            _row(st, "agent", f"[magenta]{self.selected_agent.get('name', '')}[/magenta]")
        if self.selected_knowledge:
            _row(st, "knowledge", f"[magenta]{self.selected_knowledge.get('name', '')}[/magenta]")
        if self.selected_skill:
            _row(st, "skill", f"[magenta]{self.selected_skill.get('name', '')}[/magenta]")
        console.print(Panel(st, title="[bold]Session[/bold]", expand=False))

        # ── Defaults ────────────────────────────────────────────────
        dt = Table(show_header=False, box=None, padding=(0, 2))
        dt.add_column(style="dim", no_wrap=True)
        dt.add_column()
        _row(dt, "default_model", f"[yellow]{settings.default_model}[/yellow]")
        _row(dt, "default_provider", f"[yellow]{settings.default_provider}[/yellow]")
        console.print(Panel(dt, title="[bold]Defaults[/bold]", expand=False))

        console.print(f"[dim]Config file: {CONFIG_DIR / 'config.toml'}[/dim]")

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

        was_new_chat = self.project.get("name") == "New Chat"

        # Build chip kwargs from active selections
        extra: dict = {}
        if self.selected_agent:
            extra["agent_launch_id"] = self.selected_agent["id"]
            if self.selected_agent.get("tools"):
                extra["native_tools"] = self.selected_agent["tools"]
        if self.selected_knowledge:
            extra["knowledges"] = [
                {
                    "knowledge_id": self.selected_knowledge["id"],
                    "user_id": self.selected_knowledge.get("user_id", self.user_id),
                }
            ]
        if self.selected_skill:
            extra["skill_ids"] = [self.selected_skill["id"]]

        try:
            events = _client().messages.stream_message(
                self.user_id,
                self.project["id"],
                self.chat["id"],
                text,
                model=self.model,
                provider=self.provider,
                user_settings=self.user_settings,
                **extra,
            )
            run_stream(events, model=self.model)
        except OmniaAPIError as exc:
            console.print(f"[bold red]API error {exc.status_code}:[/bold red] {exc.detail}")
            return

        # If this was the first message in a "New Chat", the backend has
        # auto-renamed the project — refresh to pick up the new name.
        if was_new_chat:
            try:
                updated = (
                    _client()
                    .projects.get_project(self.user_id, self.project["id"])
                    .model_dump(mode="json")
                )
                if updated.get("name") and updated["name"] != "New Chat":
                    self.project = updated
                    console.print(f"[dim]Chat renamed to:[/dim] [bold]{updated['name']}[/bold]")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ── Guards ────────────────────────────────────────────────────────
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if not self.user_info:
            raise NotConfiguredError("This command requires login. Run [cyan]/login[/cyan] first.")

    def _require_chat(self) -> None:
        if not self.project or not self.chat:
            raise NotConfiguredError(
                "No active chat. Run [cyan]/chats[/cyan] or [cyan]/new <name>[/cyan] first."
            )


# ---------------------------------------------------------------------------
# Rich renderers for public data
# ---------------------------------------------------------------------------


def _print_market_results(data: dict) -> None:
    items = data.get("items", data.get("results", data.get("packages", [])))
    if not items:
        console.print("[yellow]No results.[/yellow]")
        return
    total = data.get("total", len(items))
    t = Table(
        title=f"Market Intelligence  [dim]({total} total)[/dim]",
        show_lines=False,
        highlight=True,
    )
    t.add_column("Market", style="dim")
    t.add_column("ID", style="cyan")
    t.add_column("Name", style="bold white")
    t.add_column("Version", style="dim")
    t.add_column("Verdict", no_wrap=True)
    t.add_column("Risk", justify="right", style="dim")
    for item in items:
        analysis = item.get("analysis", {}) or {}
        verdict = (analysis.get("verdict") or "").lower()
        color = _VERDICT_COLOR.get(verdict, "dim")
        verdict_str = f"[{color}]{verdict}[/{color}]" if verdict else "[dim]-[/dim]"
        risk = str(analysis.get("risk_score", "-")) if analysis else "-"
        t.add_row(
            item.get("market", ""),
            item.get("market_id", ""),
            item.get("name", ""),
            item.get("version", ""),
            verdict_str,
            risk,
        )
    console.print(t)


def _print_market_package(data: dict) -> None:
    # API returns PublicPackageVersion directly (no wrapper)
    pkg = data.get("package", data)
    analysis = data.get("analysis") or data.get("latest_analysis") or {}
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
        color = _VERDICT_COLOR.get(verdict, "white")
        t.add_row(
            "[dim]Verdict[/dim]",
            f"[bold {color}]{verdict.upper()}[/bold {color}]"
            f"  risk {analysis.get('risk_score', '-')}/10",
        )
    console.print(Panel(t, title=f"[bold]{pkg.get('name', 'Package')}[/bold]", expand=False))


def _print_market_versions(data: dict) -> None:
    # API returns a plain list of version strings
    if isinstance(data, list):
        versions = data
    else:
        versions = data.get("versions", data.get("items", []))
    if not versions:
        console.print("[yellow]No versions found.[/yellow]")
        return
    t = Table(title="Versions", show_lines=False)
    t.add_column("Version", style="cyan")
    for v in versions:
        t.add_row(str(v))
    console.print(t)


def _print_shared_chat(data: dict) -> None:
    project = data.get("project", {})
    chats = data.get("chats", [])
    messages = data.get("chat_messages", [])
    chat_name = chats[0].get("name", "") if chats else ""
    title_str = chat_name or project.get("name", "Shared Chat")
    console.print(
        Panel(
            f"[bold white]{title_str}[/bold white]\n"
            + (f"[dim]Project: {project.get('name', '')}[/dim]\n" if chat_name else "")
            + f"[dim]{len(messages)} messages[/dim]",
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


def _flag(args: list[str], flag: str) -> str | None:
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
    return getpass.getpass(f"{label}: ")
