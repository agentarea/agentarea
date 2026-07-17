"""Tests for the egress-enforcer port and its core no-op default."""

import pytest
from agentarea_common.ports.egress_enforcer import EgressEnforcer, NoopEgressEnforcer


def test_noop_satisfies_the_protocol():
    assert isinstance(NoopEgressEnforcer(), EgressEnforcer)


@pytest.mark.asyncio
async def test_noop_apply_is_a_no_op():
    # Enforces nothing, accepts any allowlist (including default-deny []), no raise.
    enforcer = NoopEgressEnforcer()
    assert await enforcer.apply(mcp_instance_id="mcp-1", allowed_hosts=["*.github.com"]) is None
    assert await enforcer.apply(mcp_instance_id="mcp-2", allowed_hosts=[]) is None
