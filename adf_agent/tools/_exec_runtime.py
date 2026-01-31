"""
exec_python runtime helpers.

Imported by exec_python via subprocess, providing common data processing utility functions.
User code can use these functions directly without redefining them.
"""

import json  # noqa: F401
import re  # noqa: F401
import sys  # noqa: F401
from collections import Counter, defaultdict  # noqa: F401
from pathlib import Path

__all__ = [
    # Common standard libraries (directly available to user code)
    "json", "re", "sys", "Path", "Counter", "defaultdict",
    # Runtime variables
    "session_dir",
    # Helper functions
    "_init", "load_json", "save_json", "pretty_print",
]

# Set by _init()
session_dir: Path = Path(".")


def _init(sd: str) -> None:
    """Initialize session_dir (called automatically by exec_python, cwd is set by subprocess)"""
    global session_dir
    session_dir = Path(sd)


def load_json(filename: str):
    """Load JSON file from session directory"""
    filepath = session_dir / filename
    if not filepath.exists():
        raise FileNotFoundError(
            f"File not found: {filename}. Use list_dir() to see available files."
        )
    return json.loads(filepath.read_text(encoding="utf-8"))


def save_json(filename: str, data) -> None:
    """Save data as JSON to session directory"""
    filepath = session_dir / filename
    filepath.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved to {filename}")


def pretty_print(data, max_items: int = 10) -> None:
    """Pretty print JSON data with truncation"""
    if isinstance(data, list) and len(data) > max_items:
        print(f"Showing first {max_items} of {len(data)} items:")
        print(json.dumps(data[:max_items], indent=2, ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
