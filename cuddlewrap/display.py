"""Terminal display and input for CuddleWrap.

Uses prompt_toolkit for a persistent bottom toolbar (status bar)
that never pollutes the scrolling chat history.

Visual layout rules:
  - Model text and tool blocks are separated by blank lines
  - Within a tool block (header + output) there is NO extra spacing
  - The confirmation prompt disappears after input, leaving only a [cw] line
  - The spinner has a blank line above it for breathing room
"""

import os
import shutil
import sys
import threading

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.validation import Validator


# ── ANSI codes ──

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    RED = "\033[31m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"
    # Cursor control
    UP = "\033[A"
    CLEAR_LINE = "\033[2K"


def _enable_ansi_windows():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_ansi_windows()


# ── Shared state ──

_toolbar_state = {
    "context": "",
    "model": "",
    "mode": "chat",
    "status": "",
}

_auto_approve = False


def update_toolbar(**kwargs):
    """Update toolbar fields."""
    _toolbar_state.update(kwargs)


def set_auto_approve(value):
    """Enable/disable auto-approve for the session."""
    global _auto_approve
    _auto_approve = value


def _toolbar_html():
    """Build the toolbar content as prompt_toolkit HTML."""
    parts = []

    ctx = _toolbar_state.get("context")
    if ctx:
        parts.append(f"<b>ctx:</b> {ctx}")

    model = _toolbar_state.get("model")
    if model:
        parts.append(f"<b>model:</b> {model}")

    mode = _toolbar_state.get("mode")
    if mode:
        parts.append(f"<b>mode:</b> {mode}")

    if _auto_approve:
        parts.append("<ansiyellow>auto-approve</ansiyellow>")

    status = _toolbar_state.get("status")
    if status:
        parts.append(status)

    return HTML(" <gray>|</gray> ".join(parts)) if parts else HTML("")


# ── Spinner ──

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """Animated spinner that runs in a background thread."""

    def __init__(self, message="thinking"):
        self._message = message
        self._stop = threading.Event()
        self._thread = None

    def _animate(self):
        i = 0
        # Blank line above for breathing room (same spacing as tool calls)
        sys.stdout.write("\n")
        sys.stdout.flush()
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            sys.stdout.write(f"\r{C.CYAN}  {frame} {self._message}...{C.RESET}")
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.08)
        # Clear the spinner line and the blank line above it
        sys.stdout.write(f"\r{C.CLEAR_LINE}{C.UP}{C.CLEAR_LINE}\r")
        sys.stdout.flush()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# ── Autocomplete ──

_COMMANDS = {
    "/help": "Show available commands",
    "/model": "Show or switch model",
    "/settings": "Show current settings",
    "/resume": "Resume a past conversation",
    "/init": "Create AGENTS.md template",
    "/clear": "Clear conversation and screen",
    "/exit": "Exit CuddleWrap",
}

MAX_COMPLETIONS = 3

# Cache for available models — refreshed on /model completion
_model_cache = None
_model_cache_time = 0
_MODEL_CACHE_TTL = 30  # seconds


def _get_available_models():
    """Fetch available Ollama models, cached for 30s."""
    import time
    global _model_cache, _model_cache_time
    now = time.time()
    if _model_cache is not None and (now - _model_cache_time) < _MODEL_CACHE_TTL:
        return _model_cache
    try:
        import ollama
        result = ollama.list()
        _model_cache = [m.model for m in result.models]
        _model_cache_time = now
    except Exception:
        _model_cache = []
        _model_cache_time = now
    return _model_cache


_convo_cache = None
_convo_cache_time = 0
_CONVO_CACHE_TTL = 5  # seconds — short since convos change on /clear


def _get_conversations():
    """Fetch conversation list, cached briefly."""
    import time
    global _convo_cache, _convo_cache_time
    now = time.time()
    if _convo_cache is not None and (now - _convo_cache_time) < _CONVO_CACHE_TTL:
        return _convo_cache
    try:
        from cuddlewrap.history import list_conversations
        _convo_cache = list_conversations()
        _convo_cache_time = now
    except Exception:
        _convo_cache = []
        _convo_cache_time = now
    return _convo_cache


class CwCompleter(Completer):
    """Autocomplete for /commands, /model args, and @file paths.

    Shows up to MAX_COMPLETIONS suggestions as you type,
    in a dropdown between the prompt and the status bar.
    """

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # /resume gets more suggestions since you're browsing history
        limit = 10 if text.startswith("/resume") else MAX_COMPLETIONS
        count = 0
        for completion in self._get_all_completions(document):
            yield completion
            count += 1
            if count >= limit:
                return

    def _get_all_completions(self, document):
        text = document.text_before_cursor

        # /command completion
        if text.startswith("/"):
            parts = text.split(None, 1)
            cmd = parts[0]

            if len(parts) == 1 and not text.endswith(" "):
                for name, hint in _COMMANDS.items():
                    if name.startswith(cmd):
                        yield Completion(
                            name,
                            start_position=-len(cmd),
                            display_meta=hint,
                        )
            elif cmd == "/model":
                # Suggest "list" + available model names
                arg_text = parts[1] if len(parts) > 1 else ""
                if "list".startswith(arg_text):
                    yield Completion("list", start_position=-len(arg_text), display_meta="Show all models")
                for model_name in _get_available_models():
                    if model_name.startswith(arg_text):
                        yield Completion(model_name, start_position=-len(arg_text))
            elif cmd == "/resume":
                # Suggest past conversations from history
                arg_text = (parts[1] if len(parts) > 1 else "").lower()
                for filepath, slug, ts in _get_conversations():
                    date = ts.strftime("%m/%d %H:%M")
                    if not arg_text or arg_text in slug.lower():
                        yield Completion(
                            slug,
                            start_position=-len(parts[1]) if len(parts) > 1 else 0,
                            display=HTML(f"<b>{date}</b>  {slug}"),
                        )
            return

        # @file completion
        pos = document.cursor_position
        full_text = document.text
        at_start = None
        for i in range(pos - 1, -1, -1):
            if full_text[i] == "@":
                at_start = i
                break
            elif full_text[i] in (" ", "\t", "\n"):
                break

        if at_start is not None:
            partial = full_text[at_start + 1 : pos]
            yield from self._complete_path(partial, len(partial))

    def _complete_path(self, partial, replace_len):
        """Yield file path completions for a partial path."""
        if os.sep == "\\" and "/" in partial:
            partial = partial.replace("/", "\\")

        directory = os.path.dirname(partial) if partial else "."
        prefix = os.path.basename(partial)
        search_dir = directory if directory else "."

        try:
            entries = os.listdir(search_dir)
        except OSError:
            return

        for entry in sorted(entries):
            if entry.startswith("."):
                continue
            if entry.startswith(prefix):
                full = os.path.join(directory, entry) if directory and directory != "." else entry
                if os.path.isdir(os.path.join(search_dir, entry)):
                    full += os.sep
                yield Completion(full, start_position=-replace_len)


