"""Agentic loop for CuddleWrap — sends messages to the LLM and handles tool calls."""

import concurrent.futures
import os
import platform
import re
import ollama

from cuddlewrap import display
from cuddlewrap.agentsmd import load_agents_md
from cuddlewrap.display import Spinner
from cuddlewrap.tools import SAFE_TOOLS, ALWAYS_CONFIRM_TOOLS, truncate_output

MAX_ITERATIONS = 15
_model_ctx_cache = {}


def _build_system_prompt():
    """Build system prompt with OS-specific instructions."""
    shell = "cmd.exe / PowerShell" if os.name == "nt" else "bash"
    os_name = platform.system()
    cwd = os.getcwd()

    base = (
        f"You are an expert software engineer. You have access to tools to execute "
        f"shell commands, read files, write files, edit files, and search the codebase.\n"
        f"Use write_file to create new files OR when making large/many changes to a file.\n"
        f"Use edit_file only for small, targeted changes (1-2 replacements max).\n"
        f"NEVER use echo/type redirects to write files.\n"
        f"Use glob_search to find files by name and grep_search to find text in files.\n"
        f"Use python_run to run Python scripts (NOT 'bash python'). Use pip_install for packages.\n"
        f"Use web_search to look up ANYTHING you don't know — you DO have internet access via this tool.\n"
        f"NEVER say 'I can't access the internet' — use web_search instead.\n\n"
        f"Environment:\n"
        f"  OS: {os_name}\n"
        f"  Shell: {shell}\n"
        f"  CWD: {cwd}\n\n"
        f"{'IMPORTANT: Use Windows-compatible commands (dir, type, copy, del, etc). Use backslashes in paths.' if os.name == 'nt' else ''}\n"
        f"Use the bash tool to explore files, run code, install packages, and accomplish "
        f"tasks the user requests. Always explain what you are about to do before calling "
        f"a tool. Be concise. When a task is complete, summarize what you did."
    )

    # Append AGENTS.md instructions if they exist
    agents_md = load_agents_md()
    if agents_md:
        base += f"\n\n---\n\n{agents_md}"

    return base


SYSTEM_PROMPT = _build_system_prompt()


def _call_llm(model, messages, tools):
    """Call ollama.chat in a thread with a spinner, interruptible by Ctrl+C."""
    spinner = Spinner("thinking")
    spinner.start()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(ollama.chat, model=model, messages=messages, tools=tools)
    try:
        while True:
            try:
                result = future.result(timeout=0.3)
                spinner.stop()
                pool.shutdown(wait=False)
                return result
            except concurrent.futures.TimeoutError:
                continue
    except KeyboardInterrupt:
        spinner.stop()
        future.cancel()
        pool.shutdown(wait=False)
        raise


def _get_max_ctx(model):
    """Get the max context window size for a model (cached)."""
    if model in _model_ctx_cache:
        return _model_ctx_cache[model]
    try:
        info = ollama.show(model)
        for key, value in info.modelinfo.items():
            if key.endswith("context_length"):
                _model_ctx_cache[model] = int(value)
                return _model_ctx_cache[model]
    except Exception:
        pass
    return None


def _context_indicator(used, total):
    """Render a compact context usage string."""
    if total >= 1_000_000:
        total_label = f"{total / 1_000_000:.0f}M"
    elif total >= 1_000:
        total_label = f"{total / 1_000:.0f}K"
    else:
        total_label = str(total)

    pct = min(used / total * 100, 100)

    if pct < 1:
        return f"{used:,} / {total_label}"
    else:
        filled = round(pct / 10)
        bar = "#" * filled + "-" * (10 - filled)
        return f"[{bar}] {pct:.0f}% of {total_label}"


