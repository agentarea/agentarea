# Agent-to-Agent Delegation & Remote MCP Exposure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable agents to delegate tasks to other agents via the A2A protocol as a tool, and expose workspace MCP servers externally for remote consumption.

**Architecture:** Two independent features sharing one codebase. Feature 1 adds `type: "agent"` to the tool system — an `A2AAgentTool` calls another agent's A2A `/rpc` endpoint using `message/send`. Feature 2 adds a new FastAPI router that proxies MCP JSON-RPC calls (`tools/list`, `tools/call`) to internal MCP server instances, gated by the existing A2A auth (Bearer token / API key).

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx (async HTTP client for A2A calls), Temporal workflows, existing MCP Manager (Go)

---

## File Structure

### Feature 1: Agent-to-Agent Delegation Tool

| File | Action | Responsibility |
|------|--------|---------------|
| `agentarea-platform/libs/agents/agentarea_agents/schemas/import_export.py` | Modify | Add `type: "agent"` to `ToolConfigYAML`, add `AgentToolSettingsYAML` |
| `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_agent_tool.py` | Create | `A2AAgentTool(BaseTool)` — calls target agent via A2A `message/send` |
| `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_tool_factory.py` | Create | `A2AAgentToolFactory` — resolves agent name → A2A URL, creates tool instances |
| `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_manager.py` | Modify | Add `elif tool_type == "agent"` branch in `discover_available_tools` |
| `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/__init__.py` | Modify | Export new classes |
| `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py` | Modify | Pass `agent_service` to `ToolManager.discover_available_tools` |
| `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py` | No change | Tool calls already route through `execute_mcp_tool_activity` which uses `ToolExecutor` |
| `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_executor.py` | Modify | Register A2A tools in `execute_tool` fallback path |

### Feature 2: Remote MCP Exposure

| File | Action | Responsibility |
|------|--------|---------------|
| `agentarea-platform/apps/api/agentarea_api/api/v1/mcp_remote.py` | Create | FastAPI router for remote MCP access (`/mcp/remote/{instance_name}/rpc`) |
| `agentarea-platform/apps/api/agentarea_api/api/v1/__init__.py` or router registration | Modify | Register new `mcp_remote` router |

### Tests

| File | Action |
|------|--------|
| `agentarea-platform/tests/unit/tools/test_a2a_agent_tool.py` | Create |
| `agentarea-platform/tests/unit/tools/test_a2a_tool_factory.py` | Create |
| `agentarea-platform/tests/unit/tools/test_tool_manager_agent.py` | Create |
| `agentarea-platform/tests/unit/api/test_mcp_remote.py` | Create |

---

## Chunk 1: Agent-to-Agent Delegation Tool

### Task 1: Extend ToolConfigYAML to accept `type: "agent"`

**Files:**
- Modify: `agentarea-platform/libs/agents/agentarea_agents/schemas/import_export.py:51-71`
- Test: `agentarea-platform/tests/unit/tools/test_tool_manager_agent.py`

- [ ] **Step 1: Write the failing test for agent tool config parsing**

```python
# agentarea-platform/tests/unit/tools/test_tool_manager_agent.py
"""Tests for agent tool type in ToolConfigYAML."""

import pytest
from agentarea_agents.schemas.import_export import ToolConfigYAML, ToolSettingsYAML


class TestToolConfigYAMLAgentType:
    def test_agent_tool_config_valid(self):
        """Agent tool config should parse with type='agent'."""
        config = ToolConfigYAML(
            type="agent",
            name="research-agent",
            settings=ToolSettingsYAML(
                a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
            ),
        )
        assert config.type == "agent"
        assert config.name == "research-agent"
        assert config.settings.a2a_url == "http://localhost:8000/api/v1/agents/abc/a2a/rpc"

    def test_agent_tool_config_with_agent_name_only(self):
        """Agent tool config can reference agent by name (resolved at runtime)."""
        config = ToolConfigYAML(
            type="agent",
            name="research-agent",
        )
        assert config.type == "agent"
        assert config.name == "research-agent"

    def test_code_tool_config_still_works(self):
        """Existing code tool configs should still parse."""
        config = ToolConfigYAML(type="code", name="web_search")
        assert config.type == "code"

    def test_mcp_tool_config_still_works(self):
        """Existing MCP tool configs should still parse."""
        config = ToolConfigYAML(
            type="mcp",
            name="my-mcp-instance",
            settings=ToolSettingsYAML(allowed_tools=["tool1"]),
        )
        assert config.type == "mcp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_tool_manager_agent.py::TestToolConfigYAMLAgentType -v`
Expected: FAIL — `type="agent"` not accepted by `Literal["code", "mcp"]`

- [ ] **Step 3: Implement schema changes**

In `agentarea-platform/libs/agents/agentarea_agents/schemas/import_export.py`:

