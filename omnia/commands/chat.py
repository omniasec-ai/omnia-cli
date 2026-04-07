"""
omnia chat  — interactive streaming chat REPL

Usage:
    omnia chat                            # new chat (prompts for name)
    omnia chat --project <project_id>     # resume existing project
    omnia chat --new <name>               # create project with given name
"""

from __future__ import annotations

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel

from omnia.client.auth import get_agents, get_me
from omnia.client.base import OmniaAPIError, NotConfiguredError
from omnia.client.messages import list_messages, stream_message
from omnia.client.projects import (
    create_project_with_chat,
    get_or_create_chat,
    list_chats,
    list_projects,
)
from omnia.client.resources import list_resources, upload_resource
from omnia.config.settings import settings
from omnia.ui.messages import render_message
from omnia.ui.stream import run_stream
from omnia.ui.tables import agents_table, chats_table, projects_table, resources_table

from pathlib import Path

app = typer.Typer(help="Start an interactive chat session.")
console = Console()

# prompt_toolkit style
_PT_STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
    }
)

_HELP = """
[bold]Available commands[/bold]

  [cyan]/help[/cyan]               Show this help
  [cyan]/me[/cyan]                 Show current user info
  [cyan]/agents[/cyan]             List available agents
  [cyan]/projects[/cyan]           List your projects
  [cyan]/chats[/cyan]              List chats in the current project
  [cyan]/history[/cyan]            Print message history for this chat
  [cyan]/new <name>[/cyan]         Create a new project and switch to it
  [cyan]/switch <project_id>[/cyan] Switch to an existing project
  [cyan]/model <name>[/cyan]       Change LLM model (e.g. gemini-2.5-pro)
  [cyan]/provider <name>[/cyan]    Change provider (e.g. google, anthropic)
  [cyan]/upload <path>[/cyan]      Upload a file as a resource in this project
  [cyan]/resources[/cyan]          List resources in the current project
  [cyan]/exit[/cyan]               Quit

Any other input is sent to the agent as a message.
"""


