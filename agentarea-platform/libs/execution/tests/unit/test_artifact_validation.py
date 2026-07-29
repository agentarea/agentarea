from dataclasses import dataclass

import pytest
from agentarea_execution.activities.artifact_validation import validate_workspace_artifacts
from agentarea_execution.models import ArtifactValidationRequest


@dataclass
class _Object:
    path: str
    sha256: str = "a" * 64
    size: int = 10
    generation: int = 7


class _Repository:
    """Stands in for the durable WorkspaceRepository — only .list is consulted."""

    def __init__(self, objects: list[_Object]) -> None:
        self.objects = objects
        self.list_calls = 0

    async def list(self, workspace_id: str, task_id: str):
        self.list_calls += 1
        assert workspace_id == "workspace-1"
        assert task_id == "task-1"
        return self.objects


def _request(*paths: str) -> ArtifactValidationRequest:
    return ArtifactValidationRequest(
        workspace_id="workspace-1",
        task_id="task-1",
        workflow_id="workflow-1",
        declared_paths=list(paths),
    )


@pytest.mark.asyncio
async def test_no_declared_paths_passes() -> None:
    result = await validate_workspace_artifacts(
        _request(),
        repository=_Repository([_Object("notes.txt"), _Object("scratch.py", generation=4)]),
    )
    assert result.state == "passed"
    assert result.evidence == []
    # generation is the max across the durable objects
    assert result.generation == 7


@pytest.mark.asyncio
async def test_declared_artifact_present_in_manifest_passes_with_identity() -> None:
    result = await validate_workspace_artifacts(
        _request("reports/model.xlsx"),
        repository=_Repository([_Object("reports/model.xlsx", sha256="b" * 64, size=42)]),
    )
    assert result.state == "passed"
    assert [(e.path, e.validator, e.sha256, e.size) for e in result.evidence] == [
        ("reports/model.xlsx", "deliverable", "b" * 64, 42)
    ]


@pytest.mark.asyncio
async def test_declared_artifact_absent_from_durable_store_fails() -> None:
    # The file may exist only on the ephemeral sandbox disk (copy-out failed / over
    # quota / no pod routing); the barrier must NOT pass on that.
    result = await validate_workspace_artifacts(
        _request("reports/model.xlsx"),
        repository=_Repository([_Object("some_other_file.txt")]),
    )
    assert result.state == "failed"
    assert result.issues[0].path == "reports/model.xlsx"
    assert result.issues[0].code == "artifact_missing"
    assert "durable task workspace" in result.issues[0].message


@pytest.mark.asyncio
async def test_declared_artifact_without_content_hash_fails() -> None:
    result = await validate_workspace_artifacts(
        _request("out.pdf"),
        repository=_Repository([_Object("out.pdf", sha256="")]),
    )
    assert result.state == "failed"
    assert result.issues[0].code == "artifact_missing_identity"


@pytest.mark.asyncio
async def test_absolute_workspace_path_is_normalized_to_root_relative_key() -> None:
    # The agent should not have to know the sandbox root prefix; a declared
    # /workspace/foo resolves to the same durable key foo.
    result = await validate_workspace_artifacts(
        _request("/workspace/cash_runway.xlsx"),
        repository=_Repository([_Object("cash_runway.xlsx", sha256="c" * 64, size=7)]),
    )
    assert result.state == "passed"
    assert result.evidence[0].path == "cash_runway.xlsx"


@pytest.mark.asyncio
async def test_relative_workspace_prefix_is_a_real_directory_not_stripped() -> None:
    # A leading RELATIVE "workspace/" is a genuine top-level dir, not the sandbox
    # root; it must match the canonical stored key rather than be stripped.
    result = await validate_workspace_artifacts(
        _request("workspace/report.xlsx"),
        repository=_Repository([_Object("workspace/report.xlsx", sha256="e" * 64)]),
    )
    assert result.state == "passed"
    assert result.evidence[0].path == "workspace/report.xlsx"


@pytest.mark.asyncio
async def test_traversal_path_is_rejected() -> None:
    result = await validate_workspace_artifacts(
        _request("../../etc/passwd"),
        repository=_Repository([_Object("cash_runway.xlsx")]),
    )
    assert result.state == "failed"
    assert result.issues[0].code == "invalid_artifact_path"


@pytest.mark.asyncio
async def test_one_missing_among_several_declared_fails_the_whole_barrier() -> None:
    result = await validate_workspace_artifacts(
        _request("a.xlsx", "b.pptx", "/workspace/c.docx"),
        repository=_Repository(
            [_Object("a.xlsx", sha256="1" * 64), _Object("c.docx", sha256="3" * 64)]
        ),
    )
    assert result.state == "failed"
    # a.xlsx and c.docx are present (evidence), b.pptx is the missing one
    assert {e.path for e in result.evidence} == {"a.xlsx", "c.docx"}
    assert [i.path for i in result.issues] == ["b.pptx"]
    assert result.issues[0].code == "artifact_missing"


@pytest.mark.asyncio
async def test_duplicate_declared_paths_are_deduped() -> None:
    repository = _Repository([_Object("r.xlsx", sha256="d" * 64)])
    result = await validate_workspace_artifacts(
        _request("r.xlsx", "./r.xlsx", "/workspace/r.xlsx"),
        repository=repository,
    )
    assert result.state == "passed"
    assert len(result.evidence) == 1
    assert repository.list_calls == 1


@pytest.mark.asyncio
async def test_empty_durable_store_with_declared_artifact_fails_at_generation_zero() -> None:
    result = await validate_workspace_artifacts(
        _request("model.xlsx"),
        repository=_Repository([]),
    )
    assert result.state == "failed"
    assert result.generation == 0
    assert result.issues[0].code == "artifact_missing"
