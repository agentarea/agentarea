"""Multipart task attachments are committed before workflow dispatch."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1 import agents_tasks
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _app(task_service, agent_service, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")

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


def test_unicode_attachment_download_header_has_safe_fallback_and_utf8_name():
    value = agents_tasks._attachment_content_disposition("отчёт 2026.xlsx")

    assert value.startswith('attachment; filename="2026.xlsx"')
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87" in value
    assert "\r" not in value
    assert "\n" not in value


@pytest.mark.asyncio
async def test_multipart_attachments_commit_atomically_before_exact_id_dispatch(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    order: list[str] = []
    repository = SimpleNamespace()

    async def put_files(*args, **kwargs):
        order.append("commit")
        return SimpleNamespace(generation=1)

    repository.put_files = AsyncMock(side_effect=put_files)
    monkeypatch.setattr(
        "agentarea_common.artifacts.WorkspaceRepository", lambda **_kwargs: repository
    )

    async def reserve_run(payload, **kwargs):
        order.append("reserve")
        task_id = kwargs["task_id"]
        return SimpleNamespace(
            id=task_id,
            agent_id=payload.agent_id,
            description=payload.description,
            task_parameters=payload.parameters,
            status="failed",
            result={"error": "test stop"},
            created_at=datetime.now(UTC),
            execution_id=None,
        )

    async def dispatch_reserved_run(task):
        order.append("dispatch")
        return task

    task_service = SimpleNamespace(
        reserve_run=AsyncMock(side_effect=reserve_run),
        dispatch_reserved_run=AsyncMock(side_effect=dispatch_reserved_run),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(task_service, agent_service, context)
    payload = {
        "description": "Analyze both files",
        "parameters": {"task_type": "chat"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps(payload)},
            files=[
                ("files", ("../Quarter report.csv", b"revenue", "text/csv")),
                ("files", ("notes.txt", b"margin", "text/plain")),
            ],
        )

    assert response.status_code == 200
    assert order == ["reserve", "commit", "dispatch"]
    commit_args = repository.put_files.await_args
    reserved_task_id = commit_args.args[1]
    assert commit_args.args[0] == context.workspace_id
    assert UUID(reserved_task_id)
    assert commit_args.args[2] == {
        "inputs/attachments/Quarter_report.csv": b"revenue",
        "inputs/attachments/notes.txt": b"margin",
    }

    reserve_call = task_service.reserve_run.await_args
    assert str(reserve_call.kwargs["task_id"]) == reserved_task_id
    descriptors = reserve_call.args[0].parameters["attachments"]
    assert descriptors == [
        {
            "relative_path": "inputs/attachments/Quarter_report.csv",
            "filename": "Quarter_report.csv",
            "size": 7,
            "content_type": "text/csv",
            "sha256": hashlib.sha256(b"revenue").hexdigest(),
        },
        {
            "relative_path": "inputs/attachments/notes.txt",
            "filename": "notes.txt",
            "size": 6,
            "content_type": "text/plain",
            "sha256": hashlib.sha256(b"margin").hexdigest(),
        },
    ]
    assert reserve_call.kwargs["trusted_metadata"] == {
        "workspace_attachments": descriptors
    }
    assert b"revenue" not in json.dumps(descriptors).encode()


@pytest.mark.asyncio
async def test_storage_failure_keeps_authoritative_failed_task_record(monkeypatch):
    from agentarea_common.artifacts import WorkspaceQuotaError

    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    repository = SimpleNamespace(
        put_files=AsyncMock(side_effect=WorkspaceQuotaError("workspace full"))
    )
    monkeypatch.setattr(
        "agentarea_common.artifacts.WorkspaceRepository", lambda **_kwargs: repository
    )
    reserved_task = SimpleNamespace(id=uuid4())
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(return_value=reserved_task),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps({"description": "Inspect it"})},
            files={"files": ("report.csv", b"data", "text/csv")},
        )

    assert response.status_code == 413
    task_service.reserve_run.assert_awaited_once()
    reserved_id = task_service.reserve_run.await_args.kwargs["task_id"]
    task_service.update_task_status.assert_awaited_once_with(
        reserved_id, "failed", error="Attachment quota exceeded"
    )
    task_service.dispatch_reserved_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_attachment_quota_failures_are_explicit_and_prevent_dispatch(monkeypatch):
    monkeypatch.setattr(agents_tasks, "TASK_ATTACHMENT_MAX_FILE_BYTES", 3)
    repository = SimpleNamespace(put_files=AsyncMock())
    monkeypatch.setattr(
        "agentarea_common.artifacts.WorkspaceRepository", lambda **_kwargs: repository
    )
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _app(
        task_service,
        agent_service,
        UserContext(user_id="user-a", workspace_id="workspace-a"),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_size_response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps({"description": "Inspect it"})},
            files={"files": ("large.bin", b"four", "application/octet-stream")},
        )

        monkeypatch.setattr(agents_tasks, "TASK_ATTACHMENT_MAX_FILE_BYTES", 10)
        monkeypatch.setattr(agents_tasks, "TASK_ATTACHMENT_MAX_FILES", 1)
        file_count_response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps({"description": "Inspect them"})},
            files=[
                ("files", ("one.txt", b"1", "text/plain")),
                ("files", ("two.txt", b"2", "text/plain")),
            ],
        )

        monkeypatch.setattr(agents_tasks, "TASK_ATTACHMENT_MAX_FILES", 10)
        monkeypatch.setattr(agents_tasks, "TASK_ATTACHMENT_MAX_TOTAL_BYTES", 3)
        total_size_response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps({"description": "Inspect them"})},
            files=[
                ("files", ("one.txt", b"12", "text/plain")),
                ("files", ("two.txt", b"34", "text/plain")),
            ],
        )

    assert file_size_response.status_code == 413
    assert "per-file limit is 3" in file_size_response.json()["detail"]
    assert file_count_response.status_code == 413
    assert "Too many attachments: 2; limit is 1" in file_count_response.json()["detail"]
    assert total_size_response.status_code == 413
    assert "total limit is 3" in total_size_response.json()["detail"]
    repository.put_files.assert_not_awaited()
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_sanitized_filename_collision_rejects_whole_request(monkeypatch):
    repository = SimpleNamespace(put_files=AsyncMock())
    monkeypatch.setattr(
        "agentarea_common.artifacts.WorkspaceRepository", lambda **_kwargs: repository
    )
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
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
            f"/v1/agents/{uuid4()}/tasks/with-attachments",
            data={"task_data": json.dumps({"description": "Inspect them"})},
            files=[
                ("files", ("a b.txt", b"one", "text/plain")),
                ("files", ("a?b.txt", b"two", "text/plain")),
            ],
        )

    assert response.status_code == 422
    assert "collide after sanitization" in response.json()["detail"]
    repository.put_files.assert_not_awaited()
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()
