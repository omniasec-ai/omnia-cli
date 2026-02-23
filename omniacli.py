import time
import os
import typer
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from dotenv import load_dotenv
from typing import Optional, List, Dict
import asyncio
from datetime import datetime

# Load environment variables
load_dotenv()

OMNIA_API_URL = os.getenv("OMNIA_API_URL")
OMNIA_API_TOKEN = os.getenv("OMNIA_API_TOKEN")

app = typer.Typer()
console = Console()


class OmniaClient:
    def __init__(self, base_url: str, token: str):
        print(
            f"Initializing OmniaClient with base_url: {base_url}")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": token}
        self.client = httpx.Client(
            base_url=self.base_url, headers=self.headers, timeout=30.0
        )
        self.user_id: Optional[str] = None
        self.current_project_id: Optional[str] = (
            None  # We might need to map chat -> project
        )

    def get_me(self) -> Dict:
        # print complete request with headers and response
        response = self.client.get("/api/v1/app/users/me")
        response.raise_for_status()
        # {'message': 'This is a protected route', 'user_info': {'username': '0ce37c5a-f262-4c76-8f3f-12d379f4670f', 'user_id': '0ce37c5a-f262-4c76-8f3f-12d379f4670f', 'email': 'dariogf@gmail.com', 'auth_type': 'api_key', 'roles': ['ADMIN'], 'groups': ['GTIG', 'PUBLIC']}, 'auth_type': 'api_key', 'api_key': '9bdf338de7a0a9b3258fe539fdcc83e11d3b565186b1344b59535757850c141f', 'internal_auth_header': 'Basic MGNlMzdjNWEtZjI2Mi00Yzc2LThmM2YtMTJkMzc5ZjQ2NzBmOjliZGYzMzhkZTdhMGE5YjMyNThmZTUzOWZkY2M4M2UxMWQzYjU2NTE4NmIxMzQ0YjU5NTM1NzU3ODUwYzE0MWY='}
        data = response.json()

        self.user_id = data.get("user_info", {}).get("user_id")
        return data

    def get_agents(self) -> List[Dict]:
        response = self.client.get("/api/v1/agents")
        response.raise_for_status()
        return response.json().get("agents", [])

    def get_projects(self) -> List[Dict]:
        if not self.user_id:
            self.get_me()
        response = self.client.get(
            f"/api/v1/app/users/{self.user_id}/projects")
        response.raise_for_status()
        return response.json().get("projects", [])

    def get_chats_for_project(self, project_id: str) -> List[Dict]:
        if not self.user_id:
            self.get_me()
        response = self.client.get(
            f"/api/v1/app/users/{self.user_id}/projects/{project_id}/chats"
        )
        response.raise_for_status()
        return response.json().get("chats", [])

    def get_all_chats(self) -> List[Dict]:
        projects = self.get_projects()
        all_chats = []
        for project in projects:
            p_chats = self.get_chats_for_project(project["id"])
            for chat in p_chats:
                chat["project_id"] = project[
                    "id"
                ]  # Enrich with project_id for later use
                chat["project_name"] = project.get("name")
            all_chats.extend(p_chats)
        return all_chats

    def get_messages(self, project_id: str, chat_id: str) -> List[Dict]:
        if not self.user_id:
            self.get_me()
        response = self.client.get(
            f"/api/v1/app/users/{self.user_id}/projects/{project_id}/chats/{chat_id}/messages"
        )
        response.raise_for_status()
        return response.json().get("chat_messages", [])

    def send_message(self, project_id: str, chat_id: str, content: str, model: str = "gemini-2.5-pro",
                     mcp_servers: Optional[List] = None, resources_in_context: Optional[List] = None,
                     agent_launch: Optional[Dict] = None, additional_info: Optional[Dict] = None,
                     native_tools: Optional[List] = None, user_settings: Optional[Dict] = None,
                     provider: str = "google", mode: Optional[str] = None,
                     knowledges: Optional[List] = None, save_message: bool = False) -> Dict:
        if not self.user_id:
            self.get_me()
        payload = {
            "query": content,
            "user_id": self.user_id,
            "project_id": project_id,
            "chat_id": chat_id,
            "mcp_servers": mcp_servers or [],
            "streaming": False,  # No streaming for side-by-side
            "model": model,
            "resources_in_context": resources_in_context or [],
            "agent_launch": agent_launch or {},
            "additional_info": additional_info,
            "native_tools": native_tools or ["all"],
            "config": {
                "user_settings": user_settings or {},
                "selected_model": model,
                "selected_provider": provider,
            },
            "mode": mode,
            "knowledges": knowledges or [],
            "save_message": save_message,
        }
        response = self.client.post(
            "/api/v1/agents/OmniaMainAgent/a1/chat/run",
            json=payload,
        )
        if response.status_code == 422:
            # Print detailed error information for 422 errors
            try:
                error_data = response.json()
                console.print(
                    f"[bold red]422 Validation Error:[/bold red] {error_data}")
            except:
                console.print(
                    f"[bold red]422 Error response:[/bold red] {response.text}")
        response.raise_for_status()
        return response.json()


