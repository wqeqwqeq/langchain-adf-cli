"""
ToolCallTracker - Tool call tracker

Manages tool call state during streaming, handling incrementally arriving arguments.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ToolCallInfo:
    """Tool call information"""
    id: str
    name: str
    args: Dict = field(default_factory=dict)
    emitted: bool = False
    args_complete: bool = False  # Whether args are complete (distinguish "no args" from "args pending")
    # Buffer for accumulating input_json_delta fragments
    _json_buffer: str = ""


class ToolCallTracker:
    """Tool call tracker

    Handles the incremental arrival of tool_use blocks in LangChain streaming output.
    Supports accumulation of input_json_delta type incremental JSON fragments.

    Usage example:
        tracker = ToolCallTracker()

        # Register tool call (may arrive in multiple chunks)
        tracker.update(tool_id, name="bash")

        # Accumulate JSON fragments
        tracker.append_json_delta(tool_id, '{"command')
        tracker.append_json_delta(tool_id, '": "ls"}')

        # Finalize: parse accumulated JSON
        tracker.finalize(tool_id)

        # Emit
        info = tracker.get(tool_id)
        yield emitter.tool_call(info.name, info.args)
    """

    def __init__(self):
        self._calls: Dict[str, ToolCallInfo] = {}
        # Track the last tool_id (for input_json_delta which lacks an id)
        self._last_tool_id: Optional[str] = None

    def update(
        self,
        tool_id: str,
        name: Optional[str] = None,
        args: Optional[Dict] = None,
        args_complete: bool = False,
    ) -> None:
        """Update tool call information (accumulative)

        Args:
            tool_id: Tool call ID
            name: Tool name
            args: Tool arguments
            args_complete: Whether args are complete. Distinguishes "args is empty dict" from "args will arrive via delta"
        """
        if tool_id not in self._calls:
            self._calls[tool_id] = ToolCallInfo(
                id=tool_id,
                name=name or "",
                args=args or {},
                args_complete=args_complete,
            )
            self._last_tool_id = tool_id
        else:
            info = self._calls[tool_id]
            if name:
                info.name = name
            if args:
                info.args = args
            # Only update to True when True is passed (avoid accidental reset by subsequent calls)
            if args_complete:
                info.args_complete = True

    def append_json_delta(self, partial_json: str, index: int = 0) -> None:
        """Accumulate input_json_delta fragments

        In LangChain streaming, args may arrive as input_json_delta in batches.
        index is used to handle parallel tool call scenarios.
        """
        # Use last_tool_id (since input_json_delta has no tool_id)
        tool_id = self._last_tool_id
        if tool_id and tool_id in self._calls:
            self._calls[tool_id]._json_buffer += partial_json

    def finalize_all(self) -> None:
        """Finalize all tool calls: parse accumulated JSON fragments and mark args as complete"""
        for info in self._calls.values():
            if info._json_buffer:
                try:
                    info.args = json.loads(info._json_buffer)
                except json.JSONDecodeError:
                    pass  # Keep existing args
                info._json_buffer = ""
            # Mark all tool args as complete during finalize
            info.args_complete = True

    def is_ready(self, tool_id: str) -> bool:
        """Check if tool call is ready to emit (has name and not yet emitted)"""
        if tool_id not in self._calls:
            return False
        info = self._calls[tool_id]
        return bool(info.name) and not info.emitted

    def get_all(self) -> list[ToolCallInfo]:
        """Get all tool calls (including emitted ones)"""
        return list(self._calls.values())

    def mark_emitted(self, tool_id: str) -> None:
        """Mark as emitted"""
        if tool_id in self._calls:
            self._calls[tool_id].emitted = True

    def get(self, tool_id: str) -> Optional[ToolCallInfo]:
        """Get tool call information"""
        return self._calls.get(tool_id)

    def get_pending(self) -> list[ToolCallInfo]:
        """Get all pending (not yet emitted) tool calls"""
        return [info for info in self._calls.values() if not info.emitted]

    def emit_all_pending(self) -> list[ToolCallInfo]:
        """Emit all pending tool calls and mark them"""
        pending = self.get_pending()
        for info in pending:
            info.emitted = True
        return pending

    def clear(self) -> None:
        """Clear the tracker"""
        self._calls.clear()
