"""Which MCP connections are waiting on a credential only a person can give."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.transport import MCPTransport


def _failed(message: str = "Connection refused", code: str = "connect_failed") -> dict:
    return {"status": "failed", "error": {"code": code, "message": message, "detail": None}}


def _instance(
    *,
    transport: MCPTransport = MCPTransport.URL,
    verification: dict | None = None,
    auth_config_id: uuid.UUID | None = None,
    env_vars: list[str] | None = None,
) -> SimpleNamespace:
    json_spec = {"env_vars": env_vars} if env_vars is not None else {}
    instance = SimpleNamespace(
        id=uuid.uuid4(),
        name="Sentry",
        server_spec_id=uuid.uuid4(),
        transport=transport,
        verification=verification if verification is not None else _failed(),
        auth_config_id=auth_config_id,
        json_spec=json_spec,
    )
    instance.get_configured_env_vars = lambda: list(json_spec.get("env_vars", []))
    return instance


def _service(*, env_schema: list[dict] | None = None, probe: dict | None = None):
    secrets = InMemorySecrets()
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=secrets,
        )
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(
        return_value=SimpleNamespace(env_schema=env_schema or [])
    )
    service.probe_instance_auth = AsyncMock(return_value=probe or {"status": "ok"})
    service.repository = MagicMock()
    service.repository.update = AsyncMock()
    return service, secrets


@pytest.mark.asyncio
async def test_a_working_connection_needs_nothing_and_is_not_probed():
    service, _ = _service(probe={"status": "auth_required"})

    assert not await service.needs_connecting(
        _instance(verification={"status": "succeeded"}), probe=True
    )
    service.probe_instance_auth.assert_not_awaited()
    service.mcp_server_repository.get_server_by_id.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verification",
    [
        _failed("HTTP 401 Unauthorized", code="list_tools_failed"),
        _failed("OAuth session expired", code="oauth_reauth_required"),
        _failed("Sentry rejected the credentials", code="upstream_unauthorized"),
    ],
)
@pytest.mark.parametrize("probe", [True, False])
async def test_a_connection_its_upstream_refused_needs_connecting(verification, probe):
    service, _ = _service()

    instance = _instance(verification=verification, auth_config_id=uuid.uuid4())

    assert await service.needs_connecting(instance, probe=probe)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_declared_secret_without_a_value_needs_connecting():
    service, _ = _service(
        env_schema=[{"name": "TAVILY_API_KEY", "isSecret": True, "isRequired": True}]
    )

    instance = _instance(transport=MCPTransport.DOCKER, env_vars=["TAVILY_API_KEY"])

    assert await service.needs_connecting(instance, probe=False)


@pytest.mark.asyncio
async def test_declared_secrets_that_all_have_values_do_not():
    service, secrets = _service(
        env_schema=[{"name": "TAVILY_API_KEY", "isSecret": True, "isRequired": True}]
    )
    instance = _instance(transport=MCPTransport.DOCKER, env_vars=["TAVILY_API_KEY"])
    await secrets.set_secret(f"mcp_instance_{instance.id}_TAVILY_API_KEY", "tvly-key")

    assert not await service.needs_connecting(instance, probe=True)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_optional_secret_without_a_value_does_not():
    service, _ = _service(
        env_schema=[{"name": "GITHUB_TOKEN", "isSecret": True, "isRequired": False}]
    )
    instance = _instance(transport=MCPTransport.DOCKER, env_vars=["GITHUB_TOKEN"])

    assert not await service.needs_connecting(instance, probe=True)


@pytest.mark.asyncio
async def test_a_secret_is_optional_unless_declared_required():
    service, _ = _service(env_schema=[{"name": "GITHUB_TOKEN", "isSecret": True}])
    instance = _instance(transport=MCPTransport.DOCKER, env_vars=["GITHUB_TOKEN"])

    assert not await service.needs_connecting(instance, probe=True)


@pytest.mark.asyncio
async def test_a_url_connection_without_credentials_that_asks_for_auth_needs_connecting():
    service, _ = _service(probe={"status": "auth_required", "methods": ["oauth", "credentials"]})

    assert await service.needs_connecting(_instance(), probe=True)


@pytest.mark.asyncio
async def test_a_probe_that_finds_auth_required_records_it_on_the_verification():
    service, _ = _service(probe={"status": "auth_required", "methods": ["oauth", "credentials"]})
    instance = _instance(verification=_failed("MCPError: Server returned an error response"))

    assert await service.needs_connecting(instance, probe=True)

    service.repository.update.assert_awaited_once()
    args, kwargs = service.repository.update.await_args
    assert args == (instance.id,)
    stored = kwargs["verification"]
    assert stored["status"] == "failed"
    assert stored["error"]["code"] == "auth_required"
    assert "Sentry" in stored["error"]["message"]
    assert stored["error"]["detail"] == {"methods": ["oauth", "credentials"]}


@pytest.mark.asyncio
async def test_a_stored_auth_required_verdict_needs_connecting_on_a_read():
    service, _ = _service()
    instance = _instance(verification=_failed("Sentry requires sign-in", code="auth_required"))

    assert await service.needs_connecting(instance, probe=False)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stored_auth_required_verdict_yields_to_an_attached_credential():
    service, _ = _service()
    instance = _instance(
        verification=_failed("Sentry requires sign-in", code="auth_required"),
        auth_config_id=uuid.uuid4(),
    )

    assert not await service.needs_connecting(instance, probe=False)


@pytest.mark.asyncio
async def test_a_stored_auth_required_verdict_yields_to_a_secret_header():
    service, secrets = _service()
    instance = _instance(
        verification=_failed("Sentry requires sign-in", code="auth_required"),
        env_vars=["Authorization"],
    )
    await secrets.set_secret(f"mcp_instance_{instance.id}_Authorization", "Bearer sk")

    assert not await service.needs_connecting(instance, probe=False)


@pytest.mark.asyncio
async def test_a_url_connection_failing_for_another_reason_does_not():
    service, _ = _service(probe={"status": "error", "message": "Cannot connect"})

    assert not await service.needs_connecting(_instance(), probe=True)
    service.repository.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verification",
    [
        _failed(),
        _failed("Timed out", code="timeout"),
        _failed("HTTP 503 Service Unavailable", code="list_tools_failed"),
        {"status": "never_attempted"},
        {"status": "in_progress"},
    ],
)
async def test_a_read_decides_from_stored_state_and_never_probes(verification):
    service, _ = _service(probe={"status": "auth_required", "methods": ["oauth"]})

    assert not await service.needs_connecting(_instance(verification=verification), probe=False)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_verification_in_progress_is_never_probed():
    service, _ = _service(probe={"status": "auth_required", "methods": ["oauth"]})

    instance = _instance(verification={"status": "in_progress"})

    assert not await service.needs_connecting(instance, probe=True)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_attached_oauth_credential_is_not_second_guessed_by_a_probe():
    service, _ = _service(probe={"status": "auth_required", "methods": ["oauth", "credentials"]})

    assert not await service.needs_connecting(_instance(auth_config_id=uuid.uuid4()), probe=True)
    service.probe_instance_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_url_connection_holding_a_secret_header_is_not_probed():
    service, secrets = _service(probe={"status": "auth_required", "methods": ["credentials"]})
    instance = _instance(env_vars=["X-Api-Key"])
    await secrets.set_secret(f"mcp_instance_{instance.id}_X-Api-Key", "sk-live")

    assert not await service.needs_connecting(instance, probe=True)
    service.probe_instance_auth.assert_not_awaited()
