# ADF Agent

A LangChain-based reasoning-action agent for Azure Data Factory. Think of it as a **mini Claude Code, but with ADF tools** — it reasons about your question, picks tools, executes them, inspects results, and iterates until it has an answer.

```
$ uv run adf_agent "Which pipelines in sales dev use Snowflake?"

  💭 Thinking...
  🔧 resolve_adf_target("sales", "dev")         → OK
  🔧 adf_pipeline_list()                        → 242 pipelines saved
  🔧 adf_linked_service_list()                  → 18 linked services
  🔧 adf_dataset_list()                         → 65 datasets saved
  🔧 exec_python(cross_reference_script)         → 20 pipelines matched

  Found 20 pipelines using Snowflake linked services:
  | Pipeline         | Linked Service      |
  |------------------|---------------------|
  | daily_load       | snowflake_prod_ls   |
  | hourly_sync      | snowflake_v2_ls     |
  ...
```

## Architecture

```
User prompt
  │
  ▼
┌─────────────────────────────────────────────┐
│  Claude (Sonnet / Opus)                     │
│  Extended Thinking → Reasoning → Tool Calls │
│                                             │
│  System Prompt                              │
│  ├─ ADF domain knowledge                   │
│  ├─ Tool descriptions                      │
│  └─ Skills catalog (loaded at startup)      │
└───────┬─────────────────────────────────────┘
        │  tool calls
        ▼
┌─────────────────────────────────────────────┐
│  LangGraph Agent Loop                       │
│                                             │
│  Tools                    Skills            │
│  ├─ adf_pipeline_list     ├─ find-pipe...   │
│  ├─ adf_linked_service_*  └─ test-linked..  │
│  ├─ adf_dataset_list                        │
│  ├─ adf_integration_runtime_*               │
│  ├─ exec_python  ◄── token saver            │
│  ├─ read_file / write_file                  │
│  ├─ glob / grep / list_dir                  │
│  └─ resolve_adf_target                      │
│                                             │
│  Context: ADFConfig, session_dir, cache     │
└───────┬─────────────────────────────────────┘
        │  Azure SDK calls
        ▼
┌─────────────────────────────────────────────┐
│  Azure Data Factory REST API                │
│  (via azure-mgmt-datafactory SDK)           │
└─────────────────────────────────────────────┘
```

## How It Works

The agent follows a **ReAct (Reasoning + Acting)** loop powered by LangGraph:

1. **Reason** — Claude reads the user's question, thinks (Extended Thinking), decides what to do
2. **Act** — Calls one or more tools (can be parallel)
3. **Observe** — Reads tool outputs, decides if more work is needed
4. **Repeat** — Loops back to step 1 until the question is answered

This is the same loop that powers tools like Claude Code, but scoped to ADF operations with domain-specific tools and knowledge baked into the system prompt.

## Tools

### ADF Tools

| Tool | Description |
|------|-------------|
| `adf_pipeline_list` | List all pipelines; saves each as `pipelines/{name}.json` |
| `adf_pipeline_get` | Get a specific pipeline definition |
| `adf_dataset_list` | List all datasets with linked service mappings |
| `adf_linked_service_list` | List linked services (name + type) |
| `adf_linked_service_get` | Get full linked service definition |
| `adf_linked_service_test` | Test a linked service connection |
| `adf_integration_runtime_list` | List all Integration Runtimes |
| `adf_integration_runtime_get` | Get IR status |
| `adf_integration_runtime_enable` | Enable interactive authoring on a Managed IR |

All ADF tools require a target to be set first via `resolve_adf_target(domain, environment)`.

### General Tools

| Tool | Description |
|------|-------------|
| `resolve_adf_target` | Switch the active ADF instance (domain + environment) |
| `read_file` | Read file contents (with line numbers) |
| `write_file` | Write content to a file |
| `glob` | Find files by glob pattern |
| `grep` | Search for regex patterns in files |
| `list_dir` | List directory contents |
| `exec_python` | Execute Python code in a subprocess |

### Skill Tool

| Tool | Description |
|------|-------------|
| `load_skill` | Load detailed instructions for a named skill |

## Skills

Skills are multi-step workflows defined as Markdown files in `.claude/skills/`. The agent discovers them at startup (names + descriptions go into the system prompt), and loads the full instructions on-demand via `load_skill()` when a user request matches.

### `find-pipelines-by-service`

Find all pipelines that use a specific type of linked service (e.g., Snowflake).

Cross-references pipelines, datasets, and linked services through a 7-step workflow:
1. Resolve target
2. List pipelines, linked services, and datasets (parallel)
3. Identify matching linked services by type
4. Read sample JSON files to understand the exact schema
5. Write and run a cross-reference script via `exec_python`
6. Debug and retry if needed
7. Present results as a table

### `test-linked-service`

Test linked service connections with automatic IR handling:
1. Determine scope (single service, by type, or all)
2. Get linked service details to find its IR reference
3. Check IR status — enable interactive authoring for Managed IRs if needed
4. Run the connection test
5. Present results with actionable error suggestions

## Saving Tokens with `exec_python`

A core design principle: **keep large data out of the LLM context**.

ADF tools save JSON data to the session workspace (`workspace/sessions/{timestamp}/`) instead of returning it inline. When the agent needs to analyze this data, it writes a Python script and runs it via `exec_python` in a subprocess. The script reads JSON from disk, processes it, and prints a summary — only the summary enters the LLM context.

