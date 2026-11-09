"""An instance env var or header can reference a workspace secret instead of holding a copy.

The reference stays in ``json_spec`` as ``{"secret_name": ...}``; attaching it
requires the caller to be allowed to use that secret, and it is read at use in
the instance's workspace. A literal value is still copied into the instance's
own secret.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.transport import MCPTransport
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate, MCPServerInstanceUpdate
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretNotFoundError,
)

ENDPOINT = "https://mcp.example.com/mcp"
SPEC_ID = "00000000-0000-4000-8000-0000000000aa"
TOKEN_SECRET = "gh-token"
TOKEN_VALUE = "ghp_canary"


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


class _Catalog:
    """The secret catalog as the instance service sees it."""

    def __init__(self, refusal: Exception | None = None) -> None:
        self.refusal = refusal
        self.asked: list[str] = []
        self.ids: dict[str, uuid.UUID] = {}
        self.references: list[tuple[uuid.UUID, str, str, str]] = []
        self.cleared: list[tuple[str, str]] = []

    async def get_named_for_use(self, name: str):
        self.asked.append(name)
        if self.refusal is not None:
            raise self.refusal
        return SimpleNamespace(id=self.ids.setdefault(name, uuid.uuid4()), secret_name=name)

    async def add_reference(self, secret_id, consumer_type, consumer_id, field) -> None:
        self.references.append((secret_id, consumer_type, consumer_id, field))

    async def clear_references(self, consumer_type, consumer_id) -> None:
        self.cleared.append((consumer_type, consumer_id))
        self.references = [
            ref for ref in self.references if (ref[1], ref[2]) != (consumer_type, consumer_id)
        ]


def _server(transport: str = "url") -> MagicMock:
    server = MagicMock()
    server.id = SPEC_ID
    server.workspace_id = "ws"
    server.cmd = None
    if transport == "url":
        server.remote_url = ENDPOINT
        server.docker_image_url = None
        server.json_spec = {"type": "url", "endpoint_url": ENDPOINT}
    else:
        server.remote_url = None
        server.docker_image_url = "ghcr.io/example/mcp:1"
        server.json_spec = {"type": "docker", "image": "ghcr.io/example/mcp:1", "port": 8000}
    server.env_schema = []
    return server


def _service(
    server: MagicMock, catalog: _Catalog
) -> tuple[MCPServerInstanceService, InMemorySecrets]:
    secrets = InMemorySecrets()
    secrets._secrets[TOKEN_SECRET] = TOKEN_VALUE
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=secrets,
        )
    service.era_verdict_store = None
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server)
    repository = MagicMock()
    repository.user_context = UserContext(user_id="user", workspace_id="ws")
    repository.session = MagicMock(
        commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock()
    )
    service.repository = repository
    service._secret_catalog = lambda: catalog  # type: ignore[method-assign]
    return service, secrets


async def _create(service: MCPServerInstanceService, json_spec: dict) -> MCPServerInstance:
    created: list[MCPServerInstance] = []
    service.repository.session.add = lambda instance: (
        setattr(instance, "id", uuid.uuid4()),
        created.append(instance),
    )
    with (
        patch(
            "agentarea_mcp.application.service.verify",
            new=AsyncMock(return_value={"status": "succeeded"}),
        ),
        patch(
            "agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec",
            return_value=[],
        ),
    ):
        instance = await service.create_instance(
            MCPServerInstanceCreate(
                name="conn", server_spec_id=uuid.UUID(SPEC_ID), json_spec=json_spec
            )
        )
    assert instance is not None
    service.repository.get_by_id = AsyncMock(return_value=instance)
    return instance


def _instance_copies(secrets: InMemorySecrets) -> dict[str, str]:
    return {k: v for k, v in secrets.get_all_secrets().items() if k.startswith("mcp_instance_")}


@pytest.mark.asyncio
async def test_a_header_reference_is_stored_as_the_reference_and_nothing_is_copied():
    catalog = _Catalog()
    service, secrets = _service(_server(), catalog)

    instance = await _create(
        service,
        {"type": "url", "headers": {"Authorization": {"secret_name": TOKEN_SECRET}}},
    )

    assert instance.json_spec["headers"] == {"Authorization": {"secret_name": TOKEN_SECRET}}
    assert "Authorization" not in instance.json_spec.get("env_vars", [])
    assert _instance_copies(secrets) == {}
    assert catalog.asked == [TOKEN_SECRET]
    assert catalog.references == [
        (catalog.ids[TOKEN_SECRET], "mcp_instance", str(instance.id), "Authorization")
    ]


@pytest.mark.asyncio
async def test_an_env_reference_beside_a_literal_keeps_copying_the_literal():
    catalog = _Catalog()
    service, secrets = _service(_server("docker"), catalog)

    instance = await _create(
        service,
        {
            "environment": {
                "GITHUB_TOKEN": {"secret_name": TOKEN_SECRET},
                "OTHER_KEY": "literal-value",
            }
        },
    )

    assert instance.json_spec["environment"] == {"GITHUB_TOKEN": {"secret_name": TOKEN_SECRET}}
    assert instance.json_spec["env_vars"] == ["OTHER_KEY"]
    assert _instance_copies(secrets) == {f"mcp_instance_{instance.id}_OTHER_KEY": "literal-value"}


@pytest.mark.asyncio
async def test_a_reference_the_caller_may_not_use_is_refused_before_anything_is_written():
    catalog = _Catalog(SecretAccessDeniedError(f"Secret '{TOKEN_SECRET}' can only be used ..."))
    service, secrets = _service(_server(), catalog)
    service.repository.session.add = MagicMock()

    with pytest.raises(PermissionError, match=TOKEN_SECRET):
        await service.create_instance(
            MCPServerInstanceCreate(
                name="conn",
                server_spec_id=uuid.UUID(SPEC_ID),
                json_spec={"headers": {"Authorization": {"secret_name": TOKEN_SECRET}}},
            )
        )

    service.repository.session.add.assert_not_called()
    service.repository.session.commit.assert_not_called()
    assert _instance_copies(secrets) == {}


@pytest.mark.parametrize(
    "refusal",
    [SecretNotFoundError("No secret named 'gh-token'"), ManagedSecretError("managed")],
)
@pytest.mark.asyncio
async def test_a_reference_to_no_usable_workspace_secret_is_a_validation_error(refusal):
    service, _ = _service(_server(), _Catalog(refusal))
    service.repository.session.add = MagicMock()

    with pytest.raises(MCPValidationError) as raised:
        await service.create_instance(
            MCPServerInstanceCreate(
                name="conn",
                server_spec_id=uuid.UUID(SPEC_ID),
                json_spec={"headers": {"Authorization": {"secret_name": TOKEN_SECRET}}},
            )
        )

    assert any(TOKEN_SECRET in error for error in raised.value.errors)
    service.repository.session.add.assert_not_called()


@pytest.mark.parametrize(
    "value", [{"secret_name": ""}, {"name": TOKEN_SECRET}, {"secret_name": TOKEN_SECRET, "x": 1}]
)
@pytest.mark.asyncio
async def test_a_malformed_reference_is_a_validation_error(value):
    service, _ = _service(_server(), _Catalog())

    with pytest.raises(MCPValidationError):
        await service.create_instance(
            MCPServerInstanceCreate(
                name="conn",
                server_spec_id=uuid.UUID(SPEC_ID),
                json_spec={"headers": {"Authorization": value}},
            )
        )


@pytest.mark.asyncio
async def test_outbound_headers_read_the_referenced_secret_at_use():
    service, secrets = _service(_server(), _Catalog())
    instance = await _create(
        service, {"type": "url", "headers": {"Authorization": {"secret_name": TOKEN_SECRET}}}
    )

    assert await service.outbound_headers(instance) == {"Authorization": TOKEN_VALUE}

    await secrets.set_secret(TOKEN_SECRET, "rotated")
    assert await service.outbound_headers(instance) == {"Authorization": "rotated"}


@pytest.mark.asyncio
async def test_a_referenced_secret_that_is_gone_fails_loudly():
    service, secrets = _service(_server(), _Catalog())
    instance = await _create(
        service, {"type": "url", "headers": {"Authorization": {"secret_name": TOKEN_SECRET}}}
    )
    await secrets.delete_secret(TOKEN_SECRET)

    with pytest.raises(LookupError, match=TOKEN_SECRET):
        await service.outbound_headers(instance)


@pytest.mark.asyncio
async def test_switching_a_literal_to_a_reference_drops_the_copy():
    catalog = _Catalog()
    service, secrets = _service(_server("docker"), catalog)
    instance = await _create(service, {"environment": {"GITHUB_TOKEN": "old-literal"}})
    assert _instance_copies(secrets) == {f"mcp_instance_{instance.id}_GITHUB_TOKEN": "old-literal"}

    updated: dict = {}

    async def update(_id, **kwargs):
        updated.update(kwargs)
        instance.json_spec = kwargs.get("json_spec", instance.json_spec)
        return instance

    service.repository.update = update
    with patch.object(service, "_retire_runtime_before_mutation", new=AsyncMock()):
        await service.update_instance(
            instance.id,
            MCPServerInstanceUpdate(
                json_spec={
                    "environment": {"GITHUB_TOKEN": {"secret_name": TOKEN_SECRET}},
                    "env_vars": ["GITHUB_TOKEN"],
                }
            ),
        )

    assert updated["json_spec"]["environment"] == {"GITHUB_TOKEN": {"secret_name": TOKEN_SECRET}}
    assert "GITHUB_TOKEN" not in updated["json_spec"].get("env_vars", [])
    assert _instance_copies(secrets) == {}
    assert catalog.references == [
        (catalog.ids[TOKEN_SECRET], "mcp_instance", str(instance.id), "GITHUB_TOKEN")
    ]


@pytest.mark.asyncio
async def test_an_update_referencing_a_secret_the_caller_may_not_use_is_refused():
    catalog = _Catalog()
    service, _ = _service(_server("docker"), catalog)
    instance = await _create(service, {"environment": {"GITHUB_TOKEN": "old-literal"}})
    catalog.refusal = SecretAccessDeniedError(f"Secret '{TOKEN_SECRET}' ...")
    service.repository.update = AsyncMock()

    with pytest.raises(PermissionError):
        await service.update_instance(
            instance.id,
            MCPServerInstanceUpdate(
                json_spec={"environment": {"GITHUB_TOKEN": {"secret_name": TOKEN_SECRET}}}
            ),
        )

    service.repository.update.assert_not_called()


@pytest.mark.asyncio
async def test_deleting_the_instance_releases_its_references():
    catalog = _Catalog()
    service, _ = _service(_server(), catalog)
    instance = await _create(
        service, {"type": "url", "headers": {"Authorization": {"secret_name": TOKEN_SECRET}}}
    )
    service.repository.delete = AsyncMock(return_value=True)

    with patch.object(service, "_release_owned_auth", new=AsyncMock()):
        assert await service.delete_instance(instance.id)

    assert catalog.references == []
    assert ("mcp_instance", str(instance.id)) in catalog.cleared

