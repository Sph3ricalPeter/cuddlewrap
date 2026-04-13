"""Tool definitions for CuddleWrap."""

import fnmatch
import json
import os
import re
import subprocess
import urllib.request
import urllib.parse

# The sandbox root — set at startup, all file tools are jailed to this
SANDBOX_ROOT = os.path.abspath(os.getcwd())

# Permission tiers
SAFE_TOOLS = {"read_file", "glob_search", "grep_search", "web_search"}   # Always auto-approve
CONFIRM_TOOLS = {"write_file", "edit_file"}                  # Auto-approve with 'a'
ALWAYS_CONFIRM_TOOLS = {"bash"}                              # Always confirm, never auto

# Truncate tool output sent to the model beyond this limit
MAX_OUTPUT_CHARS = 10_000


# ── Sandbox validation ──

def _check_sandbox(path):
    """Validate that a path resolves within SANDBOX_ROOT.

    Returns the absolute path if safe, raises ValueError if not.
    """
    abs_path = os.path.abspath(path)
    # os.path.commonpath handles trailing slashes, case on Windows, etc.
    try:
        common = os.path.commonpath([abs_path, SANDBOX_ROOT])
    except ValueError:
        # Different drives on Windows (e.g. C: vs D:)
        raise ValueError(f"Path '{path}' is outside the project directory")
    if common != SANDBOX_ROOT:
        raise ValueError(f"Path '{path}' is outside the project directory")
    return abs_path


def _check_bash_paths(command):
    """Best-effort detection of paths outside the sandbox in a bash command.

    Returns a list of suspicious path fragments found, or empty list if clean.
    """
    suspicious = []

    # Detect absolute paths (Windows drive letters with \ or /, or Unix /)
    # that don't start with the sandbox root
    abs_pattern = re.compile(
        r'(?:[A-Za-z]:[/\\][^\s"\'|&>]+|/(?:etc|usr|home|tmp|var|root|opt|mnt|boot|sys|proc)[/\w]*)',
    )
    for match in abs_pattern.finditer(command):
        found = match.group()
        try:
            resolved = os.path.abspath(found)
            common = os.path.commonpath([resolved, SANDBOX_ROOT])
            if common != SANDBOX_ROOT:
                suspicious.append(found)
        except (ValueError, OSError):
            suspicious.append(found)

    # Detect .. traversal that escapes the sandbox
    if ".." in command:
        # Try to resolve relative paths containing ..
        parts = re.findall(r'["\']?(\S*\.\.[^\s"\'|&>]*)["\']?', command)
        for part in parts:
            try:
                resolved = os.path.abspath(part)
                common = os.path.commonpath([resolved, SANDBOX_ROOT])
                if common != SANDBOX_ROOT:
                    suspicious.append(part)
            except (ValueError, OSError):
                suspicious.append(part)

    return suspicious


# ── Tools ──

def bash(command: str) -> str:
    """Execute a shell command on the user's machine and return the output.

    Args:
        command (str): The shell command to execute

    Returns:
        str: The combined stdout and stderr output of the command
    """
    # Check for paths escaping the sandbox
    suspicious = _check_bash_paths(command)
    if suspicious:
        paths = ", ".join(suspicious)
        return f"[blocked: command references paths outside project directory: {paths}]"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=SANDBOX_ROOT,
            stdin=subprocess.DEVNULL,
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
        abs_path = _check_sandbox(path)
        parent = os.path.dirname(abs_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        lines = content.count("\n") + 1
        return f"Wrote {lines} lines to {abs_path}"
    except ValueError as e:
        return f"[blocked: {e}]"
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
        abs_path = _check_sandbox(path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        numbered = [f"{i + 1:4d} | {line.rstrip()}" for i, line in enumerate(lines)]
        return "\n".join(numbered) if numbered else "(empty file)"
    except ValueError as e:
        return f"[blocked: {e}]"
    except FileNotFoundError:
        return f"[error: file not found: {path}]"
    except Exception as e:
        return f"[error: {e}]"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace a specific text occurrence in a file.

    Args:
        path (str): The file path to edit
        old_text (str): The exact text to find and replace
        new_text (str): The text to replace it with

    Returns:
        str: Confirmation with line numbers affected, or an error message
    """
    try:
        abs_path = _check_sandbox(path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        count = content.count(old_text)
        if count == 0:
            return f"[error: old_text not found in {path}]"
        if count > 1:
            return f"[error: old_text found {count} times in {path} — must be unique. Provide more context.]"

        before_match = content[: content.index(old_text)]
        start_line = before_match.count("\n") + 1
        end_line = start_line + old_text.count("\n")

        new_content = content.replace(old_text, new_text, 1)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        new_line_count = new_text.count("\n") + 1
        return f"Edited {abs_path} lines {start_line}-{end_line} ({new_line_count} new lines)"
    except ValueError as e:
        return f"[blocked: {e}]"
    except FileNotFoundError:
        return f"[error: file not found: {path}]"
    except Exception as e:
        return f"[error: {e}]"


def glob_search(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern recursively.

    Args:
        pattern (str): The glob pattern to match (e.g. '*.py', '**/*.ts')
        path (str): The directory to search in (default: current directory)

    Returns:
        str: Matching file paths, one per line, or a message if none found
    """
    try:
        base = _check_sandbox(path)
        matches = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                "node_modules", "__pycache__", ".git", "venv", ".venv",
            )]
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    full = os.path.join(root, filename)
                    rel = os.path.relpath(full, base)
                    matches.append(rel)
        if not matches:
            return f"No files matching '{pattern}' found in {base}"
        matches.sort()
        return "\n".join(matches)
    except ValueError as e:
        return f"[blocked: {e}]"
    except Exception as e:
        return f"[error: {e}]"


