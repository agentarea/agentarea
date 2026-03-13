# Temporal Resilience: Heartbeats + Continue-As-New

**Date:** 2026-03-11
**Status:** Approved
**Scope:** Agent execution workflow hardening for production

## Context

Our `AgentExecutionWorkflow` handles long-running agent tasks but lacks two critical Temporal patterns:
1. **Activity heartbeats** — workers can crash during LLM calls without detection; cancellation doesn't propagate to running activities
2. **Continue-As-New** — event history grows unbounded, risking the 50K event / 50MB Temporal limit

## Architecture: Two-Tier Context Model

We already have a two-tier context architecture (no new code needed, just documenting):

```
Tier 1: Workflow State (working set)
  - Compacted messages optimized for LLM context
  - Reset on continue-as-new
  - Aggressive compaction is safe because tier 2 exists

Tier 2: DB Event Log (full history)
  - Every tool call + result, every LLM response (already published via TaskEventService)
  - Permanent, append-only, never compacted
  - Enables future: audit, recovery, cross-agent context sharing
```

## Change 1: Auto-Heartbeater Decorator

**Problem:** `call_llm_activity` and `execute_mcp_tool_activity` don't heartbeat. If a worker crashes during a 60s LLM call, Temporal won't know until `start_to_close_timeout` (2-5 min) expires. Activities can't receive cancellation signals without heartbeating.

**Solution:** Port Temporal's `_auto_heartbeater` pattern — a background asyncio task that heartbeats at `heartbeat_timeout / 2` frequency.

**New file:** `agentarea-platform/libs/execution/agentarea_execution/activities/heartbeat.py`

```python
import asyncio
from functools import wraps
from temporalio import activity

def auto_heartbeater(fn):
    """Decorator that auto-heartbeats during long-running activities."""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        heartbeat_timeout = activity.info().heartbeat_timeout
        heartbeat_task = None
        if heartbeat_timeout:
            async def _heartbeat():
                while True:
                    await asyncio.sleep(heartbeat_timeout.total_seconds() / 2)
                    activity.heartbeat()
            heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            return await fn(*args, **kwargs)
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
    return wrapper
```

**Apply to activities:**
- `call_llm_activity` — LLM calls can take 30-120s
- `execute_mcp_tool_activity` — tool execution varies
- `compact_messages_activity` — uses LLM for summarization

**Workflow scheduling changes** (in `agent_execution_workflow.py`):
- Add `heartbeat_timeout=timedelta(seconds=30)` to activity execution options for LLM and tool activities

## Change 2: Continue-As-New

**Problem:** Each iteration generates multiple Temporal events (activity scheduled, started, completed for LLM + tools + event publishing). At ~10-15 events per iteration × 50 max iterations = 500-750 events. With delegation and retries, could be higher. Not an immediate crisis but no safety net.

**Solution:** Check `workflow.info().is_continue_as_new_suggested()` each iteration. When triggered, compact messages and restart with fresh event history.

**New model:** `ContinueAsNewState` in `workflows/models.py`

```python
class ContinueAsNewState(BaseModel):
    """State carried across continue-as-new boundaries."""
    execution_id: str
    agent_id: str
    task_id: str
    user_id: str
    workspace_id: str
    goal: AgentGoal
    messages: list[dict]  # Already compacted
    agent_config: dict
    available_tools: list[dict]
    current_iteration: int
    total_cost: float
    budget_usd: float | None
    context_window: int
    user_context_data: dict
    continued_from_run_id: str | None = None  # For audit trail
```

**Workflow changes:**
- `AgentExecutionRequest` gets optional `continued_state: ContinueAsNewState | None`
- `_initialize_workflow()` checks for continued_state and restores instead of fresh init
- `_execute_main_loop()` checks `is_continue_as_new_suggested()` after each iteration
- New method `_continue_as_new()`: compact messages → build ContinueAsNewState → `workflow.continue_as_new()`
- Publish `WorkflowContinuedAsNew` event before continuing (for audit trail in tier 2)

## Files to Modify

| File | Change |
|------|--------|
| `activities/heartbeat.py` | **New** — auto_heartbeater decorator |
| `activities/agent_execution_activities.py` | Apply decorator to 3 activities |
| `workflows/agent_execution_workflow.py` | Add heartbeat_timeout to activity scheduling, add continue-as-new logic |
| `workflows/models.py` | Add ContinueAsNewState |
| `workflows/constants.py` | Add new event type |
| `workflows/events.py` | Add WorkflowContinuedAsNewEvent |
| `models.py` | Extend AgentExecutionRequest with continued_state |

## Future Work (Not in This Change)

- **Claim-check pattern** — store large payloads in S3, reference in workflow (when tool results get very large)
- **Progressive compaction** — compact old tool results in-place between full compactions
- **Recall from history** — activity to fetch specific events from DB tier 2 back into tier 1
- **Multi-agent scoped context** — different agents get different views of shared event log
- **Agent-to-agent messaging** — beyond current synchronous delegation
- **Supervisor/fan-out orchestration** — parallel agent execution patterns
- **Dedicated event store** — evaluate Cassandra/ScyllaDB when event volume demands it
- **Heartbeat progress payloads** — resume tool execution from last checkpoint on retry
