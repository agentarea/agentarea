# A2A v0.3.0 Spec Compliance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make our A2A implementation fully compliant with the Google A2A protocol v0.3.0 spec, with verified end-to-end task execution and delegation.

**Architecture:** Fix types and Agent Card to match spec field naming (camelCase), add missing methods (`tasks/resubscribe`, `tasks/list`), fix SSE streaming format to use JSON-RPC wrapper with `kind` discriminator, add missing task states (`rejected`, `auth-required`), implement `A2A-Version` header handling.

**Tech Stack:** Python/FastAPI, Pydantic v2, Temporal workflows, Redis pub/sub SSE

---

## File Structure

| File | Responsibility |
|------|---------------|
| `libs/common/agentarea_common/utils/types.py` | A2A type definitions (Pydantic models) |
| `apps/api/agentarea_api/api/v1/agents_a2a.py` | JSON-RPC endpoint, dispatch, handlers |
| `apps/api/agentarea_api/api/v1/agents_well_known.py` | `/.well-known/agent.json` discovery |
| `apps/api/agentarea_api/api/v1/a2a_validation.py` | Request validation middleware |
| `apps/api/agentarea_api/api/v1/a2a_auth.py` | Auth context extraction |
| `libs/tasks/agentarea_tasks/bridges/a2a_bridge.py` | A2A SDK bridge (cleanup/remove) |
| `tests/unit/test_a2a_types.py` | Type model tests |
| `tests/unit/test_a2a_agent_card.py` | Agent Card spec compliance tests |
| `tests/unit/test_a2a_streaming.py` | SSE format compliance tests |
| `tests/integration/test_a2a_e2e.py` | End-to-end task execution tests |

All paths below are relative to `agentarea-platform/`.

---

## Chunk 1: Fix A2A Type Models to Match Spec v0.3.0

The current types use non-spec field names (`type` instead of `kind` for Parts, `session_id` instead of `contextId` for Task, missing `protocolVersion` on AgentCard). The spec requires camelCase JSON serialization.

### Task 1: Fix Part type discriminator from `type` to `kind`

**Files:**
- Modify: `libs/common/agentarea_common/utils/types.py:27-60`
- Create: `tests/unit/test_a2a_types.py`

- [ ] **Step 1: Write failing test for Part `kind` field**

```python
# tests/unit/test_a2a_types.py
"""Tests for A2A type models spec compliance."""
import pytest
from agentarea_common.utils.types import TextPart, FilePart, DataPart, Part
from pydantic import TypeAdapter

def test_text_part_uses_kind_field():
    part = TextPart(text="hello")
    dumped = part.model_dump()
    assert "kind" in dumped
    assert dumped["kind"] == "text"
    assert "type" not in dumped

def test_file_part_uses_kind_field():
    part = FilePart(file={"uri": "https://example.com/f.txt", "mimeType": "text/plain"})
    dumped = part.model_dump()
    assert dumped["kind"] == "file"

def test_data_part_uses_kind_field():
    part = DataPart(data={"key": "value"})
    dumped = part.model_dump()
    assert dumped["kind"] == "data"

def test_part_discriminator_parses_kind():
    adapter = TypeAdapter(Part)
    parsed = adapter.validate_python({"kind": "text", "text": "hello"})
    assert isinstance(parsed, TextPart)
    assert parsed.text == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && python -m pytest ../../tests/unit/test_a2a_types.py -v -x`
Expected: FAIL — `kind` not found, `type` found instead

- [ ] **Step 3: Update Part models to use `kind` instead of `type`**

In `libs/common/agentarea_common/utils/types.py`, change:

```python
class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] | None = None

class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    file: FileContent
    metadata: dict[str, Any] | None = None

class DataPart(BaseModel):
    kind: Literal["data"] = "data"
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None

Part = Annotated[TextPart | FilePart | DataPart, Field(discriminator="kind")]
```

- [ ] **Step 4: Fix FileContent to use spec field names**

