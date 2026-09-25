"""Trigger credential selections resolve privately before any trigger mutation."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import (
    get_secret_catalog_service,
    get_secret_manager,
    get_trigger_service,
)
from agentarea_api.api.v1 import triggers
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.testing import allow_all_permissions, install_graph_ownership_stub
from agentarea_secrets.catalog_service import SecretCatalogService, SecretNotFoundError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _graph_ownership(monkeypatch):
    """Creating a row records ownership; here the graph is scenery.

    ``libs/common/tests/test_graph_resource_ownership.py`` is where that write
    is the subject.
    """
    allow_all_permissions()
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture
def harness():
    now = datetime.now(UTC)
    trigger = SimpleNamespace(
        id=uuid4(),
        name="Channel trigger",
        description="",
        agent_id=uuid4(),
        trigger_type="webhook",
        is_active=True,
        task_parameters={},
        conditions={},
        created_at=now,
        updated_at=now,
        created_by="user-a",
        failure_threshold=5,
        consecutive_failures=0,
        last_execution_at=None,
        webhook_id="channel-hook",
        webhook_type="telegram",
        allowed_methods=["POST"],
        validation_rules={},
        webhook_config={},
        event_types=[],
    )
    service = AsyncMock()
    service.get_trigger.return_value = trigger
    service.create_trigger.return_value = trigger
    service.update_trigger.return_value = trigger
    manager = AsyncMock(spec=BaseSecretManager)
    manager.get_secret.return_value = "private-channel-token"
    manager.has_secret.return_value = True
    catalog = AsyncMock(spec=SecretCatalogService)
    secret = SimpleNamespace(
        id=uuid4(),
        secret_name=f"telegram-{uuid4()}",
        owner_type=None,
        owner_id=None,
        workspace_id="workspace-a",
        created_by="user-a",
    )
    catalog.get_for_use.return_value = secret
    webhook_service = AsyncMock()
    app = FastAPI()
    app.include_router(triggers.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[get_trigger_service] = lambda: service
    app.dependency_overrides[get_secret_manager] = lambda: manager
    app.dependency_overrides[get_secret_catalog_service] = lambda: catalog
    app.dependency_overrides[triggers.get_channel_webhook_service] = lambda: webhook_service
    return SimpleNamespace(
        app=app,
        trigger=trigger,
        service=service,
        manager=manager,
        catalog=catalog,
        secret=secret,
        webhook_service=webhook_service,
    )


async def request(harness, operation, **body):
    async with AsyncClient(
        transport=ASGITransport(app=harness.app), base_url="http://test"
    ) as client:
        if operation == "create":
            return await client.post(
                "/v1/triggers/",
                json={
                    "name": "Channel trigger",
                    "agent_id": str(harness.trigger.agent_id),
                    "trigger_type": "webhook",
                    "webhook_type": "telegram",
                    **body,
                },
            )
        return await client.put(f"/v1/triggers/{harness.trigger.id}", json=body)


def assert_no_mutation(harness):
    harness.service.create_trigger.assert_not_awaited()
    harness.service.update_trigger.assert_not_awaited()
    harness.manager.set_secret.assert_not_awaited()
    harness.webhook_service.register.assert_not_awaited()


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_selected_secret_is_resolved_before_mutation_and_never_returned(harness, operation):
    async def resolve(name):
        assert_no_mutation(harness)
        if name == f"channel_cred:telegram:{harness.trigger.id}":
            return None
        assert name == harness.secret.secret_name
        return "private-channel-token"

    harness.manager.get_secret.side_effect = resolve
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == (201 if operation == "create" else 200), response.text
    harness.catalog.get_for_use.assert_awaited_once_with(harness.secret.id)
    harness.manager.set_secret.assert_awaited_once_with(
        f"channel_cred:telegram:{harness.trigger.id}",
        json.dumps({"bot_token": "private-channel-token"}),
    )
    harness.webhook_service.register.assert_awaited_once_with(
        channel_type="telegram",
        webhook_id="channel-hook",
        credentials={"bot_token": "private-channel-token"},
    )
    assert response.json()["has_channel_credentials"] is True
    assert "private-channel-token" not in response.text
    assert "channel_credentials" not in response.json()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "reference",
    [
        {},
        {"secret_id": "invalid"},
        {"secret_id": None},
        {"secret_id": 1},
        {"secret_id": str(uuid4()), "value": "must-not-appear"},
    ],
)
async def test_invalid_references_reject_without_mutation(harness, operation, reference):
    response = await request(harness, operation, channel_credentials={"bot_token": reference})

    assert response.status_code == 422, response.text
    assert "must-not-appear" not in response.text
    harness.catalog.get_for_use.assert_not_awaited()
    harness.manager.get_secret.assert_not_awaited()
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_missing_secret_rejects_without_mutation(harness, operation):
    harness.catalog.get_for_use.side_effect = SecretNotFoundError("not in current workspace")
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 422, response.text
    harness.manager.get_secret.assert_not_awaited()
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_cross_workspace_reference_uses_scoped_catalog_and_rejects(harness, operation):
    session = AsyncMock()
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    session.execute.return_value = result
    catalog = SecretCatalogService(
        session, UserContext(user_id="user-a", workspace_id="workspace-a"), harness.manager
    )
    harness.app.dependency_overrides[get_secret_catalog_service] = lambda: catalog
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 422, response.text
    query = session.execute.await_args.args[0]
    assert query.compile().params == {"id_1": harness.secret.id, "workspace_id_1": "workspace-a"}
    harness.manager.get_secret.assert_not_awaited()
    assert_no_mutation(harness)


def use_real_catalog(harness, user_id, admin_workspaces):
    """The catalog's own selection rule, over a session that finds ``harness.secret``."""
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: harness.secret)
    user = UserContext(
        user_id=user_id, workspace_id="workspace-a", admin_workspaces=admin_workspaces
    )
    catalog = SecretCatalogService(session, user, harness.manager)
    harness.app.dependency_overrides[get_secret_catalog_service] = lambda: catalog
    harness.app.dependency_overrides[get_user_context] = lambda: user


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_managed_secret_rejects_without_reading_value(harness, operation):
    harness.secret.owner_type = "mcp_auth_config"
    use_real_catalog(harness, "user-a", ["workspace-a"])
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 422, response.text
    harness.manager.get_secret.assert_not_awaited()
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_another_members_secret_is_refused_without_reading_value(harness, operation):
    # The selected value is sent where the trigger says -- an IMAP LOGIN to a
    # host this member chose -- so selecting it is reading it.
    use_real_catalog(harness, "user-b", [])
    response = await request(
        harness,
        operation,
        channel_credentials={"password": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 403, response.text
    harness.manager.get_secret.assert_not_awaited()
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("user_id", "admin_workspaces"), [("user-a", []), ("workspace-admin", ["workspace-a"])]
)
async def test_the_creator_or_an_admin_may_select_it(harness, operation, user_id, admin_workspaces):
    use_real_catalog(harness, user_id, admin_workspaces)
    harness.manager.get_secret.side_effect = lambda name: (
        "private-channel-token" if name == harness.secret.secret_name else None
    )
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == (201 if operation == "create" else 200), response.text
    assert "private-channel-token" not in response.text


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("unavailable", [None, "", ValueError("private-channel-token")])
async def test_unavailable_value_rejects_without_mutation_or_disclosure(
    harness, operation, unavailable
):
    if isinstance(unavailable, Exception):
        harness.manager.get_secret.side_effect = unavailable
    else:
        harness.manager.get_secret.return_value = unavailable
    response = await request(
        harness,
        operation,
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 422, response.text
    assert "private-channel-token" not in response.text
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_all_credentials_are_resolved_before_any_mutation(harness, operation):
    harness.catalog.get_for_use.side_effect = [harness.secret, SecretNotFoundError("missing")]
    response = await request(
        harness,
        operation,
        channel_credentials={
            "bot_token": {"secret_id": str(harness.secret.id)},
            "secret_token": {"secret_id": str(uuid4())},
        },
    )

    assert response.status_code == 422, response.text
    assert_no_mutation(harness)


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_legacy_raw_credentials_remain_supported(harness, operation):
    credentials = {"bot_token": "legacy-channel-token"}
    response = await request(harness, operation, channel_credentials=credentials)

    assert response.status_code == (201 if operation == "create" else 200), response.text
    harness.catalog.get_for_use.assert_not_awaited()
    harness.manager.get_secret.assert_not_awaited()
    assert json.loads(harness.manager.set_secret.await_args.args[1]) == credentials
    assert harness.webhook_service.register.await_args.kwargs["credentials"] == credentials
    assert "legacy-channel-token" not in response.text


@pytest.mark.parametrize(
    "credentials", [{}, {"channel_credentials": None}, {"channel_credentials": {}}]
)
async def test_update_with_omitted_credentials_preserves_stored_secret(harness, credentials):
    response = await request(harness, "update", name="Renamed trigger", **credentials)

    assert response.status_code == 200, response.text
    assert response.json()["has_channel_credentials"] is True
    harness.catalog.get_for_use.assert_not_awaited()
    harness.manager.get_secret.assert_not_awaited()
    harness.manager.set_secret.assert_not_awaited()
    harness.webhook_service.register.assert_not_awaited()


async def test_replacing_one_secret_selection_preserves_other_stored_credentials(harness):
    harness.manager.get_secret.side_effect = [
        "replacement-channel-token",
        json.dumps({"bot_token": "old-channel-token", "secret_token": "kept-webhook-token"}),
    ]
    response = await request(
        harness,
        "update",
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 200, response.text
    expected = {"bot_token": "replacement-channel-token", "secret_token": "kept-webhook-token"}
    assert json.loads(harness.manager.set_secret.await_args.args[1]) == expected
    assert harness.webhook_service.register.await_args.kwargs["credentials"] == expected
    for value in ["replacement-channel-token", "old-channel-token", "kept-webhook-token"]:
        assert value not in response.text


@pytest.mark.parametrize(
    "stored", [ValueError("private-existing-token"), "private-existing-token", "[]", "null"]
)
async def test_unreadable_existing_credentials_block_partial_edit_before_mutation(harness, stored):
    harness.manager.get_secret.side_effect = ["replacement-channel-token", stored]
    response = await request(
        harness,
        "update",
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 422, response.text
    assert "private-existing-token" not in response.text
    assert "replacement-channel-token" not in response.text
    assert_no_mutation(harness)


async def test_polling_create_uses_resolved_value_in_existing_extractor_path(harness):
    response = await request(
        harness,
        "create",
        trigger_type="polling",
        data_extractor="telegram_polling",
        data_extractor_config={"interval": 60},
        channel_credentials={"bot_token": {"secret_id": str(harness.secret.id)}},
    )

    assert response.status_code == 201, response.text
    domain = harness.service.create_trigger.await_args.args[0]
    assert domain.data_extractor_config == {"interval": 60, "bot_token": "private-channel-token"}
    assert "private-channel-token" not in response.text
