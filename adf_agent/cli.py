"""
ADF Agent CLI

Command-line entry point providing interactive conversation:
- Streaming output with Extended Thinking support
- ADF configuration status display
- Tool call visualization
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.spinner import Spinner

from .agent import ADFAgent
from .context import _use_workspace, ADFConfig
from .stream import (
    ToolResultFormatter,
    has_args,
    DisplayLimits,
    ToolStatus,
    format_tool_compact,
    is_success,
)


# Load environment variables
load_dotenv(override=True)

# MLflow tracking
from .observability import setup_mlflow_tracking
setup_mlflow_tracking()

# Rich Console configuration
console = Console(
    legacy_windows=(sys.platform == 'win32'),
    no_color=os.getenv('NO_COLOR') is not None,
)

# Global tool result formatter
formatter = ToolResultFormatter()


# === Terminal height calculation ===


def compute_height_budget(
    terminal_height: int,
    has_thinking: bool,
    has_response: bool,
    has_response_placeholder: bool,
    num_tools: int,
    num_results: int,
    show_processing: bool,
) -> dict:
    """Dynamically allocate content line counts for each region based on
    terminal height and currently active regions.

    Ensures all regions (including borders, tool name lines, and other fixed
    overhead) fit within terminal_height.
    Allocation priority: response > tools > thinking.

    Returns:
        {"thinking": int, "response": int, "lines_per_tool": int}
    """
    num_pending = max(0, num_tools - num_results)

    # Fixed overhead (borders, tool name lines, spinners, etc.)
    fixed = 2  # Top/bottom margins
    if has_thinking:
        fixed += 2  # Panel top/bottom borders
    if has_response:
        fixed += 2  # Panel top/bottom borders
    if has_response_placeholder:
        fixed += 1
    if show_processing:
        fixed += 1
    fixed += num_tools    # One name line per tool
    fixed += num_pending  # One spinner line per pending tool

    # Available content lines (thinking content + tool results + response content)
    content_budget = max(6, terminal_height - fixed)

    # Allocate by priority: response > tools > thinking
    thinking_h = 0
    tool_result_budget = 0
    response_h = 0

    if has_response:
        if has_thinking and num_results > 0:
            response_h = max(3, content_budget // 2)
            rest = content_budget - response_h
            thinking_h = max(2, rest // 3)
            tool_result_budget = rest - thinking_h
        elif has_thinking:
            response_h = max(3, content_budget * 2 // 3)
            thinking_h = max(2, content_budget - response_h)
        elif num_results > 0:
            response_h = max(3, content_budget * 3 // 5)
            tool_result_budget = content_budget - response_h
        else:
            response_h = content_budget
    elif has_thinking and num_results > 0:
        thinking_h = max(3, content_budget * 2 // 5)
        tool_result_budget = content_budget - thinking_h
    elif has_thinking:
        thinking_h = content_budget
    elif num_results > 0:
        tool_result_budget = content_budget

    # Display lines per tool result (-1 to reserve a line for token usage)
    if num_results > 0 and tool_result_budget > 0:
        lines_per_tool = max(1, tool_result_budget // num_results - 1)
    else:
        lines_per_tool = 2

    return {
        "thinking": thinking_h,
        "response": response_h,
        "lines_per_tool": lines_per_tool,
    }


def truncate_to_lines(text: str, max_lines: int) -> str:
    """Truncate text to a given number of lines, keeping the most recent content"""
    lines = text.split('\n')
    if len(lines) <= max_lines:
        return text
    return "...\n" + '\n'.join(lines[-max_lines + 1:])


# === Streaming state ===

class StreamState:
    """Streaming state container"""

    def __init__(self):
        self.thinking_text = ""
        self.response_text = ""
        self.tool_calls = []
        self.tool_results = []
        self.is_thinking = False
        self.is_responding = False
        self.is_processing = False
        self.token_usage = None  # TokenUsageInfo dict (total)
        self.turn_token_usages = []  # Per-turn token usages (aligned with tool_results)

    def handle_event(self, event: dict) -> str:
        """Handle a single streaming event"""
        event_type = event.get("type")

        if event_type == "thinking":
            self.is_thinking = True
            self.is_responding = False
            self.is_processing = False
            self.thinking_text += event.get("content", "")

        elif event_type == "text":
            self.is_thinking = False
            self.is_responding = True
            self.is_processing = False
            self.response_text += event.get("content", "")

        elif event_type == "tool_call":
            self.is_thinking = False
            self.is_responding = False
            self.is_processing = False

            tool_id = event.get("id", "")
            tc_data = {
                "id": tool_id,
                "name": event.get("name", "unknown"),
                "args": event.get("args", {}),
            }

            # Deduplicate and update by tool_id
            if tool_id:
                updated = False
                for i, tc in enumerate(self.tool_calls):
                    if tc.get("id") == tool_id:
                        self.tool_calls[i] = tc_data
                        updated = True
                        break
                if not updated:
                    self.tool_calls.append(tc_data)
            else:
                self.tool_calls.append(tc_data)

        elif event_type == "tool_result":
            self.is_processing = True
            self.tool_results.append({
                "name": event.get("name", "unknown"),
                "content": event.get("content", ""),
            })

        elif event_type == "done":
            self.is_processing = False
            if not self.response_text:
                self.response_text = event.get("response", "")

        elif event_type == "token_usage":
            usage = {
                "input_tokens": event.get("input_tokens", 0),
                "output_tokens": event.get("output_tokens", 0),
                "total_tokens": event.get("total_tokens", 0),
                "cache_creation_input_tokens": event.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": event.get("cache_read_input_tokens", 0),
            }
            is_total = event.get("is_total", False)
            parallel_count = event.get("parallel_count", 1)
            if is_total:
                # Aggregate (SUM of all API calls)
                self.token_usage = usage
            else:
                # Per-turn: parallel tools' tokens shown on the last tool
                if parallel_count > 1:
                    usage["parallel_count"] = parallel_count
                    # Fill None for preceding parallel tools
                    while len(self.turn_token_usages) < len(self.tool_results) - 1:
                        self.turn_token_usages.append(None)
                if len(self.tool_results) > len(self.turn_token_usages):
                    self.turn_token_usages.append(usage)

        elif event_type == "error":
            self.is_processing = False
            self.is_thinking = False
            self.is_responding = False
            error_msg = event.get("message", "Unknown error")
            self.response_text += f"\n\n[Error] {error_msg}"

        return event_type

    def get_display_args(self) -> dict:
        """Get arguments for create_streaming_display"""
        return {
            "thinking_text": self.thinking_text,
            "response_text": self.response_text,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "turn_token_usages": self.turn_token_usages,
            "is_thinking": self.is_thinking,
            "is_responding": self.is_responding,
            "is_processing": self.is_processing,
        }


def display_token_usage(token_usage: dict) -> None:
    """Display aggregate token usage

    LangChain's input_tokens already includes cache tokens:
        input_tokens = new_input + cache_creation + cache_read

    Display format varies by cache status:
    - Mixed:    "8,537 new + 3,269 cache init + 13,076 cached = 24,882 in / 727 out"
    - All hit:  "8,525 + 16,345 cached = 24,870 in / 692 out"
    - No cache: "5,000 in / 200 out"
    """
    if not token_usage:
        return

    input_tokens = token_usage.get("input_tokens", 0)
    output_tokens = token_usage.get("output_tokens", 0)
    total_tokens = token_usage.get("total_tokens", 0)
    cache_read = token_usage.get("cache_read_input_tokens", 0)
    cache_creation = token_usage.get("cache_creation_input_tokens", 0)

    if total_tokens == 0:
        return

    def fmt(n: int) -> str:
        return f"{n:,}"

    # Separator and token info
    console.print("─" * 40, style="dim")

    cached_total = cache_read + cache_creation
    if cached_total > 0:
        new_input = input_tokens - cached_total
        if cache_read > 0 and cache_creation > 0:
            # Mixed: itemized breakdown
            base = (
                f"Tokens: {fmt(new_input)} new"
                f" + {fmt(cache_creation)} cache init"
                f" + {fmt(cache_read)} cached"
                f" = {fmt(input_tokens)} in / {fmt(output_tokens)} out"
            )
        elif cache_creation > 0:
            base = (
                f"Tokens: {fmt(new_input)} + {fmt(cached_total)} cache init"
                f" = {fmt(input_tokens)} in / {fmt(output_tokens)} out"
            )
        else:
            base = (
                f"Tokens: {fmt(new_input)} + {fmt(cached_total)} cached"
                f" = {fmt(input_tokens)} in / {fmt(output_tokens)} out"
            )
    else:
        base = f"Tokens: {fmt(input_tokens)} in / {fmt(output_tokens)} out"

    console.print(f"[dim]{base}[/dim]")


def format_turn_token_usage(token_usage: dict | None) -> Text | None:
    """Format a single turn's token usage (inline display)

    input_tokens already includes cache tokens; shows new + cached breakdown:
    - cache init: "356 + 3,269 cache init / 162 out"  (first-time cache)
    - cached:     "1,431 + 3,269 cached / 63 out"     (cache hit)
    - no cache:   "3,625 in / 155 out"
    """
    if not token_usage:
        return None

    input_tokens = token_usage.get("input_tokens", 0)
    output_tokens = token_usage.get("output_tokens", 0)
    cache_read = token_usage.get("cache_read_input_tokens", 0)
    cache_creation = token_usage.get("cache_creation_input_tokens", 0)
    parallel_count = token_usage.get("parallel_count", 1)

    if input_tokens == 0 and output_tokens == 0:
        return None

    def fmt(n: int) -> str:
        return f"{n:,}"

    # Build input part: show new + cached breakdown
    cached_total = cache_read + cache_creation
    if cached_total > 0:
        new_input = input_tokens - cached_total
        if cache_creation > 0:
            input_part = f"{fmt(new_input)} + {fmt(cached_total)} cache init"
        else:
            input_part = f"{fmt(new_input)} + {fmt(cached_total)} cached"
    else:
        input_part = f"{fmt(input_tokens)} in"

    base = f"  ↳ {input_part} / {fmt(output_tokens)} out"

    # Parallel indicator
    if parallel_count > 1:
        base += f" ({parallel_count} tools)"

    return Text(base, style="dim")


def format_tool_result_compact(
    name: str,
    content: str,
    max_lines: int = 5,
    token_usage: dict | None = None,
) -> list:
    """Display tool results in tree format"""
    elements = []

    if not content.strip():
        elements.append(Text("  └ (empty)", style="dim"))
    else:
        lines = content.strip().split("\n")
        total_lines = len(lines)
        display_lines = lines[:max_lines]

        for i, line in enumerate(display_lines):
            prefix = "└" if i == 0 else " "
            if len(line) > 80:
                line = line[:77] + "..."
            style = "dim" if is_success(content) else "red dim"
            elements.append(Text(f"  {prefix} {line}", style=style))

        remaining = total_lines - max_lines
        if remaining > 0:
            elements.append(Text(f"    ... +{remaining} lines", style="dim italic"))

    # Add token usage display (below the result)
    token_text = format_turn_token_usage(token_usage)
    if token_text:
        elements.append(token_text)

    return elements


def display_final_results(
    state: StreamState,
    thinking_max_length: int = DisplayLimits.THINKING_FINAL,
    tool_result_max_length: int = DisplayLimits.TOOL_RESULT_FINAL,
    show_thinking: bool = True,
    show_tools: bool = True,
    show_response_panel: bool = True,
):
    """Display final results"""
    # Display thinking
    if show_thinking and state.thinking_text:
        display_thinking = state.thinking_text
        if len(display_thinking) > thinking_max_length:
            half = thinking_max_length // 2
            display_thinking = display_thinking[:half] + "\n\n... (truncated) ...\n\n" + display_thinking[-half:]
        console.print(Panel(
            Text(display_thinking, style="dim"),
            title="Thinking",
            border_style="blue",
        ))

    # Display tool calls and results
    if show_tools and state.tool_calls:
        for i, tc in enumerate(state.tool_calls):
            has_result = i < len(state.tool_results)
            tr = state.tool_results[i] if has_result else None
            content = tr.get('content', '') if tr else ''
            # Get this turn's token usage
            turn_tokens = state.turn_token_usages[i] if i < len(state.turn_token_usages) else None

            if has_result and is_success(content):
                status = ToolStatus.SUCCESS
                style = "bold green"
            elif has_result:
                status = ToolStatus.ERROR
                style = "bold red"
            else:
                status = ToolStatus.PENDING
                style = "dim"

            tool_compact = format_tool_compact(tc['name'], tc.get('args'))
            tool_text = Text()
            tool_text.append(f"{status.value} ", style=style)
            tool_text.append(tool_compact, style=style)
            console.print(tool_text)

            if has_result:
                result_elements = format_tool_result_compact(
                    tr['name'],
                    content,
                    max_lines=10,
                    token_usage=turn_tokens,
                )
                for elem in result_elements:
                    console.print(elem)
        console.print()

    # Display final response
    if state.response_text:
        if show_response_panel:
            console.print(Panel(
                Markdown(state.response_text),
                title="Response",
                border_style="green",
            ))
        else:
            console.print(f"\n[bold blue]Assistant:[/bold blue]")
            console.print(Markdown(state.response_text))
            console.print()

    # Display token usage
    display_token_usage(state.token_usage)


def create_streaming_display(
    thinking_text: str = "",
    response_text: str = "",
    tool_calls: list = None,
    tool_results: list = None,
    turn_token_usages: list = None,
    is_thinking: bool = False,
    is_responding: bool = False,
    is_waiting: bool = False,
    is_processing: bool = False,
    terminal_height: int = 25,
) -> Group:
    """Create the streaming display layout, ensuring total height does not exceed terminal height"""
    elements = []
    tool_calls = tool_calls or []
    tool_results = tool_results or []
    turn_token_usages = turn_token_usages or []

    # Initial waiting state
    if is_waiting and not thinking_text and not response_text and not tool_calls:
        spinner = Spinner("dots", text=" AI is thinking...", style="cyan")
        elements.append(spinner)
        return Group(*elements)

    # === Dynamic height budget ===
    has_thinking = bool(thinking_text)
    has_response = bool(response_text)
    has_response_placeholder = is_responding and not thinking_text and not has_response
    show_processing = (
        is_processing and not is_thinking and not is_responding and not has_response
    )

    heights = compute_height_budget(
        terminal_height=terminal_height,
        has_thinking=has_thinking,
        has_response=has_response,
        has_response_placeholder=has_response_placeholder,
        num_tools=len(tool_calls),
        num_results=len(tool_results),
        show_processing=show_processing,
    )
    thinking_h = heights["thinking"]
    response_h = heights["response"]
    lines_per_tool = heights["lines_per_tool"]

    # === Build each region ===

    # Thinking panel
    if thinking_text:
        thinking_title = "Thinking"
        if is_thinking:
            thinking_title += " ..."
        display_thinking = truncate_to_lines(thinking_text, thinking_h)
        panel_h = min(len(display_thinking.split('\n')), thinking_h) + 2
        elements.append(Panel(
            Text(display_thinking, style="dim"),
            title=thinking_title,
            border_style="blue",
            padding=(0, 1),
            height=panel_h,
        ))

    # Tool Calls display
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            has_result = i < len(tool_results)
            tr = tool_results[i] if has_result else None
            turn_tokens = turn_token_usages[i] if i < len(turn_token_usages) else None

            if has_result:
                content = tr.get('content', '') if tr else ''
                if is_success(content):
                    status = ToolStatus.SUCCESS
                    style = "bold green"
                else:
                    status = ToolStatus.ERROR
                    style = "bold red"
            else:
                status = ToolStatus.RUNNING
                style = "bold yellow"

            tool_compact = format_tool_compact(tc['name'], tc.get('args'))
            tool_text = Text()
            tool_text.append(f"{status.value} ", style=style)
            tool_text.append(tool_compact, style=style)
            elements.append(tool_text)

            if has_result:
                result_elements = format_tool_result_compact(
                    tr['name'],
                    tr.get('content', ''),
                    max_lines=lines_per_tool,
                    token_usage=turn_tokens,
                )
                elements.extend(result_elements[:lines_per_tool + 1])  # +1 for token line
            else:
                spinner = Spinner("dots", text=" Executing...", style="yellow")
                elements.append(spinner)

    # Post-tool-execution waiting
    if show_processing:
        spinner = Spinner("dots", text=" AI is analyzing results...", style="cyan")
        elements.append(spinner)

    # Response panel
    if response_text:
        response_title = "Response"
        if is_responding:
            response_title += " ..."
        display_response = truncate_to_lines(response_text, response_h)
        panel_h = min(len(display_response.split('\n')), response_h) + 2
        elements.append(Panel(
            Markdown(display_response),
            title=response_title,
            border_style="green",
            padding=(0, 1),
            height=panel_h,
        ))
    elif has_response_placeholder:
        elements.append(Text("⏳ Generating response...", style="dim"))

    return Group(*elements) if elements else Text("⏳ Processing...", style="dim")


# === Onboarding ===

def _needs_onboarding() -> bool:
    """Check if onboarding is needed (no API credentials configured)"""
    has_anthropic = bool(
        os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    )
    has_foundry = bool(os.getenv("ANTHROPIC_FOUNDRY_API_KEY"))
    return not has_anthropic and not has_foundry


def _read_key() -> str | None:
    """Read a single keypress, handling arrow key escape sequences"""
    import tty, termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            sys.stdin.read(1)  # skip '['
            arrow = sys.stdin.read(1)
            return {'A': 'up', 'B': 'down'}.get(arrow)
        if ch in ('\r', '\n'):
            return 'enter'
        if ch == '\x03':
            raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return None


def _select(title: str, options: list[tuple[str, str]], default: int = 0) -> str | None:
    """
    Arrow-key inline selector.

    Args:
        title: Title text
        options: [(value, label), ...]
        default: Default selected index

    Returns:
        Selected value, or None on Ctrl+C
    """
    selected = default
    n = len(options)
    first = True

    def render():
        nonlocal first
        if not first:
            sys.stdout.write(f"\033[{n}A")  # move cursor up
        first = False
        for i, (_, label) in enumerate(options):
            sys.stdout.write('\033[2K')  # clear line
            if i == selected:
                sys.stdout.write(f"    \033[36m▸ {label}\033[0m\n")
            else:
                sys.stdout.write(f"      {label}\n")
        sys.stdout.flush()

    console.print(f"  [bold]{title}[/bold] [dim](↑↓ select, Enter confirm)[/dim]")
    render()

    try:
        while True:
            key = _read_key()
            if key == 'up':
                selected = (selected - 1) % n
                render()
            elif key == 'down':
                selected = (selected + 1) % n
                render()
            elif key == 'enter':
                return options[selected][0]
    except KeyboardInterrupt:
        console.print()
        return None


def _update_env_file(env_path: Path, updates: dict[str, str]):
    """Update key=value pairs in a .env file, handling duplicate keys"""
    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue

        key = stripped.split('=', 1)[0].strip()

        if key in updates and key not in updated_keys:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        elif key in updates:
            # Duplicate key, comment it out
            new_lines.append(f"# {line}")
        else:
            new_lines.append(line)

    # Append keys not found in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')


def run_onboarding() -> bool:
    """
    Interactive onboarding: guide the user through API credential setup.

    Returns:
        True if configuration was completed successfully
    """
    console.print()
    console.print(Panel(
        "[bold]Welcome to ADF Agent![/bold]\n\n"
        "No API credentials detected. Let's set up your environment.",
        border_style="cyan",
    ))
    console.print()

    # Step 1: Provider
    provider = _select("API Provider", [
        ("anthropic", "Claude API (Anthropic)"),
        ("azure_foundry", "Claude API on Azure AI Foundry"),
    ])
    if provider is None:
        return False

    is_foundry = provider == "azure_foundry"
    console.print()

    # Step 2: Model
    model = _select("Model", [
        ("claude-sonnet-4-5", "claude-sonnet-4-5 (recommended)"),
        ("claude-opus-4-5", "claude-opus-4-5"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
    ])
    if model is None:
        return False

    console.print()

    # Step 3: API Key
    console.print("  [bold]API Key[/bold]")
    if is_foundry:
        api_key = input("    Azure Foundry API Key: ").strip()
    else:
        api_key = input("    Anthropic API Key: ").strip()

    if not api_key:
        console.print("  [red]API key is required.[/red]")
        return False

    # Step 4: Base URL (Foundry only)
    base_url = ""
    if is_foundry:
        console.print()
        console.print("  [bold]Azure Foundry Base URL[/bold]")
        console.print("    [dim]e.g. https://<resource>.services.ai.azure.com/anthropic[/dim]")
        base_url = input("    Base URL: ").strip()
        if not base_url:
            console.print("  [red]Base URL is required for Azure Foundry.[/red]")
            return False

    # --- Write to .env ---
    env_file = Path.cwd() / ".env"
    env_example = Path.cwd() / ".env.example"

    if not env_file.exists() and env_example.exists():
        shutil.copy2(env_example, env_file)
    elif not env_file.exists():
        env_file.touch()

    updates = {"CLAUDE_MODEL": model}
    if is_foundry:
        updates["CLAUDE_PROVIDER"] = "azure_foundry"
        updates["ANTHROPIC_FOUNDRY_API_KEY"] = api_key
        updates["ANTHROPIC_FOUNDRY_BASE_URL"] = base_url
    else:
        updates["CLAUDE_PROVIDER"] = "anthropic"
        updates["ANTHROPIC_AUTH_TOKEN"] = api_key

    _update_env_file(env_file, updates)

    # Completion message
    provider_label = "Azure AI Foundry" if is_foundry else "Anthropic"
    console.print()
    console.print(Panel(
        f"[green]Configuration saved to .env[/green]\n\n"
        f"  Provider: [bold]{provider_label}[/bold]\n"
        f"  Model:    [bold]{model}[/bold]\n\n"
        f"Run [bold cyan]adf_agent[/bold cyan] again to start.",
        border_style="green",
        title="Setup Complete",
    ))

    return True


def print_banner():
    """Print the welcome banner"""
    banner = """
