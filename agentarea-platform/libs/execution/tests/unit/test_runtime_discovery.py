import json

import httpx
import pytest
from agentarea_execution.activities.agent_execution_activities import (
    _as_tool_config_list,
)
from agentarea_execution.activities.runtime_discovery import (
    fetch_runtime_manifest,
    render_runtime_prompt,
    require_runtime_capability,
    runtime_event_data,
)


def _manifest() -> dict:
    return {
        "schema_version": 2,
        "image_version": "runtime-test",
        "managed_environment": "immutable",
        "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
        "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
        "tools": {"git": "git version 2.0"},
        "packages": {"openpyxl": "3.1.5", "pandas": "2.3.1"},
        "features": {
            "browser": "none",
            "managed_environment_mutation": False,
            "arbitrary_workspace_code": True,
        },
        "execution_supervisor": {
            "path": "/usr/local/bin/agentarea-exec-supervisor",
            "sha256": "a" * 64,
            "protocol_version": 1,
            "command_uid": 10001,
            "command_gid": 10001,
        },
    }


@pytest.mark.asyncio
async def test_fetch_and_render_runtime_manifest() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/runtime/manifest"
        assert not request.url.query
        return httpx.Response(200, content=json.dumps(_manifest()).encode())

    result = await fetch_runtime_manifest(
        "http://mcp-manager:8000",
        transport=httpx.MockTransport(handler),
    )

    assert result.error is None
    assert result.manifest is not None
    prompt = render_runtime_prompt(result)
    assert "Managed environment: immutable" in prompt
    assert "Browser automation: unavailable" in prompt
    assert "Arbitrary workspace code is supported" in prompt
    assert runtime_event_data(result) == {
        "runtime_version": "runtime-test",
        "managed_environment": "immutable",
    }


@pytest.mark.asyncio
async def test_invalid_manifest_fails_discovery_closed() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        payload = _manifest()
        payload["features"]["browser"] = "chromium"
        return httpx.Response(200, json=payload)

    result = await fetch_runtime_manifest(
        "http://mcp-manager:8000",
        transport=httpx.MockTransport(handler),
    )

    assert result.manifest is None
    assert "runtime manifest unavailable" in (result.error or "")
    assert "Do not assume a browser" in render_runtime_prompt(result)


def test_render_runtime_prompt_describes_the_three_surfaces() -> None:
    from agentarea_execution.models import RuntimeDiscoveryResult, RuntimeManifest

    result = RuntimeDiscoveryResult(manifest=RuntimeManifest.model_validate(_manifest()))
    prompt = render_runtime_prompt(result)

    # tier 1: org context store, read-only via a tool
    assert "Organization context store" in prompt
    assert "context tool" in prompt
    # tier 2/3 unified for the agent: file and shell share the live task workspace,
    # while selected deliverables are explicitly published.
    assert "working directory" in prompt
    assert "file tool" in prompt
    assert "completion `artifacts`" in prompt
    assert "artifact_id" not in prompt
    assert "Live workspace files are ephemeral" in prompt
    assert "/workspace/inputs" in prompt
    # binary deliverables must be produced via the shell, not the text file tool
    assert "Binary deliverables" in prompt
    assert "corrupts the file" in prompt


def test_browser_requirement_is_structured_blocked_result() -> None:
    from agentarea_execution.models import RuntimeDiscoveryResult, RuntimeManifest

    result = RuntimeDiscoveryResult(manifest=RuntimeManifest.model_validate(_manifest()))
    blocked = require_runtime_capability(result, "browser")

    assert blocked is not None
    assert blocked.model_dump() == {
        "status": "blocked",
        "reason": "capability_unavailable",
        "capability": "browser",
        "runtime_version": "runtime-test",
    }
    assert require_runtime_capability(result, "python") is None
    assert require_runtime_capability(result, "undeclared") is not None


def test_runtime_tools_are_not_mutated_outside_resolved_agent_configuration() -> None:
    tools = [{"name": "agentarea/shell", "type": "code", "settings": {}}]

    resolved = _as_tool_config_list(tools)

    assert resolved == tools
    assert all(tool["name"] != "agentarea/artifacts" for tool in resolved)
