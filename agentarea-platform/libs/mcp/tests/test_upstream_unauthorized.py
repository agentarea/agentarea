"""An upstream MCP server that refuses the credentials is recorded as such.

The SDK's streamable-HTTP client turns a non-2xx answer whose body is not a
JSON-RPC error into a generic "Server returned an error response" and drops the
HTTP status. Verification then stored a plain ``mcp_error``, so nothing that
keys on a refused credential — the connect page's "replace key", the OAuth
refresh-and-retry — ever saw the 401/403.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import mcp_client
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.verification import verify
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

ENDPOINT = "http://127.0.0.1/"
SPEC_ID = "00000000-0000-4000-8000-0000000000bb"


def _refusing(status: int):
    def factory(headers=None, timeout=None, auth=None, **_kwargs):
        return httpx2.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            transport=httpx2.MockTransport(
                lambda _request: httpx2.Response(status, text='{"error":"invalid API key"}')
            ),
        )

    return factory


def _mcp_app(refuse):
    """A real MCP server behind a gate that answers ``refuse(scope)`` with 401."""
    server = MCPServer(name="upstream")

    def ping() -> str:
        return "pong"

    server.add_tool(ping, name="ping")
    app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1"], allowed_origins=["http://127.0.0.1"]
        ),
    )

    async def gate(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if refuse(headers):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await app(scope, receive, send)

    def factory(headers=None, timeout=None, auth=None, **_kwargs):
        return httpx2.AsyncClient(
            headers=headers, timeout=timeout, auth=auth, transport=httpx2.ASGITransport(app=gate)
        )

    return app, factory


class _Session:
    """Answers verify()'s reads: the locked instance, then its server spec."""

    def __init__(self, rows) -> None:
        self._rows = list(rows)

    @asynccontextmanager
    async def begin(self):
        yield

    async def execute(self, _stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._rows.pop(0) if self._rows else None
        return result

    async def flush(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _server() -> MagicMock:
    server = MagicMock()
    server.id = SPEC_ID
    server.remote_url = ENDPOINT
    server.cmd = None
    server.docker_image_url = None
    server.json_spec = {
        "type": "url",
        "endpoint_url": ENDPOINT,
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}],
    }
    server.env_schema = []
    return server


def _instance(
    *, auth_config_id: uuid.UUID | None = None, env_vars: list[str] | None = None
) -> MCPServerInstance:
    json_spec: dict = {"type": "url"}
    if env_vars:
        json_spec["env_vars"] = env_vars
    instance = MCPServerInstance(
        name="remote", server_spec_id=SPEC_ID, transport="url", json_spec=json_spec
    )
    instance.id = uuid.uuid4()
    instance.auth_config_id = auth_config_id
    return instance


@asynccontextmanager
async def _verifying(instance, server, client_factory):
    db = MagicMock(async_session_factory=lambda: _Session([instance, server]))
    with (
        patch("agentarea_mcp.verification.get_database", return_value=db),
        patch("agentarea_mcp.verification._save_verification", new=AsyncMock()) as saved,
        patch.object(mcp_client, "shared_era_verdict_store", return_value=None),
        patch.object(mcp_client, "pinned_client_factory", return_value=client_factory),
    ):
        yield saved


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_connection_raises_with_the_upstream_status(status):
    with pytest.raises(mcp_client.MCPUpstreamUnauthorizedError) as exc_info:
        async with mcp_client.connected_mcp_client(
            ENDPOINT,
            {"Authorization": "Bearer stale"},
            3.0,
            transport="streamable-http",
            httpx_client_factory=_refusing(status),
        ) as client:
            await client.list_tools()

    assert exc_info.value.status == status


@pytest.mark.asyncio
async def test_a_request_refused_after_connecting_raises_with_the_upstream_status():
    app, factory = _mcp_app(lambda headers: headers.get("mcp-method") == "tools/list")

    async with app.router.lifespan_context(app):
        async with mcp_client.connected_mcp_client(
            ENDPOINT, {}, 5.0, transport="streamable-http", httpx_client_factory=factory
        ) as client:
            with pytest.raises(mcp_client.MCPUpstreamUnauthorizedError) as exc_info:
                await client.list_tools()

    assert exc_info.value.status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize(
    "credential",
    [{"env_vars": ["X-Api-Key"]}, {"auth_config_id": uuid.uuid4()}],
    ids=["stored-secret", "auth-config"],
)
async def test_verify_records_a_refused_credential_with_its_status(status, credential):
    instance, server = _instance(**credential), _server()

    async with _verifying(instance, server, _refusing(status)) as saved:
        payload = await verify(instance, force=True)

    assert payload["status"] == "failed"
    assert payload["error"] == {
        "code": "upstream_unauthorized",
        "message": f"remote rejected the credentials (HTTP {status})",
        "detail": {"status": status},
    }
    assert saved.await_args.args[1] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_verify_records_a_refusal_without_a_credential_as_needing_one(status):
    instance, server = _instance(), _server()

    async with _verifying(instance, server, _refusing(status)) as saved:
        payload = await verify(instance, force=True)

    assert payload["status"] == "failed"
    assert payload["error"] == {
        "code": "upstream_unauthorized",
        "message": f"remote requires sign-in or a key (HTTP {status})",
        "detail": {"status": status},
    }
    assert saved.await_args.args[1] == payload


@pytest.mark.asyncio
async def test_verify_keeps_a_server_error_generic():
    instance, server = _instance(), _server()

    async with _verifying(instance, server, _refusing(500)):
        payload = await verify(instance, force=True)

    assert payload["error"]["code"] == "mcp_error"


def _service(instance: MCPServerInstance) -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=InMemorySecrets(),
        )
    service.repository = MagicMock()
    service.repository.get_by_id = AsyncMock(return_value=instance)
    return service


@pytest.mark.asyncio
async def test_a_refused_oauth_token_is_refreshed_and_verification_retried():
    instance, server = _instance(auth_config_id=uuid.uuid4()), _server()
    service = _service(instance)

    async def _auth_headers(_instance, *, force_refresh=False):
        return {"Authorization": "Bearer fresh" if force_refresh else "Bearer stale"}

    service._resolve_auth_headers = AsyncMock(side_effect=_auth_headers)
    app, factory = _mcp_app(lambda headers: headers.get("authorization") != "Bearer fresh")

    async with app.router.lifespan_context(app):
        async with _verifying(instance, server, factory):
            payload = await service.verify_instance(instance.id)

    assert payload["status"] == "succeeded"
    service._resolve_auth_headers.assert_any_await(instance, force_refresh=True)


@pytest.mark.asyncio
async def test_a_refused_key_without_oauth_is_not_retried():
    instance, server = _instance(), _server()
    service = _service(instance)
    service._resolve_auth_headers = AsyncMock(return_value={})

    async with _verifying(instance, server, _refusing(401)):
        payload = await service.verify_instance(instance.id)

    assert payload["error"]["code"] == "upstream_unauthorized"
    service._resolve_auth_headers.assert_awaited_once_with(instance)


def test_a_refused_credential_is_an_auth_error_whatever_its_message():
    payload = {
        "status": "failed",
        "error": {
            "code": "upstream_unauthorized",
            "message": "remote rejected the credentials",
            "detail": {"status": 401},
        },
    }

    assert MCPServerInstanceService._is_auth_error_payload(payload)
