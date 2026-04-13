"""Agentic loop for CuddleWrap — sends messages to the LLM and handles tool calls."""

import concurrent.futures
import os
import platform
import re
import ollama

from cuddlewrap import display
from cuddlewrap.display import Spinner
from cuddlewrap.tools import SAFE_TOOLS, truncate_output

MAX_ITERATIONS = 15
_model_ctx_cache = {}


def _build_system_prompt():
    """Build system prompt with OS-specific instructions."""
    shell = "cmd.exe / PowerShell" if os.name == "nt" else "bash"
    os_name = platform.system()
    cwd = os.getcwd()

    return (
        f"You are an expert software engineer. You have access to tools to execute "
        f"shell commands, read files, write files, edit files, and search the codebase.\n"
        f"ALWAYS use write_file to create files and edit_file to modify existing files.\n"
        f"NEVER use echo/type redirects to write files.\n"
        f"Use glob_search to find files by name and grep_search to find text in files.\n\n"
        f"Environment:\n"
        f"  OS: {os_name}\n"
        f"  Shell: {shell}\n"
        f"  CWD: {cwd}\n\n"
        f"{'IMPORTANT: Use Windows-compatible commands (dir, type, copy, del, etc). Use backslashes in paths.' if os.name == 'nt' else ''}\n"
        f"Use the bash tool to explore files, run code, install packages, and accomplish "
        f"tasks the user requests. Always explain what you are about to do before calling "
        f"a tool. Be concise. When a task is complete, summarize what you did."
    )


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

        # Execute each tool call
        for tc in response.message.tool_calls:
            name = tc.function.name
            args = tc.function.arguments

            # Build compact display of the tool + args
            if name == "bash":
                args_display = args.get("command", "")
            elif name in ("write_file", "read_file", "edit_file"):
                args_display = args.get("path", "")
            elif name == "glob_search":
                args_display = args.get("pattern", "")
            elif name == "grep_search":
                args_display = args.get("pattern", "")
                inc = args.get("include", "")
                if inc:
                    args_display += f" ({inc})"
            else:
                args_display = ", ".join(f"{k}={v!r}" for k, v in args.items())

            # Show tool call (compact single line)
            display.tool_call(name, args_display)

            # Permission tiers: safe tools auto-approve, dangerous tools ask
            if name in SAFE_TOOLS:
                choice = "y"
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

                # Show result (sanitized + display-truncated) tight under the tool call
                sanitized = _sanitize(result)
                if len(sanitized) > 500:
                    sanitized = sanitized[:500] + f"\n... ({len(result)} chars total)"
                display.tool_output(sanitized)

            # Truncate for context window before appending to messages
            result_for_context = truncate_output(result)

            # Append tool result to conversation
            messages.append({
                "role": "tool",
                "content": str(result_for_context),
                "tool_name": name,
            })

        # Send tool results back to the model
        try:
            response = _call_llm(model, messages, tools)
        except Exception as e:
            _handle_llm_error(e)
            return messages

    # Update context usage in toolbar
    _update_context(response, model)

    return messages


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
