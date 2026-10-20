"""A credential grants scopes; the principal's roles decide everything else (#716, #725).

An API key acts as the user who issued it, with that user's roles: it may invite
members or grant access exactly when its creator may. What it may not do is
mint another credential or reach past the workspace it was issued for, so it
cannot outlive its own revocation. That is a scope the key lacks, decided at
authentication; no handler asks whether the caller is a key.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.audit.service import AuditService
from agentarea_common.auth.context import (
    ScopeRequiredError,
    UserContext,
    UserPrincipal,
    ensure_scope,
)
from agentarea_common.auth.credential import SESSION, Credential, Scope

KEY = Credential(kind="api_key", key_id="key-1")


def _key_principal() -> UserPrincipal:
    return UserPrincipal(
        user_id="alice",
        bound_workspace_id="ws-acme",
        credential=KEY,
        accessible_workspaces=["ws-acme"],
        admin_workspaces=["ws-acme"],
    )


def test_the_workspace_context_keeps_the_credential_it_was_entered_with():
    context = _key_principal().enter("ws-acme", "acme")

    assert context.credential == KEY
    assert context.user_id == "alice"


@pytest.mark.parametrize("scope", list(Scope))
@pytest.mark.parametrize(
    "caller",
    [_key_principal(), _key_principal().enter("ws-acme", "acme")],
    ids=["principal", "workspace-context"],
)
def test_a_key_lacks_the_scopes_even_when_its_creator_administers_the_workspace(caller, scope):
    with pytest.raises(ScopeRequiredError, match="This credential cannot mint"):
        ensure_scope(caller, scope, "mint")


@pytest.mark.parametrize("credential", [SESSION, Credential(kind="oauth")])
def test_a_signed_in_user_has_every_scope(credential):
    for scope in Scope:
        ensure_scope(UserPrincipal(user_id="alice", credential=credential), scope, "mint")


def test_a_context_minted_outside_a_request_has_no_scope():
    with pytest.raises(ScopeRequiredError):
        ensure_scope(UserContext(user_id="alice", workspace_id="ws-acme"), Scope.CREDENTIALS, "mint")


def test_the_refusal_is_a_permission_error_so_it_answers_403():
    assert issubclass(ScopeRequiredError, PermissionError)


def _audit(context: UserContext) -> AuditService:
    service = AuditService(AsyncMock(), context)
    repository = AsyncMock()
    repository.insert.side_effect = lambda event: event
    service._repository = repository
    return service


@pytest.mark.asyncio
async def test_the_audit_trail_records_the_key_that_acted():
    context = _key_principal().enter("ws-acme", "acme")

    event = await _audit(context).record(
        "member.invite", "invitation", "inv-1", event_metadata={"resource_name": "ci"}
    )

    assert event.actor_id == "alice"
    assert event.event_metadata == {
        "resource_name": "ci",
        "credential": "api_key",
        "surface": "api",
        "api_key_id": "key-1",
    }


@pytest.mark.asyncio
async def test_the_audit_trail_records_a_call_made_over_mcp():
    context = UserContext(
        user_id="alice",
        workspace_id="ws-acme",
        credential=Credential(kind="oauth", surface="mcp"),
    )

    event = await _audit(context).record("agent.create", "agent", "agent-1")

    assert event.event_metadata == {"credential": "oauth", "surface": "mcp"}


@pytest.mark.asyncio
async def test_a_context_minted_outside_a_request_records_no_credential():
    context = UserContext(user_id="alice", workspace_id="ws-acme")

    event = await _audit(context).record("agent.create", "agent", "agent-1")

    assert event.event_metadata == {}
