"""Completion barrier: the files a task promises are persisted before it is done.

Content validity is the task/eval layer's call, not the runtime's. The one
guarantee kept here is that whatever the final answer says it delivers actually
leaves the sandbox before the sandbox goes away.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from agentarea_common.artifacts import WorkspaceValidationError, normalize_workspace_path

from ..models import (
    ArtifactValidationEvidence,
    ArtifactValidationIssue,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CapabilityUnavailableResult,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize_declared(raw_path: str) -> str:
    """Map a declared path to its root-relative task-workspace key.

    Agents commonly declare an absolute ``/workspace/foo`` path; the sandbox root
    is not a prefix the agent should have to know, so treat these as
    workspace-relative rather than rejecting them as a traversal escape.
    """
    candidate = str(raw_path).strip()
    # Only strip the ABSOLUTE sandbox-root prefix and a leading ``./``. A leading
    # RELATIVE ``workspace/`` must be preserved — it is a real top-level directory
    # and matches the canonical key the write sink stores; stripping it would make
    # a genuinely-delivered ``workspace/foo`` look missing (or alias a same-named
    # root file).
    for prefix in ("/workspace/", "./"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break
    return normalize_workspace_path(candidate)


def _artifact_store_unavailable(message: str) -> ArtifactValidationResult:
    return ArtifactValidationResult(
        state="unavailable",
        generation=0,
        capability_unavailable=CapabilityUnavailableResult(capability="published_artifact_store"),
        issues=[
            ArtifactValidationIssue(
                path="",
                validator="published_artifact",
                code="capability_unavailable",
                message=message,
            )
        ],
    )


async def validate_published_artifacts(
    request: ArtifactValidationRequest,
    *,
    manager_url: str,
    auth_secret: str,
    http_client: Any = None,
) -> ArtifactValidationResult:
    """Persist the files a completion delivers, then report their identity."""
    declared: list[str] = []
    for raw_path in request.declared_paths:
        try:
            path = _normalize_declared(raw_path)
        except WorkspaceValidationError as exc:
            return ArtifactValidationResult(
                state="failed",
                generation=0,
                issues=[
                    ArtifactValidationIssue(
                        path=str(raw_path),
                        validator="published_artifact",
                        code="invalid_artifact_path",
                        message=str(exc),
                    )
                ],
            )
        if path not in declared:
            declared.append(path)
    if not declared:
        return ArtifactValidationResult(state="passed", generation=0)
    if not manager_url or not auth_secret:
        return _artifact_store_unavailable("artifact store authentication is not configured")

    client = http_client
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=60)
    issues: list[ArtifactValidationIssue] = []
    evidence: list[ArtifactValidationEvidence] = []
    try:
        for path in declared:
            try:
                response = await client.post(
                    f"{manager_url.rstrip('/')}/sandbox/artifacts",
                    json={
                        "workspace_id": request.workspace_id,
                        "task_id": request.task_id,
                        "path": path,
                    },
                    headers={"Authorization": f"Bearer {auth_secret}"},
                )
            except httpx.RequestError:
                return _artifact_store_unavailable("artifact store could not be reached")
            outcome = _artifact_publication_outcome(path, response)
            if isinstance(outcome, ArtifactValidationResult):
                return outcome
            if isinstance(outcome, ArtifactValidationIssue):
                issues.append(outcome)
            else:
                evidence.append(outcome)
    finally:
        if owned:
            await client.aclose()

    if issues:
        return ArtifactValidationResult(
            state="failed", generation=0, evidence=evidence, issues=issues
        )
    return ArtifactValidationResult(state="passed", generation=0, evidence=evidence)


def _artifact_publication_outcome(
    path: str, response: Any
) -> ArtifactValidationEvidence | ArtifactValidationIssue | ArtifactValidationResult:
    """Classify one publication response: evidence, agent-repairable, or blocked."""
    if response.status_code == 404:
        return ArtifactValidationIssue(
            path=path,
            validator="published_artifact",
            code="artifact_missing",
            message=(
                "the response declares this file but it is not in the workspace; "
                "write it before completing, or drop it from artifacts"
            ),
        )
    if response.status_code == 413:
        return ArtifactValidationIssue(
            path=path,
            validator="published_artifact",
            code="artifact_quota_exceeded",
            message="declared file exceeds the task artifact quota",
        )
    if response.status_code != 201:
        return _artifact_store_unavailable(
            f"artifact store returned HTTP {response.status_code} for {path}"
        )
    try:
        item = response.json()
        sha256 = str(item["sha256"])
        size = item["size"]
    except (TypeError, ValueError, KeyError):
        return _artifact_store_unavailable("artifact store returned an invalid response")
    if not _SHA256_RE.fullmatch(sha256) or not isinstance(size, int) or size < 0:
        return _artifact_store_unavailable(f"published artifact {path} has no valid identity")
    return ArtifactValidationEvidence(
        path=path,
        validator="published_artifact",
        sha256=sha256,
        size=size,
    )
