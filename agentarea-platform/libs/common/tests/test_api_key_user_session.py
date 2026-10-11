"""A key is told apart from its creator wherever access is handed out (#716).

An API key authenticates as the user who made it, so ``user_id`` alone cannot
say whether a person or a key is acting. The key's id now travels from the
principal into the workspace context, where ``ensure_user_session`` refuses it
on actions that hand out or take away access, and where the audit trail
records which key did what.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.audit.service import AuditService
from agentarea_common.auth.context import UserContext, UserPrincipal, UserSessionRequiredError
from agentarea_common.auth.dependencies import ensure_user_session


def _key_principal() -> UserPrincipal:
    return UserPrincipal(
        user_id="alice",
        bound_workspace_id="ws-acme",
        api_key_id="key-1",
        accessible_workspaces=["ws-acme"],
        admin_workspaces=["ws-acme"],
    )


def test_the_workspace_context_remembers_the_key_that_authenticated():
    context = _key_principal().enter("ws-acme", "acme")

    assert context.api_key_id == "key-1"
    assert context.user_id == "alice"


def test_a_signed_in_users_context_names_no_key():
    principal = UserPrincipal(user_id="alice", accessible_workspaces=["ws-acme"])

    assert principal.enter("ws-acme", "acme").api_key_id is None


@pytest.mark.parametrize(
    "caller",
    [_key_principal(), _key_principal().enter("ws-acme", "acme")],
    ids=["principal", "workspace-context"],
)
def test_a_key_is_refused_even_when_its_creator_administers_the_workspace(caller):
    with pytest.raises(UserSessionRequiredError, match="An API key cannot create API keys"):
        ensure_user_session(caller, "create API keys")


def test_the_refusal_is_a_permission_error_so_it_answers_403():
    assert issubclass(UserSessionRequiredError, PermissionError)


def test_a_signed_in_user_passes():
    ensure_user_session(UserPrincipal(user_id="alice"), "create API keys")
    ensure_user_session(UserContext(user_id="alice", workspace_id="ws-acme"), "invite members")


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
        "api_key.create", "api_key", "new-key", event_metadata={"resource_name": "ci"}
    )

    assert event.actor_id == "alice"
    assert event.event_metadata == {"resource_name": "ci", "api_key_id": "key-1"}


@pytest.mark.asyncio
async def test_a_signed_in_users_audit_event_names_no_key():
    context = UserContext(user_id="alice", workspace_id="ws-acme")

    event = await _audit(context).record("agent.create", "agent", "agent-1")

    assert event.event_metadata == {}
