"""Completion guards: declarative checks a task clears before it can claim done.

Prior art (Claude Code, OpenCode, Google ADK, AWS AgentCore, OpenAI, Devin) is
unanimous: no platform gates completion on a platform-side artifact-validity
probe — the filesystem / artifact store is the source of truth and saving is an
explicit agent action, with any real verification pushed OUT to user-owned CI.
We follow that default. What we keep is a thin, OPTIONAL guard layer so a task
with an explicit contract can assert it before completing.

Guards evaluate against the DURABLE task workspace — the manifest the ``/files``
API serves — never the ephemeral sandbox ``/workspace``. A file that exists only
in the sandbox was never made durable (copy-out failed / over quota / no pod
routing); a guard that consulted the sandbox would pass in exactly the cases
where the deliverable is about to vanish, making copy-before-claim
unrepresentable.

Active guard: ``deliverable`` — a declared deliverable must be present and
identified in the durable workspace (catches copy-out failure or a hallucinated
file). Seam: ``goal`` — judging the deliverable against a task-defined goal —
deliberately inert until goals carry a spec (that spec is task/eval-owned, never
a format probe baked into the runtime).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentarea_common.artifacts import (
    WorkspaceRepository,
    WorkspaceValidationError,
    normalize_workspace_path,
)

from ..models import (
    ArtifactValidationEvidence,
    ArtifactValidationIssue,
    ArtifactValidationRequest,
    ArtifactValidationResult,
)


@dataclass
class GuardOutcome:
    """One guard's contribution to the completion decision."""

    issues: list[ArtifactValidationIssue] = field(default_factory=list)
    evidence: list[ArtifactValidationEvidence] = field(default_factory=list)


class Guard(Protocol):
    """A completion guard: pure over the durable snapshot, side-effect free."""

    name: str

    def evaluate(
        self,
        request: ArtifactValidationRequest,
        objects_by_path: Mapping[str, Any],
    ) -> GuardOutcome: ...


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


class DeliverableGuard:
    """Every declared deliverable must be durable in the task workspace."""

    name = "deliverable"

    def evaluate(
        self,
        request: ArtifactValidationRequest,
        objects_by_path: Mapping[str, Any],
    ) -> GuardOutcome:
        outcome = GuardOutcome()
        declared: list[str] = []
        for raw_path in request.declared_paths:
            path = _normalize_declared(raw_path)  # may raise WorkspaceValidationError
            if path not in declared:
                declared.append(path)

        for path in declared:
            obj = objects_by_path.get(path)
            if obj is None:
                outcome.issues.append(
                    ArtifactValidationIssue(
                        path=path,
                        validator="deliverable",
                        code="artifact_missing",
                        message=(
                            "declared deliverable is not in the durable task workspace; "
                            "write it to your working directory so it is captured"
                        ),
                    )
                )
                continue
            sha256 = str(getattr(obj, "sha256", "") or "")
            if not sha256:
                outcome.issues.append(
                    ArtifactValidationIssue(
                        path=path,
                        validator="deliverable",
                        code="artifact_missing_identity",
                        message="durable deliverable has no recorded content hash",
                    )
                )
                continue
            outcome.evidence.append(
                ArtifactValidationEvidence(
                    path=path,
                    validator="deliverable",
                    sha256=sha256,
                    size=int(getattr(obj, "size", 0) or 0),
                )
            )
        return outcome


class GoalGuard:
    """Seam for judging the deliverable against a task-defined goal.

    Inert until goals carry an explicit, task-owned spec (criteria / judge). It is
    intentionally NOT a format probe: whether the content meets the goal is the
    task/eval layer's call, not the runtime's. Kept out of the default guard set
    so completion stays persist-and-trust until a goal spec actually exists.
    """

    name = "goal"

    def evaluate(
        self,
        request: ArtifactValidationRequest,
        objects_by_path: Mapping[str, Any],
    ) -> GuardOutcome:
        return GuardOutcome()


DEFAULT_GUARDS: tuple[Guard, ...] = (DeliverableGuard(),)


async def validate_workspace_artifacts(
    request: ArtifactValidationRequest,
    *,
    repository: WorkspaceRepository,
    guards: tuple[Guard, ...] = DEFAULT_GUARDS,
) -> ArtifactValidationResult:
    """Run the completion guards over the durable task workspace and aggregate."""
    objects = await repository.list(request.workspace_id, request.task_id)
    generation = max((item.generation for item in objects), default=0)
    objects_by_path = {obj.path: obj for obj in objects}

    issues: list[ArtifactValidationIssue] = []
    evidence: list[ArtifactValidationEvidence] = []
    for guard in guards:
        try:
            outcome = guard.evaluate(request, objects_by_path)
        except WorkspaceValidationError as exc:
            return ArtifactValidationResult(
                state="failed",
                generation=generation,
                issues=[
                    ArtifactValidationIssue(
                        path="",
                        validator=guard.name,
                        code="invalid_artifact_path",
                        message=str(exc),
                    )
                ],
            )
        issues.extend(outcome.issues)
        evidence.extend(outcome.evidence)

    if issues:
        return ArtifactValidationResult(
            state="failed", generation=generation, evidence=evidence, issues=issues
        )
    return ArtifactValidationResult(state="passed", generation=generation, evidence=evidence)
