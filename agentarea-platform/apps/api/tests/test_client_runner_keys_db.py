"""A client's runner key, issued and revoked against the real schema (ADR-0051).

The key authenticates bound to its client, revoking it closes the door, and
deleting the client deletes its keys by ON DELETE CASCADE, which a mocked
session cannot check.

Set MCP_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1.clients import issue_runner_key, list_runner_keys, revoke_runner_key
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import _validate_api_key
from agentarea_common.workspaces import Workspace
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.domain.auth_models import APIKey
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("MCP_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="MCP_TEST_DATABASE_URL not set")

OWNER = "client-owner"


@pytest.fixture
async def sessions():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await transaction.rollback()
    await engine.dispose()


async def _client(sessions, kind: str = "codex") -> Client:
    workspace_id = f"ws-runner-{uuid4().hex[:8]}"
    async with sessions() as session:
        session.add(
            Workspace(id=workspace_id, slug=workspace_id, name="runner", owner_user_id=OWNER)
        )
        client = Client(name="codex-box", kind=kind, workspace_id=workspace_id, created_by=OWNER)
        session.add(client)
        await session.commit()
        return client


def _handler_args(session: AsyncSession, client: Client) -> dict:
    context = UserContext(user_id=OWNER, workspace_id=client.workspace_id)
    return {
        "service": ClientService(ClientRepository(session, context)),
        "factory": SimpleNamespace(session=session, user_context=context),
    }


async def _issue(sessions, client: Client):
    async with sessions() as session:
        return await issue_runner_key(
            client.id, audit=AsyncMock(), **_handler_args(session, client)
        )


async def _authenticate(sessions, key: str):
    @asynccontextmanager
    async def session_factory():
        async with sessions() as session:
            yield session

    database = SimpleNamespace(async_session_factory=session_factory)
    with patch("agentarea_common.config.get_database", return_value=database):
        return await _validate_api_key(key, MagicMock())


async def test_an_issued_key_authenticates_bound_to_its_client(sessions):
    client = await _client(sessions)
    issued = await _issue(sessions, client)

    principal = await _authenticate(sessions, issued.key)

    assert principal is not None
    assert (principal.user_id, principal.bound_workspace_id, principal.bound_client_id) == (
        OWNER,
        client.workspace_id,
        str(client.id),
    )
    async with sessions() as session:
        listed = await list_runner_keys(client.id, **_handler_args(session, client))
    assert [(k.id, k.prefix) for k in listed] == [(issued.id, issued.key[:12])]


async def test_a_client_no_runner_drives_gets_no_key(sessions):
    client = await _client(sessions, kind="harness")

    with pytest.raises(HTTPException) as refused:
        await _issue(sessions, client)

    assert refused.value.status_code == 422


async def test_a_revoked_runner_key_no_longer_authenticates(sessions):
    client = await _client(sessions)
    issued = await _issue(sessions, client)

    async with sessions() as session:
        await revoke_runner_key(
            client.id, issued.id, audit=AsyncMock(), **_handler_args(session, client)
        )
        assert await list_runner_keys(client.id, **_handler_args(session, client)) == []

    assert await _authenticate(sessions, issued.key) is None


async def test_deleting_the_client_deletes_its_keys(sessions):
    client = await _client(sessions)
    issued = await _issue(sessions, client)

    async with sessions() as session:
        await session.execute(delete(Client).where(Client.id == client.id))
        await session.commit()
        assert await session.scalar(select(APIKey).where(APIKey.id == issued.id)) is None