```python
# Update ToolSettingsYAML to include agent-specific settings
class ToolSettingsYAML(BaseModel):
    """Tool settings configuration in YAML format."""

    disabled_methods: list[str] | None = None  # For code tools
    allowed_tools: list[str] | None = None  # For MCP tools
    a2a_url: str | None = None  # For agent tools: explicit A2A endpoint URL
    description_override: str | None = None  # For agent tools: override agent description in tool schema


# Update ToolConfigYAML type literal
class ToolConfigYAML(BaseModel):
    """Tool configuration in YAML format."""

    type: Literal["code", "mcp", "agent"]
    name: str
    settings: ToolSettingsYAML | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate that tool name is not empty."""
        if not v or not v.strip():
            raise ValueError("Tool name cannot be empty")
        return v.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_tool_manager_agent.py::TestToolConfigYAMLAgentType -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/agents/agentarea_agents/schemas/import_export.py agentarea-platform/tests/unit/tools/test_tool_manager_agent.py
git commit -m "feat: extend ToolConfigYAML to accept type='agent'"
```

---

### Task 2: Create A2AAgentTool — the BaseTool that calls another agent via A2A

**Files:**
- Create: `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_agent_tool.py`
- Test: `agentarea-platform/tests/unit/tools/test_a2a_agent_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# agentarea-platform/tests/unit/tools/test_a2a_agent_tool.py
"""Tests for A2AAgentTool."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentarea_agents_sdk.tools.a2a_agent_tool import A2AAgentTool


class TestA2AAgentTool:
    def test_tool_properties(self):
        """Tool should expose correct name and description."""
        tool = A2AAgentTool(
            agent_name="research-agent",
            agent_description="Researches topics on the web",
            a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
        )
        assert tool.name == "delegate_to_research_agent"
        assert "research-agent" in tool.description.lower() or "Researches" in tool.description

    def test_get_schema(self):
        """Schema should have message parameter."""
        tool = A2AAgentTool(
            agent_name="research-agent",
            agent_description="Researches topics",
            a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
        )
        schema = tool.get_schema()
        params = schema["parameters"]
        assert "message" in params["properties"]
        assert "message" in params["required"]

    def test_openai_function_definition(self):
        """Should produce valid OpenAI function definition."""
        tool = A2AAgentTool(
            agent_name="research-agent",
            agent_description="Researches topics",
            a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
        )
        defn = tool.get_openai_function_definition()
        assert defn["type"] == "function"
        assert defn["function"]["name"] == "delegate_to_research_agent"

    @pytest.mark.asyncio
    async def test_execute_sends_a2a_message(self):
        """Execute should send JSON-RPC message/send to A2A URL."""
        tool = A2AAgentTool(
            agent_name="research-agent",
            agent_description="Researches topics",
            a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "id": "task-123",
                "status": {"state": "completed"},
                "artifacts": [
                    {"parts": [{"kind": "text", "text": "Research results here"}]}
                ],
            },
        }

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            result = await tool.execute(message="Research quantum computing")

        assert result["success"] is True
        assert "Research results here" in result["result"]

        # Verify the A2A call was made correctly
        call_args = mock_post.call_args
        body = json.loads(call_args.kwargs.get("content", call_args[1].get("content", "")))
        assert body["method"] == "message/send"
        assert body["params"]["message"]["role"] == "user"
        assert body["params"]["message"]["parts"][0]["kind"] == "text"

    @pytest.mark.asyncio
    async def test_execute_handles_error(self):
        """Execute should handle A2A errors gracefully."""
        tool = A2AAgentTool(
            agent_name="research-agent",
            agent_description="Researches topics",
            a2a_url="http://localhost:8000/api/v1/agents/abc/a2a/rpc",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -32603, "message": "Internal error"},
        }

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await tool.execute(message="Research something")

        assert result["success"] is False
        assert "Internal error" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_a2a_agent_tool.py -v`
Expected: FAIL — module `a2a_agent_tool` does not exist

- [ ] **Step 3: Implement A2AAgentTool**

