"""Ref-based task attachments are copied server-side before workflow dispatch.

The upload endpoint stages a file (server-proxied or presigned) and returns a
``ref``; task creation HEADs the ref to resolve its verified digest and copies
it into the task's content-addressed store via ``attach_object`` without the
bytes ever transiting the API. Staging objects are deleted only after a
successful dispatch.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.deps.services import (
    get_read_agent_service,
    get_read_task_service,
    get_temporal_workflow_service,
)
from agentarea_api.api.v1 import agents_tasks, files
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_governance.domain.policies import PolicyValidationError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

SHA_REVENUE = hashlib.sha256(b"revenue").hexdigest()
SHA_MARGIN = hashlib.sha256(b"margin").hexdigest()


def _task_app(task_service, agent_service, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")

    app.dependency_overrides[agents_tasks.get_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = lambda: agent_service
    app.dependency_overrides[get_user_context] = lambda: context
    return app


def _files_app(context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(files.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: context
    return app


def _reserved_task(task_id, payload):
    return SimpleNamespace(
        id=task_id,
        agent_id=payload.agent_id,
        description=payload.description,
        task_parameters=payload.parameters,
        status="running",
        result=None,
        created_at=datetime.now(UTC),
        # None forces the stream's non-tailing branch so the test never touches
        # the live Redis event feed.
        execution_id=None,
        scheduled_at=None,
    )


def _install_attachment_fakes(monkeypatch, *, heads, order, attached, deleted):
    class FakeArtifactService:
        def __init__(self, *args, **kwargs):
            pass

        async def head(self, workspace_id, path):
            return heads.get(path)

        async def delete(self, workspace_id, path):
            order.append("delete")
            deleted.append(path)

    class FakeWorkspaceRepository:
        def __init__(self, *args, **kwargs):
            pass

        async def attach_object(
            self,
            workspace_id,
            task_id,
            path,
            *,
            source_key,
            expected_sha256,
            expected_size,
            content_type,
            owner=None,
        ):
            order.append("attach")
            attached.append(
                {
                    "task_id": task_id,
                    "path": path,
                    "source_key": source_key,
                    "expected_sha256": expected_sha256,
                    "expected_size": expected_size,
                    "content_type": content_type,
                }
            )
            return SimpleNamespace(generation=1)

    monkeypatch.setattr("agentarea_common.artifacts.ArtifactService", FakeArtifactService)
    monkeypatch.setattr("agentarea_common.artifacts.WorkspaceRepository", FakeWorkspaceRepository)


def test_unicode_attachment_download_header_has_safe_fallback_and_utf8_name():
    value = agents_tasks._attachment_content_disposition("отчёт 2026.xlsx")

    assert value.startswith('attachment; filename="2026.xlsx"')
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87" in value
    assert "\r" not in value
    assert "\n" not in value


def test_dedupe_attachment_name_suffixes_before_extension():
    used: set[str] = set()
    first = agents_tasks._dedupe_attachment_name("report.csv", used)
    used.add(first)
    second = agents_tasks._dedupe_attachment_name("report.csv", used)
    used.add(second)
    third = agents_tasks._dedupe_attachment_name("report.csv", used)
    used.add(third)
    extensionless = agents_tasks._dedupe_attachment_name("notes", used)
    used.add(extensionless)
    dup_extensionless = agents_tasks._dedupe_attachment_name("notes", used)

    assert [first, second, third] == ["report.csv", "report-1.csv", "report-2.csv"]
    assert extensionless == "notes"
    assert dup_extensionless == "notes-1"


@pytest.mark.asyncio
async def test_refs_attach_by_copy_then_dispatch_then_delete(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    order: list[str] = []
    attached: list[dict] = []
    deleted: list[str] = []
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_REVENUE,
        },
        "staging/bbb/notes.txt": {
            "size": 6,
            "content_type": "text/plain",
            "metadata": {},
            "sha256": SHA_MARGIN,
        },
    }
    _install_attachment_fakes(
        monkeypatch, heads=heads, order=order, attached=attached, deleted=deleted
    )

    async def reserve_run(payload, **kwargs):
        order.append("reserve")
        return _reserved_task(kwargs["task_id"], payload)

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
    app = _task_app(task_service, agent_service, context)
    payload = {
        "description": "Analyze both files",
        "parameters": {"task_type": "chat"},
        "attachments": ["staging/aaa/report.csv", "staging/bbb/notes.txt"],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/v1/agents/{uuid4()}/tasks/", json=payload)

    assert response.status_code == 200
    # attach for both refs, then reserve, dispatch, and only then the staging
    # deletions — a failed dispatch must not consume the upload.
    assert order == ["attach", "attach", "reserve", "dispatch", "delete", "delete"]
    assert deleted == ["staging/aaa/report.csv", "staging/bbb/notes.txt"]

    assert [a["source_key"] for a in attached] == [
        "staging/aaa/report.csv",
        "staging/bbb/notes.txt",
    ]
    assert [a["path"] for a in attached] == [
        "inputs/attachments/report.csv",
        "inputs/attachments/notes.txt",
    ]
    assert attached[0]["expected_sha256"] == SHA_REVENUE
    assert attached[0]["expected_size"] == 7
    assert attached[0]["content_type"] == "text/csv"

    reserve_call = task_service.reserve_run.await_args
    reserved_task_id = reserve_call.kwargs["task_id"]
    assert UUID(str(reserved_task_id))
    # attach_object targeted the same reserved task id it dispatched.
    assert attached[0]["task_id"] == str(reserved_task_id)

    descriptors = reserve_call.args[0].parameters["attachments"]
    assert descriptors == [
        {
            "relative_path": "inputs/attachments/report.csv",
            "filename": "report.csv",
            "size": 7,
            "content_type": "text/csv",
            "sha256": SHA_REVENUE,
        },
        {
            "relative_path": "inputs/attachments/notes.txt",
            "filename": "notes.txt",
            "size": 6,
            "content_type": "text/plain",
            "sha256": SHA_MARGIN,
        },
    ]
    assert reserve_call.kwargs["trusted_metadata"] == {"workspace_attachments": descriptors}
    # No file bytes were ever handed to the API in the descriptors.
    assert b"revenue" not in json.dumps(descriptors).encode()


@pytest.mark.asyncio
async def test_attachment_reservation_hides_policy_error_details(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    order: list[str] = []
    attached: list[dict] = []
    deleted: list[str] = []
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_REVENUE,
        }
    }
    _install_attachment_fakes(
        monkeypatch, heads=heads, order=order, attached=attached, deleted=deleted
    )
    raw_error = "run_budget_usd cannot loosen higher-scope ceiling"
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(side_effect=PolicyValidationError(raw_error)),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/",
            json={"description": "Analyze file", "attachments": ["staging/aaa/report.csv"]},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Task policy rejected"
    assert raw_error not in response.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_basenames_get_deterministic_suffix(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    order: list[str] = []
    attached: list[dict] = []
    deleted: list[str] = []
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_REVENUE,
        },
        "staging/bbb/report.csv": {
            "size": 6,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_MARGIN,
        },
    }
    _install_attachment_fakes(
        monkeypatch, heads=heads, order=order, attached=attached, deleted=deleted
    )

    async def reserve_run(payload, **kwargs):
        return _reserved_task(kwargs["task_id"], payload)

    task_service = SimpleNamespace(
        reserve_run=AsyncMock(side_effect=reserve_run),
        dispatch_reserved_run=AsyncMock(side_effect=lambda task: task),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)
    payload = {
        "description": "Two files, same name",
        "parameters": {},
        "attachments": ["staging/aaa/report.csv", "staging/bbb/report.csv"],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/v1/agents/{uuid4()}/tasks/", json=payload)

    assert response.status_code == 200
    # Both files survive as distinct manifest entries instead of one overwriting
    # the other.
    assert [a["path"] for a in attached] == [
        "inputs/attachments/report.csv",
        "inputs/attachments/report-1.csv",
    ]
    descriptors = task_service.reserve_run.await_args.args[0].parameters["attachments"]
    assert [d["filename"] for d in descriptors] == ["report.csv", "report-1.csv"]


@pytest.mark.asyncio
async def test_ref_outside_staging_is_rejected(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    _install_attachment_fakes(monkeypatch, heads={}, order=[], attached=[], deleted=[])
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/",
            json={
                "description": "escape attempt",
                "attachments": ["tasks/other/workspace/secret.txt"],
            },
        )

    assert response.status_code == 422
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_ref_returns_404(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    # head() returns None for an unknown staging key.
    _install_attachment_fakes(monkeypatch, heads={}, order=[], attached=[], deleted=[])
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/",
            json={"description": "missing", "attachments": ["staging/gone/report.csv"]},
        )

    assert response.status_code == 404
    task_service.reserve_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_unresolvable_digest_fails_loudly(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": None,
        }
    }
    _install_attachment_fakes(monkeypatch, heads=heads, order=[], attached=[], deleted=[])
    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/",
            json={"description": "no digest", "attachments": ["staging/aaa/report.csv"]},
        )

    assert response.status_code == 422
    task_service.reserve_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_failure_maps_to_413_and_prevents_dispatch(monkeypatch):
    from agentarea_common.artifacts import WorkspaceQuotaError

    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_REVENUE,
        }
    }

    class FakeArtifactService:
        def __init__(self, *args, **kwargs):
            pass

        async def head(self, workspace_id, path):
            return heads.get(path)

        async def delete(self, workspace_id, path):  # pragma: no cover - never reached
            raise AssertionError("staging must not be deleted when attach fails")

    class FakeWorkspaceRepository:
        def __init__(self, *args, **kwargs):
            pass

        async def attach_object(self, *args, **kwargs):
            raise WorkspaceQuotaError("workspace full")

    monkeypatch.setattr("agentarea_common.artifacts.ArtifactService", FakeArtifactService)
    monkeypatch.setattr("agentarea_common.artifacts.WorkspaceRepository", FakeWorkspaceRepository)

    task_service = SimpleNamespace(
        reserve_run=AsyncMock(),
        dispatch_reserved_run=AsyncMock(),
        update_task_status=AsyncMock(),
    )
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="Analyst"))
    )
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/",
            json={"description": "too big", "attachments": ["staging/aaa/report.csv"]},
        )

    assert response.status_code == 413
    task_service.reserve_run.assert_not_awaited()
    task_service.dispatch_reserved_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_path_attaches_and_deletes_after_dispatch(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    order: list[str] = []
    attached: list[dict] = []
    deleted: list[str] = []
    heads = {
        "staging/aaa/report.csv": {
            "size": 7,
            "content_type": "text/csv",
            "metadata": {},
            "sha256": SHA_REVENUE,
        }
    }
    _install_attachment_fakes(
        monkeypatch, heads=heads, order=order, attached=attached, deleted=deleted
    )

    async def reserve_run(payload, **kwargs):
        order.append("reserve")
        task = _reserved_task(kwargs["task_id"], payload)
        return SimpleNamespace(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            task_parameters=task.task_parameters,
            status="running",
            result=None,
            error_message=None,
            created_at=task.created_at,
            execution_id="exec-1",
            scheduled_at=None,
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
    app = _task_app(task_service, agent_service, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{uuid4()}/tasks/sync",
            json={"description": "sync", "attachments": ["staging/aaa/report.csv"]},
        )

    assert response.status_code == 200
    assert order == ["attach", "reserve", "dispatch", "delete"]
    assert deleted == ["staging/aaa/report.csv"]


# --- files.py unified upload endpoint --------------------------------------


def _install_files_fakes(monkeypatch, *, puts, presigns):
    class FakeArtifactService:
        def __init__(self, *args, **kwargs):
            pass

        async def put(self, workspace_id, path, content, content_type=None):
            puts.append(
                {
                    "workspace_id": workspace_id,
                    "path": path,
                    "content": content,
                    "content_type": content_type,
                }
            )
            return SimpleNamespace(path=path, size=len(content), content_type=content_type)

        async def presigned_put_url(
            self, workspace_id, path, *, content_type=None, sha256_b64=None, expires_in=3600
        ):
            presigns.append(
                {
                    "workspace_id": workspace_id,
                    "path": path,
                    "content_type": content_type,
                    "sha256_b64": sha256_b64,
                    "expires_in": expires_in,
                }
            )
            return f"https://s3.local/bucket/{path}?sig=abc"

    monkeypatch.setattr(files, "ArtifactService", FakeArtifactService)


@pytest.mark.asyncio
async def test_upload_defaults_to_workspace_root_and_returns_204(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    puts: list[dict] = []
    _install_files_fakes(monkeypatch, puts=puts, presigns=[])
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files", files={"file": ("report.csv", b"revenue", "text/csv")}
        )

    assert response.status_code == 204
    assert puts == [
        {
            "workspace_id": "workspace-a",
            "path": "report.csv",
            "content": b"revenue",
            "content_type": "text/csv",
        }
    ]


@pytest.mark.asyncio
async def test_upload_attachment_stages_and_returns_descriptor(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    puts: list[dict] = []
    _install_files_fakes(monkeypatch, puts=puts, presigns=[])
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files",
            data={"purpose": "attachment"},
            files={"file": ("report.csv", b"revenue", "text/csv")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ref"].startswith("staging/")
    assert body["ref"].endswith("/report.csv")
    assert body["filename"] == "report.csv"
    assert body["size"] == 7
    assert body["sha256"] == SHA_REVENUE
    assert body["content_type"] == "text/csv"
    # Stored under the staging ref it returned, not at the workspace root.
    assert puts[0]["path"] == body["ref"]


@pytest.mark.asyncio
async def test_upload_attachment_over_cap_is_413(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    puts: list[dict] = []
    _install_files_fakes(monkeypatch, puts=puts, presigns=[])
    monkeypatch.setattr(files, "MAX_ATTACHMENT_BYTES", 3)
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files",
            data={"purpose": "attachment"},
            files={"file": ("big.bin", b"four", "application/octet-stream")},
        )

    assert response.status_code == 413
    assert puts == []


@pytest.mark.asyncio
async def test_unknown_purpose_is_422(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    puts: list[dict] = []
    _install_files_fakes(monkeypatch, puts=puts, presigns=[])
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files",
            data={"purpose": "bogus"},
            files={"file": ("report.csv", b"revenue", "text/csv")},
        )

    assert response.status_code == 422
    assert puts == []


@pytest.mark.asyncio
async def test_upload_url_binds_checksum_and_returns_ref(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    presigns: list[dict] = []
    _install_files_fakes(monkeypatch, puts=[], presigns=presigns)
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files/upload-url",
            json={
                "filename": "report.csv",
                "content_type": "text/csv",
                "sha256": SHA_REVENUE,
                "size": 7,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ref"].startswith("staging/")
    assert body["ref"].endswith("/report.csv")
    assert body["upload_url"].startswith("https://")
    assert body["expires_in"] == 3600
    assert presigns[0]["path"] == body["ref"]
    assert presigns[0]["content_type"] == "text/csv"
    # The hex digest is bound into the signature as base64 so the store enforces
    # integrity on the direct upload.
    assert presigns[0]["sha256_b64"] == base64.b64encode(bytes.fromhex(SHA_REVENUE)).decode("ascii")


@pytest.mark.asyncio
async def test_upload_url_rejects_non_hex_sha256(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    presigns: list[dict] = []
    _install_files_fakes(monkeypatch, puts=[], presigns=presigns)
    app = _files_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files/upload-url",
            json={
                "filename": "report.csv",
                "content_type": "text/csv",
                "sha256": "not-a-real-digest",
                "size": 7,
            },
        )

    assert response.status_code == 422
    assert presigns == []


@pytest.mark.asyncio
async def test_task_status_hides_raw_workflow_error(monkeypatch):
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    agent_id = uuid4()
    task_id = uuid4()
    task = SimpleNamespace(
        agent_id=agent_id,
        execution_id="workflow-1",
        status="failed",
        error_message=None,
        result=None,
    )
    task_service = SimpleNamespace(
        get_task_with_workflow_status=AsyncMock(return_value=task),
    )
    workflow_service = SimpleNamespace(
        get_workflow_status=AsyncMock(
            return_value={
                "status": "failed",
                "error": "upstream failure: SECRET_MANAGER_ACCESS_KEY=private-value",
            }
        )
    )
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: context
    app.dependency_overrides[get_read_agent_service] = lambda: SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id=agent_id))
    )
    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_temporal_workflow_service] = lambda: workflow_service
    monkeypatch.setattr(agents_tasks, "_list_task_artifact_items", AsyncMock(return_value=[]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/status")

    assert response.status_code == 200
    assert response.json()["error"] is None
    assert "private-value" not in response.text