_completer = CwCompleter()


# ── Input functions (these render the toolbar) ──

_non_empty = Validator.from_callable(
    lambda text: len(text.strip()) > 0,
    error_message="",
    move_cursor_to_end=True,
)


def get_input():
    """Get user input with the persistent bottom toolbar.

    Completions show as-you-type in a dropdown between the prompt
    and the status bar, capped at 3 suggestions.
    Blocks empty submissions — Enter on a blank line does nothing.
    Raises EOFError on Ctrl+D, KeyboardInterrupt on Ctrl+C.
    """
    return pt_prompt(
        [("bold", "› ")],
        bottom_toolbar=_toolbar_html,
        validator=_non_empty,
        completer=_completer,
        complete_while_typing=True,
        complete_in_thread=True,            # Non-blocking, acts as debounce
        reserve_space_for_menu=MAX_COMPLETIONS + 1,  # Space for dropdown
    ).strip()


def confirm_tool(tool_name, force=False):
    """Ask for confirmation to run a tool.

    Args:
        tool_name: Name of the tool.
        force: If True, always ask even when auto-approve is on (for bash).

    The prompt disappears after input.
    Returns 'y' or 'n'. 'a' enables auto-approve and returns 'y'.
    """
    global _auto_approve

    if _auto_approve and not force:
        return "y"

    bindings = KeyBindings()

    @bindings.add("y")
    def _accept(event):
        event.app.exit(result="y")

    @bindings.add("n")
    def _reject(event):
        event.app.exit(result="n")

    @bindings.add("a")
    def _always(event):
        event.app.exit(result="a")

    @bindings.add("c-c")
    def _cancel(event):
        event.app.exit(result="n")

    try:
        label = f"  Run {tool_name}? [y/n/a] "
        result = pt_prompt(
            [("class:yellow", label)],
            bottom_toolbar=_toolbar_html,
            key_bindings=bindings,
        )
        choice = result.strip().lower() if result else "n"

        # Erase the prompt line so it doesn't stay in history
        sys.stdout.write(f"{C.UP}{C.CLEAR_LINE}\r")
        sys.stdout.flush()

        if choice == "a":
            _auto_approve = True
            return "y"
        elif choice == "y":
            return "y"
        else:
            return "n"
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write(f"{C.UP}{C.CLEAR_LINE}\r")
        sys.stdout.flush()
        return "n"


# ── Print functions (scrolling chat history) ──
#
# Layout rules:
#   model_text:  blank line above and below (major section break)
#   tool_call:   blank line above (new section), tight to output below
#   tool_output: tight to tool_call above, blank line below
#   harness:     inline, no extra spacing


def model_text(text):
    """Print model response — green, separated from surrounding content."""
    print(f"\n{C.GREEN}{text}{C.RESET}\n")


TOOL_OUTPUT_MAX_LINES = 10


def _hr():
    """Print a full-width gray horizontal rule."""
    width = shutil.get_terminal_size().columns
    print(f"{C.GRAY}{'─' * width}{C.RESET}")


def tool_call(tool_name, args_display):
    """Print a compact tool call — top rule + tool + args."""
    print()
    _hr()
    print(f"{C.YELLOW}▶ {tool_name}{C.RESET} {args_display}")


def tool_output(text):
    """Print tool output — dim, truncated to last N lines, closed with a rule."""
    lines = text.split("\n")
    if len(lines) > TOOL_OUTPUT_MAX_LINES:
        skipped = len(lines) - TOOL_OUTPUT_MAX_LINES
        print(f"  {C.DIM}({skipped} lines hidden){C.RESET}")
        lines = lines[-TOOL_OUTPUT_MAX_LINES:]
    for line in lines:
        print(f"  {C.DIM}{line}{C.RESET}")
    _hr()


def tool_declined():
    """Print when user declines a tool call."""
    print(f"  {C.DIM}(skipped){C.RESET}")
    _hr()


def harness_info(text):
    """Print harness info — gray, compact."""
    print(f"  {C.GRAY}[cw] {text}{C.RESET}")


def harness_error(text):
    """Print harness error — red."""
    print(f"  {C.RED}[cw] {text}{C.RESET}")