```python
# agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_agent_tool.py
"""A2A Agent Tool — delegates tasks to another agent via A2A protocol."""

import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)

# Timeout for A2A calls (agent execution can be slow)
A2A_CALL_TIMEOUT = 120.0


def _sanitize_tool_name(agent_name: str) -> str:
    """Convert agent name to a valid tool function name."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"
    return f"delegate_to_{sanitized}"


class A2AAgentTool(BaseTool):
    """Tool that delegates a task to another agent via the A2A protocol.

    Sends a `message/send` JSON-RPC request to the target agent's A2A endpoint
    and returns the completed task result.
    """

    def __init__(
        self,
        agent_name: str,
        agent_description: str,
        a2a_url: str,
        auth_token: str | None = None,
    ):
        self._agent_name = agent_name
        self._agent_description = agent_description
        self._a2a_url = a2a_url
        self._auth_token = auth_token

    @property
    def name(self) -> str:
        return _sanitize_tool_name(self._agent_name)

    @property
    def description(self) -> str:
        return (
            f"Delegate a task to the '{self._agent_name}' agent. "
            f"{self._agent_description}"
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            f"The task or question to send to the '{self._agent_name}' agent. "
                            "Be specific and provide all necessary context."
                        ),
                    },
                },
                "required": ["message"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Send message/send to the target agent and return the result."""
        message_text = kwargs.get("message", "")
        if not message_text:
            raise ToolExecutionError(self.name, "message is required")

        # Build A2A JSON-RPC request
        rpc_request = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": message_text}],
                },
            },
        }

        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        try:
            async with httpx.AsyncClient(timeout=A2A_CALL_TIMEOUT) as client:
                response = await client.post(
                    self._a2a_url,
                    content=json.dumps(rpc_request),
                    headers=headers,
                )

            if response.status_code != 200:
                raise ToolExecutionError(
                    self.name,
                    f"A2A request failed with HTTP {response.status_code}",
                )

            rpc_response = response.json()

            # Check for JSON-RPC error
            if "error" in rpc_response and rpc_response["error"]:
                error_msg = rpc_response["error"].get("message", "Unknown A2A error")
                return {
                    "success": False,
                    "result": "",
                    "error": error_msg,
                    "tool_name": self.name,
                }

            # Extract result from task
            task = rpc_response.get("result", {})
            result_text = self._extract_task_result(task)

            return {
                "success": True,
                "result": result_text,
                "error": None,
                "tool_name": self.name,
                "task_id": task.get("id"),
                "task_state": task.get("status", {}).get("state"),
            }

        except httpx.TimeoutException as e:
            raise ToolExecutionError(
                self.name, f"A2A call to '{self._agent_name}' timed out"
            ) from e
        except ToolExecutionError:
            raise
        except Exception as e:
            logger.error(f"A2A agent tool call failed: {e}")
            raise ToolExecutionError(self.name, str(e), e) from e

    def _extract_task_result(self, task: dict[str, Any]) -> str:
        """Extract readable text from a task's artifacts and status message."""
        parts = []

        # Extract from artifacts
        for artifact in task.get("artifacts") or []:
            for part in artifact.get("parts") or []:
                if part.get("kind") == "text":
                    parts.append(part["text"])
                elif part.get("kind") == "data":
                    parts.append(json.dumps(part.get("data", {})))

        # Fallback: extract from status message
        if not parts:
            status_msg = task.get("status", {}).get("message")
            if status_msg:
                for part in status_msg.get("parts") or []:
                    if part.get("kind") == "text":
                        parts.append(part["text"])

        return "\n".join(parts) if parts else "(No output from agent)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_a2a_agent_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_agent_tool.py agentarea-platform/tests/unit/tools/test_a2a_agent_tool.py
git commit -m "feat: add A2AAgentTool for delegating tasks via A2A protocol"
```

---

### Task 3: Create A2AAgentToolFactory — resolves agent names to A2A URLs

**Files:**
- Create: `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_tool_factory.py`
- Test: `agentarea-platform/tests/unit/tools/test_a2a_tool_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# agentarea-platform/tests/unit/tools/test_a2a_tool_factory.py
"""Tests for A2AAgentToolFactory."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_agents_sdk.tools.a2a_tool_factory import A2AAgentToolFactory


@pytest.fixture
def mock_agent_service():
    service = AsyncMock()
    agent = MagicMock()
    agent.id = uuid4()
    agent.name = "research-agent"
    agent.description = "Researches topics on the web"
    service.get_by_name.return_value = agent
    return service


class TestA2AAgentToolFactory:
    @pytest.mark.asyncio
    async def test_create_tool_from_agent_name(self, mock_agent_service):
        """Should resolve agent name and create A2AAgentTool."""
        tool = await A2AAgentToolFactory.create_tool(
            agent_name="research-agent",
            agent_service=mock_agent_service,
            base_url="http://localhost:8000/api/v1",
        )
        assert tool is not None
        assert tool.name == "delegate_to_research_agent"
        assert "research-agent" in tool.description.lower() or "Researches" in tool.description

    @pytest.mark.asyncio
    async def test_create_tool_with_explicit_url(self, mock_agent_service):
        """Should use explicit A2A URL when provided."""
        tool = await A2AAgentToolFactory.create_tool(
            agent_name="research-agent",
            agent_service=mock_agent_service,
            base_url="http://localhost:8000/api/v1",
            a2a_url_override="https://external.example.com/a2a/rpc",
        )
        assert tool is not None
        assert tool._a2a_url == "https://external.example.com/a2a/rpc"

    @pytest.mark.asyncio
    async def test_create_tool_agent_not_found(self, mock_agent_service):
        """Should return None if agent name not found."""
        mock_agent_service.get_by_name.return_value = None
        tool = await A2AAgentToolFactory.create_tool(
            agent_name="nonexistent-agent",
            agent_service=mock_agent_service,
            base_url="http://localhost:8000/api/v1",
        )
        assert tool is None

    @pytest.mark.asyncio
    async def test_create_tools_from_config(self, mock_agent_service):
        """Should create multiple tools from agent tool configs."""
        tools_config = [
            {"type": "agent", "name": "research-agent"},
        ]
        tools = await A2AAgentToolFactory.create_tools_from_config(
            tools_config=tools_config,
            agent_service=mock_agent_service,
            base_url="http://localhost:8000/api/v1",
        )
        assert len(tools) == 1
        assert tools[0].name == "delegate_to_research_agent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_a2a_tool_factory.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement A2AAgentToolFactory**

```python
# agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_tool_factory.py
"""Factory for creating A2A agent tools from configuration."""

