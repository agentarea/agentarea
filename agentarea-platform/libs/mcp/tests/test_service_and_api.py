"""Tests for MCPServerInstanceService and API endpoints (Task #4)."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_mcp.application.service import (
    MCPServerInstanceService,
    derive_bundle_verification,
)
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION
from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerInstanceCreate

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
    inst.server_spec_id = "test-spec-id"
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
    repo.user_context.user_id = str(uuid.uuid4())
    repo.user_context.workspace_id = str(uuid.uuid4())
    repo.session = MagicMock()
    repo.session.add = MagicMock()
    repo.session.commit = AsyncMock()
    repo.session.refresh = AsyncMock()
    repo.session.rollback = AsyncMock()

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

    server_spec = MagicMock()
    server_spec.id = "test-spec-id"
    # Workspace-owned spec → no copy-on-write on connect.
    server_spec.workspace_id = svc.repository.user_context.workspace_id
    server_spec.remote_url = None
    server_spec.cmd = None
    server_spec.docker_image_url = "test-image:latest"
    server_spec.json_spec = {"type": "docker", "image": "test-image:latest"}
    server_spec.env_schema = []
    svc.mcp_server_repository.get_by_id = AsyncMock(return_value=server_spec)
    # Spec resolution is catalog-aware (ADR-003): code resolves via get_server_by_id.
    svc.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server_spec)

    return svc


# ---------------------------------------------------------------------------
# create_instance_with_spec - slug regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_instance_with_spec_populates_slug():
    """Regression: the with-spec create path must populate the NOT NULL `slug`.

    It previously built ``MCPServer(...)`` without a slug, so the first real
    INSERT raised ``NotNullViolationError`` (500) on the UI "Add Server".
    Mocked-DB tests never caught it because a mock session does not enforce the
    constraint - so assert the *behavior*: the slug is resolved via the single
    repository resolver and set on the persisted server.
    """
    svc = _make_service()
    svc.repository.session.flush = AsyncMock()
    svc.mcp_server_repository.resolve_unique_slug = AsyncMock(return_value="my-server")
    svc.create_instance = AsyncMock(return_value=MagicMock(spec=MCPServerInstance))

    server_payload = MCPServerCreate(
        name="My Server",
        description="created in a regression test",
        docker_image_url="img:latest",
        version="1.0.0",
    )
    instance_payload = MCPServerInstanceCreate.model_construct(
        name="My Server",
        description="created in a regression test",
        server_spec_id="",
        json_spec={},
        auth_config_id=None,
    )

    await svc.create_instance_with_spec(server_payload, instance_payload)

    svc.mcp_server_repository.resolve_unique_slug.assert_awaited_once_with("My Server")
    added_server = svc.repository.session.add.call_args[0][0]
    assert added_server.slug == "my-server"


@pytest.mark.asyncio
async def test_materialize_workspace_spec_copy_populates_slug():
    """Regression: copy-on-write of a catalog spec must populate the NOT NULL `slug`.

    Connecting a built-in catalog MCP (e.g. the Vercel remote-OAuth entry)
    materializes a workspace copy. That path built ``MCPServer(...)`` without a
    slug, so the INSERT raised ``NotNullViolationError``. Assert the slug is
    resolved and set on the copy that gets added to the session.
    """
    svc = _make_service()
    svc.repository.session.flush = AsyncMock()
    svc.mcp_server_repository.resolve_unique_slug = AsyncMock(return_value="vercel")

    source = MagicMock()
    source.name = "Vercel"
    source.description = "Remote MCP server for Vercel."
    source.docker_image_url = None
    source.version = "1.0.0"
    source.tags = ["registry", "url", "streamable-http"]
    source.env_schema = []
    source.cmd = None
    source.remote_url = "https://mcp.vercel.com"
    source.registry_item_id = uuid.uuid4()
    source.json_spec = {"name": "ai.agentarea.catalog/vercel"}
    source.registry_url = "https://example.com/mcp-remote-oauth-registry.json"

    await svc._materialize_workspace_spec_copy(source)

    svc.mcp_server_repository.resolve_unique_slug.assert_awaited_once_with("Vercel")
    added_copy = svc.repository.session.add.call_args[0][0]
    assert added_copy.slug == "vercel"


@pytest.mark.asyncio
async def test_auto_create_spec_for_instance_populates_slug():
    """Regression: auto-created specs (no server_spec_id) must populate `slug`."""
    svc = _make_service()
    svc.repository.session.flush = AsyncMock()
    svc.mcp_server_repository.resolve_unique_slug = AsyncMock(return_value="my-server")

    payload = MCPServerInstanceCreate.model_construct(
        name="My Server",
        description="auto-created in a regression test",
        server_spec_id="",
        json_spec={"type": "docker", "image": "img:latest"},
        auth_config_id=None,
    )

    await svc._auto_create_spec_for_instance(payload)

    svc.mcp_server_repository.resolve_unique_slug.assert_awaited_once_with("My Server")
    added_server = svc.repository.session.add.call_args[0][0]
    assert added_server.slug == "my-server"


# ---------------------------------------------------------------------------
# verify_instance — OAuth reactive re-auth (401/403)
# ---------------------------------------------------------------------------


def _payload(status: str, message: str | None = None):
    from agentarea_mcp.domain.verification_types import (
        VERIFICATION_SCHEMA_VERSION,
        VerificationError,
        VerificationPayload,
    )

    return VerificationPayload(
        schema_version=VERIFICATION_SCHEMA_VERSION,
        status=status,  # type: ignore[arg-type]
        at="2026-07-03T00:00:00Z",
        error=(
            VerificationError(code="mcp_error", message=message, detail=None) if message else None
        ),
    )


@pytest.mark.asyncio
async def test_verify_instance_reactive_refresh_recovers_from_403():
    """A 403 on an OAuth instance triggers one force-refresh + retry that succeeds."""
    inst = _make_instance("url")
    inst.auth_config_id = uuid.uuid4()
    svc = _make_service({str(inst.id): inst})

    async def resolve(instance, *, force_refresh=False):
        return {"Authorization": "Bearer fresh"} if force_refresh else {}

    svc._resolve_auth_headers = resolve
    verify_mock = AsyncMock(
        side_effect=[_payload("failed", "HTTPStatusError: 403 Forbidden"), _payload("succeeded")]
    )
    with patch("agentarea_mcp.application.service.verify", verify_mock):
        result = await svc.verify_instance(inst.id)

    assert verify_mock.await_count == 2  # initial + one retry
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_verify_instance_surfaces_reauth_when_refresh_dead():
    """When the OAuth session can't be renewed, verify surfaces oauth_reauth_required."""
    from agentarea_mcp.application.auth_service import OAuthReauthRequiredError

    inst = _make_instance("url")
    inst.auth_config_id = uuid.uuid4()
    svc = _make_service({str(inst.id): inst})
    svc.repository.update = AsyncMock()

    async def resolve(instance, *, force_refresh=False):
        if force_refresh:
            raise OAuthReauthRequiredError("no refresh_token")
        return {}

    svc._resolve_auth_headers = resolve
    verify_mock = AsyncMock(return_value=_payload("failed", "HTTPStatusError: 403 Forbidden"))
    with patch("agentarea_mcp.application.service.verify", verify_mock):
        result = await svc.verify_instance(inst.id)

    assert result["status"] == "failed"
    assert result["error"]["code"] == "oauth_reauth_required"


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
        url_spec = MagicMock()
        url_spec.id = "test-spec-id"
        url_spec.workspace_id = svc.repository.user_context.workspace_id
        url_spec.remote_url = "http://test.example.com/mcp"
        url_spec.cmd = None
        url_spec.docker_image_url = None
        url_spec.json_spec = {"type": "url", "endpoint_url": "http://test.example.com/mcp"}
        url_spec.env_schema = []
        svc.mcp_server_repository.get_by_id = AsyncMock(return_value=url_spec)
        svc.mcp_server_repository.get_server_by_id = AsyncMock(return_value=url_spec)

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
                    server_spec_id="test-spec-id",
                    json_spec={"type": "url", "endpoint_url": "http://test.example.com/mcp"},
                )
            )

        assert inst is not None
        assert inst.verification == fake_verification
        # type is persisted onto the instance spec so the UI derives status.
        assert inst.json_spec.get("type") == "url"

    @pytest.mark.asyncio
    async def test_catalog_spec_is_copied_into_workspace_on_connect(self):
        """Connecting a spec owned by another workspace (platform catalog mirror)
        materializes a workspace-owned copy and points the instance at it."""
        svc = _make_service()
        catalog_spec = MagicMock()
        catalog_spec.id = "platform-spec-id"
        catalog_spec.workspace_id = "platform"  # NOT the caller's workspace
        catalog_spec.remote_url = "http://test.example.com/mcp"
        catalog_spec.cmd = None
        catalog_spec.docker_image_url = None
        catalog_spec.json_spec = {"type": "url", "endpoint_url": "http://test.example.com/mcp"}
        catalog_spec.env_schema = []
        svc.mcp_server_repository.get_server_by_id = AsyncMock(return_value=catalog_spec)

        owned_copy = MagicMock()
        owned_copy.id = "workspace-copy-id"
        owned_copy.workspace_id = svc.repository.user_context.workspace_id
        owned_copy.remote_url = catalog_spec.remote_url
        owned_copy.cmd = None
        owned_copy.docker_image_url = None
        owned_copy.json_spec = catalog_spec.json_spec
        owned_copy.env_schema = []
        svc._materialize_workspace_spec_copy = AsyncMock(return_value=owned_copy)

        fake_verification = {"schema_version": 1, "status": "succeeded", "at": "x", "error": None}
        with patch("agentarea_mcp.application.service.verify", new=AsyncMock(return_value=fake_verification)), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="asana",
                    server_spec_id="platform-spec-id",
                    json_spec={"type": "url", "endpoint_url": "http://test.example.com/mcp"},
                )
            )

        svc._materialize_workspace_spec_copy.assert_awaited_once()
        assert inst is not None
        assert inst.server_spec_id == "workspace-copy-id"

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
                    server_spec_id="test-spec-id",
                    json_spec={"type": "docker"},
                )
            )

        assert inst is not None
        # Drain event loop to allow background task to run
        await asyncio.sleep(0)
        assert len(verify_called) == 1

    @pytest.mark.asyncio
    async def test_container_instance_is_marked_lazy_when_enabled(self, monkeypatch):
        """Nothing else writes lazy_provisioning, so if creation does not stamp
        it the platform flag is inert: every instance stays eager, is never
        reaped, and runs until someone deletes it."""
        monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "true")
        svc = _make_service()

        with patch("agentarea_mcp.application.service.verify", new=AsyncMock()), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="docker-inst",
                    server_spec_id="test-spec-id",
                    json_spec={"type": "docker"},
                )
            )

        assert inst is not None
        assert inst.json_spec.get("lazy_provisioning") is True

    @pytest.mark.asyncio
    async def test_container_instance_is_eager_when_flag_off(self, monkeypatch):
        """The decision is recorded at creation, so turning the flag on later
        must not retroactively shorten the life of an existing instance."""
        monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "false")
        svc = _make_service()

        with patch("agentarea_mcp.application.service.verify", new=AsyncMock()), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="docker-inst",
                    server_spec_id="test-spec-id",
                    json_spec={"type": "docker"},
                )
            )

        assert inst is not None
        assert inst.json_spec.get("lazy_provisioning") is False

    @pytest.mark.asyncio
    async def test_url_instance_is_never_lazy(self, monkeypatch):
        """A url-type instance has no container to start or stop, so marking it
        lazy would defer a verification that costs nothing to run now."""
        monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "true")
        svc = _make_service()
        url_spec = MagicMock()
        url_spec.id = "test-spec-id"
        url_spec.workspace_id = svc.repository.user_context.workspace_id
        url_spec.remote_url = "http://test.example.com/mcp"
        url_spec.cmd = None
        url_spec.docker_image_url = None
        url_spec.json_spec = {"type": "url", "endpoint_url": "http://test.example.com/mcp"}
        url_spec.env_schema = []
        svc.mcp_server_repository.get_server_by_id = AsyncMock(return_value=url_spec)

        fake_verification = {"schema_version": 1, "status": "succeeded", "at": "x", "error": None}
        with patch("agentarea_mcp.application.service.verify", new=AsyncMock(return_value=fake_verification)), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="url-inst",
                    server_spec_id="test-spec-id",
                    json_spec={"type": "url", "endpoint_url": "http://test.example.com/mcp"},
                )
            )

        assert inst is not None
        assert "lazy_provisioning" not in inst.json_spec

    @pytest.mark.asyncio
    async def test_explicit_lazy_choice_is_not_overridden(self, monkeypatch):
        """An explicit per-instance choice wins over the platform default."""
        monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "false")
        svc = _make_service()

        with patch("agentarea_mcp.application.service.verify", new=AsyncMock()), \
             patch("agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec", return_value=[]):
            inst = await svc.create_instance(
                MCPServerInstanceCreate(
                    name="docker-inst",
                    server_spec_id="test-spec-id",
                    json_spec={"type": "docker", "lazy_provisioning": True},
                )
            )

        assert inst is not None
        assert inst.json_spec.get("lazy_provisioning") is True

    def test_bundle_create_payload_is_rejected(self):
        """Bundle is no longer a valid MCP server instance type."""
        with pytest.raises(ValueError, match="bundle"):
            MCPServerInstanceCreate(
                name="bundle-inst",
                server_spec_id="test-spec-id",
                json_spec={"type": "bundle", "members": [str(uuid.uuid4())]},
            )

    def test_derived_env_schema_defaults_to_secret(self):
        """When an instance has no explicit env_schema, we never guess a
        variable's sensitivity from its name — every derived field is secret."""
        svc = _make_service()
        derived = svc._derive_env_schema_from_instance_spec(
            {
                "headers": {"Authorization": "x", "User-Agent": "y"},
                "environment": {"GITHUB_TOKEN": "x", "LOG_LEVEL": "info"},
            }
        )
        by_name = {e["name"]: e["isSecret"] for e in derived}
        assert by_name == {
            "Authorization": True,
            "User-Agent": True,
            "GITHUB_TOKEN": True,
            "LOG_LEVEL": True,
        }


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

    @pytest.mark.asyncio
    async def test_execute_tool_passes_httpx_client_factory_to_mcp_transport(self):
        inst = _make_instance(
            "url",
            verification={"schema_version": 1, "status": "succeeded", "at": "x", "error": None},
        )
        inst.tools = [{"name": "paid_tool"}]
        svc = _make_service({str(inst.id): inst})
        factory = MagicMock(name="payment_httpx_client_factory")
        captured = {}

        async def fake_call_tool_via_mcp(
            mcp_url,
            headers,
            tool_name,
            tool_args,
            httpx_client_factory=None,
            transport=None,
        ):
            captured["factory"] = httpx_client_factory
            return MagicMock(content=[MagicMock(type="text", text="ok")], isError=False)

        svc._call_tool_via_mcp = fake_call_tool_via_mcp

        import agentarea_execution.activities.agent_execution_activities as mod
        orig = getattr(mod, "_enqueue_last_dispatch", None)
        mod._enqueue_last_dispatch = lambda *a, **k: None
        try:
            result = await svc.execute_tool(
                inst.id,
                "paid_tool",
                {},
                httpx_client_factory=factory,
            )
        finally:
            if orig is not None:
                mod._enqueue_last_dispatch = orig

        assert result["success"] is True
        assert captured["factory"] is factory


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
        import inspect

        from agentarea_api.api.v1.mcp_server_instances import create_mcp_server_instance
        src = inspect.getsource(create_mcp_server_instance)
        assert "202" in src, "create endpoint must set 202 for docker/command"


class TestNormalizeUrlKeys:
    """Canonical key is `endpoint_url`; `url`/`external_url` are accepted aliases."""

    def test_canonical_endpoint_url_passes_through(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "endpoint_url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}

    def test_url_alias_gets_renamed(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}
        assert "url" not in out

    def test_external_url_alias_gets_renamed(self):
        from agentarea_mcp.application.service import _normalize_url_keys

        out = _normalize_url_keys({"type": "url", "external_url": "https://x/mcp"})
        assert out == {"type": "url", "endpoint_url": "https://x/mcp"}
        assert "external_url" not in out

    def test_canonical_wins_over_alias(self):
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
