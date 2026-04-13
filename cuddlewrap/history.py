"""Conversation history persistence for CuddleWrap.

Saves conversations to ~/.cuddlewrap/history/ as JSON files.
Each file is named with a timestamp and first few words of the first user message.
"""

import json
import os
import re
from datetime import datetime

from cuddlewrap.config import CONFIG_DIR

HISTORY_DIR = os.path.join(CONFIG_DIR, "history")


def _slugify(text, max_words=5):
    """Turn text into a filename-safe slug."""
    words = re.sub(r"[^\w\s]", "", text).split()[:max_words]
    return "-".join(words).lower() or "conversation"


def _get_first_user_message(messages):
    """Extract the first user message content for the filename."""
    for msg in messages:
        role = msg.get("role") or (msg.role if hasattr(msg, "role") else None)
        if role == "user":
            content = msg.get("content") or (msg.content if hasattr(msg, "content") else "")
            return content[:80]
    return "empty"


def save_conversation(messages):
    """Save a conversation to ~/.cuddlewrap/history/.

    Returns the path of the saved file, or None on error.
    """
    if len(messages) <= 1:
        return None  # Don't save empty conversations (just system prompt)

    os.makedirs(HISTORY_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(_get_first_user_message(messages))
    filename = f"{timestamp}_{slug}.json"
    filepath = os.path.join(HISTORY_DIR, filename)

    # Serialize messages — handle both dicts and ollama Message objects
    serialized = []
    for msg in messages:
        if isinstance(msg, dict):
            serialized.append(msg)
        else:
            # Ollama Message objects
            entry = {"role": msg.role, "content": msg.content or ""}
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = [
                    {"name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in msg.tool_calls
                ]
            serialized.append(entry)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2, ensure_ascii=False)
        return filepath
    except Exception:
        return None


def list_conversations(limit=20):
    """List recent conversation files.

    Returns list of (filepath, display_name, timestamp) sorted newest first.
    """
    if not os.path.isdir(HISTORY_DIR):
        return []

    files = []
    for name in os.listdir(HISTORY_DIR):
        if not name.endswith(".json"):
            continue
        filepath = os.path.join(HISTORY_DIR, name)
        # Parse timestamp from filename: YYYYMMDD_HHMMSS_slug.json
        parts = name.split("_", 2)
        if len(parts) >= 3:
            try:
                ts = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
                slug = parts[2].replace(".json", "").replace("-", " ")
                files.append((filepath, slug, ts))
            except ValueError:
                files.append((filepath, name, datetime.min))
        else:
            files.append((filepath, name, datetime.min))

    files.sort(key=lambda x: x[2], reverse=True)
    return files[:limit]


def load_conversation(filepath):
    """Load a conversation from a JSON file.

    Returns list of message dicts, or None on error.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
