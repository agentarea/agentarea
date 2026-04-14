# Event System Refactoring TODO

## Current Problems
- Events are untyped `dict[str, Any]` — no compile-time safety
- `DomainEvent.data = kwargs` mixes metadata with payload
- Event types are raw strings scattered across codebase
- Adapters use `d.get("result", "fallback")` hiding missing data bugs
- `original_data` nesting creates double-indirection bugs (subscriber must unwrap)

## Required Changes

### 1. EventType Enum
```python
class EventType(str, Enum):
    WORKFLOW_STARTED = "WorkflowStarted"
    WORKFLOW_COMPLETED = "WorkflowCompleted"
    WORKFLOW_FAILED = "WorkflowFailed"
    ITERATION_STARTED = "IterationStarted"
    ITERATION_COMPLETED = "IterationCompleted"
    LLM_CALL_STARTED = "LLMCallStarted"
    LLM_CALL_COMPLETED = "LLMCallCompleted"
    TOOL_CALL_STARTED = "ToolCallStarted"
    TOOL_CALL_COMPLETED = "ToolCallCompleted"
    TOOL_CALL_FAILED = "ToolCallFailed"
    ...
```

### 2. Typed Event Payloads (Pydantic)
```python
class WorkflowCompletedEvent(BaseModel):
    task_id: str
    agent_id: str
    execution_id: str
    success: bool
    result: str  # required, no default
    iterations_completed: int
    total_cost: str
```

### 3. No Default Fallbacks
- Remove all `d.get("result", "Task completed.")` patterns
- If a required field is missing, log error + send error message to channel

### 4. Clean DomainEvent
- Separate metadata (event_id, timestamp, event_type) from payload (data)
- Remove `self.data = kwargs` pattern
- Use typed event models instead of raw dicts

## Files Affected
- `libs/common/agentarea_common/events/base_events.py`
- `libs/execution/agentarea_execution/workflows/helpers.py` (EventManager)
- `libs/execution/agentarea_execution/workflows/visibility.py` (EventTypes)
- `libs/execution/agentarea_execution/activities/agent_execution_activities.py`
- `libs/triggers/agentarea_triggers/channels/subscriber.py`
- `libs/triggers/agentarea_triggers/channels/adapters.py`
- `libs/triggers/agentarea_triggers/channels/telegram.py`
- `agentarea-webapp/src/types/events.ts` (frontend mirror)
