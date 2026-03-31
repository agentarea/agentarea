"""Unit tests for audit decorator behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentarea_common.audit.decorator import audited


class _FakeAuditService:
    """Captures audit calls for assertions."""

    calls: list[dict] = []

    def __init__(self, session, user_context):
        self.session = session
        self.user_context = user_context

    async def record(self, **kwargs):
        _FakeAuditService.calls.append(kwargs)


class _Resource:
    def __init__(self, resource_id: str, data: dict):
        self.id = resource_id
        self._data = data

    def to_dict(self):
        return self._data


@pytest.mark.asyncio
async def test_audited_create_extracts_resource_id_from_result(monkeypatch):
    _FakeAuditService.calls = []
    monkeypatch.setattr("agentarea_common.audit.decorator.AuditService", _FakeAuditService)

    class Service:
        def __init__(self):
            self.repository_factory = MagicMock(session=MagicMock(), user_context=MagicMock())

        @audited("agent.create", resource_type="agent")
        async def create_agent(self):
            return {"id": "agent-1", "name": "demo"}

    result = await Service().create_agent()

    assert result["id"] == "agent-1"
    assert len(_FakeAuditService.calls) == 1
    assert _FakeAuditService.calls[0]["resource_id"] == "agent-1"
    assert _FakeAuditService.calls[0]["action"] == "agent.create"
    assert _FakeAuditService.calls[0]["changes"] is None


@pytest.mark.asyncio
async def test_audited_update_computes_changes_and_uses_resource_id_param(monkeypatch):
    _FakeAuditService.calls = []
    monkeypatch.setattr("agentarea_common.audit.decorator.AuditService", _FakeAuditService)

    class Repo:
        async def get(self, resource_id):
            return _Resource(
                resource_id,
                {"id": resource_id, "name": "before", "created_at": "x", "updated_at": "old"},
            )

    class Service:
        def __init__(self):
            self.repository_factory = MagicMock(session=MagicMock(), user_context=MagicMock())
            self.repository = Repo()

        @audited("agent.update", resource_type="agent", resource_id_param="agent_id")
        async def update_agent(self, agent_id: str, name: str):
            return _Resource(
                agent_id, {"id": agent_id, "name": name, "created_at": "x", "updated_at": "new"}
            )

    await Service().update_agent("agent-2", "after")

    assert len(_FakeAuditService.calls) == 1
    call = _FakeAuditService.calls[0]
    assert call["resource_id"] == "agent-2"
    assert call["action"] == "agent.update"
    assert call["changes"] == [{"field": "name", "before": "before", "after": "after"}]


@pytest.mark.asyncio
async def test_audited_skips_when_repository_factory_missing():
    class Service:
        @audited("agent.create", resource_type="agent")
        async def create_agent(self):
            return {"id": "agent-3"}

    assert await Service().create_agent() == {"id": "agent-3"}


@pytest.mark.asyncio
async def test_audited_logs_warning_when_audit_record_fails(monkeypatch):
    class _FailingAuditService:
        def __init__(self, session, user_context):
            self.session = session
            self.user_context = user_context

        async def record(self, **kwargs):
            raise RuntimeError("write failed")

    monkeypatch.setattr("agentarea_common.audit.decorator.AuditService", _FailingAuditService)

    class Service:
        def __init__(self):
            self.repository_factory = MagicMock(session=MagicMock(), user_context=MagicMock())
            self.repository = MagicMock()
            self.repository.get = AsyncMock(return_value=None)

        @audited("agent.update", resource_type="agent", resource_id_param="agent_id")
        async def update_agent(self, agent_id: str):
            return _Resource(agent_id, {"id": agent_id, "name": "ok"})

    with patch("agentarea_common.audit.decorator.logger.warning") as mock_warning:
        result = await Service().update_agent("agent-4")

    assert result.id == "agent-4"
    mock_warning.assert_called_once()
