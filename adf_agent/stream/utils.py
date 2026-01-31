"""
Stream utility functions and constants

Provides unified helper functions and constant definitions.
"""

import sys
from pathlib import Path, PurePath
from enum import Enum


# === Status prefix constants ===
SUCCESS_PREFIX = "[OK]"
FAILURE_PREFIX = "[FAILED]"


# === Tool status indicators ===
class ToolStatus(str, Enum):
    """Tool execution status indicators (Claude Code style)"""
    RUNNING = "●"   # Running - yellow
    SUCCESS = "●"   # Success - green
    ERROR = "●"     # Error - red
    PENDING = "○"   # Pending - gray


def get_status_symbol(status: ToolStatus) -> str:
    """
    Get status symbol, with ASCII fallback for Windows cmd.exe

    On terminals that don't support Unicode (e.g. Windows cmd.exe),
    dot symbols may render as boxes, so ASCII fallbacks are provided.

    Args:
        status: Tool status

    Returns:
        Status symbol (Unicode or ASCII)
    """
    # Check Unicode support
    try:
        supports_unicode = (
            sys.stdout.encoding
            and 'utf' in sys.stdout.encoding.lower()
        )
    except Exception:
        supports_unicode = False

    if supports_unicode:
        return status.value

    # ASCII fallback
    fallback = {
        ToolStatus.RUNNING: "*",
        ToolStatus.SUCCESS: "+",
        ToolStatus.ERROR: "x",
        ToolStatus.PENDING: "-",
    }
    return fallback.get(status, "?")


# === Display limit constants ===
class DisplayLimits:
    """Display-related length limits"""
    THINKING_STREAM = 1000      # Thinking length during streaming
    THINKING_FINAL = 2000       # Thinking length for final display
    ARGS_INLINE = 100           # Args length for inline display
    ARGS_FORMATTED = 300        # Args length for formatted display
    TOOL_RESULT_STREAM = 500    # Tool result length during streaming
    TOOL_RESULT_FINAL = 800     # Tool result length for final display
    TOOL_RESULT_MAX = 2000      # Maximum tool result length


def has_args(args) -> bool:
    """
    Check if args has content

    Fixes empty dict falsy issue: empty dict {} is falsy in Python,
    but for tool calls, an empty dict means no arguments, which is valid.

    Args:
        args: Tool arguments, may be None, {} or a dict with arguments

    Returns:
        True if args has actual content (not None and not empty dict)
    """
    return args is not None and args != {}


def is_success(content: str) -> bool:
    """
    Determine whether tool output indicates successful execution

    Based on [OK]/[FAILED] prefix detection.

    Args:
        content: Tool output content

    Returns:
        True if execution was successful
    """
    content = content.strip()
    if content.startswith(SUCCESS_PREFIX):
        return True
    if content.startswith(FAILURE_PREFIX):
        return False
    # Other cases: detect error patterns
    error_patterns = [
        'Traceback (most recent call last)',
        'Exception:',
        'Error:',
    ]
    return not any(pattern in content for pattern in error_patterns)


def resolve_path(file_path: str, working_directory: Path) -> Path:
    """
    Resolve file path, handling relative paths and ~ expansion

    Args:
        file_path: File path (absolute or relative, supports ~ for home directory)
        working_directory: Working directory

    Returns:
        Resolved absolute path
    """
    path = Path(file_path).expanduser()  # Handle ~ expansion
    if not path.is_absolute():
        path = working_directory / path
    return path


def truncate(content: str, max_length: int, suffix: str = "\n... (truncated)") -> str:
    """
    Truncate content to specified length

    Args:
        content: Content to truncate
        max_length: Maximum length
        suffix: Suffix to append after truncation

    Returns:
        Truncated content
    """
    if len(content) > max_length:
        return content[:max_length] + suffix
    return content


# === Claude Code style compact formatting ===