class CLIState:
    def __init__(self):
        self.client: Optional[OmniaClient] = None
        self.current_chat: Optional[Dict] = None
        self.current_agent: Optional[Dict] = None

    def start(self):
        if not OMNIA_API_URL or not OMNIA_API_TOKEN:
            console.print(
                "[bold red]Error:[/bold red] OMNIA_API_URL and OMNIA_API_TOKEN must be set in .env"
            )
            return

        self.client = OmniaClient(OMNIA_API_URL, OMNIA_API_TOKEN)

        try:
            user = self.client.get_me()
            user_info = user.get('user_info', {})
            console.print(
                f"[green]Authenticated as:[/green] {user_info.get('email', 'Unknown')} ({user_info.get('user_id', 'Unknown')})"
            )
        except Exception as e:
            console.print(f"[bold red]Authentication failed:[/bold red] {e}")
            return

        self.loop()

    def loop(self):
        while True:
            prefix = ""
            if self.current_chat:
                prefix = f"[blue]({self.current_chat.get('name', 'chat')})[/blue] "

            user_input = Prompt.ask(f"{prefix}>>>")

            if user_input.startswith("/"):
                self.handle_command(user_input)
            elif user_input.strip():
                self.handle_message(user_input)

    def handle_command(self, command_str: str):
        parts = command_str.split()
        command = parts[0]
        args = parts[1:]

        try:
            if command == "/me":
                user = self.client.get_me()
                console.print(Panel(str(user), title="User Info"))

            elif command == "/agents":
                agents = self.client.get_agents()
                table = Table(title="Available Agents")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="magenta")
                table.add_column("Description", style="green")

                for agent in agents:
                    table.add_row(
                        agent.get("id"), agent.get(
                            "name"), agent.get("description", "")
                    )
                console.print(table)

            elif command == "/chats":
                with console.status("Fetching chats..."):
                    chats = self.client.get_all_chats()

                if not chats:
                    console.print("No chats found.")
                    return

                table = Table(title="Your Chats")
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Name", style="magenta")
                table.add_column("Project", style="blue")

                # Handling nested message structure safely
                table.add_column("Last Message", style="white")
                table.add_column("Date", style="yellow")

                for chat in chats:
                    last_msg = ""
                    date_str = ""
                    # You might need to adjust accessing last_message depending on exact API structure
                    # Assuming chat object has simple fields or we parse them

                    table.add_row(
                        chat.get("id"),
                        chat.get("name"),
                        chat.get("project_name", "N/A"),
                        last_msg,
                        date_str,
                    )
                console.print(table)
                self.chats_cache = chats  # Cache for easy lookup by ID if needed

            elif command == "/chat":
                if not args:
                    console.print("[red]Usage: /chat <chat_id>[/red]")
                    return
                chat_id = args[0]

                # Check cache or fetch
                # For simplicity, we need to know the project_id for this chat.
                # In a real app we might look it up from the previous /chats call
                # or have an endpoint to get chat by ID directly (which might not exist in this hierarchy).

                found_chat = None
                # We need to re-fetch or use a cache. Let's assume we populate a cache in /chats
                # If cache is empty, we force a fetch
                if not hasattr(self, "chats_cache"):
                    with console.status("Locating chat..."):
                        self.chats_cache = self.client.get_all_chats()

                for c in self.chats_cache:
                    if c.get("id") == chat_id:
                        found_chat = c
                        break

                if found_chat:
                    self.current_chat = found_chat
                    console.print(
                        f"[green]Switched to chat: {found_chat.get('name')}[/green]"
                    )
                    self.print_history()
                else:
                    console.print(
                        f"[red]Chat {chat_id} not found in your projects.[/red]"
                    )

            elif command == "/messages":
                self.print_history()

            elif command == "/exit":
                console.print("Goodbye!")
                exit(0)

            elif command == "/agent":
                if not args:
                    console.print("[red]Usage: /agent <agent_id>[/red]")
                    return
                self.current_agent = {
                    "id": args[0]
                }  # Placeholder, validation could be added
                console.print(
                    f"[yellow]Target agent set to {args[0]} (Note: This client just tracks it, ensure API supports agent selection if needed)[/yellow]"
                )

            else:
                console.print(f"[red]Unknown command: {command}[/red]")

        except Exception as e:
            console.print(f"[bold red]Error executing command:[/bold red] {e}")

    def print_history(self):
        if not self.current_chat:
            console.print(
                "[yellow]No chat selected. Use /chat <id> first.[/yellow]")
            return

        project_id = self.current_chat.get("project_id")
        chat_id = self.current_chat.get("id")

        with console.status("Fetching messages..."):
            messages = self.client.get_messages(project_id, chat_id)

        # Reverse if API returns newest first? Usually APIs return chronological or reverse.
        for msg in messages:
            # Assuming chronological for now or we sort.
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            style = "green" if role == "user" else "blue"
            console.print(f"[{style}][{role}][/{style}] {content}")

    def handle_message(self, content: str):
        if not self.current_chat:
            console.print(
                "[yellow]No active chat. Select one with /chat <id> or create a new one (not impl).[/yellow]"
            )
            return

        project_id = self.current_chat.get("project_id")
        chat_id = self.current_chat.get("id")

        try:
            with console.status("Sending..."):
                response = self.client.send_message(
                    project_id, chat_id, content)

            # Print user message
            console.print(f"[green][user][/green] {content}")

            # Print the API response
            if isinstance(response, dict):
                # Try to extract the response content from various possible structures
                response_text = response.get("response") or response.get(
                    "content") or response.get("message") or str(response)
                console.print(f"[blue][assistant][/blue] {response_text}")
            else:
                console.print(f"[blue][assistant][/blue] {response}")

            # Refresh message history to show the new messages
            time.sleep(0.5)  # small wait for message to be persisted
            self.print_history()

        except Exception as e:
            console.print(f"[bold red]Failed to send:[/bold red] {e}")


@app.command()
def start():
    state = CLIState()
    state.start()


if __name__ == "__main__":
    app()
