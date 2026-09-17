"""Resolving an id into whoever it belongs to, as its own resource.

Every `created_by` in the schema (28 columns and counting) eventually needs a
name next to it. Attaching that name to each read model would mean writing the
same "go ask the identity provider" 28 times, and would make each of those
resources fail when the identity provider is slow. It lives here instead: one
endpoint, cacheable on its own terms, joined by the caller.

The response carries `type` because an id is not necessarily a person. Users,
agents and the reserved platform principals occur today; clients are expected
to follow (see #425), and the shape is what lets them arrive without another
breaking change.

Agents are resolved before users and from the same database, so an id that
belongs to an agent is never asked about in Kratos at all.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service
from agentarea_api.api.v1 import principals
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.identity_directory import IdentityRecord
from httpx import ASGITransport, AsyncClient

ARTEM = "bb206374-f612-420d-acd0-b62051061c63"
MISHA = "5b1edbaf-8480-4885-a003-78adc92ab513"
SEO_AGENT = "391de587-1c93-4f5a-9f97-98beabe101f4"


def _directory(records: dict[str, IdentityRecord]):
    directory = MagicMock()
    directory.resolve = AsyncMock(return_value=records)
    return lambda: directory


def _agent(agent_id: str, name: str):
    agent = MagicMock()
    agent.id = agent_id
    agent.name = name
    return agent


@pytest_asyncio.fixture
async def agent_service():
    """The workspace's agents. Empty unless a test puts something in it."""
    service = AsyncMock()
    service.list.return_value = []
    app.dependency_overrides[get_read_agent_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_read_agent_service, None)


@pytest_asyncio.fixture
async def client(agent_service):
    user_context = MagicMock()
    user_context.user_id = ARTEM
    user_context.workspace_id = "workspace-1"
    user_context.email = "artem@aadocs.local"
    app.dependency_overrides[get_user_context] = lambda: user_context
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_user_context, None)


@pytest.mark.asyncio
async def test_resolves_several_ids_in_one_call(client, monkeypatch) -> None:
    monkeypatch.setattr(
        principals,
        "get_identity_directory",
        _directory(
            {
                ARTEM: IdentityRecord(ARTEM, "artem@aadocs.local", "Artem Astapenko"),
                MISHA: IdentityRecord(MISHA, "misha@aadocs.local", "Misha Dev"),
            }
        ),
    )

    response = await client.get(f"/v1/principals?ids={ARTEM}&ids={MISHA}")

    assert response.status_code == 200, response.text
    by_id = {p["id"]: p for p in response.json()}
    assert by_id[ARTEM]["display_name"] == "Artem Astapenko"
    assert by_id[ARTEM]["type"] == "user"
    assert by_id[MISHA]["display_name"] == "Misha Dev"


@pytest.mark.asyncio
async def test_an_id_the_directory_does_not_know_is_absent(client, monkeypatch) -> None:
    """Absent, not a row with the id echoed back as its own name."""
    monkeypatch.setattr(
        principals,
        "get_identity_directory",
        _directory({ARTEM: IdentityRecord(ARTEM, "artem@aadocs.local", "Artem Astapenko")}),
    )

    response = await client.get(f"/v1/principals?ids={ARTEM}&ids=deleted-user")

    assert response.status_code == 200, response.text
    returned = {p["id"] for p in response.json()}
    assert returned == {ARTEM}


@pytest.mark.asyncio
async def test_reserved_platform_ids_resolve_without_the_directory(client, monkeypatch) -> None:
    """`platform` and `system` are constants, not people — no lookup, no name."""
    directory = MagicMock()
    directory.resolve = AsyncMock(return_value={})
    monkeypatch.setattr(principals, "get_identity_directory", lambda: directory)

    response = await client.get("/v1/principals?ids=platform&ids=system")

    assert response.status_code == 200, response.text
    by_id = {p["id"]: p for p in response.json()}
    assert by_id["platform"]["type"] == "platform"
    assert by_id["platform"]["display_name"] is None
    assert by_id["system"]["type"] == "platform"
    # Reserved ids must never be sent to the identity provider.
    assert directory.resolve.await_args.args[0] == []