class ChatSession:
    def __init__(self, user_id: str, project: dict, chat: dict) -> None:
        self.user_id = user_id
        self.project = project
        self.chat = chat
        self.model = settings.default_model
        self.provider = settings.default_provider
        self._prompt_session: PromptSession = PromptSession(
            history=InMemoryHistory(), style=_PT_STYLE
        )

    @property
    def project_id(self) -> str:
        return self.project["id"]

    @property
    def chat_id(self) -> str:
        return self.chat["id"]

    def _prompt_text(self) -> str:
        project_name = self.project.get("name", "chat")
        return f"({project_name}) >> "

    def run(self) -> None:
        console.print(
            Panel(
                f"Project: [bold cyan]{self.project.get('name')}[/bold cyan]  "
                f"[dim]({self.project_id})[/dim]\n"
                f"Chat:    [dim]{self.chat_id}[/dim]\n"
                f"Model:   [dim]{self.model}[/dim]\n\n"
                f"Type [cyan]/help[/cyan] for commands, [cyan]/exit[/cyan] to quit.",
                title="[bold]Omnia Chat[/bold]",
                border_style="cyan",
                expand=False,
            )
        )

        while True:
            try:
                user_input = self._prompt_session.prompt(self._prompt_text()).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                should_exit = self._handle_command(user_input)
                if should_exit:
                    break
            else:
                self._send(user_input)

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _handle_command(self, raw: str) -> bool:
        """Returns True if the loop should exit."""
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        try:
            if cmd == "/exit":
                return True
            elif cmd == "/help":
                console.print(_HELP)
            elif cmd == "/me":
                self._cmd_me()
            elif cmd == "/agents":
                self._cmd_agents()
            elif cmd == "/projects":
                self._cmd_projects()
            elif cmd == "/chats":
                self._cmd_chats()
            elif cmd == "/history":
                self._cmd_history()
            elif cmd == "/new":
                if not arg:
                    console.print("[red]Usage: /new <project name>[/red]")
                else:
                    self._cmd_new(arg)
            elif cmd == "/switch":
                if not arg:
                    console.print("[red]Usage: /switch <project_id>[/red]")
                else:
                    self._cmd_switch(arg)
            elif cmd == "/model":
                if not arg:
                    console.print(f"[dim]Current model:[/dim] {self.model}")
                else:
                    self.model = arg
                    console.print(f"[green]Model set to:[/green] {self.model}")
            elif cmd == "/provider":
                if not arg:
                    console.print(f"[dim]Current provider:[/dim] {self.provider}")
                else:
                    self.provider = arg
                    console.print(f"[green]Provider set to:[/green] {self.provider}")
            elif cmd == "/upload":
                if not arg:
                    console.print("[red]Usage: /upload <file path>[/red]")
                else:
                    self._cmd_upload(arg)
            elif cmd == "/resources":
                self._cmd_resources()
            else:
                console.print(f"[red]Unknown command: {cmd}[/red]  Type [cyan]/help[/cyan]")
        except (OmniaAPIError, NotConfiguredError) as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
        except Exception as exc:
            console.print(f"[bold red]Unexpected error:[/bold red] {exc}")

        return False

    def _cmd_me(self) -> None:
        from omnia.client.auth import get_me

        data = get_me()
        info = data.get("user_info", {})
        console.print(
            f"[bold]{info.get('email')}[/bold]  "
            f"[dim]{info.get('user_id')}[/dim]  "
            f"roles: {', '.join(info.get('roles', []))}"
        )

    def _cmd_agents(self) -> None:
        agents = get_agents()
        if agents:
            console.print(agents_table(agents))
        else:
            console.print("[yellow]No agents found.[/yellow]")

    def _cmd_projects(self) -> None:
        projects = list_projects(self.user_id)
        if projects:
            console.print(projects_table(projects))
        else:
            console.print("[yellow]No projects.[/yellow]")

    def _cmd_chats(self) -> None:
        chats = list_chats(self.user_id, self.project_id)
        enriched = [dict(c, project_name=self.project.get("name", "")) for c in chats]
        if enriched:
            console.print(chats_table(enriched))
        else:
            console.print("[yellow]No chats.[/yellow]")

    def _cmd_history(self) -> None:
        messages = list_messages(self.user_id, self.project_id, self.chat_id)
        if not messages:
            console.print("[dim]No messages yet.[/dim]")
            return
        for msg in messages:
            render_message(msg)

    def _cmd_new(self, name: str) -> None:
        with console.status(f"Creating project [cyan]{name}[/cyan]…"):
            project, chat = create_project_with_chat(self.user_id, name)
        self.project = project
        self.chat = chat
        console.print(
            f"[green]Switched to new project:[/green] [bold]{name}[/bold]  "
            f"[dim]({project['id']})[/dim]"
        )

    def _cmd_switch(self, project_id: str) -> None:
        # Find the project in the list to get its name
        all_projects = list_projects(self.user_id)
        found = next((p for p in all_projects if p["id"] == project_id), None)
        if not found:
            console.print(f"[red]Project {project_id!r} not found.[/red]")
            return
        chat = get_or_create_chat(self.user_id, project_id)
        self.project = found
        self.chat = chat
        console.print(
            f"[green]Switched to:[/green] [bold]{found.get('name')}[/bold]  "
            f"[dim]({project_id})[/dim]"
        )

    def _cmd_upload(self, path_str: str) -> None:
        file_path = Path(path_str).expanduser()
        if not file_path.exists():
            console.print(f"[red]File not found: {path_str}[/red]")
            return
        with console.status(f"Uploading [cyan]{file_path.name}[/cyan]…"):
            resource = upload_resource(self.user_id, self.project_id, file_path)
        resource_id = resource.get("id", "")
        console.print(f"[green]Uploaded.[/green] Resource ID: [cyan]{resource_id}[/cyan]")

    def _cmd_resources(self) -> None:
        resources = list_resources(self.user_id, self.project_id)
        if resources:
            console.print(resources_table(resources))
        else:
            console.print("[dim]No resources in this project.[/dim]")

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def _send(self, query: str) -> None:
        console.print(f"\n[bold green]You[/bold green]  {query}")
        try:
            events = stream_message(
                self.user_id,
                self.project_id,
                self.chat_id,
                query,
                model=self.model,
                provider=self.provider,
            )
            run_stream(events)
        except OmniaAPIError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
        except NotConfiguredError as exc:
            console.print(f"[bold red]Not configured:[/bold red] {exc}")


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def chat(
    project_id: str = typer.Option(None, "--project", "-p", help="Resume a project by ID"),
    new: str = typer.Option(None, "--new", "-n", help="Create a new project with this name"),
) -> None:
    """Start an interactive chat session."""
    try:
        data = get_me()
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Not authenticated:[/bold red] {exc}")
        console.print("Run [bold]omnia auth login[/bold] first.")
        raise typer.Exit(code=1)

    user_id = data["user_info"]["user_id"]

    try:
        if new:
            with console.status(f"Creating project [cyan]{new}[/cyan]…"):
                project, chat_obj = create_project_with_chat(user_id, new)
        elif project_id:
            all_projects = list_projects(user_id)
            project = next((p for p in all_projects if p["id"] == project_id), None)
            if not project:
                console.print(f"[bold red]Project {project_id!r} not found.[/bold red]")
                raise typer.Exit(code=1)
            chat_obj = get_or_create_chat(user_id, project_id)
        else:
            # Interactive: ask for project name
            name = typer.prompt("New project name", default="Omnia session")
            with console.status(f"Creating project [cyan]{name}[/cyan]…"):
                project, chat_obj = create_project_with_chat(user_id, name)
    except (OmniaAPIError, NotConfiguredError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    session = ChatSession(user_id=user_id, project=project, chat=chat_obj)
    session.run()
