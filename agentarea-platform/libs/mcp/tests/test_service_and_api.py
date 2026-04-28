"""Tests for MCPServerInstanceService and API endpoints (Task #4)."""

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentarea_mcp.application.service import (
    MCPServerInstanceService,
    derive_bundle_verification,
)
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION, VERIFICATION_SCHEMA_VERSION
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_instance(
    instance_type: str = "docker",
    verification: dict | None = None,
    name: str = "test-inst",
    instance_id: uuid.UUID | None = None,
) -> MCPServerInstance:
    inst = MagicMock(spec=MCPServerInstance)
    inst.id = instance_id or uuid.uuid4()
    inst.name = name
    inst.json_spec = {"type": instance_type}
    inst.workspace_id = uuid.uuid4()
    inst.created_by = str(uuid.uuid4())
    inst.verification = verification if verification is not None else dict(DEFAULT_VERIFICATION)
    inst.last_dispatch = None
    inst.tools = None
    inst.server_spec_id = None
    inst.auth_config_id = None
    inst.get_configured_env_vars = MagicMock(return_value=[])

    if instance_type in ("docker", "command"):
        inst.endpoint_url = f"http://mcp-{inst.id}:8080"
    elif instance_type == "url":
        inst.json_spec = {"type": "url", "endpoint_url": "http://test.example.com/mcp"}
        inst.endpoint_url = "http://test.example.com/mcp"

    return inst


def _make_service(instances: dict[str, MCPServerInstance] | None = None) -> MCPServerInstanceService:
    """Build a service with a mocked repository."""
    instances = instances or {}

    repo = MagicMock()
    repo.user_context = MagicMock()
    repo.session = MagicMock()

    async def get_by_id(id_):
        return instances.get(str(id_))

    async def create(**kwargs):
        inst = MagicMock(spec=MCPServerInstance)
        inst.id = uuid.uuid4()
        inst.name = kwargs.get("name", "inst")
        inst.json_spec = kwargs.get("json_spec", {})
        inst.verification = kwargs.get("verification", dict(DEFAULT_VERIFICATION))
        inst.last_dispatch = None
        inst.tools = None
        inst.server_spec_id = kwargs.get("server_spec_id")
        inst.auth_config_id = kwargs.get("auth_config_id")
        inst.get_configured_env_vars = MagicMock(return_value=[])
        instances[str(inst.id)] = inst
        return inst

    async def delete(id_):
        instances.pop(str(id_), None)
        return True

    repo.get_by_id = get_by_id
    repo.create = create
    repo.delete = delete

    repo_factory = MagicMock()
    repo_factory.create_repository = MagicMock(return_value=repo)

    event_broker = MagicMock()
    event_broker.publish = AsyncMock()

    secret_manager = MagicMock()

    svc = MCPServerInstanceService.__new__(MCPServerInstanceService)
    svc.repository = repo
    svc.mcp_server_repository = MagicMock()
    svc.repository_factory = repo_factory
    svc.event_broker = event_broker
    svc.secret_manager = secret_manager
    svc.env_service = MagicMock()
    svc.env_service.set_instance_environment = AsyncMock()
    svc.env_service.get_instance_environment = AsyncMock(return_value={})
    svc.db = MagicMock()

    svc.mcp_server_repository.get_by_id = AsyncMock(return_value=None)

    return svc


# ---------------------------------------------------------------------------
# derive_bundle_verification
# ---------------------------------------------------------------------------

class TestDeriveBundleVerification:
    def _make_bundle(self, member_ids: list[str]) -> MCPServerInstance:
        b = MagicMock(spec=MCPServerInstance)
        b.id = uuid.uuid4()
        b.json_spec = {"type": "bundle", "members": member_ids}
        b.verification = dict(DEFAULT_VERIFICATION)
        return b

    def _make_member(self, status: str, name: str = "m") -> MCPServerInstance:
        m = MagicMock(spec=MCPServerInstance)
        m.id = uuid.uuid4()
        m.name = name
        m.verification = {"schema_version": 1, "status": status, "at": None, "error": None}
        return m

    def test_all_succeeded(self):
        m1 = self._make_member("succeeded", "m1")
        m2 = self._make_member("succeeded", "m2")
        bundle = self._make_bundle([str(m1.id), str(m2.id)])
        result = derive_bundle_verification(bundle, [m1, m2])
        assert result["status"] == "succeeded"
        assert result["error"] is None

    def test_any_failed(self):
        m1 = self._make_member("succeeded", "m1")
        m2 = self._make_member("failed", "m2")
        bundle = self._make_bundle([str(m1.id), str(m2.id)])
        result = derive_bundle_verification(bundle, [m1, m2])
        assert result["status"] == "failed"
        assert "m2" in result["error"]["message"]

    def test_empty_members(self):
        bundle = self._make_bundle([])
        result = derive_bundle_verification(bundle, [])
        assert result["status"] == "failed"
        assert result["error"]["code"] == "bundle_empty"

    def test_missing_member(self):
        missing_id = str(uuid.uuid4())
        bundle = self._make_bundle([missing_id])
        result = derive_bundle_verification(bundle, [])
        assert result["status"] == "failed"
        assert result["error"]["code"] == "bundle_member_missing"

    def test_never_attempted_member_causes_fail(self):
        m = self._make_member("never_attempted", "m")
        bundle = self._make_bundle([str(m.id)])
        result = derive_bundle_verification(bundle, [m])
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# service.create_instance
# ---------------------------------------------------------------------------

