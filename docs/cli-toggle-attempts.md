# CLI Toggle 功能实现尝试记录

## 目标

在交互式 CLI 中实现 Ctrl+O 快捷键，用于 toggle 显示/隐藏 thinking 和 tool calls 的详细信息，实现"原地替换"效果。

## 技术栈

- `prompt_toolkit`: 处理用户输入和键盘绑定
- `rich`: 终端格式化输出（Panel, Markdown, Live 等）
- 纯 Python 标准库

---

## 尝试方案

### 方案 1: ANSI 行数计算 + 清除

**思路**: 计算输出的行数，toggle 时用 ANSI 转义码清除这些行，然后重新渲染。

```python
def clear_lines(n: int):
    """清除终端中最后 n 行"""
    sys.stdout.write(f"\033[{n}A\033[J")
    sys.stdout.flush()
```

**问题**:
1. **行数计算不准确**: Rich 渲染 Panel、Markdown 时会根据终端宽度自动换行，用 `StringIO` 捕获的行数与实际显示不一致
2. **清除过多/过少**: 导致内容残留或误删其他内容

---

### 方案 2: ANSI 光标保存/恢复

**思路**: 在显示结果前保存光标位置，toggle 时恢复到该位置并清除下方内容。

```python
def save_cursor_position():
    sys.stdout.write("\033[s")
    sys.stdout.flush()

def restore_cursor_and_clear():
    sys.stdout.write("\033[u\033[J")
    sys.stdout.flush()
```

**问题**:
1. **prompt_toolkit 冲突**: key binding 在等待用户输入时触发，此时 prompt_toolkit 正在管理光标位置
2. **清除了输入提示符**: 恢复光标后清除操作会把 `>` 或 `You:` 提示符也清掉
3. **终端兼容性**: 不同终端对 ANSI 光标保存/恢复的支持程度不同

---

### 方案 3: Rich Console Capture 精确计算

**思路**: 使用 `console.capture()` 捕获 Rich 渲染后的输出，精确计算行数。

```python
def display_with_capture(state, **kwargs) -> int:
    with console.capture() as capture:
        display_final_results(state, **kwargs)

    output = capture.get()
    sys.stdout.write(output)
    sys.stdout.flush()
    return output.count('\n')
```

**问题**:
1. **仍然无法解决 prompt 被清除**: ANSI 清除行时，prompt_toolkit 的输入提示符位于清除范围内
2. **Rich capture 与实际输出差异**: 有时仍存在细微差异

---

### 方案 4: 简单追加（不清除）

**思路**: 放弃原地替换，toggle 时只追加新内容，用分隔线区分。

```python
@bindings.add('c-o')
def toggle_details(event):
    console.print("\n" + "─" * 40)
    console.print(f"[dim]Detail display: {status}[/dim]")
    # 追加显示新内容...
```

**问题**:
1. **内容堆积**: 多次 toggle 会产生大量重复内容
2. **用户体验差**: 不是真正的 toggle

---

### 方案 5: 只影响下次响应

**思路**: Ctrl+O 只改变设置状态，下次 agent 响应时才应用新设置。

```python
@bindings.add('c-o')
def toggle_details(event):
    show = state.toggle_details()
    print(f"\n[Details: {'ON' if show else 'OFF'}]")
```

**问题**:
1. **不是即时 toggle**: 用户期望的是立即看到效果
2. **语义不符**: 更像是"设置"而不是"toggle"

---

## 根本原因分析

### 为什么在终端中难以实现原地替换？

1. **终端是流式输出**: 传统终端是逐行输出的，没有"区域"概念。一旦内容打印出去，就成为终端历史的一部分。

2. **ANSI 转义码的局限性**:
   - `\033[nA` 上移 n 行
   - `\033[J` 清除到屏幕底部
   - 这些只能操作当前屏幕可见区域，且会影响到其他内容（如输入提示符）

3. **prompt_toolkit 与 Rich 的冲突**:
   - `prompt_toolkit` 管理输入区域和光标
   - `Rich` 管理输出渲染
   - 两者同时运行时，直接操作终端（ANSI codes）会导致状态不一致

4. **Rich Live 的限制**:
   - `Live` 上下文可以实现原地更新，但退出 Live 后内容固定
   - 在 prompt_toolkit 等待输入时，不能同时运行 Live

---

## 正确的解决方案

要实现真正的"固定输入框 + 可 toggle 的输出区域"，需要使用 **TUI (Text User Interface) 框架**:

### 推荐方案: Textual

[Textual](https://github.com/Textualize/textual) 是 Rich 团队开发的现代 TUI 框架：

```python
from textual.app import App
from textual.widgets import Input, RichLog

class ChatApp(App):
    def compose(self):
        yield RichLog(id="output")  # 可滚动的输出区域
        yield Input(id="input")     # 固定的输入框

    def on_key(self, event):
        if event.key == "ctrl+o":
            # 可以安全地操作输出区域
            self.query_one("#output").clear()
            # 重新渲染...
```

**优点**:
- 真正的区域管理（输出区 + 输入区分离）
- 支持滚动、焦点管理
- 与 Rich 完美集成

**缺点**:
- 需要添加依赖
- 需要重构 CLI 架构

### 其他选项

- **blessed** / **urwid**: 更底层的 TUI 库
- **ink** (Node.js): React for CLI，Claude Code 可能使用的方案

---

## 当前实现

鉴于不添加额外依赖的限制，当前采用最简单可靠的方案：

- **始终显示所有信息**（thinking + tools + response）
- **不实现 toggle 功能**
- **使用 `transient=True` 的 Live** 保持流式显示干净
- **最终结果完整显示** 便于用户回顾

---

## 未来改进

如果需要实现 toggle 功能，建议：

1. **添加 `textual` 依赖** 并重构为 TUI 应用
2. 或 **提供 Web UI** 作为替代方案（更容易实现固定布局）

---

*文档创建时间: 2024-01*
