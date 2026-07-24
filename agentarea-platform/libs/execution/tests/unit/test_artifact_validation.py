import json
import subprocess
from dataclasses import dataclass

import pytest
from agentarea_execution.activities.artifact_validation import (
    _build_validator_command,
    validate_workspace_artifacts,
)
from agentarea_execution.models import (
    ArtifactValidationRequest,
    RuntimeDiscoveryResult,
    RuntimeManifest,
)


@dataclass
class _Object:
    path: str
    sha256: str = "a" * 64
    size: int = 10
    generation: int = 7
    object_uri: str = "s3://artifacts/workspaces/workspace-1/tasks/task-1/objects/object"


class _Repository:
    def __init__(self, paths: list[str]) -> None:
        self.objects = [_Object(path) for path in paths]

    async def list(self, workspace_id: str, task_id: str):
        assert workspace_id == "workspace-1"
        assert task_id == "task-1"
        return self.objects

    async def current_manifest_ref(self, workspace_id: str, task_id: str):
        assert workspace_id == "workspace-1"
        assert task_id == "task-1"
        return type("ManifestRef", (), {"generation": 7})()


class _ChangingRepository(_Repository):
    def __init__(self) -> None:
        super().__init__(["src/main.py"])
        self.list_calls = 0

    async def list(self, workspace_id: str, task_id: str):
        self.list_calls += 1
        objects = await super().list(workspace_id, task_id)
        if self.list_calls > 1:
            return [_Object("src/main.py", sha256="b" * 64)]
        return objects


def _runtime(*, browser: str = "none") -> RuntimeDiscoveryResult:
    return RuntimeDiscoveryResult(
        manifest=RuntimeManifest.model_validate(
            {
                "schema_version": 1,
                "image_version": "runtime-test",
                "managed_environment": "mutable",
                "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
                "node": {"version": "v22.0.0", "npm_version": "10.0.0"},
                "packages": {
                    "openpyxl": "3.1.5",
                    "python-docx": "1.2.0",
                    "python-pptx": "1.0.2",
                    "pypdf": "5.9.0",
                },
                "features": {
                    "browser": browser,
                    "managed_environment_mutation": True,
                    "arbitrary_workspace_code": True,
                },
            }
        )
    )


def _request(*paths: str) -> ArtifactValidationRequest:
    return ArtifactValidationRequest(
        workspace_id="workspace-1",
        task_id="task-1",
        workflow_id="workflow-1",
        declared_paths=list(paths),
    )


@pytest.mark.asyncio
async def test_no_artifacts_is_explicit_and_does_not_schedule_sandbox() -> None:
    calls: list[str] = []

    async def execute(command: str):
        calls.append(command)
        return {"success": True, "result": "{}"}

    result = await validate_workspace_artifacts(
        _request(),
        repository=_Repository(
            ["inputs/attachments/source.py", "skills/report/render.py", "notes.txt"]
        ),
        runtime=_runtime(),
        execute_in_sandbox=execute,
    )

    assert result.state == "no_artifacts"
    assert result.generation == 7
    assert calls == []


@pytest.mark.asyncio
async def test_missing_declared_artifact_fails_before_sandbox() -> None:
    async def execute(_: str):
        raise AssertionError("sandbox must not be called")

    result = await validate_workspace_artifacts(
        _request("reports/missing.xlsx"),
        repository=_Repository([]),
        runtime=_runtime(),
        execute_in_sandbox=execute,
    )

    assert result.state == "failed"
    assert result.issues[0].code == "artifact_missing"
    assert result.issues[0].path == "reports/missing.xlsx"


@pytest.mark.asyncio
async def test_html_fails_closed_when_browser_capability_is_absent() -> None:
    async def execute(_: str):
        raise AssertionError("sandbox must not be called")

    result = await validate_workspace_artifacts(
        _request(),
        repository=_Repository(["site/index.html"]),
        runtime=_runtime(browser="none"),
        execute_in_sandbox=execute,
    )

    assert result.state == "unavailable"
    assert result.capability_unavailable is not None
    assert result.capability_unavailable.capability == "browser"
    assert result.issues[0].validator == "playwright"