def format_tool_compact(name: str, args: dict | None) -> str:
    """
    Format as Claude Code style compact format: ToolName(arg1, arg2, ...)

    Args:
        name: Tool name
        args: Tool arguments dictionary

    Returns:
        Formatted string, e.g. "Bash(git status)" or "Read(path/to/file.py)"
    """
    if not args:
        return f"{name}()"

    # Extract key parameters for common tools
    name_lower = name.lower()

    if name_lower == "bash":
        cmd = args.get("command", "")
        # Truncate long commands
        if len(cmd) > 50:
            cmd = cmd[:47] + "..."
        return f"Bash({cmd})"

    elif name_lower in ("read", "read_file"):
        path = args.get("file_path", "")
        # Show only filename or short path (cross-platform compatible)
        if len(path) > 40:
            path_obj = PurePath(path)
            parts = path_obj.parts
            if len(parts) > 2:
                path = ".../" + "/".join(parts[-2:])
        return f"Read({path})"

    elif name_lower in ("write", "write_file"):
        path = args.get("file_path", "")
        if len(path) > 40:
            path_obj = PurePath(path)
            parts = path_obj.parts
            if len(parts) > 2:
                path = ".../" + "/".join(parts[-2:])
        return f"Write({path})"

    elif name_lower == "edit":
        path = args.get("file_path", "")
        if len(path) > 40:
            path_obj = PurePath(path)
            parts = path_obj.parts
            if len(parts) > 2:
                path = ".../" + "/".join(parts[-2:])
        return f"Edit({path})"

    elif name_lower == "glob":
        pattern = args.get("pattern", "")
        if len(pattern) > 40:
            pattern = pattern[:37] + "..."
        return f"Glob({pattern})"

    elif name_lower == "grep":
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        if len(pattern) > 30:
            pattern = pattern[:27] + "..."
        return f"Grep({pattern}, {path})"

    elif name_lower == "list_dir":
        path = args.get("path", ".")
        return f"ListDir({path})"

    elif name_lower == "exec_python":
        code = args.get("code", "")
        # Show first line of code or first 30 characters
        first_line = code.split('\n')[0] if code else ""
        if len(first_line) > 30:
            first_line = first_line[:27] + "..."
        return f"exec_python({first_line})"

    # Compact format for ADF tools
    elif name_lower.startswith("adf_"):
        # Extract key parameters
        key_params = []
        for key in ["name", "filter_type", "minutes"]:
            if key in args:
                val = str(args[key])
                if len(val) > 20:
                    val = val[:17] + "..."
                key_params.append(val)
        params_str = ", ".join(key_params) if key_params else ""
        return f"{name}({params_str})"

    # Default format: show first few parameters
    params = []
    for k, v in list(args.items())[:2]:
        v_str = str(v)
        if len(v_str) > 20:
            v_str = v_str[:17] + "..."
        params.append(f"{k}={v_str}")

    params_str = ", ".join(params)
    if len(params_str) > 50:
        params_str = params_str[:47] + "..."

    return f"{name}({params_str})"


def format_tree_output(lines: list[str], max_lines: int = 5, indent: str = "  ") -> str:
    """
    Format output as tree structure (Claude Code style)

    Args:
        lines: List of output lines
        max_lines: Maximum number of lines to display
        indent: Indent characters

    Returns:
        Formatted tree output string

    Example output:
        └ On branch main
          Your branch is up to date
          ... +16 lines
    """
    if not lines:
        return ""

    result = []
    display_lines = lines[:max_lines]

    for i, line in enumerate(display_lines):
        prefix = "└" if i == 0 else " "
        result.append(f"{indent}{prefix} {line}")

    # Show collapse hint if there are more lines
    remaining = len(lines) - max_lines
    if remaining > 0:
        result.append(f"{indent}  ... +{remaining} lines")

    return "\n".join(result)


def count_lines(content: str) -> int:
    """Count lines in content"""
    if not content:
        return 0
    return len(content.strip().split("\n"))


def truncate_with_line_hint(content: str, max_lines: int = 5) -> tuple[str, int]:
    """
    Truncate content by line count and return remaining line count

    Args:
        content: Content to truncate
        max_lines: Maximum number of lines to display

    Returns:
        (truncated content, remaining line count)
    """
    lines = content.strip().split("\n")
    total = len(lines)

    if total <= max_lines:
        return content.strip(), 0

    truncated = "\n".join(lines[:max_lines])
    remaining = total - max_lines
    return truncated, remaining
