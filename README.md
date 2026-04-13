# CuddleWrap

> **⚠️ Educational project** — Intended for f*cking around with LLM tool-calling harnesses and getting familiar with how they work under the hood. Not intended as a production tool - it might accidentaly delete your cute cat images. Use with extra caution.

A minimal LLM tool-calling harness for your terminal. Local-first with Ollama.

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
| `/history` | List recent conversations |
| `/history <n>` | Resume conversation #n |
| `/init` | Create a starter AGENTS.md template |
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

### AGENTS.md

Drop an `AGENTS.md` file in your project root to give the model project-specific instructions. It's loaded into the system prompt at startup — like Claude Code's `CLAUDE.md`.

```bash
cw
› /init    # creates a starter AGENTS.md template
```

CuddleWrap checks two locations:
1. `~/.cuddlewrap/AGENTS.md` — user-level defaults (applied to all projects)
2. `./AGENTS.md` — project-level instructions (takes priority)

## Architecture

```
cuddlewrap/
├── pyproject.toml      # Package config, registers `cw` command
├── AGENTS.md           # Project instructions (optional, loaded into system prompt)
└── cuddlewrap/
    ├── __init__.py      # Version
    ├── main.py          # Entry point, REPL loop, @file resolution
    ├── agent.py         # Agentic loop, LLM calls, spinner
    ├── tools.py         # Tool definitions (6 tools)
    ├── commands.py      # Slash command dispatch
    ├── display.py       # Terminal formatting, prompt_toolkit toolbar
    ├── config.py        # Config file loading (~/.cuddlewrap/config.toml)
    ├── history.py       # Conversation persistence (~/.cuddlewrap/history/)
    └── agentsmd.py      # AGENTS.md loader (project + user level)
```

## Roadmap

- [x] ~~`edit_file` tool (search-and-replace)~~
- [x] ~~`glob_search` and `grep_search` tools~~
- [x] ~~Permission tiers (auto-approve reads, confirm writes)~~
- [x] ~~Context truncation (10K char limit per tool output)~~
- [x] ~~Path sandboxing (tools jailed to project directory)~~
- [x] ~~Autocomplete (commands, model names, @file paths)~~
- [x] ~~Conversation history persistence~~
- [x] ~~Config file (`~/.cuddlewrap/config.toml`)~~
- [x] ~~AGENTS.md support (project instructions in system prompt)~~
- [ ] Web search tool
- [ ] Multi-provider support (Anthropic, OpenAI)

## License

MIT
