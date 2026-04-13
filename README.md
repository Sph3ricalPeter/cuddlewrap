# CuddleWrap

A minimal LLM tool-calling harness for your terminal. Think Claude Code, but local-first with Ollama.

```
   ______          __    ____     _       __
  / ____/__  ____/ /___/ / /__  | |     / /________ _____
 / /   / / / / __  / __  / / _ \| | /| / / ___/ __ `/ __ \
/ /___/ /_/ / /_/ / /_/ / /  __/| |/ |/ / /  / /_/ / /_/ /
\____/\__,_/\__,_/\__,_/_/\___/ |__/|__/_/   \__,_/ .___/
                                                  /_/
```

## Features

- **`cw` command** — launches from anywhere in your terminal
- **Tool calling** — the model can run shell commands, read files, and write files
- **Confirmation prompts** — `y/n/a` before executing commands (`a` = auto-approve for session)
- **`@file` references** — type `explain @src/app.py` to include file contents in your message
- **Slash commands** — `/model`, `/model list`, `/settings`, `/clear`, `/help`, `/exit`
- **Context tracking** — live context window usage in the bottom toolbar
- **Loading spinner** — animated indicator while the model thinks
- **OS-aware** — automatically uses Windows or Unix commands

## Requirements

- Python 3.12+
- [Ollama](https://ollama.com/) running locally with a model pulled

## Install

```bash
# Clone the repo
git clone https://github.com/Sph3ricalPeter/cuddlewrap.git
cd cuddlewrap

# Pull a model (pick one)
ollama pull devstral-small-2
ollama pull gemma4:e4b

# Install cuddlewrap
pip install -e .
```

## Usage

```bash
cw
```

That's it. You'll see the banner, a prompt, and a status bar at the bottom.

### Examples

```
› list files in this directory

▶ bash dir
  pyproject.toml
  cuddlewrap/

› create a hello.py that prints hello world

▶ write_file hello.py
  Wrote 1 lines to hello.py

▶ bash python hello.py
  hello world

› explain @cuddlewrap/agent.py
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/model` | Show current model |
| `/model list` | List all locally available models |
| `/model <name>` | Switch to a different model |
| `/settings` | Show current settings |
| `/clear` | Clear conversation history and screen |
| `/exit` | Exit CuddleWrap |

### Tools

The model has access to:

| Tool | Description | Permission |
|------|-------------|------------|
| `bash` | Execute shell commands | Requires confirmation |
| `write_file` | Create or overwrite files | Requires confirmation |
| `edit_file` | Search-and-replace in files | Requires confirmation |
| `read_file` | Read file contents with line numbers | Auto-approved |
| `glob_search` | Find files by name pattern | Auto-approved |
| `grep_search` | Search file contents by regex | Auto-approved |

## Architecture

```
cuddlewrap/
├── pyproject.toml      # Package config, registers `cw` command
└── cuddlewrap/
    ├── __init__.py      # Version
    ├── main.py          # Entry point, REPL loop, @file resolution
    ├── agent.py         # Agentic loop, LLM calls, spinner
    ├── tools.py         # Tool definitions (bash, write_file, read_file, edit_file, glob_search, grep_search)
    ├── commands.py      # Slash command dispatch
    └── display.py       # Terminal formatting, prompt_toolkit toolbar
```

## Roadmap

- [x] ~~`edit_file` tool (search-and-replace)~~
- [x] ~~`glob_search` and `grep_search` tools~~
- [x] ~~Permission tiers (auto-approve reads, confirm writes)~~
- [x] ~~Context truncation (10K char limit per tool output)~~
- [ ] Conversation history persistence
- [ ] Config file (`~/.cuddlewrap/config.toml`)
- [ ] Multi-provider support (Anthropic, OpenAI)

## License

MIT
