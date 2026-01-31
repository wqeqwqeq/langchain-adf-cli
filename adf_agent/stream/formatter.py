"""
ToolResultFormatter - Tool result formatter

Intelligently formats tool output based on content characteristics.
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, List

from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.markdown import Markdown

from .utils import SUCCESS_PREFIX, FAILURE_PREFIX, is_success as _is_success, truncate


class ContentType(Enum):
    """Content type"""
    SUCCESS = "success"
    ERROR = "error"
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"


@dataclass
class FormattedResult:
    """Formatted result"""
    content_type: ContentType
    elements: List[Any]  # Rich renderable elements
    success: bool = True  # Whether successful


class ToolResultFormatter:
    """Tool result formatter

    Usage example:
        formatter = ToolResultFormatter()
        result = formatter.format("bash", output, max_length=800)
        for elem in result.elements:
            console.print(elem)
    """

    def detect_type(self, content: str) -> ContentType:
        """Detect content type"""
        content = content.strip()

        # 1. Status prefix based detection (highest priority)
        if content.startswith(SUCCESS_PREFIX):
            # Check for JSON output
            body = self._extract_body(content)
            if self._is_json(body):
                return ContentType.JSON
            return ContentType.SUCCESS

        if content.startswith(FAILURE_PREFIX):
            return ContentType.ERROR

        # 2. JSON detection
        if self._is_json(content):
            return ContentType.JSON

        # 3. Actual error detection
        if self._is_error(content):
            return ContentType.ERROR

        # 4. Markdown detection
        if self._is_markdown(content):
            return ContentType.MARKDOWN

        return ContentType.TEXT

    def is_success(self, content: str) -> bool:
        """Determine whether content indicates successful execution"""
        return _is_success(content)

    def format(self, name: str, content: str, max_length: int = 800) -> FormattedResult:
        """Format tool result"""
        content_type = self.detect_type(content)
        success = self.is_success(content)

        # Dispatch to specific formatting method
        formatter_map = {
            ContentType.SUCCESS: self._format_success,
            ContentType.ERROR: self._format_error,
            ContentType.JSON: self._format_json,
            ContentType.MARKDOWN: self._format_markdown,
            ContentType.TEXT: self._format_text,
        }

        formatter = formatter_map.get(content_type, self._format_text)
        elements = formatter(name, content, max_length)

        return FormattedResult(content_type=content_type, elements=elements, success=success)

    # === Private methods: Type detection ===

    def _extract_body(self, content: str) -> str:
        """Extract content body after status prefix"""
        lines = content.split("\n", 2)
        return lines[2].strip() if len(lines) > 2 else ""

    def _is_json(self, content: str) -> bool:
        """Check if content is JSON"""
        content = content.strip()
        if not content:
            return False
        if (content.startswith('{') and content.endswith('}')) or \
           (content.startswith('[') and content.endswith(']')):
            try:
                json.loads(content)
                return True
            except (json.JSONDecodeError, ValueError):
                pass
        return False

    def _is_error(self, content: str) -> bool:
        """Check if content is an error"""
        error_patterns = [
            'Traceback (most recent call last)',
            'Exception:',
            'Error:',
        ]
        return any(pattern in content for pattern in error_patterns)

    def _is_markdown(self, content: str) -> bool:
        """Check if content is Markdown"""
        md_patterns = ['```', '**', '##', '- **']
        return content.startswith('#') or any(p in content for p in md_patterns)

    # === Private methods: Formatting ===

    def _format_success(self, name: str, content: str, max_length: int) -> List[Any]:
        """Format success output"""
        display = self._truncate(content, max_length)
        return [Panel(
            Text(display, style="green"),
            title=f"{name}",
            border_style="green",
        )]

    def _format_error(self, name: str, content: str, max_length: int) -> List[Any]:
        """Format error output"""
        display = self._truncate(content, max_length)
        return [Panel(
            Text(display, style="red"),
            title=f"{name}",
            border_style="red",
        )]

    def _format_json(self, name: str, content: str, max_length: int) -> List[Any]:
        """Format JSON output"""
        # Extract JSON content
        json_content = content
        if content.startswith(SUCCESS_PREFIX):
            json_content = self._extract_body(content)

        try:
            data = json.loads(json_content)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            formatted = self._truncate(formatted, max_length)
            return [
                Text(f"{name}", style="cyan bold"),
                Syntax(formatted, "json", theme="monokai", line_numbers=False),
            ]
        except (json.JSONDecodeError, ValueError):
            return self._format_text(name, content, max_length)

    def _format_markdown(self, name: str, content: str, max_length: int) -> List[Any]:
        """Format Markdown output"""
        display = self._truncate(content, max_length)
        return [Panel(
            Markdown(display),
            title=f"{name}",
            border_style="cyan dim",
        )]

    def _format_text(self, name: str, content: str, max_length: int) -> List[Any]:
        """Format plain text output"""
        display = self._truncate(content, max_length)
        return [
            Text(f"{name}:", style="cyan bold"),
            Text(f"   {display}", style="dim"),
        ]

    def _truncate(self, content: str, max_length: int) -> str:
        """Truncate content"""
        return truncate(content, max_length)
