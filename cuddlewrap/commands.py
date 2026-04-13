"""Slash command dispatch for CuddleWrap."""

import os
import re

import ollama

from cuddlewrap import display
from cuddlewrap.config import save_config, CONFIG_FILE
from cuddlewrap.history import list_conversations, load_conversation


def parse_command(line):
    """Parse a /command from user input.

    Returns:
        (cmd_name, args_string) if valid command,
        (None, error_message) if it looks like a command but is malformed,
        None if not a command at all.
    """
    if not line.startswith("/"):
        return None
    match = re.match(r"^/(\w+)(?:\s+(.*))?$", line)
    if not match:
        return None, f"Invalid command: '{line}'. Type /help for commands"
    return match.group(1), (match.group(2) or "").strip()


def cmd_help(args, state):
    """Print available commands."""
    print(
        """
Commands:
  /help                Show this help message
  /model               Show current model
  /model list          List all available models
  /model <name>        Switch to a different model
  /settings            Show current settings
  /resume              Resume a past conversation (interactive picker)
  /init                Create AGENTS.md in current directory
  /clear               Clear conversation history and screen
  /exit                Exit CuddleWrap

Usage:
  @path/to/file        Include file contents in your message
  You can use multiple @file references in one message.

Tools (available to the model):
  bash                 Execute shell commands (always requires confirmation)
  write_file           Create or overwrite files (requires confirmation)
  edit_file            Search-and-replace in files (requires confirmation)
  read_file            Read file contents (auto-approved)
  glob_search          Find files by name pattern (auto-approved)
  grep_search          Search file contents by regex (auto-approved)
"""
    )


def cmd_exit(args, state):
    """Exit the program."""
    return "EXIT"


