"""AGENTS.md support for CuddleWrap.

Loads project-specific instructions from AGENTS.md (project root)
and user-level defaults from ~/.cuddlewrap/AGENTS.md.
Appended to the system prompt so the model follows project conventions.
"""

import os

from cuddlewrap.config import CONFIG_DIR

# Filenames to look for (checked in order)
AGENTS_FILENAMES = ["AGENTS.md", "agents.md"]


def load_agents_md():
    """Load AGENTS.md content from project root and/or user config dir.

    Returns the combined content string (may be empty).
    Loads in order:
      1. ~/.cuddlewrap/AGENTS.md  (user-level defaults)
      2. ./AGENTS.md              (project-level, takes priority)
    """
    sections = []

    # User-level AGENTS.md
    for name in AGENTS_FILENAMES:
        user_path = os.path.join(CONFIG_DIR, name)
        if os.path.isfile(user_path):
            content = _read_file(user_path)
            if content:
                sections.append(f"# User Instructions (from {user_path})\n\n{content}")
            break

    # Project-level AGENTS.md (in CWD)
    cwd = os.getcwd()
    for name in AGENTS_FILENAMES:
        project_path = os.path.join(cwd, name)
        if os.path.isfile(project_path):
            content = _read_file(project_path)
            if content:
                sections.append(f"# Project Instructions (from {name})\n\n{content}")
            break

    return "\n\n---\n\n".join(sections)


def _read_file(path):
    """Read a file, return content or empty string on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""
