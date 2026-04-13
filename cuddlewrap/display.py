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


# ── Input functions (these render the toolbar) ──

_non_empty = Validator.from_callable(
    lambda text: len(text.strip()) > 0,
    error_message="",
    move_cursor_to_end=True,
)


def get_input():
    """Get user input with the persistent bottom toolbar.

    Blocks empty submissions — Enter on a blank line does nothing.
    Raises EOFError on Ctrl+D, KeyboardInterrupt on Ctrl+C.
    """
    return pt_prompt(
        [("bold", "› ")],
        bottom_toolbar=_toolbar_html,
        validator=_non_empty,
    ).strip()


def confirm_tool(tool_name):
    """Ask for confirmation to run a tool.

    The prompt disappears after input — only a [cw] status line remains.
    Returns 'y' or 'n'. 'a' enables auto-approve and returns 'y'.
    """
    global _auto_approve

    if _auto_approve:
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
        result = pt_prompt(
            [("class:yellow", f"  Run {tool_name}? [y/n/a] ")],
            bottom_toolbar=_toolbar_html,
            key_bindings=bindings,
        )
        choice = result.strip().lower() if result else "n"

        # Erase the prompt line — move up, clear, so it doesn't stay in history
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
