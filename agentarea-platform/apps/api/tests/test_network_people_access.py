"""Current-workspace roster and invocation-admission inspection boundaries."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1 import network, network_people
from agentarea_common.auth.access import AGENT_EXECUTE, EdgeDecision
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_common.rebac import OpenFGAUnavailableError, RelationTuple
from agentarea_common.workspaces.models import Workspace
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: BaseModel.metadata.create_all(
                sync, tables=[Agent.__table__, Workspace.__table__]
            )
        )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as db_session:
            yield db_session
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def authorization():
    service = WorkspaceScopedAuthorizationService()
    register_singleton(AuthorizationService, service)
    return service


@pytest.fixture
def actor():
    return UserContext(
        user_id="actor",
        workspace_id="current",
        accessible_workspaces=["current", "other"],
        email="actor@example.test",
    )


def graph_with_members(monkeypatch, ids):
    graph = SimpleNamespace(
        query_all_tuples=AsyncMock(
            return_value=[
                RelationTuple(
                    namespace="Workspace",
                    object="current",
                    relation="members",
                    subject_id=f"User:{user_id}",
                )
                for user_id in ids
            ]
        ),
        write_tuple=AsyncMock(),
        delete_tuple=AsyncMock(),
    )
    monkeypatch.setattr(network_people, "get_workspace_membership_graph", lambda: graph)
    return graph


async def seed(session, *, owner="owner", count=1, other=True):
    session.add(Workspace(id="current", slug="current", name="Current", owner_user_id=owner))
    agents = [
        Agent(
            id=UUID(int=(0xA << 124) + index + 1),
            name=f"Agent {index}",
            slug=f"agent-{index}",
            workspace_id="current",
            created_by="actor",
        )
        for index in range(count)
    ]
    session.add_all(agents)
    if other:
        session.add(Workspace(id="other", slug="other", name="Other", owner_user_id="other-owner"))
        session.add(
            Agent(
                id=uuid4(),
                name="Other agent",
                slug="other-agent",
                workspace_id="other",
                created_by="other-owner",
            )
        )
    await session.commit()
    return agents


async def test_actual_edge_authorizer_allows_verified_members_and_owner_without_writes(
    session, actor, monkeypatch
):
    agents = await seed(session)
    graph = graph_with_members(monkeypatch, ["member", "actor", "member", "owner"])
    graph.query_all_tuples.return_value.append(
        RelationTuple(
            namespace="Workspace",
            object="current",
            relation="members",
            subject_id="Agent:not-a-human",
        )
    )
    commit = AsyncMock()
    monkeypatch.setattr(session, "commit", commit)

    result = await network_people.get_network_people_access(actor, session)

    assert result.workspace_id == "current"
    assert result.decision_source == "agent_edge_admission"
    assert result.directory_status == "available"
    assert result.complete is True
    assert result.total_people == 3
    assert result.total_agents == 1
    assert [person.user_id for person in result.people] == ["actor", "member", "owner"]
    assert {(item.user_id, item.agent_id, item.allowed, item.reason) for item in result.access} == {
        (user_id, str(agents[0].id), True, "workspace scope")
        for user_id in ["actor", "member", "owner"]
    }
    assert result.people[0].email == actor.email
    assert all(person.display_name is None for person in result.people)
    assert all(person.email is None for person in result.people[1:])
    query = graph.query_all_tuples.await_args.args[0]
    assert (query.namespace, query.object, query.relation) == ("Workspace", "current", "members")
    graph.write_tuple.assert_not_awaited()
    graph.delete_tuple.assert_not_awaited()
    commit.assert_not_awaited()


async def test_admin_denial_precedes_graph_and_database_reads(actor, monkeypatch, authorization):
    gate = AsyncMock(return_value=False)
    monkeypatch.setattr(authorization, "can_write_workspace", gate)
    graph_loader = MagicMock()
    monkeypatch.setattr(network_people, "get_workspace_membership_graph", graph_loader)
    db_session = SimpleNamespace(execute=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await network_people.get_network_people_access(actor, db_session)

    assert error.value.status_code == 403
    gate.assert_awaited_once_with(actor, "current")
    graph_loader.assert_not_called()
    db_session.execute.assert_not_awaited()


async def test_membership_unavailability_is_503_not_an_empty_or_denied_roster(
    actor, monkeypatch, caplog
):
    graph = graph_with_members(monkeypatch, [])
    graph.query_all_tuples.side_effect = OpenFGAUnavailableError("offline")
    db_session = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await network_people.get_network_people_access(actor, db_session)
    assert error.value.status_code == 503
    db_session.execute.assert_not_awaited()
    assert any(record.exc_info for record in caplog.records)


async def test_disabled_directory_evaluates_only_persisted_owner_and_marks_roster_unknown(
    session, actor, monkeypatch
):
    agents = await seed(session)
    monkeypatch.setattr(network_people, "get_workspace_membership_graph", lambda: None)
    enumeration = AsyncMock()
    monkeypatch.setattr(network_people, "list_workspace_member_ids", enumeration)
    result = await network_people.get_network_people_access(actor, session)
    enumeration.assert_not_awaited()
    assert result.directory_status == "disabled"
    assert result.complete is False
    assert result.total_people is None
    assert result.total_agents == 1
    assert [person.user_id for person in result.people] == ["owner"]
    assert result.people[0].display_name is None
    assert result.people[0].email is None
    assert [(item.user_id, item.agent_id, item.allowed, item.reason) for item in result.access] == [
        ("owner", str(agents[0].id), True, "workspace scope")
    ]


async def test_disabled_directory_without_owner_does_not_infer_caller_membership(
    session, actor, monkeypatch
):
    monkeypatch.setattr(network_people, "get_workspace_membership_graph", lambda: None)
    result = await network_people.get_network_people_access(actor, session)
    assert result.directory_status == "disabled"
    assert result.complete is False
    assert result.total_people is None
    assert result.people == []
    assert result.access == []


async def test_verified_evaluation_subjects_never_replace_actor_repository_context(
    session, actor, monkeypatch
):
    await seed(session)
    graph_with_members(monkeypatch, ["member"])
    original_factory = network_people.RepositoryFactory
    factory = MagicMock(wraps=original_factory)
    monkeypatch.setattr(network_people, "RepositoryFactory", factory)
    before = deepcopy(actor)
    evaluate = AsyncMock(return_value=EdgeDecision(False, "explicit evaluation result"))
    monkeypatch.setattr(network_people, "authorize_agent_action", evaluate)

    result = await network_people.get_network_people_access(actor, session)

    factory.assert_called_once_with(session, actor)
    assert actor == before
    assert [item.user_id for item in result.access] == ["member", "owner"]
    for call in evaluate.await_args_list:
        subject, action = call.args
        assert subject is not actor
        assert subject.user_id in {"member", "owner"}
        assert subject.workspace_id == "current"
        assert subject.accessible_workspaces == ["current"]
        assert action == AGENT_EXECUTE
        assert call.kwargs["agent_workspace_id"] == "current"
    assert all(
        not item.allowed and item.reason == "explicit evaluation result" for item in result.access
    )


async def test_mixed_admission_decisions_are_propagated_without_deriving_allow_from_membership(
    session, actor, monkeypatch
):
    await seed(session)
    graph_with_members(monkeypatch, ["member"])
    evaluate = AsyncMock(
        side_effect=[
            EdgeDecision(False, "denied by shared authorizer"),
            EdgeDecision(True, "public grant"),
        ]
    )
    monkeypatch.setattr(network_people, "authorize_agent_action", evaluate)
    result = await network_people.get_network_people_access(actor, session)
    assert [(item.allowed, item.reason) for item in result.access] == [
        (False, "denied by shared authorizer"),
        (True, "public grant"),
    ]


async def test_truncation_is_deterministic_bounded_and_retains_verified_owner(
    session, actor, monkeypatch
):
    await seed(session, owner="zz-owner", count=105)
    members = [f"user-{index:03}" for index in range(103)]
    graph = graph_with_members(monkeypatch, list(reversed(members)))
    result = await network_people.get_network_people_access(actor, session)
    graph.query_all_tuples.return_value.reverse()
    repeated = await network_people.get_network_people_access(actor, session)
    assert repeated == result
    assert result.complete is False
    assert result.total_people == 104
    assert result.total_agents == 105
    assert len(result.people) == 100
    assert len(result.access) == 10000
    assert [person.user_id for person in result.people] == [*members[:99], "zz-owner"]
    assert {item.agent_id for item in result.access} == {
        str(UUID(int=(0xA << 124) + index)) for index in range(1, 101)
    }


async def test_empty_graph_roster_uses_persisted_owner_but_not_unverified_actor(
    session, actor, monkeypatch
):
    await seed(session, count=0)
    graph_with_members(monkeypatch, [])
    result = await network_people.get_network_people_access(actor, session)
    assert [person.user_id for person in result.people] == ["owner"]
    assert result.access == []
    assert result.total_agents == 0
    assert result.complete is True


async def test_personal_workspace_owner_is_inspected_without_bootstrap_grants(session, monkeypatch):
    await seed(session, owner="current")
    graph = graph_with_members(monkeypatch, [])
    actor = UserContext(user_id="current", workspace_id="current")
    result = await network_people.get_network_people_access(actor, session)
    assert [person.user_id for person in result.people] == ["current"]
    assert result.access[0].allowed is True
    graph.write_tuple.assert_not_awaited()
    graph.delete_tuple.assert_not_awaited()


async def test_registered_http_route_ignores_other_workspace_query_and_uses_actor_scope(
    session, actor, monkeypatch
):
    agents = await seed(session)
    graph_with_members(monkeypatch, ["actor"])
    app = FastAPI()
    app.include_router(network.router, prefix="/v1")

    async def current_user():
        return actor

    async def current_session():
        yield session

    app.dependency_overrides[get_user_context] = current_user
    app.dependency_overrides[network_people.get_db_session] = current_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/network/people-access?workspace_id=other&user_id=other-owner"
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == "current"
    assert {item["agent_id"] for item in payload["access"]} == {str(agents[0].id)}
    assert {person["user_id"] for person in payload["people"]} == {"actor", "owner"}
