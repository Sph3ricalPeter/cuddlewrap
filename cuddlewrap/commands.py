"""Slash command dispatch for CuddleWrap."""

import os
import re

import ollama


def parse_command(line):
    """Parse a /command from user input.

    Returns:
        (cmd_name, args_string) if valid command,
        (None, error_message) if it looks like a command but is malformed,
        None if not a command at all.
    """
    if not line.startswith("/"):
        return None
    # It starts with / so the user intended a command
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
  /clear               Clear conversation history and screen
  /exit                Exit CuddleWrap

Usage:
  @path/to/file        Include file contents in your message
  You can use multiple @file references in one message.

Tools (available to the model):
  bash                 Execute shell commands (requires confirmation)
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
    """Clear conversation history and screen."""
    state["messages"] = [state["messages"][0]]  # Keep system prompt
    os.system("cls" if os.name == "nt" else "clear")
    print("[cw: conversation cleared]\n")


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
            print(f"  [cw: error listing models: {e}]\n")
    elif args:
        state["model"] = args
        print(f"[cw: switched to model '{args}']\n")
    else:
        print(f"[cw: current model is '{state['model']}']\n")
        print(f"  Tip: /model list — show all available models\n")


def cmd_settings(args, state):
    """Show current settings."""
    print(
        f"""
Settings:
  model:          {state['model']}
  max_iterations: {state['max_iterations']}
  timeout:        120s
"""
    )


COMMANDS = {
    "help": cmd_help,
    "exit": cmd_exit,
    "clear": cmd_clear,
    "model": cmd_model,
    "settings": cmd_settings,
}


def run_command(cmd_name, args, state):
    """Execute a slash command. Returns 'EXIT' to quit, else None."""
    handler = COMMANDS.get(cmd_name)
    if not handler:
        print(f"[cw: unknown command '/{cmd_name}'. Type /help for commands]\n")
        return None
    return handler(args, state)
