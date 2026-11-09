"""The reconcile grants the owner of each user secret the graph does not have yet."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_common.rebac.ownership import root_project_id
from agentarea_common.testing import install_graph_ownership_stub
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


def _session(*secrets: EncryptedSecret) -> AsyncMock:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: list(secrets))
    )
    return session


async def test_each_pending_secret_gets_its_creator_as_manager_and_is_stamped(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)
    first, second = _secret("ws1", "alice"), _secret("ws2", "bob")
    session = _session(first, second)

    assert await grant_pending_secret_owners(session) == 2

    on_first = {(t.relation, t.subject_id) for t in graph.recorded if t.object == str(first.id)}
    assert ("manager", "User:alice") in on_first
    assert ("project", f"project:{root_project_id('ws1')}") in on_first
    assert ("manager", "User:bob") in {
        (t.relation, t.subject_id) for t in graph.recorded if t.object == str(second.id)
    }
    assert first.graph_granted_at is not None and second.graph_granted_at is not None
    assert session.commit.await_count == 2


async def test_nothing_pending_writes_nothing(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)

    assert await grant_pending_secret_owners(_session()) == 0
    assert graph.recorded == []
