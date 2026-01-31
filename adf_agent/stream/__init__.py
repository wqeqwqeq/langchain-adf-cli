"""
Stream submodule - Streaming event processing

Provides:
- StreamEventEmitter: Event emitter
- ToolCallTracker: Tool call tracker
- ToolResultFormatter: Tool result formatter
- Utility functions: has_args, is_success, resolve_path, truncate, get_status_symbol
- Constants: SUCCESS_PREFIX, FAILURE_PREFIX, DisplayLimits
"""

from .emitter import StreamEventEmitter, StreamEvent
from .tracker import ToolCallTracker, ToolCallInfo
from .formatter import ToolResultFormatter, ContentType, FormattedResult
from .token_tracker import TokenTracker, TokenUsageInfo
from .utils import (
    SUCCESS_PREFIX,
    FAILURE_PREFIX,
    ToolStatus,
    DisplayLimits,
    has_args,
    is_success,
    resolve_path,
    truncate,
    format_tool_compact,
    format_tree_output,
    count_lines,
    truncate_with_line_hint,
    get_status_symbol,
)

__all__ = [
    # Emitter
    "StreamEventEmitter",
    "StreamEvent",
    # Tracker
    "ToolCallTracker",
    "ToolCallInfo",
    # Token Tracker
    "TokenTracker",
    "TokenUsageInfo",
    # Formatter
    "ToolResultFormatter",
    "ContentType",
    "FormattedResult",
    # Utils
    "SUCCESS_PREFIX",
    "FAILURE_PREFIX",
    "ToolStatus",
    "DisplayLimits",
    "has_args",
    "is_success",
    "resolve_path",
    "truncate",
    "format_tool_compact",
    "format_tree_output",
    "count_lines",
    "truncate_with_line_hint",
    "get_status_symbol",
]
