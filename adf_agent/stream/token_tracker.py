"""
TokenTracker - Token usage tracking

Extracts usage_metadata from AIMessage/AIMessageChunk and accumulates
statistics across multiple LLM calls (e.g. in tool use scenarios).

The usage_metadata returned by the API is an independent value per API call (not accumulated across turns):
- input_tokens: Total input tokens for this call (already includes cache tokens)
- output_tokens: Output tokens for this call (independent value)
- input_token_details.cache_creation: Tokens written to cache for the first time (cache init)
- input_token_details.cache_read: Tokens read from cache (cached)

LangChain's input_tokens = raw_input + cache_creation + cache_read,
i.e. cache tokens are a subset of input_tokens, not additional.
"""

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, AIMessageChunk


@dataclass
class TokenUsageInfo:
    """Token usage information"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def __add__(self, other: "TokenUsageInfo") -> "TokenUsageInfo":
        """Support + operator for accumulation"""
        return TokenUsageInfo(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )

    def is_empty(self) -> bool:
        """Check if empty (no token statistics)"""
        return self.total_tokens == 0


@dataclass
class TokenTracker:
    """
    Token usage tracker

    The usage_metadata returned by each LLM API call is an independent value for that call.
    TokenTracker uses the raw values directly as per-turn statistics,
    and computes the final total by summing all turns.
    """
    # Current turn's usage (directly from API raw values)
    _current_turn: TokenUsageInfo = field(default_factory=TokenUsageInfo)
    # Total of all finalized turns
    _total: TokenUsageInfo = field(default_factory=TokenUsageInfo)
    # Whether current turn's usage data has been received
    _has_current_usage: bool = False

    def update(self, chunk: AIMessage | AIMessageChunk) -> None:
        """
        Extract token statistics from chunk

        Uses a merge strategy: takes the max of each field to ensure that when
        usage is spread across multiple chunks (e.g. input and cache in earlier
        chunks, output in later ones), no data is lost.

        LangChain input_tokens already includes cache tokens:
        input_tokens = raw_input + cache_read + cache_creation
        """
        usage = getattr(chunk, "usage_metadata", None)
        if not usage:
            return

        input_tokens, output_tokens, cache_creation, cache_read = \
            self._extract_usage(usage)

        if input_tokens > 0 or output_tokens > 0:
            # Merge: take max to preserve non-zero values from each chunk
            cur = self._current_turn
            merged_input = max(cur.input_tokens, input_tokens)
            merged_output = max(cur.output_tokens, output_tokens)
            self._current_turn = TokenUsageInfo(
                input_tokens=merged_input,
                output_tokens=merged_output,
                total_tokens=merged_input + merged_output,
                cache_creation_input_tokens=max(cur.cache_creation_input_tokens, cache_creation),
                cache_read_input_tokens=max(cur.cache_read_input_tokens, cache_read),
            )
            self._has_current_usage = True

    @staticmethod
    def _extract_usage(usage) -> tuple[int, int, int, int]:
        """Extract (input, output, cache_creation, cache_read) from usage_metadata"""
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            details = usage.get("input_token_details", {}) or {}
            cache_creation = details.get("cache_creation", 0) or 0
            cache_read = details.get("cache_read", 0) or 0
        else:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            details = getattr(usage, "input_token_details", None)
            if details and isinstance(details, dict):
                cache_creation = details.get("cache_creation", 0) or 0
                cache_read = details.get("cache_read", 0) or 0
            else:
                cache_creation = getattr(details, "cache_creation", 0) or 0 if details else 0
                cache_read = getattr(details, "cache_read", 0) or 0 if details else 0
        return input_tokens, output_tokens, cache_creation, cache_read

    def finalize_turn(self) -> TokenUsageInfo | None:
        """
        Finalize the current turn, return its usage and accumulate into total

        Called after a tool result is returned, indicating one round of LLM calls is complete.

        Returns:
            TokenUsageInfo for this turn, or None if there is no usage
        """
        if self._has_current_usage:
            current = self._current_turn
            self._total = self._total + current
            self._current_turn = TokenUsageInfo()
            self._has_current_usage = False
            return current
        return None

    def get_usage(self) -> TokenUsageInfo:
        """
        Get total usage (including unfinalized turn)

        Returns:
            TokenUsageInfo: Sum of all turns
        """
        if self._has_current_usage:
            return self._total + self._current_turn
        return self._total

    def reset(self) -> None:
        """Reset all statistics"""
        self._current_turn = TokenUsageInfo()
        self._total = TokenUsageInfo()
        self._has_current_usage = False