class TestServiceCreateInstance:
    @pytest.mark.asyncio
    async def test_url_type_sync_verify(self):
        """URL type runs verify() synchronously and returns 201-like result."""
        svc = _make_service()

        fake_verification = {
            "schema_version": 1,
            "status": "succeeded",
            "at": "2026-04-18T00:00:00+00:00",
            "error": None,
        }

        with patch("agentarea_mcp.application.service.verify", new=AsyncMock(return_value=fake_verification)), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="url-inst",
                    json_spec={"type": "url", "endpoint_url": "http://test.example.com/mcp"},
                )
            )

        assert inst is not None
        assert inst.verification == fake_verification

    @pytest.mark.asyncio
    async def test_docker_type_async_verify(self):
        """docker type fires background verify() and returns immediately."""
        svc = _make_service()

        verify_called = []

        async def fake_verify(instance):
            verify_called.append(str(instance.id))

        with patch("agentarea_mcp.application.service.verify", side_effect=fake_verify), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="docker-inst",
                    json_spec={"type": "docker"},
                )
            )

        assert inst is not None
        # Drain event loop to allow background task to run
        await asyncio.sleep(0)
        assert len(verify_called) == 1

    @pytest.mark.asyncio
    async def test_bundle_validates_members_succeed(self):
        """Bundle creation succeeds when all members have succeeded verification."""
        m_id = uuid.uuid4()
        member = _make_instance(
            "docker",
            verification={"schema_version": 1, "status": "succeeded", "at": "x", "error": None},
            instance_id=m_id,
        )
        svc = _make_service({str(m_id): member})

        with patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="bundle-inst",
                    json_spec={"type": "bundle", "members": [str(m_id)]},
                )
            )

        assert inst is not None

    @pytest.mark.asyncio
    async def test_bundle_rejects_non_ready_member(self):
        """Bundle creation raises ValueError when any member is not succeeded."""
        m_id = uuid.uuid4()
        member = _make_instance(
            "docker",
            verification={"schema_version": 1, "status": "failed", "at": "x", "error": None},
            instance_id=m_id,
            name="failing-member",
        )
        svc = _make_service({str(m_id): member})

        with patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            with pytest.raises(ValueError) as exc_info:
                await svc.create_instance(
                    MCPServerInstanceCreate(
                        name="bad-bundle",
                        json_spec={"type": "bundle", "members": [str(m_id)]},
                    )
                )

        assert "failing-member" in str(exc_info.value)
        assert "not ready" in str(exc_info.value)


# ---------------------------------------------------------------------------
# service.verify_instance
# ---------------------------------------------------------------------------