[bold cyan]ADF Agent[/bold cyan]
[dim]Azure Data Factory Assistant[/dim]

Helps you explore and manage Azure Data Factory resources:
- List and analyze Pipelines, Linked Services, Integration Runtimes
- Test connections, enable Interactive Authoring
- Analyze JSON data with Python
"""
    console.print(Panel(banner, title="ADF Agent", border_style="cyan"))


def show_config_status(agent: ADFAgent = None):
    """Display configuration status

    Args:
        agent: Optional; if provided, shows the actual session_dir
    """
    if agent:
        config = agent.adf_config
    else:
        config = ADFConfig()

    if config.is_configured():
        console.print(f"[green]✓[/green] ADF: {config.factory_name} (RG: {config.resource_group})")

    # Show storage location (only when using temp directory)
    if not _use_workspace():
        if agent:
            # Use Agent's actual session_dir
            console.print(f"[dim]📁 Session dir: {agent.context.session_dir}[/dim]")
        else:
            # Show base path only
            import tempfile
            base_path = Path(tempfile.gettempdir()) / "adf_agent" / "sessions"
            console.print(f"[dim]📁 Output dir: {base_path}/[/dim]")


def cmd_run(prompt: str, enable_thinking: bool = True):
    """Execute a single request"""
    console.print(Panel(f"[bold cyan]User Request:[/bold cyan]\n{prompt}"))
    console.print()

    agent = ADFAgent(enable_thinking=enable_thinking)

    console.print("[dim]Running agent...[/dim]\n")

    try:
        state = StreamState()

        with Live(console=console, refresh_per_second=10, transient=True) as live:
            live.update(create_streaming_display(is_waiting=True))

            for event in agent.stream_events(prompt):
                event_type = state.handle_event(event)
                live.update(create_streaming_display(
                    **state.get_display_args(),
                    terminal_height=console.height or 25,
                ))

                if event_type in ("tool_call", "tool_result"):
                    live.refresh()

        console.print()
        display_final_results(
            state,
            tool_result_max_length=1000,
            show_response_panel=True,
        )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise


def cmd_interactive(enable_thinking: bool = True):
    """Interactive conversation mode"""
    print_banner()

    agent = ADFAgent(enable_thinking=enable_thinking)

    # Display configuration status (pass agent to show actual session_dir)
    show_config_status(agent)
    console.print()

    thinking_status = "[green]enabled[/green]" if enable_thinking else "[dim]disabled[/dim]"
    console.print(f"[dim]Extended Thinking: {thinking_status}[/dim]")
    console.print("[dim]Commands: /exit to quit, /help for examples[/dim]\n")

    thread_id = "interactive"

    # Initialize prompt_toolkit session
    history_file = str(Path.home() / ".adf_agent_history")
    session = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=True,
    )

    while True:
        try:
            user_input = session.prompt(
                HTML('<ansigreen><b>You:</b></ansigreen> ')
            ).strip()

            if not user_input:
                continue

            # Special commands
            if user_input.lower() in ("/exit", "/quit", "/q"):
                console.print("[dim]Goodbye![/dim]")
                break

            if user_input.lower() == "/help":
                show_help()
                continue

            if user_input.lower() == "/config":
                show_config_status(agent)
                continue

            # Run agent
            console.print()

            state = StreamState()

            with Live(console=console, refresh_per_second=10, transient=True) as live:
                live.update(create_streaming_display(is_waiting=True))

                for event in agent.stream_events(user_input, thread_id=thread_id):
                    event_type = state.handle_event(event)
                    live.update(create_streaming_display(
                        **state.get_display_args(),
                        terminal_height=console.height or 25,
                    ))

                    if event_type in ("tool_call", "tool_result"):
                        live.refresh()

            # Display final results (simplified for interactive mode)
            display_final_results(
                state,
                thinking_max_length=500,
                tool_result_max_length=DisplayLimits.TOOL_RESULT_FINAL,
                show_thinking=True,
                show_tools=True,
                show_response_panel=True,
            )
            console.print()  # Spacing before next input prompt

        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def show_help():
    """Display help information"""
    help_text = """
