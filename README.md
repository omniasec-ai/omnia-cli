# Omnia CLI

Terminal client for the Omnia platform — chat, file analysis, templates and more.

## Requirements

- Docker + Docker Compose

## Setup

1. Copy the env example and fill in your credentials:

```bash
cp dotenv.example .env
```

```dotenv
OMNIA_API_URL=https://your-omnia-api.example.com
OMNIA_API_TOKEN=your_api_key_here
```

2. Build the image:

```bash
docker compose build
```

## Usage

```bash
# Show available commands
docker compose run --rm omnia omnia --help

# Authenticate and verify credentials
docker compose run --rm omnia omnia auth login

# Start interactive chat (creates a new project)
docker compose run --rm omnia omnia chat

# Resume an existing project
docker compose run --rm omnia omnia chat --project <project_id>

# List projects
docker compose run --rm omnia omnia project list

# Upload a file for analysis
docker compose run --rm -v $(pwd):/files omnia omnia analysis upload /files/sample.exe

# List analyses
docker compose run --rm omnia omnia analysis list

# List templates
docker compose run --rm omnia omnia template list
```

## Development

Mount the source code for live reloading:

```bash
docker compose run --rm -v $(pwd)/omnia:/app/omnia omnia omnia chat
```

## Commands

| Command | Description |
|---|---|
| `omnia auth login` | Set API URL + key, verify credentials |
| `omnia auth logout` | Clear stored credentials |
| `omnia auth whoami` | Show current user |
| `omnia chat` | Start interactive streaming chat |
| `omnia chat --project <id>` | Resume existing project |
| `omnia chat --new <name>` | Create project and start chat |
| `omnia project list` | List all projects |
| `omnia project create <name>` | Create a new project |
| `omnia project delete <id>` | Delete a project |
| `omnia analysis upload <file>` | Upload file for analysis |
| `omnia analysis upload <file> --watch` | Upload and poll until done |
| `omnia analysis list` | List analyses |
| `omnia analysis show <id>` | Show analysis detail |
| `omnia template list` | List templates |
| `omnia template show <id>` | Show template detail |
| `omnia template fork <id>` | Fork a template |
| `omnia config show` | Print current config |
| `omnia config set <key> <value>` | Set a config value |

### Chat REPL commands

Inside `omnia chat`, type these slash commands:

| Command | Description |
|---|---|
| `/help` | Show help |
| `/me` | Show current user |
| `/agents` | List available agents |
| `/projects` | List your projects |
| `/chats` | List chats in current project |
| `/history` | Print message history |
| `/new <name>` | Create and switch to new project |
| `/switch <project_id>` | Switch to existing project |
| `/model <name>` | Change LLM model |
| `/provider <name>` | Change provider |
| `/upload <path>` | Upload file as project resource |
| `/resources` | List project resources |
| `/exit` | Quit |