class TestServiceVerifyInstance:
    @pytest.mark.asyncio
    async def test_verify_instance_returns_payload(self):
        inst = _make_instance("docker")
        svc = _make_service({str(inst.id): inst})

        fake_payload = {
            "schema_version": 1,
            "status": "succeeded",
            "at": "2026-04-18T00:00:00+00:00",
            "error": None,
        }

        with patch("agentarea_mcp.application.service.verify", new=AsyncMock(return_value=fake_payload)):
            result = await svc.verify_instance(inst.id)

        assert result["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_verify_instance_not_found_raises(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="not found"):
            await svc.verify_instance(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_verify_bundle_derives_from_members(self):
        m_id = uuid.uuid4()
        member = _make_instance(
            "docker",
            verification={"schema_version": 1, "status": "succeeded", "at": "x", "error": None},
            instance_id=m_id,
        )
        bundle = MagicMock(spec=MCPServerInstance)
        bundle.id = uuid.uuid4()
        bundle.json_spec = {"type": "bundle", "members": [str(m_id)]}
        bundle.verification = dict(DEFAULT_VERIFICATION)

        svc = _make_service({str(m_id): member, str(bundle.id): bundle})

        result = await svc.verify_instance(bundle.id)
        assert result["status"] == "succeeded"


# ---------------------------------------------------------------------------
# service.execute_tool — all failure paths have populated result
# ---------------------------------------------------------------------------

class TestServiceExecuteTool:
    @pytest.mark.asyncio
    async def test_result_not_empty_when_instance_not_found(self):
        svc = _make_service()

        import agentarea_execution.activities.agent_execution_activities as mod
        orig = getattr(mod, "_enqueue_last_dispatch", None)
        mod._enqueue_last_dispatch = lambda *a, **k: None
        try:
            result = await svc.execute_tool(uuid.uuid4(), "some_tool", {})
        finally:
            if orig is not None:
                mod._enqueue_last_dispatch = orig

        assert result["success"] is False
        assert result["result"]  # must not be empty string
        assert len(result["result"]) > 0

    @pytest.mark.asyncio
    async def test_result_not_empty_when_verification_not_succeeded(self):
        inst = _make_instance(
            "docker",
            verification={"schema_version": 1, "status": "failed", "at": "x",
                          "error": {"code": "list_tools_timeout", "message": "timed out", "detail": None}},
        )
        svc = _make_service({str(inst.id): inst})

        import agentarea_execution.activities.agent_execution_activities as mod
        orig = getattr(mod, "_enqueue_last_dispatch", None)
        mod._enqueue_last_dispatch = lambda *a, **k: None
        try:
            result = await svc.execute_tool(inst.id, "some_tool", {})
        finally:
            if orig is not None:
                mod._enqueue_last_dispatch = orig

        assert result["success"] is False
        assert result["result"]
        assert "timed out" in result["result"] or "not available" in result["result"]

    @pytest.mark.asyncio
    async def test_bundle_member_not_ready_returns_populated_result(self):
        """Bundle dispatch to a non-ready member returns populated error message."""
        m_id = uuid.uuid4()
        member = _make_instance(
            "docker",
            verification={"schema_version": 1, "status": "failed", "at": "x",
                          "error": {"code": "image_not_found", "message": "Image missing", "detail": None}},
            instance_id=m_id,
            name="bad-member",
        )
        bundle = MagicMock(spec=MCPServerInstance)
        bundle.id = uuid.uuid4()
        bundle.json_spec = {"type": "bundle"}
        bundle.verification = {"schema_version": 1, "status": "succeeded", "at": "x", "error": None}
        bundle.tools = [
            {
                "name": "bad_member__some_tool",
                "member_instance_id": str(m_id),
                "original_tool_name": "some_tool",
            }
        ]

        svc = _make_service({str(m_id): member, str(bundle.id): bundle})

        import agentarea_execution.activities.agent_execution_activities as mod
        orig = getattr(mod, "_enqueue_last_dispatch", None)
        mod._enqueue_last_dispatch = lambda *a, **k: None
        try:
            result = await svc.execute_tool(bundle.id, "bad_member__some_tool", {})
        finally:
            if orig is not None:
                mod._enqueue_last_dispatch = orig

        assert result["success"] is False
        assert result["result"]
        assert "Image missing" in result["result"] or "bad-member" in result["result"]


# ---------------------------------------------------------------------------
# API endpoint presence tests (unit — no DB)
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    def _get_router_routes(self):
        from agentarea_api.api.v1.mcp_server_instances import router
        return {route.path: set(route.methods) for route in router.routes}

    def test_start_endpoint_removed(self):
        routes = self._get_router_routes()
        for path in routes:
            assert "start" not in path, f"start endpoint should be removed, found: {path}"

    def test_stop_endpoint_removed(self):
        routes = self._get_router_routes()
        for path in routes:
            assert "stop" not in path, f"stop endpoint should be removed, found: {path}"

    def test_verify_endpoint_present(self):
        routes = self._get_router_routes()
        assert any("verify" in path for path in routes), "POST /{id}/verify must exist"

    def test_validate_endpoint_present(self):
        routes = self._get_router_routes()
        assert any(
            path.endswith("/validate") or "/validate" in path for path in routes
        ), "POST /validate must exist"

    def test_create_returns_different_status_codes(self):
        """Verify the create endpoint sets 202 for docker/command types."""
        from agentarea_api.api.v1.mcp_server_instances import create_mcp_server_instance
        import inspect
        src = inspect.getsource(create_mcp_server_instance)
        assert "202" in src, "create endpoint must set 202 for docker/command"


class TestNormalizeUrlKeys:
    """Canonical key is `endpoint_url`; legacy `url`/`external_url` are aliased."""

    def test_canonical_endpoint_url_passes_through(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "endpoint_url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}

    def test_legacy_url_gets_renamed(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}
        assert "url" not in out

    def test_legacy_external_url_gets_renamed(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "external_url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}
        assert "external_url" not in out

    def test_canonical_wins_over_legacy(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys(
            {"type": "url", "endpoint_url": "https://canonical/mcp", "url": "https://legacy/mcp"}
        )
        assert out["endpoint_url"] == "https://canonical/mcp"
        assert out.get("url") == "https://legacy/mcp"  # left untouched when canonical present

    def test_non_url_type_untouched(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        spec = {"type": "docker", "image": "x:y", "port": 8080}
        assert _normalize_url_keys(spec) is spec