```
Without exec_python:                    With exec_python:
─────────────────────                   ─────────────────
adf_pipeline_list()                     adf_pipeline_list()
  → 42 pipelines as JSON                 → "42 pipelines saved to pipelines/"
  → ~200K tokens in context               → ~50 tokens in context

LLM reads all 200K tokens              exec_python(analysis_script)
to find Snowflake pipelines              → script reads files from disk
  → expensive                            → prints "7 pipelines matched"
                                         → ~100 tokens in context
                                         → cheap
```

### Pre-loaded Runtime

To avoid boilerplate in every `exec_python` call, a helper module (`_exec_runtime.py`) is deployed to the session directory once and auto-imported:

```python
# These are available in every exec_python call without importing:
json, re, sys, Path, Counter, defaultdict

# Helper functions:
load_json("datasets.json")       # Load from session dir
save_json("results.json", data)  # Save to session dir
pretty_print(data)               # Pretty-print with truncation
session_dir                      # Path to current session directory
```

This means the agent can write concise analysis code:

```python
exec_python("""
datasets = load_json("datasets.json")
snowflake_ds = [d for d in datasets if "Snowflake" in d["type"]]
print(f"Found {len(snowflake_ds)} Snowflake datasets")
for d in snowflake_ds:
    print(f"  - {d['name']} -> {d['linked_service']}")
""")
```

Instead of wasting tokens on `import json; from pathlib import Path; ...` every time.

## Observability with MLflow

The agent uses `mlflow.langchain.autolog()` for zero-config tracing of all LangChain agent calls:

```python
# adf_agent/observability/mlflow_setup.py
mlflow.set_experiment("ADF-Agent")
mlflow.langchain.autolog()
```

Every agent invocation is logged as an MLflow run under the `ADF-Agent` experiment, capturing:
- Input/output messages
- Tool calls and results
- Token usage
- Latency

### Local tracking (default)

```bash
# Runs are saved to ./mlruns/ by default
mlflow ui  # View at http://localhost:5000
```

### Remote tracking

```bash
export MLFLOW_TRACKING_URI=http://your-mlflow-server:5000
uv run adf_agent --interactive
```

## Model Support

The agent supports models hosted by **Anthropic** directly or via **Azure AI Foundry**.

### Anthropic (default)

```env
CLAUDE_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-5-20250929   # optional, this is the default
```

### Azure AI Foundry

```env
CLAUDE_PROVIDER=azure_foundry
ANTHROPIC_FOUNDRY_API_KEY=your-key
ANTHROPIC_FOUNDRY_BASE_URL=https://<resource>.services.ai.azure.com/anthropic
CLAUDE_MODEL=claude-sonnet-4-5-20250929   # optional
```

The Azure Foundry integration uses a custom `ChatAzureFoundryClaude` class that extends `ChatAnthropic` and swaps the HTTP client to `AnthropicFoundry`, so all LangChain features (streaming, tool calling, Extended Thinking) work identically on both providers.

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Azure credentials configured (`az login` or service principal)
- Anthropic API key or Azure Foundry endpoint

### Install

```bash
uv sync
```

### Configure

Create a `.env` file (or run `uv run adf_agent` for guided onboarding):

```env
# Model provider
CLAUDE_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Optional overrides
CLAUDE_MODEL=claude-sonnet-4-5-20250929
MAX_TOKENS=16000
```

Azure credentials are resolved via `DefaultAzureCredential` (Azure CLI, managed identity, environment variables, etc.).

### Run

```bash
# Interactive mode (default)
uv run adf_agent

# Explicit interactive flag
uv run adf_agent --interactive

# Single request
uv run adf_agent "list all pipelines in sales prod"

# Disable Extended Thinking
uv run adf_agent --no-thinking "list linked services"
```

## Token Tracking

The CLI displays per-turn and total token usage with Anthropic Prompt Caching breakdown:

```
─── Token Usage (turn) ───
 Input: 3,625  (cache_create: 3,269 · cache_read: 0)
 Output: 155
 Total: 3,780

─── Token Usage (total) ───
 Input: 7,250  (cache_create: 3,269 · cache_read: 3,269)
 Output: 410
 Total: 7,660
```

System prompt and skills catalog are marked with `cache_control: ephemeral` (5-min TTL), so multi-turn conversations benefit from cache hits at 0.1x the cost of fresh input tokens.

## Project Structure

```
ADFAgent/
├── adf_agent/
│   ├── agent.py              # Agent core: model init, ReAct loop, streaming
│   ├── cli.py                # Interactive CLI with Rich live display
│   ├── context.py            # Runtime context: ADF config, session dir, cache
│   ├── prompts.py            # System prompt builder with skills injection
│   ├── skill_loader.py       # Two-tier skill discovery and loading
│   ├── azure_claude.py       # Azure Foundry ChatAnthropic adapter
│   ├── tools/
│   │   ├── adf_tools.py      # ADF pipeline/dataset/linked service/IR tools
│   │   ├── general_tools.py  # File ops, exec_python, target resolution
│   │   ├── skill_tools.py    # load_skill tool
│   │   ├── azure_adf_client.py  # Azure SDK wrapper
│   │   └── _exec_runtime.py  # Pre-loaded helpers for exec_python
│   ├── stream/               # Streaming event system + token tracking
│   └── observability/        # MLflow autolog setup
├── azure_tools/              # Reusable Azure SDK wrappers (ADF, KeyVault, Storage, Batch)
├── .claude/skills/           # Skill definitions (Markdown with YAML frontmatter)
└── workspace/sessions/       # Per-session output (pipeline JSON, scripts, results)
```