## Example Queries

**List resources:**
- List all pipelines
- List all linked services
- List Snowflake-type linked services

**Find relationships:**
- Which pipelines use a Snowflake linked service?
- Analyze linked service type distribution

**Test connections:**
- Test linked service "my-snowflake" connection
- Enable interactive authoring for Integration Runtime "ir-managed"

**Analyze data:**
- Analyze data in workspace/pipelines.json
- Count the number of activities per pipeline

## Commands

- `/exit` - Exit the agent
- `/help` - Show this help
- `/config` - Show ADF configuration status
"""
    console.print(Markdown(help_text))


def main():
    """CLI main entry point"""
    parser = argparse.ArgumentParser(
        description="ADF Agent - Azure Data Factory Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  %(prog)s --interactive

  # Execute a single request
  %(prog)s "List all pipelines"

  # Disable thinking
  %(prog)s --no-thinking "List all linked services"
""",
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Request to execute",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Enter interactive conversation mode",
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable Extended Thinking",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        help="Set working directory",
    )

    args = parser.parse_args()

    # Set working directory
    if args.cwd:
        os.chdir(args.cwd)

    # Onboarding: check API credentials, guide setup if missing
    if _needs_onboarding():
        run_onboarding()
        sys.exit(0)

    # Thinking toggle
    enable_thinking = not args.no_thinking

    # Execute command
    if args.interactive:
        cmd_interactive(enable_thinking=enable_thinking)
    elif args.prompt:
        cmd_run(args.prompt, enable_thinking=enable_thinking)
    else:
        # Default to interactive mode
        cmd_interactive(enable_thinking=enable_thinking)


if __name__ == "__main__":
    main()