@pytest.mark.asyncio
async def test_no_ids_is_an_empty_answer_not_an_error(client, monkeypatch) -> None:
    monkeypatch.setattr(principals, "get_identity_directory", _directory({}))

    response = await client.get("/v1/principals")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_duplicate_ids_cost_one_lookup(client, monkeypatch) -> None:
    directory = MagicMock()
    directory.resolve = AsyncMock(
        return_value={ARTEM: IdentityRecord(ARTEM, "artem@aadocs.local", "Artem Astapenko")}
    )
    monkeypatch.setattr(principals, "get_identity_directory", lambda: directory)

    response = await client.get(f"/v1/principals?ids={ARTEM}&ids={ARTEM}&ids={ARTEM}")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert directory.resolve.await_args.args[0] == [ARTEM]


@pytest.mark.asyncio
async def test_identity_resolution_switched_off_yields_no_names(client, monkeypatch) -> None:
    """No KRATOS_ADMIN_URL means no names — never ids dressed up as names.

    Asked about someone else: the caller's own id still resolves from their own
    verified token, which is an authority for exactly one id and not a guess.
    """
    monkeypatch.setattr(principals, "get_identity_directory", lambda: None)

    response = await client.get(f"/v1/principals?ids={MISHA}")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_the_caller_can_always_resolve_themselves(client, monkeypatch) -> None:
    """The caller's own token is a second authority for exactly one id."""
    monkeypatch.setattr(principals, "get_identity_directory", _directory({}))

    response = await client.get(f"/v1/principals?ids={ARTEM}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["email"] == "artem@aadocs.local"


@pytest.mark.asyncio
async def test_an_agent_id_resolves_to_the_agent(client, agent_service, monkeypatch) -> None:
    agent_service.list.return_value = [_agent(SEO_AGENT, "SEO")]
    monkeypatch.setattr(principals, "get_identity_directory", _directory({}))

    response = await client.get(f"/v1/principals?ids={SEO_AGENT}")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"id": SEO_AGENT, "type": "agent", "display_name": "SEO", "email": None}
    ]


@pytest.mark.asyncio
async def test_an_agent_id_is_never_sent_to_the_identity_provider(
    client, agent_service, monkeypatch
) -> None:
    """Agents live in our own database; asking Kratos about one is pure waste."""
    agent_service.list.return_value = [_agent(SEO_AGENT, "SEO")]
    directory = MagicMock()
    directory.resolve = AsyncMock(
        return_value={MISHA: IdentityRecord(MISHA, "misha@aadocs.local", "Misha Dev")}
    )
    monkeypatch.setattr(principals, "get_identity_directory", lambda: directory)

    response = await client.get(f"/v1/principals?ids={SEO_AGENT}&ids={MISHA}")

    assert response.status_code == 200, response.text
    assert directory.resolve.await_args.args[0] == [MISHA]
    by_id = {p["id"]: p["type"] for p in response.json()}
    assert by_id == {SEO_AGENT: "agent", MISHA: "user"}


@pytest.mark.asyncio
async def test_an_id_that_is_no_agent_still_falls_through_to_the_directory(
    client, agent_service, monkeypatch
) -> None:
    agent_service.list.return_value = [_agent(str(uuid4()), "Some other agent")]
    monkeypatch.setattr(
        principals,
        "get_identity_directory",
        _directory({MISHA: IdentityRecord(MISHA, "misha@aadocs.local", "Misha Dev")}),
    )

    response = await client.get(f"/v1/principals?ids={MISHA}")

    assert response.status_code == 200, response.text
    assert response.json()[0]["type"] == "user"


@pytest.mark.asyncio
async def test_a_deleted_agent_is_absent_rather_than_named(
    client, agent_service, monkeypatch
) -> None:
    """Same contract as an unresolvable user — the caller renders it unknown."""
    agent_service.list.return_value = []
    monkeypatch.setattr(principals, "get_identity_directory", _directory({}))

    response = await client.get(f"/v1/principals?ids={SEO_AGENT}")

    assert response.status_code == 200, response.text
    assert response.json() == []