```python
class FileContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(None, alias="filename")
    mime_type: str | None = Field(None, alias="mimeType")
    data: str | None = None  # base64 bytes (was "bytes")
    uri: str | None = Field(None, alias="url")

    @model_validator(mode="after")
    def check_content(self) -> Self:
        if not (self.data or self.uri):
            raise ValueError("Either 'data' or 'uri' must be present in the file")
        if self.data and self.uri:
            raise ValueError("Only one of 'data' or 'uri' can be present")
        return self
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest ../../tests/unit/test_a2a_types.py -v`
Expected: PASS

- [ ] **Step 6: Grep for all usages of `.type` on Part objects and update**

Search: `grep -rn "\.type ==" libs/ apps/ --include="*.py" | grep -i part`
Update any code that references `part.type` to use `part.kind`.

- [ ] **Step 7: Commit**

```bash
git add libs/common/agentarea_common/utils/types.py tests/unit/test_a2a_types.py
git commit -m "fix(a2a): rename Part discriminator from 'type' to 'kind' per spec v0.3.0"
```

### Task 2: Fix Task model — `session_id` → `contextId`, add `protocolVersion`

**Files:**
- Modify: `libs/common/agentarea_common/utils/types.py:89-96`
- Modify: `tests/unit/test_a2a_types.py`

- [ ] **Step 1: Write failing test**

