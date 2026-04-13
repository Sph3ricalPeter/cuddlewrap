"""CuddleWrap — a minimal LLM tool-calling harness."""

import os
import re

from cuddlewrap import display
from cuddlewrap.agent import SYSTEM_PROMPT, run_turn
from cuddlewrap.commands import parse_command, run_command
from cuddlewrap.tools import TOOLS, TOOL_MAP

DEFAULT_MODEL = "devstral-small-2"

BANNER = rf"""
{display.C.CYAN}   ______          __    ____     _       __
  / ____/__  ____/ /___/ / /__  | |     / /________ _____
 / /   / / / / __  / __  / / _ \| | /| / / ___/ __ `/ __ \
/ /___/ /_/ / /_/ / /_/ / /  __/| |/ |/ / /  / /_/ / /_/ /
\____/\__,_/\__,_/\__,_/_/\___/ |__/|__/_/   \__,_/ .___/
                                                  /_/{display.C.RESET}
"""


def resolve_file_refs(text):
    """Replace @path/to/file tokens with file contents."""
    errors = []

    def replacer(match):
        filepath = match.group(1)
        if not os.path.isfile(filepath):
            errors.append(f"File not found: {filepath}")
            return match.group(0)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return f"\n[file: {filepath}]\n{content}\n[end file: {filepath}]\n"
        except Exception as e:
            errors.append(f"Error reading {filepath}: {e}")
            return match.group(0)

    resolved = re.sub(r"@([\w./\\:~\-]+)", replacer, text)
    return resolved, errors


def main():
    """Entry point for the `cw` command."""
    os.system("cls" if os.name == "nt" else "clear")
    print(BANNER)

    state = {
        "model": DEFAULT_MODEL,
        "max_iterations": 15,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
    }

    # Initialize toolbar
    display.update_toolbar(model=state["model"], context="ready")
    display.harness_info(f"type /help for commands, @file to include files")
    print()

    while True:
        try:
            user_input = display.get_input()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Check for slash commands
        parsed = parse_command(user_input)
        if parsed is not None:
            cmd_name, args = parsed
            if cmd_name is None:
                display.harness_error(args)
                continue
            result = run_command(cmd_name, args, state)
            if result == "EXIT":
                print("Goodbye!")
                break
            # Update toolbar in case model changed
            display.update_toolbar(model=state["model"])
            continue

        # Resolve @file references
        resolved, errors = resolve_file_refs(user_input)
        for err in errors:
            display.harness_error(err)

        # Append user message and run agentic turn
        state["messages"].append({"role": "user", "content": resolved})

        try:
            state["messages"] = run_turn(
                state["messages"],
                state["model"],
                TOOLS,
                TOOL_MAP,
            )
        except KeyboardInterrupt:
            print()
            display.harness_info("interrupted")
            print()
        except Exception as e:
            display.harness_error(str(e))
            print()


if __name__ == "__main__":
    main()