import logging
from typing import Any

from .a2a_agent_tool import A2AAgentTool

logger = logging.getLogger(__name__)


class A2AAgentToolFactory:
    """Factory for creating A2AAgentTool instances.

    Resolves agent names to their A2A endpoint URLs using the agent service,
    then creates tool instances that can call those agents.
    """

    @staticmethod
    async def create_tool(
        agent_name: str,
        agent_service,
        base_url: str,
        a2a_url_override: str | None = None,
        auth_token: str | None = None,
        description_override: str | None = None,
    ) -> A2AAgentTool | None:
        """Create an A2AAgentTool for a given agent name.

        Args:
            agent_name: Name of the target agent in the workspace
            agent_service: AgentService to look up agent details
            base_url: Base API URL (e.g., http://localhost:8000/api/v1)
            a2a_url_override: Explicit A2A URL (skips resolution)
            auth_token: Optional Bearer token for A2A auth
            description_override: Override the agent's description in tool schema

        Returns:
            A2AAgentTool instance, or None if agent not found
        """
        try:
            # Look up agent by name
            agent = await agent_service.get_by_name(agent_name)
            if not agent:
                logger.warning(f"Agent '{agent_name}' not found for A2A tool creation")
                return None

            # Determine A2A URL
            if a2a_url_override:
                a2a_url = a2a_url_override
            else:
                a2a_url = f"{base_url}/agents/{agent.id}/a2a/rpc"

            description = description_override or agent.description or f"Agent: {agent_name}"

            return A2AAgentTool(
                agent_name=agent_name,
                agent_description=description,
                a2a_url=a2a_url,
                auth_token=auth_token,
            )

        except Exception as e:
            logger.error(f"Failed to create A2A tool for agent '{agent_name}': {e}")
            return None

    @staticmethod
    async def create_tools_from_config(
        tools_config: list[dict[str, Any]],
        agent_service,
        base_url: str,
        auth_token: str | None = None,
    ) -> list[A2AAgentTool]:
        """Create A2AAgentTool instances from tool config entries with type='agent'.

        Args:
            tools_config: List of tool config dicts (from agent.tools JSON)
            agent_service: AgentService for agent lookups
            base_url: Base API URL
            auth_token: Optional auth token

        Returns:
            List of created A2AAgentTool instances
        """
        tools = []
        for config in tools_config:
            if config.get("type") != "agent":
                continue

            agent_name = config.get("name")
            if not agent_name:
                continue

            settings = config.get("settings") or {}
            tool = await A2AAgentToolFactory.create_tool(
                agent_name=agent_name,
                agent_service=agent_service,
                base_url=base_url,
                a2a_url_override=settings.get("a2a_url"),
                auth_token=auth_token,
                description_override=settings.get("description_override"),
            )
            if tool:
                tools.append(tool)
                logger.info(f"Created A2A agent tool: {tool.name}")

        return tools
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_a2a_tool_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/a2a_tool_factory.py agentarea-platform/tests/unit/tools/test_a2a_tool_factory.py
git commit -m "feat: add A2AAgentToolFactory for resolving agent names to tools"
```

---

### Task 4: Wire agent tools into ToolManager.discover_available_tools

**Files:**
- Modify: `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_manager.py:25-81`
- Modify: `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/__init__.py`
- Test: `agentarea-platform/tests/unit/tools/test_tool_manager_agent.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/tools/test_tool_manager_agent.py`:

```python
class TestToolManagerAgentDiscovery:
    @pytest.mark.asyncio
    async def test_discover_agent_tools(self):
        """ToolManager should discover agent-type tools."""
        from unittest.mock import AsyncMock, MagicMock
        from uuid import uuid4

        from agentarea_agents_sdk import ToolManager

        # Mock agent service
        mock_agent_service = AsyncMock()
        target_agent = MagicMock()
        target_agent.id = uuid4()
        target_agent.name = "research-agent"
        target_agent.description = "Researches topics"
        mock_agent_service.get_by_name.return_value = target_agent

        tools_config = [
            {"type": "agent", "name": "research-agent"},
        ]

        manager = ToolManager()
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
            agent_service=mock_agent_service,
            base_url="http://localhost:8000/api/v1",
        )

        # Should have built-in tools (completion) + the agent tool
        agent_tools = [t for t in tools if "delegate_to_" in t.get("function", {}).get("name", "")]
        assert len(agent_tools) == 1
        assert agent_tools[0]["function"]["name"] == "delegate_to_research_agent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_tool_manager_agent.py::TestToolManagerAgentDiscovery -v`