```python
# append to tests/unit/test_a2a_types.py
from agentarea_common.utils.types import Task, TaskState, TaskStatus

def test_task_uses_context_id():
    task = Task(
        id="t1",
        contextId="ctx1",
        status=TaskStatus(state=TaskState.SUBMITTED),
    )
    dumped = task.model_dump(by_alias=True)
    assert "contextId" in dumped
    assert "session_id" not in dumped

def test_task_serializes_camel_case():
    task = Task(
        id="t1",
        context_id="ctx1",
        status=TaskStatus(state=TaskState.SUBMITTED),
    )
    dumped = task.model_dump(by_alias=True)
    assert "contextId" in dumped
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update Task model**

```python
class Task(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    metadata: dict[str, Any] | None = None
```

- [ ] **Step 4: Update all references from `session_id` to `context_id`**

Search `agents_a2a.py` and `a2a_bridge.py` for `session_id` usage in Task construction and update.

- [ ] **Step 5: Run tests, verify pass**

- [ ] **Step 6: Commit**

```bash
git commit -am "fix(a2a): rename Task.session_id to context_id (contextId) per spec"
```

### Task 3: Add missing TaskState values and Artifact fields

**Files:**
- Modify: `libs/common/agentarea_common/utils/types.py:17-25,79-87`

- [ ] **Step 1: Write failing test**

```python
def test_task_states_match_spec():
    """A2A v0.3.0 requires these 8 states."""
    assert TaskState.SUBMITTED.value == "submitted"
    assert TaskState.WORKING.value == "working"
    assert TaskState.INPUT_REQUIRED.value == "input-required"
    assert TaskState.AUTH_REQUIRED.value == "auth-required"
    assert TaskState.COMPLETED.value == "completed"
    assert TaskState.FAILED.value == "failed"
    assert TaskState.CANCELED.value == "canceled"
    assert TaskState.REJECTED.value == "rejected"

def test_artifact_has_artifact_id():
    from agentarea_common.utils.types import Artifact
    a = Artifact(artifactId="a1", parts=[{"kind": "text", "text": "hi"}])
    dumped = a.model_dump(by_alias=True)
    assert "artifactId" in dumped
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update TaskState enum and Artifact model**

```python
class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"

class Artifact(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    artifact_id: str | None = Field(None, alias="artifactId")
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None
    index: int = 0
    append: bool | None = None
    last_chunk: bool | None = Field(None, alias="lastChunk")
```

- [ ] **Step 4: Update `convert_simple_task_to_a2a_task` in agents_a2a.py to handle new states**

Add mappings for `input-required`, `auth-required`, `rejected`, `pending` in the `task_state_mapping` dict at line ~389.

- [ ] **Step 5: Run tests, verify pass**

- [ ] **Step 6: Commit**

```bash
git commit -am "fix(a2a): add missing TaskState values and fix Artifact field names"
```

### Task 4: Add `protocolVersion` and missing fields to AgentCard

**Files:**
- Modify: `libs/common/agentarea_common/utils/types.py:283-294`

- [ ] **Step 1: Write failing test**

```python
from agentarea_common.utils.types import AgentCard, AgentCapabilities

def test_agent_card_has_protocol_version():
    card = AgentCard(
        name="test",
        url="http://localhost",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[],
    )
    dumped = card.model_dump(by_alias=True)
    assert "protocolVersion" in dumped

def test_agent_card_has_security_schemes():
    card = AgentCard(
        name="test",
        url="http://localhost",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[],
    )
    dumped = card.model_dump(by_alias=True)
    assert "supportsAuthenticatedExtendedCard" in dumped
    assert "defaultInputModes" in dumped
    assert "defaultOutputModes" in dumped
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update AgentCard model**

```python
class AgentCard(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str | None = None
    url: str
    protocol_version: str = Field("0.3.0", alias="protocolVersion")
    version: str = "1.0.0"
    provider: AgentProvider | None = None
    documentation_url: str | None = Field(None, alias="documentationUrl")
    capabilities: AgentCapabilities
    authentication: AgentAuthentication | None = None
    default_input_modes: list[str] = Field(["text/plain", "application/json"], alias="defaultInputModes")
    default_output_modes: list[str] = Field(["text/plain", "application/json"], alias="defaultOutputModes")
    skills: list[AgentSkill]
    supports_authenticated_extended_card: bool = Field(True, alias="supportsAuthenticatedExtendedCard")
    security_schemes: dict[str, Any] | None = Field(None, alias="securitySchemes")
    security: list[dict[str, list[str]]] | None = None
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Update `agents_well_known.py` and `agents_a2a.py` card construction**

Both `create_agent_card_for_agent()` in `agents_well_known.py` and `handle_agent_card()` in `agents_a2a.py` build AgentCard manually. Update to include `security_schemes` and `security` fields with the Kratos bearer scheme.

- [ ] **Step 6: Commit**

```bash
git commit -am "fix(a2a): add protocolVersion, securitySchemes, input/outputModes to AgentCard"
```

---

## Chunk 2: Fix SSE Streaming Format to Match Spec

Current streaming sends custom event format. Spec requires JSON-RPC 2.0 wrapper with `kind` discriminator (`task`, `status-update`, `artifact-update`).

### Task 5: Fix SSE event format to use JSON-RPC wrapper with `kind`

**Files:**
- Modify: `apps/api/agentarea_api/api/v1/agents_a2a.py:742-853`
- Create: `tests/unit/test_a2a_streaming_format.py`

- [ ] **Step 1: Write test for spec-compliant SSE format**

```python
# tests/unit/test_a2a_streaming_format.py
"""Tests for A2A SSE streaming format compliance."""
import json
import pytest

def test_initial_event_is_kind_task():
    """First SSE event must be kind=task with full task object."""
    event_data = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "kind": "task",
            "id": "task-1",
            "contextId": "ctx-1",
            "status": {"state": "submitted", "timestamp": "2026-03-10T00:00:00"},
            "metadata": {},
        },
    }
    parsed = json.loads(json.dumps(event_data))
    assert parsed["result"]["kind"] == "task"
    assert "id" in parsed["result"]
    assert "status" in parsed["result"]

def test_status_update_event_format():
    """Status updates must have kind=status-update with final flag."""
    event_data = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "kind": "status-update",
            "taskId": "task-1",
            "contextId": "ctx-1",
            "status": {"state": "working", "timestamp": "2026-03-10T00:00:01"},
            "final": False,
        },
    }
    parsed = json.loads(json.dumps(event_data))
    assert parsed["result"]["kind"] == "status-update"
    assert "final" in parsed["result"]

def test_artifact_update_event_format():
    """Artifact updates must have kind=artifact-update."""
    event_data = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "kind": "artifact-update",
            "taskId": "task-1",
            "contextId": "ctx-1",
            "artifact": {
                "artifactId": "art-1",
                "parts": [{"kind": "text", "text": "output"}],
            },
            "append": False,
            "lastChunk": False,
        },
    }
    parsed = json.loads(json.dumps(event_data))
    assert parsed["result"]["kind"] == "artifact-update"
    assert "append" in parsed["result"]
    assert "lastChunk" in parsed["result"]

def test_final_event_has_final_true():
    """Terminal status update must have final=true."""
    event_data = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "kind": "status-update",
            "taskId": "task-1",
            "contextId": "ctx-1",
            "status": {"state": "completed", "timestamp": "2026-03-10T00:00:02"},
            "final": True,
        },
    }
    parsed = json.loads(json.dumps(event_data))
    assert parsed["result"]["final"] is True
```

- [ ] **Step 2: Add SSE event builder types to types.py**

```python
# Add to types.py after TaskArtifactUpdateEvent

class StreamResponseTask(BaseModel):
    """SSE event: initial task object."""
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["task"] = "task"
    id: str
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    history: list[Message] | None = None
    artifacts: list[Artifact] | None = None
    metadata: dict[str, Any] | None = None

class StreamResponseStatusUpdate(BaseModel):
    """SSE event: task status change."""
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["status-update"] = "status-update"
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    final: bool = False

class StreamResponseArtifactUpdate(BaseModel):
    """SSE event: artifact/output chunk."""
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["artifact-update"] = "artifact-update"
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    artifact: Artifact
    append: bool = False
    last_chunk: bool = Field(False, alias="lastChunk")
```

- [ ] **Step 3: Rewrite `event_stream()` in `handle_message_stream_sse`**

Replace the custom event format in `agents_a2a.py:742-853` with spec-compliant JSON-RPC wrapped events:

```python
async def event_stream():
    """Stream events in A2A v0.3.0 SSE format."""
    try:
        # 1. Send initial "task" event
        initial = JSONRPCResponse(
            id=request_id,
            result=StreamResponseTask(
                id=str(created_task.id),
                context_id=None,
                status=TaskStatus(state=TaskState.SUBMITTED),
            ).model_dump(by_alias=True),
        )
        yield f"data: {initial.model_dump_json(by_alias=True)}\n\n"

        # 2. Stream workflow events, converting to status-update / artifact-update
        async for event in event_stream_service.stream_events_for_task(
            created_task.id, event_patterns=["workflow.*"]
        ):
            event_type = event.get("event_type", "")
            event_data = event.get("event_data", {})

            # Map workflow events to A2A SSE events
            terminal_events = {
                "workflow.task_completed": TaskState.COMPLETED,
                "workflow.task_failed": TaskState.FAILED,
                "workflow.task_cancelled": TaskState.CANCELED,
                "task_completed": TaskState.COMPLETED,
                "task_failed": TaskState.FAILED,
                "task_cancelled": TaskState.CANCELED,
            }

            is_terminal = event_type in terminal_events
            state = terminal_events.get(event_type)

            if state:
                # Terminal status update
                update = JSONRPCResponse(
                    id=request_id,
                    result=StreamResponseStatusUpdate(
                        taskId=str(created_task.id),
                        status=TaskStatus(state=state),
                        final=True,
                    ).model_dump(by_alias=True),
                )
                yield f"data: {update.model_dump_json(by_alias=True)}\n\n"
                break
            elif "llm_response" in event_type or "content" in event_data:
                # Artifact update for LLM output
                content = event_data.get("content", event_data.get("text", ""))
                if content:
                    artifact_update = JSONRPCResponse(
                        id=request_id,
                        result=StreamResponseArtifactUpdate(
                            taskId=str(created_task.id),
                            artifact=Artifact(
                                artifactId=str(uuid4()),
                                parts=[TextPart(text=content)],
                            ),
                            append=True,
                            lastChunk=False,
                        ).model_dump(by_alias=True),
                    )
                    yield f"data: {artifact_update.model_dump_json(by_alias=True)}\n\n"
            else:
                # Status update for other workflow events
                update = JSONRPCResponse(
                    id=request_id,
                    result=StreamResponseStatusUpdate(
                        taskId=str(created_task.id),
                        status=TaskStatus(state=TaskState.WORKING),
                        final=False,
                    ).model_dump(by_alias=True),
                )
                yield f"data: {update.model_dump_json(by_alias=True)}\n\n"

    except Exception as e:
        error_resp = JSONRPCResponse(
            id=request_id,
            error=JSONRPCError(code=-32603, message=str(e)),
        )
        yield f"data: {error_resp.model_dump_json(by_alias=True)}\n\n"
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "fix(a2a): rewrite SSE streaming to use JSON-RPC wrapper with kind discriminator"
```

---

## Chunk 3: Add Missing RPC Methods

### Task 6: Add `tasks/resubscribe` handler

**Files:**
- Modify: `apps/api/agentarea_api/api/v1/agents_a2a.py`
- Modify: `apps/api/agentarea_api/api/v1/a2a_validation.py:74-80`

- [ ] **Step 1: Add `tasks/resubscribe` to SUPPORTED_METHODS in a2a_validation.py**

```python
SUPPORTED_METHODS: ClassVar[set[str]] = {
    "message/send",
    "message/stream",
    "tasks/get",
    "tasks/cancel",
    "tasks/resubscribe",
    "tasks/list",
    "agent/authenticatedExtendedCard",
}
```

- [ ] **Step 2: Add handler in agents_a2a.py**

```python
async def handle_task_resubscribe(
    request, request_id, params, task_service, agent_id, auth_context, event_stream_service
):
    """Handle tasks/resubscribe — re-attach to SSE stream for an existing task."""
    task_id = validate_task_id_param(params)

    set_user_context_from_a2a_auth(auth_context)

    task = await task_service.get_task_with_workflow_status(task_id)
    if not task:
        return create_error_response(request_id, -32001, f"Task not found: {task_id}")

    # If task already terminal, return final status update
    if task.status in ("completed", "failed", "cancelled", "canceled"):
        state = convert_simple_task_to_a2a_task(task).status.state

        async def done_stream():
            final = JSONRPCResponse(
                id=request_id,
                result=StreamResponseStatusUpdate(
                    taskId=str(task_id),
                    status=TaskStatus(state=state),
                    final=True,
                ).model_dump(by_alias=True),
            )
            yield f"data: {final.model_dump_json(by_alias=True)}\n\n"

        return StreamingResponse(done_stream(), media_type="text/event-stream")

    # Otherwise, stream live events (same logic as message/stream but for existing task)
    async def event_stream():
        async for event in event_stream_service.stream_events_for_task(
            task_id, event_patterns=["workflow.*"]
        ):
            # ... same event mapping as handle_message_stream_sse
            pass
        # Send terminal status when done

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 3: Register in `_dispatch_rpc_method`**

Add to the `handlers` dict:
```python
"tasks/resubscribe": lambda: handle_task_resubscribe(
    request, request_id, params, task_service, agent_id, auth_context, event_stream_service
),
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(a2a): add tasks/resubscribe method for SSE reconnection"
```

### Task 7: Add `tasks/list` handler

**Files:**
- Modify: `apps/api/agentarea_api/api/v1/agents_a2a.py`

- [ ] **Step 1: Add handler**

```python
async def handle_task_list(request_id, params, task_service, agent_id, auth_context):
    """Handle tasks/list — list tasks for an agent with optional filtering."""
    set_user_context_from_a2a_auth(auth_context)

    limit = params.get("limit", 50)
    offset = params.get("offset", 0)

    tasks = await task_service.get_agent_tasks(agent_id, limit=limit, offset=offset)
    a2a_tasks = [convert_simple_task_to_a2a_task(t) for t in tasks]

    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=[
        t.model_dump(by_alias=True) for t in a2a_tasks
    ])
```

- [ ] **Step 2: Register in dispatch and commit**

```bash
git commit -am "feat(a2a): add tasks/list method"
```

### Task 8: Add `A2A-Version` header handling

**Files:**
- Modify: `apps/api/agentarea_api/api/v1/agents_a2a.py:1337-1345`

- [ ] **Step 1: Add version check at start of `handle_agent_jsonrpc`**

After parsing the request body, before dispatch:

```python
# Check A2A-Version header
a2a_version = request.headers.get("a2a-version", "0.3")
if a2a_version and not a2a_version.startswith("0.3"):
    return create_error_response(
        request_id, -32007, f"Unsupported A2A version: {a2a_version}. Supported: 0.3.x"
    )
```

- [ ] **Step 2: Add -32007 error code to types.py**

```python
class VersionNotSupportedError(JSONRPCError):
    code: int = -32007
    message: str = "Version not supported"
    data: None = None
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(a2a): add A2A-Version header validation"
```

---

## Chunk 4: Fix Agent Card camelCase Serialization

### Task 9: Add camelCase serialization to all A2A models

**Files:**
- Modify: `libs/common/agentarea_common/utils/types.py`

- [ ] **Step 1: Write test**

```python
def test_agent_capabilities_camel_case():
    caps = AgentCapabilities(
        streaming=True,
        push_notifications=True,
        state_transition_history=True,
    )
    dumped = caps.model_dump(by_alias=True)
    assert "pushNotifications" in dumped
    assert "stateTransitionHistory" in dumped

def test_agent_skill_camel_case():
    skill = AgentSkill(
        id="s1", name="test",
        input_modes=["text"], output_modes=["text"],
    )
    dumped = skill.model_dump(by_alias=True)
    assert "inputModes" in dumped
    assert "outputModes" in dumped

def test_task_send_params_camel_case():
    from agentarea_common.utils.types import TaskSendParams, Message, TextPart
    params = TaskSendParams(
        id="t1",
        message=Message(role="user", parts=[TextPart(text="hi")]),
        accepted_output_modes=["text"],
        history_length=10,
    )
    dumped = params.model_dump(by_alias=True)
    assert "acceptedOutputModes" in dumped
    assert "historyLength" in dumped
```

- [ ] **Step 2: Add Field aliases to all models that need camelCase**

For `AgentCapabilities`:
```python
class AgentCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    streaming: bool = False
    push_notifications: bool = Field(False, alias="pushNotifications")
    state_transition_history: bool = Field(False, alias="stateTransitionHistory")
```

For `AgentSkill`:
```python
class AgentSkill(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    examples: list[str] | None = None
    input_modes: list[str] | None = Field(None, alias="inputModes")
    output_modes: list[str] | None = Field(None, alias="outputModes")
```

For `TaskSendParams`:
```python
class TaskSendParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    session_id: str = Field(default_factory=lambda: uuid4().hex, alias="contextId")
    message: Message
    accepted_output_modes: list[str] | None = Field(None, alias="acceptedOutputModes")
    push_notification: PushNotificationConfig | None = Field(None, alias="pushNotification")
    history_length: int | None = Field(None, alias="historyLength")
    metadata: dict[str, Any] | None = None
```

For `TaskStatusUpdateEvent`:
```python
class TaskStatusUpdateEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    status: TaskStatus
    final: bool = False
    metadata: dict[str, Any] | None = None
```

For `TaskArtifactUpdateEvent` (no changes needed for field names, already simple).

For `PushNotificationConfig`:
```python
class PushNotificationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    url: str
    token: str | None = None
    authentication: AuthenticationInfo | None = None
    webhook_secret_token: str | None = Field(None, alias="webhookSecretToken")
```

- [ ] **Step 3: Update all `.model_dump()` calls to use `by_alias=True`**

Search agents_a2a.py for `.model_dump()` calls and ensure they use `by_alias=True`.

- [ ] **Step 4: Update `agents_well_known.py` card construction**

The current `create_agent_card_for_agent` uses keyword args like `pushNotifications=False` which won't work with Python field names. Update to use `push_notifications=False` (the Python field name) and let `by_alias=True` handle serialization.

- [ ] **Step 5: Run tests, verify pass**

- [ ] **Step 6: Commit**

```bash
git commit -am "fix(a2a): add camelCase aliases to all A2A models for spec compliance"
```

---

## Chunk 5: Cleanup, Remove Dead Code, End-to-End Validation

### Task 10: Clean up a2a_bridge.py (uses old a2a-sdk types)

**Files:**
- Modify: `libs/tasks/agentarea_tasks/bridges/a2a_bridge.py`

- [ ] **Step 1: Check if a2a_bridge.py is imported anywhere**

```bash
grep -rn "a2a_bridge\|A2ATaskBridge" apps/ libs/ --include="*.py"
```

- [ ] **Step 2: If unused, delete it. If used, update to use our types.py instead of `a2a.types`**

The bridge currently imports from `a2a.types` (external SDK) but our `agents_a2a.py` uses `agentarea_common.utils.types`. This is confusing. Either:
- Delete if unused
- Or update imports to use our types

- [ ] **Step 3: Also fix stack trace leaks in a2a_bridge.py**

Lines 99, 145, 180 expose `{e!s}` in error responses. Replace with generic messages.

- [ ] **Step 4: Commit**

```bash
git commit -am "chore(a2a): clean up a2a_bridge.py, remove dead code"
```

### Task 11: Write end-to-end integration test

**Files:**
- Create: `tests/integration/test_a2a_spec_compliance.py`

- [ ] **Step 1: Write comprehensive spec compliance test**

```python
# tests/integration/test_a2a_spec_compliance.py
"""End-to-end A2A v0.3.0 spec compliance tests.

These tests require a running API server with Temporal.
Run with: pytest tests/integration/test_a2a_spec_compliance.py -v --run-integration
"""
import json
import httpx
import pytest

BASE_URL = "http://localhost:8000/api/v1"

@pytest.fixture
def auth_headers():
    """Get valid auth headers for testing."""
    # TODO: Replace with actual token retrieval
    return {"Authorization": "Bearer test-token", "A2A-Version": "0.3"}

@pytest.fixture
def agent_id():
    """Get a valid test agent ID."""
    # TODO: Create test agent or use known ID
    return "your-test-agent-uuid"

class TestAgentCardCompliance:
    """Test /.well-known/agent.json spec compliance."""

    def test_agent_card_has_protocol_version(self, agent_id):
        resp = httpx.get(f"{BASE_URL}/agents/{agent_id}/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["protocolVersion"] == "0.3.0"

    def test_agent_card_has_required_fields(self, agent_id):
        resp = httpx.get(f"{BASE_URL}/agents/{agent_id}/.well-known/agent.json")
        card = resp.json()
        required = ["name", "url", "protocolVersion", "capabilities", "skills"]
        for field in required:
            assert field in card, f"Missing required field: {field}"

    def test_agent_card_capabilities_camel_case(self, agent_id):
        resp = httpx.get(f"{BASE_URL}/agents/{agent_id}/.well-known/agent.json")
        caps = resp.json()["capabilities"]
        assert "streaming" in caps
        assert "pushNotifications" in caps
        assert "stateTransitionHistory" in caps

class TestRPCCompliance:
    """Test JSON-RPC endpoint compliance."""

    def test_message_send_returns_task(self, agent_id, auth_headers):
        payload = {
            "jsonrpc": "2.0",
            "id": "test-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello agent"}],
                },
            },
        }
        resp = httpx.post(
            f"{BASE_URL}/agents/{agent_id}/a2a/rpc",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "test-1"
        task = result["result"]
        assert "id" in task
        assert "status" in task
        assert task["status"]["state"] == "submitted"

    def test_tasks_get_returns_task(self, agent_id, auth_headers):
        # First create a task
        # Then get it
        pass

    def test_unsupported_version_returns_error(self, agent_id, auth_headers):
        headers = {**auth_headers, "A2A-Version": "1.0"}
        payload = {
            "jsonrpc": "2.0",
            "id": "test-ver",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
        }
        resp = httpx.post(
            f"{BASE_URL}/agents/{agent_id}/a2a/rpc",
            json=payload,
            headers=headers,
        )
        result = resp.json()
        assert result["error"]["code"] == -32007
```

- [ ] **Step 2: Commit**

```bash
git commit -am "test(a2a): add end-to-end spec compliance integration tests"
```

### Task 12: Final verification — run all tests and validate

- [ ] **Step 1: Run unit tests**

```bash
cd agentarea-platform && make test
```

- [ ] **Step 2: Run integration tests against local stack**

```bash
cd agentarea-platform && python -m pytest tests/integration/test_a2a_spec_compliance.py -v
```

- [ ] **Step 3: Manual verification with curl**

```bash
# Get agent card
curl -s http://localhost:8000/api/v1/agents/{AGENT_ID}/.well-known/agent.json | jq .

# Send message
curl -s -X POST http://localhost:8000/api/v1/agents/{AGENT_ID}/a2a/rpc \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "A2A-Version: 0.3" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Hello"}]}}}' | jq .

# Stream response
curl -s -X POST http://localhost:8000/api/v1/agents/{AGENT_ID}/a2a/rpc \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":"2","method":"message/stream","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Hello"}]}}}'
```

- [ ] **Step 4: Commit final state**

```bash
git commit -am "chore(a2a): A2A v0.3.0 spec compliance complete"
```
