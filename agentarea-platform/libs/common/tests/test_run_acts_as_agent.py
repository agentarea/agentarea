"""A run acts as its agent: the graph is asked about the agent, not the person.

A request acts as the user who made it. A run executes as its agent, whose
relations were granted to it when it was created, so whoever the run is
attributed to lends it nothing.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.context import Subject, UserContext
from agentarea_common.auth.permission import PermissionService, require_permission
from agentarea_common.di.container import get_container
from agentarea_common.rebac import ownership
from agentarea_common.rebac.models import RelationTuple


@pytest.fixture(autouse=True)
def clean_container():
    container = get_container()
    yield
    container.clear()


def _run_context() -> UserContext:
    return UserContext(
        user_id="alice", workspace_id="ws-1", subject=Subject(kind="agent", id="agent-7")
    )


def test_a_request_asks_the_graph_about_its_user():
    assert UserContext(user_id="alice", workspace_id="ws-1").graph_subject == "User:alice"


def test_a_run_asks_the_graph_about_its_agent():
    assert _run_context().graph_subject == "Agent:agent-7"


def test_a_subject_names_someone():
    with pytest.raises(ValueError):
        Subject(kind="agent", id="")


@pytest.mark.asyncio
async def test_a_permission_check_in_a_run_reaches_the_pdp_as_the_agent():
    pdp = AsyncMock(spec=PermissionService)
    pdp.check.return_value = True
    get_container().register_singleton(PermissionService, pdp)

    await require_permission("edit", "stream", "stream-1", _run_context())

    pdp.check.assert_awaited_once_with("Agent:agent-7", "edit", "stream", "stream-1")


class _Graph:
    def __init__(self) -> None:
        self.written: list[RelationTuple] = []
        self.deleted: list[RelationTuple] = []

    async def write_tuple(self, relationship: RelationTuple) -> None:
        self.written.append(relationship)

    async def delete_tuple(self, relationship: RelationTuple) -> None:
        self.deleted.append(relationship)


ENROLLMENT = [
    RelationTuple(
        namespace="Workspace", object="ws-1", relation="members", subject_id="Agent:agent-7"
    ),
    RelationTuple(
        namespace="project",
        object=ownership.root_project_id("ws-1"),
        relation="writer",
        subject_id="Agent:agent-7",
    ),
]


@pytest.mark.asyncio
async def test_a_new_agent_can_act_in_its_workspace(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(ownership, "resolve_graph_client", lambda: graph)

    await ownership.enroll_agent(agent_id="agent-7", workspace_id="ws-1")

    assert graph.written == ENROLLMENT


@pytest.mark.asyncio
async def test_a_deleted_agent_loses_what_it_acted_with(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(ownership, "resolve_graph_client", lambda: graph)

    await ownership.withdraw_agent(agent_id="agent-7", workspace_id="ws-1")

    assert graph.deleted == ENROLLMENT
