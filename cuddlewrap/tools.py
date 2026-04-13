"""Tool definitions for CuddleWrap."""

import os
import subprocess


def bash(command: str) -> str:
    """Execute a shell command on the user's machine and return the output.

    Args:
        command (str): The shell command to execute

    Returns:
        str: The combined stdout and stderr output of the command
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.getcwd(),
        )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "[error: command timed out after 120 seconds]"
    except Exception as e:
        return f"[error: {e}]"


def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with the given content.

    Args:
        path (str): The file path to write to
        content (str): The full content to write to the file

    Returns:
        str: Confirmation message or error
    """
    try:
        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        lines = content.count("\n") + 1
        return f"Wrote {lines} lines to {abs_path}"
    except Exception as e:
        return f"[error: {e}]"


def read_file(path: str) -> str:
    """Read the contents of a file and return it with line numbers.

    Args:
        path (str): The file path to read

    Returns:
        str: The file contents with line numbers, or an error message
    """
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        numbered = [f"{i + 1:4d} | {line.rstrip()}" for i, line in enumerate(lines)]
        return "\n".join(numbered) if numbered else "(empty file)"
    except FileNotFoundError:
        return f"[error: file not found: {path}]"
    except Exception as e:
        return f"[error: {e}]"


TOOLS = [bash, write_file, read_file]
TOOL_MAP = {"bash": bash, "write_file": write_file, "read_file": read_file}
