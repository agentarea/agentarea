"""Task attachments follow the staging-ref model.

Files are pre-uploaded to a temp staging area via POST /v1/files/staging, then
referenced by ref in the JSON task-create body. The task-create path resolves
each ref into the task workspace under ``inputs/attachments/`` and consumes the
staged object.
"""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import agents_tasks, files
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _fake_service_factory(store: dict):
    """ArtifactService stand-in over an in-memory store shared across surfaces."""

    class _Svc:
        def __init__(self, **_kwargs):
            pass

        async def put(self, workspace_id, path, data, content_type=None):
            store[(workspace_id, path)] = (data, content_type)
            return SimpleNamespace(path=path, size=len(data), content_type=content_type)

        async def get(self, workspace_id, path):
            if (workspace_id, path) not in store:
                raise FileNotFoundError(path)
            return store[(workspace_id, path)]

        async def delete(self, workspace_id, path):
            store.pop((workspace_id, path), None)

    return _Svc


def _fake_repo_factory(committed: dict):
    class _Repo:
        def __init__(self, **_kwargs):
            pass

        async def put_files(
            self,
            workspace_id,
            task_id,
            staged,
            content_types=None,
            provenance=None,
            owner=None,
        ):
            for rel, data in staged.items():
                committed[(workspace_id, task_id, rel)] = data
            return SimpleNamespace(generation=1)

    return _Repo


def _patch_storage(monkeypatch, store: dict, committed: dict):
    service = _fake_service_factory(store)
    repo = _fake_repo_factory(committed)
    # Staging upload resolves ArtifactService from the files module namespace;
    # task-create resolves it (and WorkspaceRepository) from the artifacts pkg.
    monkeypatch.setattr(files, "ArtifactService", service)
    monkeypatch.setattr("agentarea_common.artifacts.ArtifactService", service)
    monkeypatch.setattr("agentarea_common.artifacts.WorkspaceRepository", repo)


def _app(task_service, agent_service, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")
    app.include_router(files.router, prefix="/v1")

    async def override_task_service():
        return task_service

    async def override_agent_service():
        return agent_service

    async def override_user_context():
        return context

    app.dependency_overrides[agents_tasks.get_task_service] = override_task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = override_agent_service
    app.dependency_overrides[get_user_context] = override_user_context
    return app


def _run_task_service():
    async def reserve_run(payload, **kwargs):
        return SimpleNamespace(
            id=kwargs["task_id"],
            agent_id=payload.agent_id,
            description=payload.description,
            task_parameters=payload.parameters,
            status="running",
            result=None,
            error_message=None,
            created_at=datetime.now(UTC),
            execution_id=f"task-{kwargs['task_id']}",
        )

    return SimpleNamespace(
        reserve_run=AsyncMock(side_effect=reserve_run),
        dispatch_reserved_run=AsyncMock(side_effect=lambda task: task),
        start_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )


def test_unicode_attachment_download_header_has_safe_fallback_and_utf8_name():
    value = agents_tasks._attachment_content_disposition("отчёт 2026.xlsx")

    assert value.startswith('attachment; filename="2026.xlsx"')
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87" in value
    assert "\r" not in value
    assert "\n" not in value


@pytest.mark.asyncio
async def test_staged_ref_is_committed_into_task_workspace_and_consumed(monkeypatch):
    store: dict = {}
    committed: dict = {}
    _patch_storage(monkeypatch, store, committed)

    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    task_service = _run_task_service()
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(task_service, agent_service, context)
    agent_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        staging_response = await client.post(
            "/v1/files/staging",
            files={"file": ("../Quarter report.csv", b"revenue", "text/csv")},
        )
        assert staging_response.status_code == 200
        staged = staging_response.json()
        ref = staged["ref"]
        assert ref.startswith("staging/")
        assert staged["filename"] == "Quarter report.csv"
        assert staged["size"] == 7
        # The staged object exists before the task consumes it.
        assert (context.workspace_id, ref) in store

        task_response = await client.post(
            f"/v1/agents/{agent_id}/tasks/sync",
            json={"description": "Analyze it", "attachments": [ref]},
        )

    assert task_response.status_code == 200

    reserve_call = task_service.reserve_run.await_args
    reserved_task_id = str(reserve_call.kwargs["task_id"])
    descriptors = reserve_call.args[0].parameters["attachments"]
    assert descriptors == [
        {
            "relative_path": "inputs/attachments/Quarter report.csv",
            "filename": "Quarter report.csv",
            "size": 7,
            "content_type": "text/csv",
            "sha256": hashlib.sha256(b"revenue").hexdigest(),
        }
    ]
    assert reserve_call.kwargs["trusted_metadata"] == {"workspace_attachments": descriptors}
    task_service.dispatch_reserved_run.assert_awaited_once()

    # The file landed in the task workspace under inputs/attachments/.
    assert (
        committed[(context.workspace_id, reserved_task_id, "inputs/attachments/Quarter report.csv")]
        == b"revenue"
    )
    # The staging object was consumed (best-effort delete).
    assert (context.workspace_id, ref) not in store


@pytest.mark.asyncio
async def test_non_staging_ref_is_rejected(monkeypatch):
    store: dict = {}
    committed: dict = {}
    _patch_storage(monkeypatch, store, committed)

    task_service = _run_task_service()
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(
        task_service,
        agent_service,
        UserContext(user_id="user-a", workspace_id="workspace-a"),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/sync",
            json={"description": "Inspect it", "attachments": ["tasks/other/secret.csv"]},
        )

    assert response.status_code == 422
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_staging_ref_returns_not_found(monkeypatch):
    store: dict = {}
    committed: dict = {}
    _patch_storage(monkeypatch, store, committed)

    task_service = _run_task_service()
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(
        task_service,
        agent_service,
        UserContext(user_id="user-a", workspace_id="workspace-a"),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/sync",
            json={"description": "Inspect it", "attachments": ["staging/deadbeef/gone.csv"]},
        )

    assert response.status_code == 404
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()
