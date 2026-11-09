"""Granting the owners of user secrets made before secrets were graph resources."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_common.rebac.ownership import root_project_id
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_secrets.graph_owners import grant_user_secret_owners


def _session(*rows):
    session = AsyncMock()
    session.execute.return_value = [
        SimpleNamespace(workspace_id=ws, id=secret_id, created_by=user)
        for ws, secret_id, user in rows
    ]
    return session


async def test_each_user_secret_gets_its_creator_as_manager_under_its_root_project(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)
    first, second = uuid4(), uuid4()

    owners = await grant_user_secret_owners(
        _session(("ws1", first, "alice"), ("ws2", second, "bob")), dry_run=False
    )

    assert [o.secret_id for o in owners] == [str(first), str(second)]
    on_first = {(t.relation, t.subject_id) for t in graph.recorded if t.object == str(first)}
    assert ("manager", "User:alice") in on_first
    assert ("project", f"project:{root_project_id('ws1')}") in on_first
    assert ("manager", "User:bob") in {
        (t.relation, t.subject_id) for t in graph.recorded if t.object == str(second)
    }


async def test_a_dry_run_writes_nothing(monkeypatch):
    graph = install_graph_ownership_stub(monkeypatch)

    owners = await grant_user_secret_owners(_session(("ws1", uuid4(), "alice")), dry_run=True)

    assert len(owners) == 1
    assert graph.recorded == []
