"""Configuration management for CuddleWrap.

Loads settings from ~/.cuddlewrap/config.toml (if it exists).
Falls back to defaults for any missing values.
"""

import os
import tomllib

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".cuddlewrap")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")

DEFAULTS = {
    "model": "devstral-small-2",
    "max_iterations": 15,
    "timeout": 120,
}


def load_config():
    """Load config from ~/.cuddlewrap/config.toml, merged with defaults.

    Returns a plain dict with all settings.
    """
    config = dict(DEFAULTS)
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "rb") as f:
                user_config = tomllib.load(f)
            config.update(user_config)
        except Exception as e:
            print(f"[cw] Warning: could not read config: {e}")
    return config


def save_config(config):
    """Save config dict to ~/.cuddlewrap/config.toml."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lines = []
    for key, value in config.items():
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def ensure_config_dir():
    """Create ~/.cuddlewrap/ if it doesn't exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
