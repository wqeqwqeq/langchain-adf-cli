# CLI Toggle Feature Implementation Attempts

## Goal

Implement a Ctrl+O keyboard shortcut in the interactive CLI to toggle show/hide thinking and tool call details, achieving an "in-place replacement" effect.

## Tech Stack

- `prompt_toolkit`: Handles user input and key bindings
- `rich`: Terminal formatted output (Panel, Markdown, Live, etc.)
- Python standard library

---

## Attempted Approaches

### Approach 1: ANSI Line Counting + Clear

**Idea**: Count the number of output lines, then use ANSI escape codes to clear those lines and re-render on toggle.

```python
def clear_lines(n: int):
    """Clear the last n lines in the terminal"""
    sys.stdout.write(f"\033[{n}A\033[J")
    sys.stdout.flush()
```

**Problems**:
1. **Inaccurate line counting**: Rich renders Panel, Markdown, etc. with automatic line wrapping based on terminal width. Line counts captured via `StringIO` don't match the actual display.
2. **Over/under-clearing**: Results in leftover content or accidental deletion of other content.

---

### Approach 2: ANSI Cursor Save/Restore

**Idea**: Save the cursor position before displaying results, then restore to that position and clear below on toggle.

```python
def save_cursor_position():
    sys.stdout.write("\033[s")
    sys.stdout.flush()

def restore_cursor_and_clear():
    sys.stdout.write("\033[u\033[J")
    sys.stdout.flush()
```

**Problems**:
1. **prompt_toolkit conflict**: The key binding triggers while waiting for user input, when prompt_toolkit is managing cursor position.
2. **Clears the input prompt**: The restore + clear operation also removes the `>` or `You:` prompt.
3. **Terminal compatibility**: Different terminals have varying levels of support for ANSI cursor save/restore.

---

### Approach 3: Rich Console Capture for Precise Counting

**Idea**: Use `console.capture()` to capture Rich-rendered output and precisely count lines.

```python
def display_with_capture(state, **kwargs) -> int:
    with console.capture() as capture:
        display_final_results(state, **kwargs)

    output = capture.get()
    sys.stdout.write(output)
    sys.stdout.flush()
    return output.count('\n')
```

**Problems**:
1. **Still can't prevent prompt clearing**: When clearing lines with ANSI codes, prompt_toolkit's input prompt falls within the clear range.
2. **Rich capture vs actual output discrepancy**: Subtle differences sometimes remain.

---

### Approach 4: Simple Append (No Clear)

**Idea**: Give up on in-place replacement; on toggle, just append new content with a separator line.

```python
@bindings.add('c-o')
def toggle_details(event):
    console.print("\n" + "─" * 40)
    console.print(f"[dim]Detail display: {status}[/dim]")
    # Append new content...
```

**Problems**:
1. **Content accumulation**: Multiple toggles produce large amounts of duplicate content.
2. **Poor UX**: Not a true toggle.

---

### Approach 5: Only Affect Next Response

**Idea**: Ctrl+O only changes a settings flag; the new setting is applied on the next agent response.

```python
@bindings.add('c-o')
def toggle_details(event):
    show = state.toggle_details()
    print(f"\n[Details: {'ON' if show else 'OFF'}]")
```

**Problems**:
1. **Not an instant toggle**: Users expect to see the effect immediately.
2. **Semantically incorrect**: Behaves more like a "setting" than a "toggle".

---

## Root Cause Analysis

### Why is in-place replacement difficult in a terminal?

1. **Terminals are stream-based output**: Traditional terminals output line by line with no concept of "regions". Once content is printed, it becomes part of the terminal history.

2. **ANSI escape code limitations**:
   - `\033[nA` moves up n lines
   - `\033[J` clears to bottom of screen
   - These only operate on the currently visible screen area and affect other content (such as the input prompt).

3. **prompt_toolkit and Rich conflict**:
   - `prompt_toolkit` manages the input area and cursor
   - `Rich` manages output rendering
   - When both run simultaneously, directly manipulating the terminal (ANSI codes) causes state inconsistencies.

4. **Rich Live limitations**:
   - The `Live` context can achieve in-place updates, but content is fixed once Live exits.
   - While prompt_toolkit waits for input, Live cannot run simultaneously.

---

## The Right Solution

To achieve a true "fixed input box + toggleable output area", a **TUI (Text User Interface) framework** is needed:

### Recommended: Textual

[Textual](https://github.com/Textualize/textual) is a modern TUI framework by the Rich team:

```python
from textual.app import App
from textual.widgets import Input, RichLog

class ChatApp(App):
    def compose(self):
        yield RichLog(id="output")  # Scrollable output area
        yield Input(id="input")     # Fixed input box

    def on_key(self, event):
        if event.key == "ctrl+o":
            # Can safely manipulate the output area
            self.query_one("#output").clear()
            # Re-render...
```

**Pros**:
- True region management (separate output + input areas)
- Supports scrolling and focus management
- Integrates seamlessly with Rich

**Cons**:
- Requires adding a dependency
- Requires refactoring the CLI architecture

### Other Options

- **blessed** / **urwid**: Lower-level TUI libraries
- **ink** (Node.js): React for CLI, possibly the approach used by Claude Code

---

## Current Implementation

Given the constraint of not adding extra dependencies, the simplest reliable approach was adopted:

- **Always show all information** (thinking + tools + response)
- **No toggle functionality**
- **Use `transient=True` with Live** for clean streaming display
- **Show complete final results** for easy user review

---

## Future Improvements

If toggle functionality is needed, the recommendations are:

1. **Add `textual` as a dependency** and refactor into a TUI application
2. Or **provide a Web UI** as an alternative (easier to implement fixed layouts)

---

*Document created: 2024-01*