@pytest.mark.asyncio
async def test_known_artifacts_return_hash_only_evidence() -> None:
    commands: list[str] = []

    async def execute(command: str):
        commands.append(command)
        return {
            "success": True,
            "result": json.dumps(
                {
                    "results": [
                        {"path": "src/main.py", "validator": "py_compile", "status": "passed"},
                        {"path": "reports/q3.xlsx", "validator": "openpyxl", "status": "passed"},
                    ]
                }
            ),
        }

    result = await validate_workspace_artifacts(
        _request(),
        repository=_Repository(["src/main.py", "reports/q3.xlsx"]),
        runtime=_runtime(),
        execute_in_sandbox=execute,
    )

    assert result.state == "passed"
    assert [item.path for item in result.evidence] == ["src/main.py", "reports/q3.xlsx"]
    assert all(item.sha256 == "a" * 64 for item in result.evidence)
    assert len(commands) == 1
    assert "py_compile.compile" in commands[0]
    assert "load_workbook" in commands[0]


@pytest.mark.asyncio
async def test_declared_paths_are_unioned_with_all_other_eligible_artifacts() -> None:
    selected: list[str] = []

    async def execute(command: str):
        assert "inputs/ignored.py" not in command
        assert '"reports/declared.xlsx"' in command
        assert '"src/undeclared.py"' in command
        selected.extend(["reports/declared.xlsx", "src/undeclared.py"])
        return {
            "success": True,
            "result": json.dumps(
                {
                    "results": [
                        {
                            "path": path,
                            "validator": "openpyxl" if path.endswith(".xlsx") else "py_compile",
                            "status": "passed",
                        }
                        for path in selected
                    ]
                }
            ),
        }

    result = await validate_workspace_artifacts(
        _request("reports/declared.xlsx"),
        repository=_Repository(
            ["reports/declared.xlsx", "src/undeclared.py", "inputs/ignored.py"]
        ),
        runtime=_runtime(),
        execute_in_sandbox=execute,
    )

    assert result.state == "passed"
    assert [item.path for item in result.evidence] == selected


@pytest.mark.asyncio
async def test_validation_rejects_artifact_identity_change_during_sandbox_run() -> None:
    async def execute(_: str):
        return {
            "success": True,
            "result": json.dumps(
                {
                    "results": [
                        {"path": "src/main.py", "validator": "py_compile", "status": "passed"}
                    ]
                }
            ),
        }

    with pytest.raises(RuntimeError, match="changed during validation"):
        await validate_workspace_artifacts(
            _request(),
            repository=_ChangingRepository(),
            runtime=_runtime(),
            execute_in_sandbox=execute,
        )


@pytest.mark.asyncio
async def test_invalid_artifact_returns_actionable_repair_issue() -> None:
    async def execute(_: str):
        return {
            "success": True,
            "result": json.dumps(
                {
                    "results": [
                        {
                            "path": "src/main.py",
                            "validator": "py_compile",
                            "status": "failed",
                            "code": "validation_failed",
                            "message": "invalid syntax",
                        }
                    ]
                }
            ),
        }

    result = await validate_workspace_artifacts(
        _request("src/main.py"),
        repository=_Repository(["src/main.py"]),
        runtime=_runtime(),
        execute_in_sandbox=execute,
    )

    assert result.state == "failed"
    assert result.issues[0].message == "invalid syntax"


@pytest.mark.asyncio
async def test_sandbox_cannot_omit_a_selected_artifact_result() -> None:
    async def execute(_: str):
        return {"success": True, "result": json.dumps({"results": []})}

    with pytest.raises(RuntimeError, match="omitted artifact results"):
        await validate_workspace_artifacts(
            _request("src/main.py"),
            repository=_Repository(["src/main.py"]),
            runtime=_runtime(),
            execute_in_sandbox=execute,
        )


def test_python_failure_does_not_echo_artifact_source_bytes(tmp_path) -> None:
    canary = "UNIQUE_FILE_BODY_CANARY_73df"
    (tmp_path / "broken.py").write_text(f"if {canary}\n", encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - fixed validator command under test
        ["/bin/bash", "-c", _build_validator_command(["broken.py"], browser_available=False)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert canary not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["results"][0]["status"] == "failed"
