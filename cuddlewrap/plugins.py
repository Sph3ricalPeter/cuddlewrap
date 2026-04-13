"""Plugin discovery and loading for CuddleWrap.

Plugins are Python files in ~/.cuddlewrap/plugins/ that define tool functions
with Google-style docstrings. They're auto-discovered at startup and registered
alongside built-in tools.

Plugin conventions:
  - Each .py file can define one or more tool functions
  - Functions must have type hints and Google-style docstrings
  - Optionally define SAFE_TOOLS, CONFIRM_TOOLS, ALWAYS_CONFIRM_TOOLS sets
  - If no permission sets are defined, all plugin tools require confirmation
"""

import importlib.util
import os
import inspect

from cuddlewrap import display
from cuddlewrap.config import CONFIG_DIR

PLUGINS_DIR = os.path.join(CONFIG_DIR, "plugins")


def discover_plugins():
    """Scan ~/.cuddlewrap/plugins/ and load all plugin tools.

    Returns:
        tools: list of callable functions to pass to ollama.chat()
        tool_map: dict of {name: callable}
        safe: set of tool names that are safe (auto-approve)
        always_confirm: set of tool names that always need confirmation
    """
    tools = []
    tool_map = {}
    safe = set()
    always_confirm = set()

    if not os.path.isdir(PLUGINS_DIR):
        return tools, tool_map, safe, always_confirm

    for filename in sorted(os.listdir(PLUGINS_DIR)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        filepath = os.path.join(PLUGINS_DIR, filename)
        plugin_name = filename[:-3]  # strip .py

        try:
            spec = importlib.util.spec_from_file_location(
                f"cuddlewrap_plugin_{plugin_name}", filepath
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            display.harness_error(f"failed to load plugin '{filename}': {e}")
            continue

        # Collect permission sets from the module
        plugin_safe = getattr(module, "SAFE_TOOLS", set())
        plugin_always = getattr(module, "ALWAYS_CONFIRM_TOOLS", set())

        # Find all public functions with docstrings (these are tools)
        count = 0
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue
            if not func.__doc__:
                continue
            # Only include functions defined in this module (not imports)
            if func.__module__ != module.__name__:
                continue

            tools.append(func)
            tool_map[name] = func
            count += 1

            if name in plugin_safe:
                safe.add(name)
            elif name in plugin_always:
                always_confirm.add(name)

        if count > 0:
            display.harness_info(f"loaded plugin '{plugin_name}' ({count} tools)")

    return tools, tool_map, safe, always_confirm


def ensure_plugins_dir():
    """Create ~/.cuddlewrap/plugins/ if it doesn't exist."""
    os.makedirs(PLUGINS_DIR, exist_ok=True)
