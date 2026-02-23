# Omnia CLI

A Python 3 CLI for the Omnia API, built with Typer and Rich.

## Development

This project is configured to use **Dev Containers**.

1.  Open the project in VS Code.
2.  When prompted, re-open in Container (or run "Dev Containers: Reopen in Container" from the command palette).
3.  The container will automatically install dependencies from `requirements.txt`.
4.  Create a `.env` file in the root with your API credentials (see `.env.example` or ask for them).

```bash
OMNIA_API_URL=...
OMNIA_API_TOKEN=...
```

5.  Run the CLI:

```bash
python main.py start
```

## Commands

- `/me`: Get current user details.
- `/agents`: List all agent plugins.
- `/agent <agent_id>`: Change to this agent.
- `/chats`: List all chats in a beautiful table.
- `/chat <chat_id>`: Switch to this chat.
- `/messages`: List all messages in the current chat.
- `<message>`: Send a message to the current chat.