def grep_search(pattern: str, path: str = ".", include: str = "") -> str:
    """Search file contents for lines matching a regex pattern.

    Args:
        pattern (str): The regex pattern to search for
        path (str): The directory or file to search in (default: current directory)
        include (str): Optional glob to filter files (e.g. '*.py')

    Returns:
        str: Matching lines with file paths and line numbers
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"[error: invalid regex: {e}]"

    try:
        base = _check_sandbox(path)
        results = []
        max_results = 50

        if os.path.isfile(base):
            files_to_search = [base]
        else:
            files_to_search = []
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                    "node_modules", "__pycache__", ".git", "venv", ".venv",
                )]
                for filename in files:
                    if include and not fnmatch.fnmatch(filename, include):
                        continue
                    files_to_search.append(os.path.join(root, filename))

        for filepath in files_to_search:
            if len(results) >= max_results:
                break
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if compiled.search(line):
                            rel = os.path.relpath(filepath, base) if not os.path.isfile(base) else os.path.basename(filepath)
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= max_results:
                                break
            except (PermissionError, OSError):
                continue

        if not results:
            return f"No matches for '{pattern}' in {base}"

        output = "\n".join(results)
        if len(results) >= max_results:
            output += f"\n... (limited to {max_results} results)"
        return output
    except ValueError as e:
        return f"[blocked: {e}]"
    except Exception as e:
        return f"[error: {e}]"


def web_search(query: str) -> str:
    """Search the web and return top results with titles, snippets, and URLs.

    Args:
        query (str): The search query

    Returns:
        str: Top search results formatted as title, snippet, and URL
    """
    try:
        # Use DuckDuckGo HTML endpoint (no API key needed)
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Parse results from HTML (simple regex extraction)
        results = []
        # DuckDuckGo HTML results are in <a class="result__a"> with <a class="result__snippet">
        title_pattern = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'class="result__snippet">(.*?)</(?:a|td)', re.DOTALL)
        url_pattern = re.compile(r'class="result__url"[^>]*>(.*?)</a>', re.DOTALL)

        titles = title_pattern.findall(html)
        snippets = snippet_pattern.findall(html)
        urls = url_pattern.findall(html)

        for i in range(min(5, len(titles))):
            title = re.sub(r"<[^>]+>", "", titles[i]).strip()
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
            link = re.sub(r"<[^>]+>", "", urls[i]).strip() if i < len(urls) else ""
            results.append(f"{i+1}. {title}\n   {snippet}\n   {link}")

        if not results:
            return f"No results found for '{query}'"
        return "\n\n".join(results)
    except Exception as e:
        return f"[error: web search failed: {e}]"


def truncate_output(result):
    """Truncate tool output if it exceeds MAX_OUTPUT_CHARS for context management."""
    if len(result) <= MAX_OUTPUT_CHARS:
        return result
    half = MAX_OUTPUT_CHARS // 2
    return (
        result[:half]
        + f"\n\n... [{len(result) - MAX_OUTPUT_CHARS} chars truncated] ...\n\n"
        + result[-half:]
    )


TOOLS = [bash, write_file, read_file, edit_file, glob_search, grep_search, web_search]
TOOL_MAP = {
    "bash": bash,
    "write_file": write_file,
    "read_file": read_file,
    "edit_file": edit_file,
    "glob_search": glob_search,
    "grep_search": grep_search,
    "web_search": web_search,
}
