"""Unit tests for CompoundMCPService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_mcp.application.compound_service import CompoundMCPService
from agentarea_mcp.domain.auth_models import CompoundMCPMember


# ---------------------------------------------------------------------------
# CompoundMCPService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCompoundMCPService:
    def _make_service(self):
        repo = AsyncMock()
        return CompoundMCPService(repo), repo

    async def test_create_returns_compound(self):
        svc, repo = self._make_service()
        expected = MagicMock(id=uuid4(), name="test", routing_mode="parallel")
        repo.create.return_value = expected

        result = await svc.create(name="test")
        repo.create.assert_called_once_with(
            name="test", routing_mode="parallel", description=None
        )
        assert result is expected

    async def test_create_invalid_routing_mode_raises(self):
        svc, repo = self._make_service()
        with pytest.raises(ValueError):
            from agentarea_mcp.domain.auth_models import CompoundMCP
            CompoundMCP(name="x", routing_mode="invalid")

    async def test_get_tool_namespace_uses_config(self):
        svc, _ = self._make_service()
        member = MagicMock(spec=CompoundMCPMember)
        member.mcp_instance_id = uuid4()
        member.config = {"namespace_prefix": "my_ns"}
        assert svc.get_tool_namespace(member) == "my_ns"

    async def test_get_tool_namespace_falls_back_to_id_prefix(self):
        svc, _ = self._make_service()
        member = MagicMock(spec=CompoundMCPMember)
        member.mcp_instance_id = uuid4()
        member.config = {}
        ns = svc.get_tool_namespace(member)
        assert ns == str(member.mcp_instance_id)[:8]

    async def test_get_status_summary_all_running(self):
        svc, _ = self._make_service()
        assert svc.get_status_summary({"a": "running", "b": "running"}) == "running"

    async def test_get_status_summary_some_running(self):
        svc, _ = self._make_service()
        assert svc.get_status_summary({"a": "running", "b": "stopped"}) == "degraded"

    async def test_get_status_summary_none_running(self):
        svc, _ = self._make_service()
        assert svc.get_status_summary({"a": "stopped", "b": "stopped"}) == "stopped"

    async def test_delete_delegates_to_repo(self):
        svc, repo = self._make_service()
        repo.delete.return_value = True
        result = await svc.delete(uuid4())
        assert result is True