def cmd_clear(args, state):
    """Save current conversation to history, then start a new one."""
    from cuddlewrap.agent import SYSTEM_PROMPT
    from cuddlewrap.history import save_conversation
    # Save the current conversation before wiping
    saved = save_conversation(state["messages"])
    state["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}]
    os.system("cls" if os.name == "nt" else "clear")
    if saved:
        display.harness_info("conversation saved to history")
    display.harness_info("new conversation started")
    print()


def cmd_model(args, state):
    """Show, switch, or list models."""
    if args == "list":
        try:
            models = ollama.list()
            print("\n  Available models:")
            for m in models.models:
                name = m.model
                size_gb = m.size / (1024 ** 3)
                marker = " (active)" if name == state["model"] else ""
                print(f"    {name:<30} {size_gb:.1f} GB{marker}")
            print()
        except Exception as e:
            display.harness_error(f"error listing models: {e}")
    elif args:
        state["model"] = args
        display.harness_info(f"switched to model '{args}'")
        # Persist to config
        try:
            save_config({"model": args})
        except Exception:
            pass
    else:
        print(f"\n  Current model: {state['model']}")
        print(f"  Tip: /model list — show all available models\n")


def cmd_settings(args, state):
    """Show current settings."""
    agents_md = "found" if os.path.isfile("AGENTS.md") or os.path.isfile("agents.md") else "not found"
    print(
        f"""
Settings:
  model:          {state['model']}
  max_iterations: {state['max_iterations']}
  timeout:        120s
  config file:    {CONFIG_FILE}
  AGENTS.md:      {agents_md}
"""
    )


def _replay_conversation(messages):
    """Replay past conversation exactly as it appeared live. No truncation."""
    for msg in messages:
        role = msg.get("role") or (msg.role if hasattr(msg, "role") else None)
        content = msg.get("content") or (msg.content if hasattr(msg, "content") else "")

        if role == "system":
            continue
        elif role == "user":
            print(f"{display.C.BOLD}› {content}{display.C.RESET}")
        elif role == "assistant":
            if content:
                display.model_text(content)
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name", "?")
                tc_args = tc.get("arguments", {})
                display.tool_call(name, str(tc_args).strip("{}"))
        elif role == "tool":
            display.tool_output(content)

    print()  # Blank line before new prompt


def cmd_resume(args, state):
    """Resume a past conversation. Arg is the conversation slug from autocomplete."""
    conversations = list_conversations()

    if not conversations:
        display.harness_info("no conversation history yet")
        return

    # No args → resume the most recent conversation
    if not args:
        args = conversations[0][1]  # slug of most recent

    # Find matching conversation by slug
    for filepath, slug, ts in conversations:
        if slug == args or args in slug:
            messages = load_conversation(filepath)
            if messages:
                state["messages"] = messages
                display.harness_info(f"resumed '{slug}' ({ts.strftime('%Y-%m-%d %H:%M')})")
                display.harness_info(f"{len(messages)} messages loaded\n")
                _replay_conversation(messages)
            else:
                display.harness_error("failed to load conversation")
            return

    display.harness_error(f"no conversation matching '{args}'")


INIT_PROMPT = """\
Generate an AGENTS.md file for this project. This file is loaded into your \
system prompt on future sessions, so write instructions that help you (an AI \
coding assistant) work effectively on this project.

Step 1: Use glob_search with pattern '*' to see what files exist in the current directory.

Step 2: If there ARE files, use read_file to inspect the key ones (configs, READMEs, \
entry points), then use write_file to create AGENTS.md with these sections:
  # Project Instructions
  ## Project Overview — what this project does, tech stack, purpose
  ## Architecture — key files/modules and how they connect
  ## Conventions — coding style, naming patterns, frameworks used
  ## Common Commands — build, test, run, deploy commands
  ## Important Notes — gotchas, warnings, things to remember

Step 2 (alternative): If the directory is EMPTY or has no meaningful files, \
DO NOT try to explore parent directories or other paths. Instead, respond with \
a message asking the user to describe what the project is about, what tech stack \
they plan to use, and any conventions they want to follow. Then STOP and wait. \
Do NOT create a generic AGENTS.md — it must be specific to this project.

Keep it concise (under 200 lines). Write the file as AGENTS.md in the current directory.
"""


def cmd_init(args, state):
    """Scan the project and generate an AGENTS.md using the model.

    Runs a mini conversation loop: the model explores, may ask the user
    for details, and keeps going until AGENTS.md is created or the user cancels.
    """
    from cuddlewrap.agent import run_turn
    from cuddlewrap.tools import TOOLS, TOOL_MAP

    filename = "AGENTS.md"
    if os.path.isfile(filename):
        display.harness_info(f"{filename} already exists. Delete it first to regenerate.")
        return

    display.harness_info("scanning project to generate AGENTS.md...")
    display.harness_info("(type 'cancel' to abort)\n")

    # Separate conversation just for init — doesn't pollute main chat
    init_messages = [
        {"role": "system", "content": state["messages"][0]["content"]},
        {"role": "user", "content": INIT_PROMPT},
    ]

    # Loop: let model explore, ask questions, user responds, until AGENTS.md exists
    max_rounds = 5
    for _round in range(max_rounds):
        try:
            init_messages = run_turn(init_messages, state["model"], TOOLS, TOOL_MAP)
        except KeyboardInterrupt:
            display.harness_info("init interrupted")
            return
        except Exception as e:
            display.harness_error(f"init failed: {e}")
            return

        # Check if AGENTS.md was created
        if os.path.isfile(filename):
            display.harness_info(f"created {filename} — it will be loaded on next startup")
            display.harness_info("review and edit it to match your project's conventions")
            return

        # Model asked a question — get user's response and continue
        try:
            user_reply = display.get_input()
        except (KeyboardInterrupt, EOFError):
            display.harness_info("init cancelled")
            return

        if user_reply.lower() in ("cancel", "abort", "quit"):
            display.harness_info("init cancelled")
            return

        init_messages.append({"role": "user", "content": user_reply
            + "\n\nNow use write_file to create AGENTS.md based on this information."
            + " Do NOT create the actual project files — only create AGENTS.md."})

    display.harness_error("could not generate AGENTS.md — create it manually or try /init again")


COMMANDS = {
    "help": cmd_help,
    "exit": cmd_exit,
    "clear": cmd_clear,
    "model": cmd_model,
    "settings": cmd_settings,
    "resume": cmd_resume,
    "init": cmd_init,
}


def run_command(cmd_name, args, state):
    """Execute a slash command. Returns 'EXIT' to quit, else None."""
    handler = COMMANDS.get(cmd_name)
    if not handler:
        display.harness_error(f"unknown command '/{cmd_name}'. Type /help for commands")
        return None
    return handler(args, state)