def _sanitize(text):
    """Strip control characters that mess up the terminal."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    return text


def _update_context(response, model):
    """Update the toolbar with current context usage."""
    max_ctx = _get_max_ctx(model)
    if max_ctx and hasattr(response, "prompt_eval_count") and response.prompt_eval_count:
        used = response.prompt_eval_count + (response.eval_count or 0)
        display.update_toolbar(context=_context_indicator(used, max_ctx))


def run_turn(messages, model, tools, tool_map):
    """Run one agentic turn: call LLM, execute tool calls in a loop until done."""
    try:
        response = _call_llm(model, messages, tools)
    except Exception as e:
        _handle_llm_error(e)
        return messages

    iterations = 0

    while True:
        # Print any text the model produced
        if response.message.content:
            display.model_text(_sanitize(response.message.content))

        # No tool calls -> done
        if not response.message.tool_calls:
            messages.append(response.message)
            break

        # Safety limit
        iterations += 1
        if iterations > MAX_ITERATIONS:
            display.harness_info(f"iteration limit ({MAX_ITERATIONS}) reached, stopping")
            messages.append(response.message)
            break

        # Append assistant message (with tool_calls) BEFORE tool results
        messages.append(response.message)

        # Execute tool calls — parallel for safe tools, sequential for dangerous
        tool_calls = list(response.message.tool_calls)
        _execute_tool_calls(tool_calls, tool_map, messages)

        # Send tool results back to the model
        try:
            response = _call_llm(model, messages, tools)
        except Exception as e:
            _handle_llm_error(e)
            return messages

    # Update context usage in toolbar
    _update_context(response, model)

    return messages


def _tool_args_display(name, args):
    """Build a compact display string for a tool call."""
    if name == "bash":
        return args.get("command", "")
    elif name in ("write_file", "read_file", "edit_file"):
        return args.get("path", "")
    elif name == "glob_search":
        return args.get("pattern", "")
    elif name == "grep_search":
        display_str = args.get("pattern", "")
        inc = args.get("include", "")
        if inc:
            display_str += f" ({inc})"
        return display_str
    elif name == "web_search":
        return args.get("query", "")
    elif name == "python_run":
        return args.get("script", "")
    elif name == "pip_install":
        return args.get("packages", "")
    elif name in ("format_code", "format_check", "lint_check", "lint_fix"):
        return args.get("path", ".")
    else:
        return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _execute_tool_calls(tool_calls, tool_map, messages):
    """Execute a batch of tool calls.

    Safe (read-only) tools that don't need confirmation run in parallel.
    Dangerous tools run sequentially with confirmation.
    """
    # Separate into safe (can run in parallel) and needs-confirmation
    safe_batch = []
    confirm_batch = []

    for tc in tool_calls:
        name = tc.function.name
        args = tc.function.arguments
        if name in SAFE_TOOLS:
            safe_batch.append((tc, name, args))
        else:
            confirm_batch.append((tc, name, args))

    # Run safe tools in parallel
    if len(safe_batch) > 1:
        _execute_parallel(safe_batch, tool_map, messages)
    elif safe_batch:
        _execute_single(safe_batch[0], tool_map, messages, auto=True)

    # Run dangerous tools sequentially with confirmation
    for item in confirm_batch:
        _execute_single(item, tool_map, messages, auto=False)


def _execute_parallel(batch, tool_map, messages):
    """Execute multiple safe tool calls concurrently."""
    # Show all tool calls first
    for tc, name, args in batch:
        display.tool_call(name, _tool_args_display(name, args))

    # Execute in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for tc, name, args in batch:
            func = tool_map.get(name)
            if func:
                future = pool.submit(func, **args)
                futures[future] = (name, args)
            else:
                # Unknown tool — handle inline
                messages.append({
                    "role": "tool",
                    "content": f"[error: unknown tool '{name}']",
                    "tool_name": name,
                })

        for future in concurrent.futures.as_completed(futures):
            name, args = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = f"[error: {e}]"

            # Display result — diffs shown in full, other output truncated
            display.tool_output(_display_truncate(_sanitize(result)))

            # Append to messages
            messages.append({
                "role": "tool",
                "content": str(truncate_output(result)),
                "tool_name": name,
            })


def _display_truncate(text):
    """Truncate text for display, but never truncate diffs."""
    is_diff = any(text.startswith(p) for p in ("---", "+++", "@@", "diff "))
    if is_diff:
        return text
    if len(text) > 500:
        return text[:500] + f"\n... ({len(text)} chars total)"
    return text


def _execute_single(item, tool_map, messages, auto=False):
    """Execute a single tool call with optional confirmation."""
    tc, name, args = item
    args_display = _tool_args_display(name, args)

    display.tool_call(name, args_display)

    if auto:
        choice = "y"
    elif name in ALWAYS_CONFIRM_TOOLS:
        choice = display.confirm_tool(name, force=True)
    else:
        choice = display.confirm_tool(name)

    if choice != "y":
        result = "[user declined to execute this command]"
        display.tool_declined()
    else:
        func = tool_map.get(name)
        if func:
            result = func(**args)
        else:
            result = f"[error: unknown tool '{name}']"

        display.tool_output(_display_truncate(_sanitize(result)))

    messages.append({
        "role": "tool",
        "content": str(truncate_output(result)),
        "tool_name": name,
    })


def _handle_llm_error(e):
    """Handle errors from ollama.chat with friendly messages."""
    error_str = str(e)

    if "ConnectError" in type(e).__name__ or "Connection refused" in error_str:
        display.harness_error("Cannot connect to Ollama. Is it running? Try: ollama serve")
    elif "not found" in error_str.lower() or "404" in error_str:
        display.harness_error(f"Model not found. Pull it first with: ollama pull <model>")
    elif "context length" in error_str.lower() or "too long" in error_str.lower():
        display.harness_error("Context window full. Use /clear to reset the conversation.")
    else:
        display.harness_error(f"LLM error: {error_str}")