Expected: FAIL — `discover_available_tools` doesn't accept `agent_service` or `base_url`

- [ ] **Step 3: Implement the wiring**

In `tool_manager.py`, update `discover_available_tools` signature and add the `elif tool_type == "agent"` branch:

```python
# tool_manager.py — updated imports
from .a2a_tool_factory import A2AAgentToolFactory

# Updated method signature
async def discover_available_tools(
    self,
    agent_id: UUID,
    tools_config: list[dict[str, Any]] | None,
    mcp_server_instance_service,
    agent_service=None,
    base_url: str = "",
    auth_token: str | None = None,
) -> list[dict[str, Any]]:
    # ... existing code for "code" and "mcp" ...

    elif tool_type == "agent":
        # A2A agent delegation tool
        if not agent_service or not base_url:
            logger.warning(
                f"Agent tool '{tool_name}' skipped: agent_service or base_url not provided"
            )
            continue

        from .a2a_tool_factory import A2AAgentToolFactory

        a2a_tool = await A2AAgentToolFactory.create_tool(
            agent_name=tool_name,
            agent_service=agent_service,
            base_url=base_url,
            a2a_url_override=settings.get("a2a_url"),
            auth_token=auth_token,
            description_override=settings.get("description_override"),
        )
        if a2a_tool:
            all_tools.append(a2a_tool.get_openai_function_definition())
            logger.info(f"Added agent tool: {tool_name}")
        else:
            logger.warning(f"Agent tool '{tool_name}' could not be created")
```

Update `__init__.py` to export new classes:

```python
from .a2a_agent_tool import A2AAgentTool
from .a2a_tool_factory import A2AAgentToolFactory
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/tools/test_tool_manager_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_manager.py agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/__init__.py agentarea-platform/tests/unit/tools/test_tool_manager_agent.py
git commit -m "feat: wire agent tools into ToolManager discovery pipeline"
```

---

### Task 5: Wire agent_service into discover_available_tools_activity

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py:128-152`

- [ ] **Step 1: Write the failing test (integration-level)**

This is a wiring change. The test from Task 4 validates the ToolManager logic. Here we update the Temporal activity to pass the new parameters.

- [ ] **Step 2: Implement the wiring in activities**

In `agent_execution_activities.py`, update `discover_available_tools_activity`:

```python
@activity.defn
async def discover_available_tools_activity(
    request: ToolDiscoveryRequest,
) -> list[dict[str, Any]]:
    """Discover available tools for an agent."""
    user_context = create_user_context(request.user_context_data)

    async with ActivityContext(container, user_context) as ctx:
        agent_service = await ctx.get_agent_service()
        mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

        # Get agent configuration
        agent = await agent_service.get(request.agent_id)
        if not agent:
            raise ValueError(f"Agent {request.agent_id} not found")

        # Determine base URL for A2A agent tools
        import os
        base_url = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")

        # Use tool manager to discover available tools
        tool_manager = ToolManager()
        all_tools = await tool_manager.discover_available_tools(
            agent_id=request.agent_id,
            tools_config=agent.tools,
            mcp_server_instance_service=mcp_server_instance_service,
            agent_service=agent_service,
            base_url=base_url,
        )

        return all_tools
```

- [ ] **Step 3: Run existing tests to ensure nothing breaks**

Run: `cd agentarea-platform && python -m pytest tests/ -k "tool" -v --timeout=30`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py
git commit -m "feat: pass agent_service to ToolManager for A2A tool discovery"
```

---

### Task 6: Register A2AAgentTool in ToolExecutor for execution

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py:316-386`

The workflow calls `execute_mcp_tool_activity` for ALL tool calls (not just MCP). It routes through `ToolExecutor`. We need to also register agent tools there so they can be executed.

- [ ] **Step 1: Implement agent tool registration in execute_mcp_tool_activity**

In `execute_mcp_tool_activity`, after the code tool registration block, add:

```python
# Register agent tools from configuration
if request.tools_config and isinstance(request.tools_config, list):
    import os
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")

    for tool_config in request.tools_config:
        if not isinstance(tool_config, dict):
            continue
        if tool_config.get("type") != "agent":
            continue

        agent_name = tool_config.get("name")
        if not agent_name:
            continue

        # Create A2A tool for execution
        from agentarea_agents_sdk.tools.a2a_tool_factory import A2AAgentToolFactory

        a2a_tool = await A2AAgentToolFactory.create_tool(
            agent_name=agent_name,
            agent_service=await ctx.get_agent_service(),
            base_url=base_url,
            a2a_url_override=(tool_config.get("settings") or {}).get("a2a_url"),
        )
        if a2a_tool:
            tool_executor.register_tool(a2a_tool)
            logger.info(f"Registered agent tool for execution: {agent_name}")
