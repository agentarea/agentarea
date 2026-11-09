"""The reconcile grants the owner of each user secret the graph does not have yet."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_common.rebac.ownership import ResourceOwnershipError, root_project_id
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_secrets import graph_owners
from agentarea_secrets.graph_owners import grant_pending_secret_owners
from agentarea_secrets.models import EncryptedSecret


def _secret(workspace_id: str, created_by: str) -> EncryptedSecret:
    return EncryptedSecret(
        id=uuid4(),
        workspace_id=workspace_id,
        secret_name=f"key-{created_by}",
        encrypted_value="ciphertext",
        created_by=created_by,
    )


def _session(secrets: list[EncryptedSecret], agent_ids: tuple[str, ...] = ()) -> AsyncMock:
    results = [
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(secrets))),
        SimpleNamespace(scalars=lambda: list(agent_ids)),
    ]
    session = AsyncMock()
    session.execute.side_effect = results
    return session


def _owners(graph, secret: EncryptedSecret) -> set[tuple[str, str]]:
    return {(t.relation, t.subject_id) for t in graph.recorded if t.object == str(secret.id)}


async def test_each_pending_secret_gets_its_creator_as_manager_and_is_stamped(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)
    first, second = _secret("ws1", "alice"), _secret("ws2", "bob")
    session = _session([first, second])

    result = await grant_pending_secret_owners(session)

    assert (result.granted, result.skipped, result.failed) == (2, 0, 0)
    assert ("manager", "User:alice") in _owners(graph, first)
    assert ("project", f"project:{root_project_id('ws1')}") in _owners(graph, first)
    assert ("manager", "User:bob") in _owners(graph, second)
    assert first.graph_granted_at is not None and second.graph_granted_at is not None
    assert session.commit.await_count == 2


async def test_a_secret_an_agent_created_is_granted_to_that_agent(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)
    agent_id = str(uuid4())
    secret = _secret("ws1", agent_id)

    await grant_pending_secret_owners(_session([secret], (agent_id,)))

    assert ("manager", f"Agent:{agent_id}") in _owners(graph, secret)
    assert ("manager", f"User:{agent_id}") not in _owners(graph, secret)


async def test_a_secret_the_platform_created_is_skipped_and_left_unstamped(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)
    secret = _secret("ws1", "platform")

    result = await grant_pending_secret_owners(_session([secret]))

    assert (result.granted, result.skipped) == (0, 1)
    assert graph.recorded == []
    assert secret.graph_granted_at is None


async def test_a_row_the_graph_refuses_is_counted_and_the_pass_goes_on(monkeypatch):
    install_graph_ownership_stub(monkeypatch)
    refused, fine = _secret("ws1", "alice"), _secret("ws1", "bob")
    real_grant = graph_owners.grant_resource_owner

    async def grant(*, resource_id, workspace_id, owner):
        if resource_id == refused.id:
            raise ResourceOwnershipError("OpenFGA grant write failed")
        await real_grant(resource_id=resource_id, workspace_id=workspace_id, owner=owner)

    monkeypatch.setattr(graph_owners, "grant_resource_owner", grant)

    result = await grant_pending_secret_owners(_session([refused, fine]))

    assert (result.granted, result.failed) == (1, 1)
    assert refused.graph_granted_at is None
    assert fine.graph_granted_at is not None


async def test_nothing_pending_writes_nothing(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)

    result = await grant_pending_secret_owners(_session([]))

    assert (result.granted, result.skipped, result.failed) == (0, 0, 0)
    assert graph.recorded == []
