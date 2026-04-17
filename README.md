# Omnia CLI

Terminal client for the Omnia platform — interactive REPL for chat, file analysis, templates, workflows and market intelligence.

## Installation

```bash
curl -fsSL https://omniasec.ai/cli | bash
```

Then open a new terminal and run `omnia`.

## Development setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
omnia
```

To uninstall from the venv:

```bash
pip uninstall omnia-cli
```

## Commands

Once inside the REPL, use these slash commands:

### No login required

| Command | Description |
|---|---|
| `/version` | Check API version and connectivity |
| `/market search <query>` | Search packages in market intelligence |
| `/market show <market> <id>` | Show package details |
| `/market versions <market> <id>` | List package versions |
| `/share <token>` | View a shared chat by token |

### Require login

| Command | Description |
|---|---|
| `/login` | Authenticate (browser or API key) |
| `/logout` | Clear credentials |
| `/me` | Show current user |
| `/new <name>` | Create a new chat |
| `/chats` | Pick a recent chat with arrow keys |
| `/delete` | Delete the current chat |
| `/leave` | Leave the current chat |
| `/history` | Show this chat's message history |
| `/agent` | Attach an agent to next messages |
| `/knowledge` | Attach a knowledge base to next messages |
| `/skill` | Attach a skill to next messages |
| `/prompt` | Browse prompts and insert one into the conversation |
| `/workflow` | Launch a workflow |
| `/analysis` | List your file analyses |
| `/analysis upload <file>` | Upload a file for analysis |
| `/analysis show <id>` | Show analysis detail |
| `/templates` | List available templates |
| `/template show <id>` | Show template detail |
| `/template fork <id>` | Fork a template to your account |
| `/resources` | List resources in current chat |
| `/analyze <file>` | Upload a file as a chat resource |
| `/newprovider` | Configure API key for a provider |
| `/model [name]` | Show or change the LLM model |
| `/config` | Show current configuration |
| `/uninstall` | Remove omnia from this machine |
| `/help` | Show help |
| `/clear` | Clear the screen |
| `/exit` | Quit |

Any plain text (no leading `/`) is sent as a message to the current chat.

## Releasing a new version

Releases are triggered by pushing a git tag. The CI workflow builds standalone binaries for Linux (amd64) and macOS (arm64) using PyInstaller and publishes them as GitHub Release assets alongside `install.sh`.

```bash
git tag v0.2.7
git push origin v0.2.7
```

That's it — the release and binaries are created automatically in ~5 minutes.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `OMNIA_API_TOKEN` | Your API key | — |
| `OMNIA_ENV` | `prod`, `staging` or `dev` | `prod` |
| `OMNIA_API_URL` | Explicit API URL override | — |