```

Note: This requires wrapping the existing `execute_mcp_tool_activity` body inside the `ActivityContext` context manager. The current code already uses `ActivityContext` — we just need to also call `ctx.get_agent_service()` when agent tools are present.

- [ ] **Step 2: Run tests**

Run: `cd agentarea-platform && python -m pytest tests/ -k "tool" -v --timeout=30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agentarea-platform/libs/execution/agentarea_execution/activities/agent_execution_activities.py
git commit -m "feat: register A2A agent tools in ToolExecutor for runtime execution"
```

---

## Chunk 2: Remote MCP Exposure

### Task 7: Create Remote MCP endpoint router

**Files:**
- Create: `agentarea-platform/apps/api/agentarea_api/api/v1/mcp_remote.py`
- Test: `agentarea-platform/tests/unit/api/test_mcp_remote.py`

- [ ] **Step 1: Write the failing test**

```python
# agentarea-platform/tests/unit/api/test_mcp_remote.py
"""Tests for remote MCP exposure endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test FastAPI app with the remote MCP router."""
    from agentarea_api.api.v1.mcp_remote import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestRemoteMCPEndpoint:
    def test_tools_list_requires_auth(self, client):
        """Should reject unauthenticated requests."""
        response = client.post(
            "/api/v1/mcp/remote/my-instance/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        # Should return 401 or 403 without auth
        assert response.status_code in (401, 403)

    def test_invalid_method_returns_error(self, client):
        """Should reject unsupported MCP methods."""
        # With mock auth
        response = client.post(
            "/api/v1/mcp/remote/my-instance/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "dangerous/method",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        body = response.json()
        assert body.get("error") is not None
        assert body["error"]["code"] == -32601  # Method not found

    def test_missing_instance_returns_404(self, client):
        """Should return error if MCP instance not found."""
        response = client.post(
            "/api/v1/mcp/remote/nonexistent/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        # Should be a JSON-RPC error or HTTP 404
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            body = response.json()
            assert body.get("error") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/api/test_mcp_remote.py -v`
Expected: FAIL — module `mcp_remote` does not exist

- [ ] **Step 3: Implement Remote MCP router**

```python
# agentarea-platform/apps/api/agentarea_api/api/v1/mcp_remote.py
"""Remote MCP exposure endpoint.

Allows external systems to call MCP tools on workspace MCP server instances
via a JSON-RPC proxy. Supports:
- tools/list: List available tools on the instance
- tools/call: Execute a tool on the instance

Authentication: Reuses the A2A auth flow (Bearer token via Kratos / API key).
"""

import logging
from typing import Any

from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_api.api.v1.a2a_auth import require_a2a_execute_auth, A2AAuthContext
from agentarea_common.auth.context_manager import ContextManager
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/remote", tags=["mcp-remote"])

# Allowed MCP methods (whitelist for safety)
ALLOWED_MCP_METHODS = {"tools/list", "tools/call", "resources/list", "resources/read", "prompts/list", "prompts/get"}


class MCPJSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class MCPJSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class MCPJSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: MCPJSONRPCError | None = None


@router.post("/{instance_name}/rpc")
async def mcp_remote_rpc(
    instance_name: str,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    mcp_service=Depends(get_mcp_server_instance_service),
):
    """JSON-RPC proxy for remote MCP access.

    Routes tools/list and tools/call to the named MCP server instance.
    """
    # Parse JSON-RPC request
    try:
        body = await request.json()
        rpc_request = MCPJSONRPCRequest(**body)
    except Exception:
        return MCPJSONRPCResponse(
            error=MCPJSONRPCError(code=-32700, message="Parse error"),
        ).model_dump(exclude_none=True)

    request_id = rpc_request.id

    # Validate method
    if rpc_request.method not in ALLOWED_MCP_METHODS:
        return MCPJSONRPCResponse(
            id=request_id,
            error=MCPJSONRPCError(code=-32601, message=f"Method not found: {rpc_request.method}"),
        ).model_dump(exclude_none=True)

    # Set workspace context from auth
    workspace_id = auth_context.workspace_id
    if not workspace_id:
        return MCPJSONRPCResponse(
            id=request_id,
            error=MCPJSONRPCError(code=-32603, message="Missing workspace context"),
        ).model_dump(exclude_none=True)

    ContextManager.set_workspace(workspace_id)

    try:
        # Resolve MCP instance by name
        instance = await mcp_service.get_by_name(instance_name)
        if not instance:
            return MCPJSONRPCResponse(
                id=request_id,
                error=MCPJSONRPCError(code=-32001, message=f"MCP instance '{instance_name}' not found"),
            ).model_dump(exclude_none=True)

        # Check instance is running
        if getattr(instance, "status", None) != "running":
            return MCPJSONRPCResponse(
                id=request_id,
                error=MCPJSONRPCError(code=-32002, message=f"MCP instance '{instance_name}' is not running"),
            ).model_dump(exclude_none=True)

        # Route to handler
        if rpc_request.method == "tools/list":
            result = await _handle_tools_list(instance, mcp_service)
        elif rpc_request.method == "tools/call":
            result = await _handle_tools_call(instance, rpc_request.params or {}, mcp_service)
        elif rpc_request.method == "resources/list":
            result = await _handle_resources_list(instance, mcp_service)
        elif rpc_request.method == "resources/read":
            result = await _handle_resources_read(instance, rpc_request.params or {}, mcp_service)
        elif rpc_request.method == "prompts/list":
            result = await _handle_prompts_list(instance, mcp_service)
        elif rpc_request.method == "prompts/get":
            result = await _handle_prompts_get(instance, rpc_request.params or {}, mcp_service)
        else:
            return MCPJSONRPCResponse(
                id=request_id,
                error=MCPJSONRPCError(code=-32601, message="Method not found"),
            ).model_dump(exclude_none=True)

        return MCPJSONRPCResponse(
            id=request_id,
            result=result,
        ).model_dump(exclude_none=True)

    except Exception as e:
        logger.error(f"[mcp/remote] Error processing {rpc_request.method}: {e}")
        return MCPJSONRPCResponse(
            id=request_id,
            error=MCPJSONRPCError(code=-32603, message="Internal error"),
        ).model_dump(exclude_none=True)


async def _handle_tools_list(instance, mcp_service) -> dict[str, Any]:
    """List tools available on the MCP instance."""
    for method_name in ("list_tools", "get_tools", "discover_tools"):
        fn = getattr(mcp_service, method_name, None)
        if callable(fn):
            tools_data = await fn(instance.id)
            if tools_data is not None:
                # Normalize
                if isinstance(tools_data, dict) and "tools" in tools_data:
                    return tools_data
                if isinstance(tools_data, list):
                    return {"tools": tools_data}
                return {"tools": []}

    return {"tools": []}


async def _handle_tools_call(instance, params: dict[str, Any], mcp_service) -> dict[str, Any]:
    """Execute a tool on the MCP instance."""
    tool_name = params.get("name")
    tool_args = params.get("arguments", {})

    if not tool_name:
        raise ValueError("Missing 'name' in tools/call params")

    # Use execute_tool if available
    for method_name in ("execute_tool", "run_tool", "invoke_tool", "call_tool"):
        fn = getattr(mcp_service, method_name, None)
        if callable(fn):
            result = await fn(
                server_instance_id=instance.id,
                tool_name=tool_name,
                tool_args=tool_args,
            )
            if isinstance(result, dict):
                return result
            return {"content": [{"type": "text", "text": str(result)}]}

    raise ValueError("MCP service does not support tool execution")


async def _handle_resources_list(instance, mcp_service) -> dict[str, Any]:
    """List resources on the MCP instance."""
    fn = getattr(mcp_service, "list_resources", None)
    if callable(fn):
        result = await fn(instance.id)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"resources": result}
    return {"resources": []}


async def _handle_resources_read(instance, params: dict[str, Any], mcp_service) -> dict[str, Any]:
    """Read a resource from the MCP instance."""
    uri = params.get("uri")
    if not uri:
        raise ValueError("Missing 'uri' in resources/read params")

    fn = getattr(mcp_service, "read_resource", None)
    if callable(fn):
        result = await fn(instance.id, uri)
        if isinstance(result, dict):
            return result
        return {"contents": [{"uri": uri, "text": str(result)}]}
    raise ValueError("MCP service does not support resource reading")


async def _handle_prompts_list(instance, mcp_service) -> dict[str, Any]:
    """List prompts on the MCP instance."""
    fn = getattr(mcp_service, "list_prompts", None)
    if callable(fn):
        result = await fn(instance.id)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"prompts": result}
    return {"prompts": []}


async def _handle_prompts_get(instance, params: dict[str, Any], mcp_service) -> dict[str, Any]:
    """Get a prompt from the MCP instance."""
    name = params.get("name")
    if not name:
        raise ValueError("Missing 'name' in prompts/get params")

    fn = getattr(mcp_service, "get_prompt", None)
    if callable(fn):
        result = await fn(instance.id, name, params.get("arguments", {}))
        if isinstance(result, dict):
            return result
    raise ValueError("MCP service does not support prompts")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/api/test_mcp_remote.py -v`
Expected: PASS (at least for method validation and structure tests)

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/api/v1/mcp_remote.py agentarea-platform/tests/unit/api/test_mcp_remote.py
git commit -m "feat: add remote MCP JSON-RPC proxy endpoint"
```

---

### Task 8: Register mcp_remote router in the API app

**Files:**
- Modify: Router registration file (where other v1 routers are included)

- [ ] **Step 1: Find and read the router registration file**

Run: `grep -rn "include_router.*agents_a2a\|include_router.*mcp_server" agentarea-platform/apps/api/`

This will show where routers are registered. The `mcp_remote.router` needs to be included the same way.

- [ ] **Step 2: Add the import and include**

```python
from agentarea_api.api.v1 import mcp_remote

# In the router registration section:
app.include_router(mcp_remote.router, prefix="/api/v1", tags=["mcp-remote"])
```

- [ ] **Step 3: Verify the server starts**

Run: `cd agentarea-platform && python -c "from agentarea_api.api.v1.mcp_remote import router; print('Router imported OK')"`
Expected: "Router imported OK"

- [ ] **Step 4: Commit**

```bash
git add <router-registration-file>
git commit -m "feat: register remote MCP router in API app"
```

---

### Task 9: Add remote MCP discovery to Agent Card

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/agents_well_known.py`

The Agent Card should advertise available MCP servers so external consumers know what's available.

- [ ] **Step 1: Add MCP capabilities to the Agent Card extensions**

In the agent card builder, add a section for MCP exposure. This is an extension field:

```python
# In the agent card construction, add to the card's metadata or a custom field:
"extensions": {
    "mcp": {
        "endpoint": f"{base_url}/mcp/remote/{{instance_name}}/rpc",
        "instances": [instance.name for instance in mcp_instances],
    }
}
```

This is optional and depends on product needs — can be deferred.

- [ ] **Step 2: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/api/v1/agents_well_known.py
git commit -m "feat: advertise remote MCP endpoint in Agent Card extensions"
```

---

## Chunk 3: Verification & Cleanup

### Task 10: End-to-end smoke test

- [ ] **Step 1: Write a combined integration test**

```python
# agentarea-platform/tests/integration/test_agent_delegation_e2e.py
"""Integration test for agent-to-agent delegation flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agentarea_agents_sdk import ToolManager


class TestAgentDelegationE2E:
    @pytest.mark.asyncio
    async def test_full_discovery_and_schema(self):
        """ToolManager discovers agent tools and produces valid OpenAI schema."""
        mock_agent_service = AsyncMock()
        target = MagicMock()
        target.id = uuid4()
        target.name = "summarizer"
        target.description = "Summarizes long documents"
        mock_agent_service.get_by_name.return_value = target

        tools_config = [
            {"type": "code", "name": "web_search"},
            {"type": "agent", "name": "summarizer"},
        ]

        manager = ToolManager()
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
            agent_service=mock_agent_service,
            base_url="http://api:8000/api/v1",
        )

        # Verify agent tool is in the list
        names = [t.get("function", {}).get("name", "") for t in tools]
        assert "delegate_to_summarizer" in names

        # Verify schema is valid OpenAI format
        agent_tool = next(t for t in tools if "delegate_to_" in t.get("function", {}).get("name", ""))
        assert agent_tool["type"] == "function"
        assert "parameters" in agent_tool["function"]
        assert "message" in agent_tool["function"]["parameters"]["properties"]
```

- [ ] **Step 2: Run all tests**

Run: `cd agentarea-platform && python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add agentarea-platform/tests/integration/test_agent_delegation_e2e.py
git commit -m "test: add e2e smoke test for agent delegation flow"
```

---

### Task 11: Clean up old AgentHandoffTool (optional)

**Files:**
- Modify: `agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/handoff_tool.py`

The existing `AgentHandoffTool` and `AgentRegistryTool` are now superseded by `A2AAgentTool`. They can be deprecated (add deprecation warning) or removed if nothing imports them.

- [ ] **Step 1: Check for imports**

Run: `grep -rn "AgentHandoffTool\|AgentRegistryTool\|handoff_tool" agentarea-platform/ --include="*.py" | grep -v __pycache__ | grep -v test_`

- [ ] **Step 2: If unused, remove or deprecate**

Add deprecation notice at top of `handoff_tool.py`:

```python
import warnings
warnings.warn(
    "AgentHandoffTool is deprecated. Use A2AAgentTool for A2A-protocol agent delegation.",
    DeprecationWarning,
    stacklevel=2,
)
```

- [ ] **Step 3: Commit**

```bash
git add agentarea-platform/libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/handoff_tool.py
git commit -m "chore: deprecate AgentHandoffTool in favor of A2AAgentTool"
```

---

## Summary of Changes

| Feature | What it enables |
|---------|----------------|
| `type: "agent"` in tool config | Users can add other workspace agents as tools in agent configuration |
| `A2AAgentTool` | Runtime tool that sends `message/send` to target agent's A2A endpoint |
| `A2AAgentToolFactory` | Resolves agent name → A2A URL → tool instance |
| ToolManager wiring | Agent tools discovered alongside code and MCP tools |
| Activity wiring | Temporal workflow can execute agent delegation tools |
| Remote MCP endpoint | External systems can call `tools/list` and `tools/call` on workspace MCP instances |
| Auth reuse | Both features use existing A2A auth (Bearer token / API key) |

## Agent YAML Example

After implementation, users can configure agent-to-agent delegation like this:

```yaml
agents:
  - name: orchestrator
    description: "Coordinates research and summarization"
    tools:
      - type: code
        name: web_search
      - type: agent
        name: research-agent
      - type: agent
        name: summarizer
        settings:
          description_override: "Summarizes documents into bullet points"
      - type: mcp
        name: github-mcp
```

## Remote MCP Usage Example

External systems can call workspace MCP tools:

```bash
curl -X POST https://app.agentarea.ai/api/v1/mcp/remote/github-mcp/rpc \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```
