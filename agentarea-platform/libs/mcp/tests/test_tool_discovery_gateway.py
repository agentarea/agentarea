"""Container-backed tool discovery must go through the manager gateway."""

from contextlib import suppress
from unittest.mock import patch

import pytest
from agentarea_mcp.activities.mcp_instance_activities import discover_mcp_tools


class _Recorder:
    """Captures the URL discovery would dial."""

    def __init__(self):
        self.url = None

    def candidates(self, base_url, transport):
        self.url = base_url
        return [base_url], None


@pytest.fixture
def gateway_credential(monkeypatch):
    """Container-backed access is fail-closed without this, by design."""
    monkeypatch.setenv("MCP_GATEWAY_AUTH_SECRET", "x" * 32)
    from agentarea_common.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_container_backed_discovery_uses_the_gateway_route(gateway_credential):
    """It used to read `direct_http_endpoint` off the manager health payload and
    dial the workload, or fall back to a retired Traefik path keyed by instance
    name. Both skipped the gateway's on-demand start, request lease and idle
    reclamation."""
    recorder = _Recorder()

    with patch(
        "agentarea_mcp.verification.mcp_transport_candidates",
        side_effect=recorder.candidates,
    ):
        with suppress(Exception):
            await discover_mcp_tools(
                instance_id="11111111-1111-1111-1111-111111111111",
                instance_name="legacy-name",
                timeout=0.01,
            )

    assert recorder.url is not None
    assert "11111111-1111-1111-1111-111111111111" in recorder.url
    # Never the instance name — that was the retired Traefik path's key.
    assert "legacy-name" not in recorder.url


@pytest.mark.asyncio
async def test_url_type_discovery_still_dials_the_given_endpoint():
    recorder = _Recorder()

    with patch(
        "agentarea_mcp.verification.mcp_transport_candidates",
        side_effect=recorder.candidates,
    ):
        with suppress(Exception):
            await discover_mcp_tools(endpoint_url="https://remote.example/mcp", timeout=0.01)

    assert recorder.url == "https://remote.example/mcp"


@pytest.mark.asyncio
async def test_discovery_without_any_target_fails_loudly():
    with pytest.raises(ValueError, match=r"endpoint_url|instance_id"):
        await discover_mcp_tools(instance_name="only-a-name")


def test_no_direct_workload_addressing_remains_in_discovery():
    """Tripwire on executable code — comments explaining the removal are fine."""
    from pathlib import Path

    import agentarea_mcp.activities.mcp_instance_activities as activities

    code = "\n".join(
        line
        for line in Path(activities.__file__).read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for removed in ("direct_http_endpoint", "MCP_GATEWAY_URL"):
        assert removed not in code, f"{removed} still addresses a workload directly"
