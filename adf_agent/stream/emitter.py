"""
StreamEventEmitter - Unified event format

All events contain a type and associated data.
"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class StreamEvent:
    """Unified stream event"""
    type: str
    data: Dict[str, Any]


class StreamEventEmitter:
    """Stream event emitter"""

    @staticmethod
    def thinking(content: str, thinking_id: int = 0) -> StreamEvent:
        """Thinking content event"""
        return StreamEvent("thinking", {"type": "thinking", "content": content, "id": thinking_id})

    @staticmethod
    def text(content: str) -> StreamEvent:
        """Text content event"""
        return StreamEvent("text", {"type": "text", "content": content})

    @staticmethod
    def tool_call(name: str, args: Dict[str, Any], tool_id: str = "") -> StreamEvent:
        """Tool call event"""
        return StreamEvent("tool_call", {"type": "tool_call", "name": name, "args": args, "id": tool_id})

    @staticmethod
    def tool_result(name: str, content: str, success: bool = True) -> StreamEvent:
        """Tool result event"""
        return StreamEvent("tool_result", {
            "type": "tool_result",
            "name": name,
            "content": content,
            "success": success,
        })

    @staticmethod
    def done(response: str = "") -> StreamEvent:
        """Done event"""
        return StreamEvent("done", {"type": "done", "response": response})

    @staticmethod
    def error(message: str) -> StreamEvent:
        """Error event"""
        return StreamEvent("error", {"type": "error", "message": message})

    @staticmethod
    def token_usage(
        input_tokens: int,
        output_tokens: int,
        total_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        is_total: bool = False,
        parallel_count: int = 1,
    ) -> StreamEvent:
        """Token usage event

        Args:
            is_total: True means this is a summary across all turns, False means usage for a single API call
            parallel_count: Number of tools executed in parallel in this API call (>1 means parallel tool use)
        """
        return StreamEvent("token_usage", {
            "type": "token_usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens or (input_tokens + output_tokens),
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "is_total": is_total,
            "parallel_count": parallel_count,
        })
