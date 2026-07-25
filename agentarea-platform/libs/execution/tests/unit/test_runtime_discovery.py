import json

import httpx
import pytest
from agentarea_execution.activities.agent_execution_activities import (
    _effective_runtime_profile,
)
from agentarea_execution.activities.runtime_discovery import (
    fetch_runtime_manifest,
    render_runtime_prompt,
    require_runtime_capability,
    runtime_event_data,
)


def _manifest() -> dict:
    return {
        "schema_version": 1,
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
    }


@pytest.mark.asyncio
async def test_fetch_and_render_runtime_manifest() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/runtime/manifest"
        assert request.url.params["package_install"] == "locked"
        return httpx.Response(200, content=json.dumps(_manifest()).encode())

    result = await fetch_runtime_manifest(
        "http://mcp-manager:8000",
        package_install="locked",
        transport=httpx.MockTransport(handler),
    )

    assert result.error is None
    assert result.manifest is not None
    prompt = render_runtime_prompt(result, package_install="locked")
    assert "Managed environment: immutable" in prompt
    assert "Package installation profile: locked" in prompt
    assert "active runtime satisfies" in prompt
    assert "Browser automation: unavailable" in prompt
    assert "Arbitrary code can still be downloaded and run" in prompt
    assert runtime_event_data(result, package_install="locked") == {
        "runtime_version": "runtime-test",
        "managed_environment": "immutable",
        "package_install": "locked",
        "runtime_profile_compatible": True,
    }

    mismatch = runtime_event_data(result, package_install="allowed")
    assert mismatch["runtime_profile_compatible"] is False


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
    prompt = render_runtime_prompt(result, package_install="locked")

    # tier 1: org context store, read-only via a tool
    assert "Organization context store" in prompt
    assert "context tool" in prompt
    # tier 2/3 unified for the agent: its working directory IS the durable task
    # workspace — files created there (relative paths) are captured, and an
    # absolute path outside it is scratch that is not delivered.
    assert "working directory" in prompt
    assert "captured durably" in prompt
    assert "relative paths" in prompt
    assert "NOT delivered" in prompt
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


def test_effective_runtime_profile_prefers_task_override() -> None:
    tools = [
        {
            "name": "agentarea/shell",
            "settings": {"package_install": "allowed"},
        }
    ]

    assert _effective_runtime_profile(None, tools) == "allowed"
    assert (
        _effective_runtime_profile({"package_install": "locked"}, tools)
        == "locked"
    )


def test_effective_runtime_profile_rejects_invalid_agent_setting() -> None:
    tools = [
        {
            "name": "agentarea/shell",
            "settings": {"package_install": "unexpected"},
        }
    ]

    with pytest.raises(ValueError, match="allowed or locked"):
        _effective_runtime_profile(None, tools)
