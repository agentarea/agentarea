# Dynamic Context Discovery for AgentArea

**Date:** 2026-03-15
**Status:** Draft
**Inspired by:** [Cursor Blog — Dynamic Context Discovery](https://cursor.com/blog/dynamic-context-discovery)

## Problem

Agent execution workflows load all context statically at startup:
- All MCP tool definitions (name + description + inputSchema) passed to every LLM call
- Tool results stored in full in message history until compaction
- Compacted messages lost except via limited `recall_history` (500 char truncation)
- Skill script outputs go entirely into tool result messages

With 5 MCP servers × 20 tools each, tool definitions alone can consume 15-20K tokens per LLM call. Large tool results (JSON responses, terminal output) further bloat the context window, triggering premature compaction and losing valuable information.

## Solution Overview

Apply progressive disclosure across all context types: load only what the agent needs, when it needs it. Use MinIO (S3-compatible, in-cluster, ~1-5ms reads) as the backing store for deferred content.

| # | Feature | Approach |
|---|---------|----------|
| 1 | MCP Tool Discovery | Catalog of names in system prompt, `activate_tool_source()` loads full schemas on demand |
| 2 | Tool Output Offloading | Results > 2000 tokens → MinIO, summary + reference in context |
| 3 | Chat History Preservation | Full messages saved to MinIO before compaction, searchable via enhanced `recall_history` |
| 4 | Terminal Output Offloading | Skill script outputs > 2000 tokens → same pattern as #2 |
| 5 | Agent Skills | Already implemented with progressive disclosure |

**Token threshold for offloading:** 2000 tokens (~8000 characters).

## Design

### 1. Tool Progressive Disclosure (Strategy + Proxy pattern)

**Current flow:**
```
Agent start → discover_available_tools_activity → ALL tool definitions → state.available_tools → every LLM call
```

**New flow:**
```
Agent start → ToolCatalog builds lightweight entries from all ToolProviders → system prompt
Agent calls activate_tool_source("github") → full tool definitions loaded into state.available_tools
Subsequent LLM calls → only activated tools in tools list
```

#### Architecture (SOLID + GoF)

**ToolProvider** (Protocol) — abstraction for any tool source:
```python
class ToolProvider(Protocol):
    """Any source of tools — MCP server, OpenAPI spec, code tools, agent."""

    @property
    def name(self) -> str: ...

    @property
    def provider_type(self) -> str: ...  # "mcp", "openapi", "agent", "code"

    def get_catalog_entry(self) -> CatalogEntry:
        """Lightweight: name + tool names only. No schemas."""

    def get_tool_definitions(self) -> list[dict]:
        """Full OpenAI-compatible tool definitions with schemas."""
```

**CatalogEntry** — lightweight value object (Proxy for full definitions):
```python
@dataclass
class CatalogEntry:
    name: str
    provider_type: str
    tool_names: list[str]
```

**Concrete providers** (Strategy pattern — each type implements discovery differently):
- `MCPToolProvider` — wraps `MCPServerInstance`, extracts tools from `json_spec["available_tools"]`
- `CodeToolProvider` — wraps code-based tool definitions
- `AgentToolProvider` — wraps A2A agent tool definitions
- New types (OpenAPI, etc.) — add a new `ToolProvider` implementation, nothing else changes

**ToolCatalog** — aggregates providers, manages activation state:
```python
class ToolCatalog:
    """Aggregates ToolProviders, builds prompt catalog, handles activation."""

    def __init__(self, providers: list[ToolProvider]):
        self._providers = {p.name: p for p in providers}
        self._activated: set[str] = set()

    def build_prompt_text(self) -> str:
        """Compact catalog for system prompt."""
        # Available Tool Sources:
        # - github [mcp] (5 tools): list_repos, create_issue, ...
        # - data-api [openapi] (12 tools): get_users, create_order, ...
        # Use activate_tool_source("name") to enable tools before using them.

    def activate(self, source_name: str) -> list[dict]:
        """Load full tool definitions for a source. Returns OpenAI-format tools."""

    def get_openai_function_definition(self) -> dict:
        """Tool definition for activate_tool_source with enum of available sources."""

    @property
    def activated_sources(self) -> list[str]: ...
```

**Design principles:**
- **Open/Closed**: New tool type = new `ToolProvider` impl. `ToolCatalog` and workflow unchanged.
- **Liskov**: All providers interchangeable via protocol.
- **Dependency Inversion**: Workflow depends on `ToolProvider` abstraction, not concrete MCP/OpenAPI.
- **Interface Segregation**: Catalog only needs `get_catalog_entry()`, activation only needs `get_tool_definitions()`.
- **GoF Strategy**: Each provider encapsulates a different tool discovery strategy.
- **GoF Proxy**: `CatalogEntry` is a lightweight proxy for full tool definitions.

**Workflow changes** (`agent_execution_workflow.py`):
- `_prepare_execution_step()`: wrap each tool source in a `ToolProvider`, build `ToolCatalog`
- Inject `activate_tool_source` tool into `state.available_tools`
- On `activate_tool_source` call: `catalog.activate(name)` → append definitions to `state.available_tools`
- Subsequent LLM calls see expanded tools list (KV cache re-stabilizes after activation)

**KV cache benefit:** Tools list is shorter initially → smaller cached prefix. After activation, list stabilizes → cache works for all subsequent calls. If agent uses 1 of 5 sources, cacheable prefix stays ~5x smaller throughout.

#### Data flow

```
Agent tool config (mcp, code, agent, ...)
         ↓
ToolProvider implementations (one per source)
         ↓
ToolCatalog(providers)
         ↓
catalog.build_prompt_text()          catalog (holds providers internally)
         ↓                                      ↓
System prompt text                   Agent calls activate_tool_source("github")
"github [mcp] (5 tools): ..."               ↓
         ↓                           catalog.activate("github")
LLM sees catalog                     → provider.get_tool_definitions()
         ↓                                      ↓
Decides which source needed          Full tool definitions returned
                                                 ↓
                                     Appended to state.available_tools
                                                 ↓
                                     Next LLM call includes full schemas
```

### 2. Tool Output Offloading

**Current flow:**
```
MCP tool result → Message(role="tool", content=FULL_RESULT) → stays in context until compaction
```

**New flow (result > 2000 tokens):**
```
MCP tool result → store full result in MinIO → Message(role="tool", content=SUMMARY + reference)
Agent calls read_tool_output("output_12", grep="error") → targeted read from MinIO
```

#### Components

**ContextStore** (new, see section 5) — unified MinIO storage for outputs and history.

**Temporal activities** (new, in `agent_execution_activities.py`):
- `store_context_output_activity(StoreOutputRequest) -> StoreOutputResult` — saves to MinIO
- `read_context_output_activity(ReadOutputRequest) -> ReadOutputResult` — selective read with grep/head/tail
- `store_history_chunk_activity(StoreHistoryRequest) -> StoreHistoryResult` — saves compacted messages
- `search_history_activity(SearchHistoryRequest) -> SearchHistoryResult` — searches across chunks

All MinIO I/O **must** go through activities — Temporal workflows are deterministic and cannot perform I/O directly.

**Output summarization** (in workflow, inline — no I/O, just string ops):
- For results > 2000 tokens: extract first 500 chars + last 200 chars + basic stats
- Summary format:
  ```
  [Output stored as output_12 — 15,230 chars, 47 lines]
  Preview: {"repositories": [{"name": "agentarea", "stars": 142, ...
  ...
  Use read_tool_output("output_12") for full content, or read_tool_output("output_12", grep="pattern") to search.
  ```

**read_tool_output tool** (new built-in tool):
- Parameters: `output_id: str`, `grep: str?`, `head: int?`, `tail: int?`
- Routed in `_execute_tool_calls()` dispatch alongside `recall_history`, `activate_skill`, etc.
- Calls `read_context_output_activity` under the hood
- Added to `state.available_tools` alongside other built-in tools

#### Workflow changes

In `_process_tool_results()` (after `execute_mcp_tool_activity`):
```python
result_text = mcp_result.result
estimated_tokens = len(result_text) // 4

if estimated_tokens > TOOL_OUTPUT_OFFLOAD_THRESHOLD:  # 2000
    output_id = tool_call.id  # use unique tool_call ID, not index
    await workflow.execute_activity(
        store_context_output_activity,
        args=[StoreOutputRequest(task_id=task_id, output_id=output_id, content=result_text)],
        start_to_close_timeout=timedelta(seconds=10),
    )
    summary = build_output_summary(result_text, output_id)
    message = Message(role="tool", content=summary, tool_call_id=..., name=...)
else:
    message = Message(role="tool", content=result_text, tool_call_id=..., name=...)
```

**Fallback on MinIO failure:** If `store_context_output_activity` fails, fall through to current behavior — keep full output in message context. The agent loses nothing; it just uses more tokens.

In `_execute_tool_calls()` dispatch:
```python
# Add alongside existing recall_calls, skill_calls, etc.
read_output_calls = [tc for tc in tool_calls if tc.function.name == "read_tool_output"]
for call in read_output_calls:
    result = await workflow.execute_activity(
        read_context_output_activity,
        args=[ReadOutputRequest(task_id=task_id, **call.function.arguments)],
        start_to_close_timeout=timedelta(seconds=10),
    )
    # ... append tool result message
```

### 3. Chat History Preservation

**Current flow:**
```
Compaction triggered → LLM summarizes old messages → originals discarded
recall_history → DB events with 500 char truncation
```

**New flow:**
```
Compaction triggered → save full messages to MinIO → LLM summarizes → originals replaced
recall_history → search full history in MinIO with grep support
```

#### Components

**HistoryStore** (new, or extend `ToolOutputStore` as `ContextStore`):
- `store_history_chunk(task_id, chunk_index, messages: list[dict]) -> None`
- `search_history(task_id, grep=None, message_type=None, tool_name=None) -> str`
- MinIO path: `tasks/{workspace_id}/{task_id}/history/chunk_{n}.json`

#### Workflow changes

In `_compact_messages()`:
```python
# Before compaction — save full messages to MinIO via activity
messages_to_compact = self.state.messages[1:boundary]  # exclude system prompt
chunk_index = self.state.history_chunk_counter
await workflow.execute_activity(
    store_history_chunk_activity,
    args=[StoreHistoryRequest(
        task_id=task_id,
        chunk_index=chunk_index,
        messages=[m.model_dump() for m in messages_to_compact],
    )],
    start_to_close_timeout=timedelta(seconds=15),
)
self.state.history_chunk_counter += 1

# Existing compaction logic continues...
```

**Fallback:** If `store_history_chunk_activity` fails, compaction proceeds normally — we lose full history access but don't block the agent.

**SkillContextGuard interaction:** Protected messages (activated skill content) are included in history chunks for completeness, but `find_compaction_boundary` still skips them as before — they stay in active context.

Enhanced `recall_history` tool:
- Add `grep: str?` parameter for pattern search across all history chunks
- Add `tool_name: str?` to filter by specific tool results
- Remove 500-char truncation — return full matched content (with reasonable limit)
- Routes through `search_history_activity` instead of DB events
- **Breaking change** to `RecallHistoryRequest` model — add new optional fields, backward compatible

### 4. Terminal Output Offloading

Same pattern as #2, applied specifically to skill script execution.

#### Workflow changes

In skill script result handling:
```python
script_result = await execute_skill_script_activity(request)
combined_output = script_result.stdout + ("\nSTDERR:\n" + script_result.stderr if script_result.stderr else "")
estimated_tokens = len(combined_output) // 4

if estimated_tokens > TOOL_OUTPUT_OFFLOAD_THRESHOLD:  # 2000
    output_id = f"script_{script_name}_{tool_call.id}"
    await workflow.execute_activity(
        store_context_output_activity,
        args=[StoreOutputRequest(task_id=task_id, output_id=output_id, content=combined_output)],
        start_to_close_timeout=timedelta(seconds=10),
    )
    summary = build_output_summary(combined_output, output_id)
    content = summary
else:
    content = combined_output
```

No new components needed — reuses `ContextStore` and `store_context_output_activity` from #2.

### 5. Unified Storage: ContextStore

Features #2, #3, #4 all use MinIO with similar patterns. Unify into a single `ContextStore`.

**Important:** `ContextStore` lives in the **activity layer**, not the workflow layer. It is instantiated inside activity functions and accessed only through `workflow.execute_activity()` calls. The workflow never touches `ContextStore` directly.

```python
class ContextStore:
    """Manages offloaded context in MinIO for a task execution.

    Used inside Temporal activities only — never in workflow code directly.
    Resolved from DI container within activity context.
    """

    def __init__(self, s3_client, bucket: str, workspace_id: UUID, task_id: UUID):
        self.prefix = f"tasks/{workspace_id}/{task_id}"

    # Tool outputs
    async def store_output(self, output_id: str, content: str) -> None
    async def read_output(self, output_id: str, grep=None, head=None, tail=None) -> str

    # History chunks
    async def store_history_chunk(self, chunk_index: int, messages: list[dict]) -> None
    async def search_history(self, grep=None, tool_name=None) -> str

    # Cleanup
    async def cleanup(self) -> None  # Called on task completion
```

**MinIO path structure:**
```
tasks/{workspace_id}/{task_id}/
├── outputs/
│   ├── output_0.json
│   ├── output_1.json
│   └── script_data_fetcher.json
└── history/
    ├── chunk_0.json
    └── chunk_1.json
```

## New Tools Summary

| Tool | Purpose | Parameters |
|------|---------|------------|
| `activate_tool_source` | Load tool source definitions into context | `source_name: str` (enum) |
| `read_tool_output` | Read offloaded tool result | `output_id: str`, `grep?: str`, `head?: int`, `tail?: int` |
| `recall_history` (enhanced) | Search compacted-out history | `grep?: str`, `tool_name?: str`, `message_type?: str` |

## Constants

```python
# In constants.py
TOOL_OUTPUT_OFFLOAD_THRESHOLD = 2000  # tokens (~8000 chars)
OUTPUT_SUMMARY_HEAD_CHARS = 500
OUTPUT_SUMMARY_TAIL_CHARS = 200
READ_OUTPUT_MAX_RETURN_CHARS = 16000  # safety limit for read_tool_output
HISTORY_SEARCH_MAX_RESULTS = 20
```

## ContinueAsNewState

When a workflow crosses the continue-as-new boundary, state is serialized through `ContinueAsNewState`. The following fields must be added:

```python
class ContinueAsNewState(BaseModel):
    # ... existing fields ...
    history_chunk_counter: int = 0
    activated_tool_sources: list[str] = []  # names of activated servers
```

**MCP registry on continue-as-new:** The full tool definitions for activated servers are already in `state.available_tools` (which is serialized as `available_tools: list[dict]`). The MCP registry (name → definitions lookup) does NOT need to be carried — on continue-as-new, we only need to know which servers were activated to prevent re-activation. If the agent needs a new server post-continue, it calls `activate_tool_source` again.

**Payload size:** `available_tools` is already serialized. Adding `activated_tool_sources` (list of strings) is negligible. No Temporal payload size concerns.

## Files to Create/Modify

**New files:**
- `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_provider.py` — `ToolProvider` protocol, `CatalogEntry`, concrete providers (MCP, Code, Agent)
- `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_catalog.py` — `ToolCatalog` (aggregation, prompt text, activation)
- `agentarea-platform/libs/execution/agentarea_execution/workflows/context_store.py` — ContextStore (MinIO)

**Modified files:**
- `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py` — integrate all 4 features, add `read_tool_output` dispatch
- `agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py` — new thresholds
- `agentarea-platform/libs/execution/agentarea_execution/workflows/models.py` — add `history_chunk_counter`, `activated_tool_sources` to state and `ContinueAsNewState`
- `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py` — new activities for store/read/search
- `agentarea-platform/libs/execution/agentarea_execution/models.py` — new request/result models for context store activities
- `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_manager.py` — split discovery into catalog vs full, add per-server grouping

## Migration & Rollout

1. **Phase 1:** ContextStore + Tool Output Offloading (#2, #4) — lowest risk, immediate token savings
2. **Phase 2:** Chat History Preservation (#3) — enhances compaction, improves recall
3. **Phase 3:** MCP Tool Progressive Disclosure (#1) — biggest impact, requires prompt engineering to ensure agent activates servers reliably

Phase 3 last because it changes agent behavior — need to validate that agents reliably call `activate_tool_source` before using tools. Can A/B test with `feature_flag` on agent config.

## Expected Impact

- **Token reduction:** 30-50% on agents with multiple MCP servers (matches Cursor's 46.9%)
- **Context quality:** Less noise from unused tool definitions and large outputs
- **Recall accuracy:** Full history searchable vs 500-char truncated events
- **KV cache efficiency:** Smaller, more stable prefix = better cache hit rate
- **Cost:** MinIO storage negligible (~KB per task), reads ~1-5ms in-cluster
