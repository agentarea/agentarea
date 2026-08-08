from uuid import uuid4

import httpx
import pytest
from agentarea_execution.activities.artifact_validation import validate_published_artifacts
from agentarea_execution.models import ArtifactValidationRequest

MANAGER_URL = "http://mcp-manager:8000"


def _request(*paths: str) -> ArtifactValidationRequest:
    return ArtifactValidationRequest(
        workspace_id="workspace-1",
        task_id="task-1",
        workflow_id="workflow-1",
        declared_paths=list(paths),
    )


def _published(path: str, *, sha256: str = "b" * 64, size: int = 42) -> httpx.Response:
    return httpx.Response(
        201, json={"id": "art_" + "0" * 32, "path": path, "size": size, "sha256": sha256}
    )


class _Store:
    """Records every publication the barrier attempts, replying per path."""

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.published: list[str] = []

    def client(self, credential: str) -> httpx.AsyncClient:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/sandbox/artifacts"
            assert request.headers["authorization"] == f"Bearer {credential}"
            import json

            payload = json.loads(request.content)
            assert payload["workspace_id"] == "workspace-1"
            assert payload["task_id"] == "task-1"
            path = payload["path"]
            self.published.append(path)
            return self.responses.get(path, httpx.Response(404, json={"error": "file_not_found"}))

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_no_declared_artifacts_passes_without_touching_the_store() -> None:
    store = _Store({})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request(), manager_url=MANAGER_URL, auth_secret=credential, http_client=client
        )
    assert result.state == "passed"
    assert result.evidence == []
    assert store.published == []


@pytest.mark.asyncio
async def test_declared_file_is_published_and_reported_with_identity() -> None:
    store = _Store({"reports/model.xlsx": _published("reports/model.xlsx", size=42)})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("reports/model.xlsx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "passed"
    assert store.published == ["reports/model.xlsx"]
    assert [(e.path, e.validator, e.sha256, e.size) for e in result.evidence] == [
        ("reports/model.xlsx", "published_artifact", "b" * 64, 42)
    ]


@pytest.mark.asyncio
async def test_declared_file_the_agent_never_wrote_fails_the_completion() -> None:
    store = _Store({})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("reports/model.xlsx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "failed"
    assert result.issues[0].path == "reports/model.xlsx"
    assert result.issues[0].code == "artifact_missing"


@pytest.mark.asyncio
async def test_absolute_workspace_path_is_normalized_to_root_relative_key() -> None:
    store = _Store({"cash_runway.xlsx": _published("cash_runway.xlsx")})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("/workspace/cash_runway.xlsx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "passed"
    assert store.published == ["cash_runway.xlsx"]


@pytest.mark.asyncio
async def test_relative_workspace_prefix_is_a_real_directory_not_stripped() -> None:
    store = _Store({"workspace/report.xlsx": _published("workspace/report.xlsx")})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("workspace/report.xlsx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "passed"
    assert store.published == ["workspace/report.xlsx"]


@pytest.mark.asyncio
async def test_traversal_path_is_rejected_before_the_store_is_reached() -> None:
    store = _Store({})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("../../etc/passwd"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "failed"
    assert result.issues[0].code == "invalid_artifact_path"
    assert store.published == []


@pytest.mark.asyncio
async def test_duplicate_declared_paths_are_published_once() -> None:
    store = _Store({"r.xlsx": _published("r.xlsx")})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("r.xlsx", "./r.xlsx", "/workspace/r.xlsx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "passed"
    assert store.published == ["r.xlsx"]
    assert len(result.evidence) == 1


@pytest.mark.asyncio
async def test_one_missing_among_several_fails_while_keeping_the_rest() -> None:
    store = _Store({"a.xlsx": _published("a.xlsx"), "c.docx": _published("c.docx")})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("a.xlsx", "b.pptx", "/workspace/c.docx"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "failed"
    assert {e.path for e in result.evidence} == {"a.xlsx", "c.docx"}
    assert [i.path for i in result.issues] == ["b.pptx"]


@pytest.mark.asyncio
async def test_expired_sandbox_blocks_instead_of_failing_the_agent() -> None:
    store = _Store({"out.pdf": httpx.Response(410, json={"error": "sandbox_expired"})})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("out.pdf"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "unavailable"
    assert result.capability_unavailable is not None
    assert result.capability_unavailable.capability == "published_artifact_store"


@pytest.mark.asyncio
async def test_quota_rejection_is_reported_to_the_agent() -> None:
    store = _Store({"huge.bin": httpx.Response(413, json={"error": "artifact_quota_exceeded"})})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("huge.bin"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "failed"
    assert result.issues[0].code == "artifact_quota_exceeded"


@pytest.mark.asyncio
async def test_store_without_credentials_blocks_rather_than_passing_empty() -> None:
    result = await validate_published_artifacts(
        _request("out.pdf"), manager_url=MANAGER_URL, auth_secret=""
    )
    assert result.state == "unavailable"


@pytest.mark.asyncio
async def test_publication_without_valid_identity_blocks() -> None:
    store = _Store({"out.pdf": httpx.Response(201, json={"sha256": "nope", "size": 3})})
    credential = uuid4().hex
    async with store.client(credential) as client:
        result = await validate_published_artifacts(
            _request("out.pdf"),
            manager_url=MANAGER_URL,
            auth_secret=credential,
            http_client=client,
        )
    assert result.state == "unavailable"
