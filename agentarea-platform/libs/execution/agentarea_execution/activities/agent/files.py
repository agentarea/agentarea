"""Sandbox files: the completion artifact barrier and skill materialization."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import (
    ArtifactValidationRequest,
    ArtifactValidationResult,
    MaterializeSkillFilesRequest,
    MaterializeSkillFilesResult,
)
from ..artifact_validation import validate_published_artifacts
from .sandbox import agent_artifact_actor, sandbox_file_auth_secret

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def make_files_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn(name="validate_artifacts_activity")
    async def validate_artifacts_activity(
        request: ArtifactValidationRequest,
    ) -> ArtifactValidationResult:
        """Completion barrier: persist the declared files before the task is done."""
        if not request.declared_paths:
            return ArtifactValidationResult(state="passed", generation=0)
        return await validate_published_artifacts(
            request,
            manager_url=dependencies.settings.mcp.MCP_MANAGER_URL,
            auth_secret=sandbox_file_auth_secret(dependencies),
        )

    @activity.defn(name="materialize_skill_files_activity")
    async def materialize_skill_files_activity(
        request: MaterializeSkillFilesRequest,
    ) -> MaterializeSkillFilesResult:
        """Copy a skill's bundle into the task's sandbox workspace.

        The sandbox workspace persists for the life of the workflow, so the
        bundle is uploaded once at activation and stays on disk for every later
        shell call. A skill carrying only prose is still a bundle — its text is
        written as SKILL.md, so there is one kind of skill, not two.
        """
        from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
        from agentarea_common.artifacts import DbArtifactEventRecorder, WorkspaceRepository

        from ..skill_materialization import (
            assemble_skill_bundle,
            build_skill_workspace_files,
            skill_workspace_dir,
        )

        try:
            if not request.workspace_id:
                raise ValueError("skill materialization requires a workspace_id")
            user_context = create_user_context(request.user_context_data)
            async with ActivityContext(container, user_context) as ctx:
                skill_service = await ctx.get_skill_service()
                skill = await skill_service.get_with_catalog(request.skill_id)
                if not skill:
                    return MaterializeSkillFilesResult(
                        success=False, error=f"Skill {request.skill_id} not found"
                    )

                # A skill is a folder. Files may be absent, prose may be absent,
                # but the folder always gets a manifest — there is one kind of
                # skill, not a "content-only" second kind.
                bundled: list[tuple[str, bytes]] = []
                if skill.s3_path:
                    storage_service = SkillStorageService()
                    for info in await storage_service.list_files(skill.s3_path):
                        relative_path = getattr(info, "path", None) or getattr(info, "name", "")
                        if not relative_path:
                            continue
                        bundled.append(
                            (
                                relative_path,
                                await storage_service.get_file_content(
                                    skill.s3_path, relative_path
                                ),
                            )
                        )

                files = assemble_skill_bundle(skill.content, bundled)
                workspace_files = build_skill_workspace_files(
                    request.skill_name, str(request.skill_id), files
                )
                if not workspace_files:
                    return MaterializeSkillFilesResult(
                        success=False,
                        error=f"Skill '{request.skill_name}' bundle contained no usable paths",
                    )

                if not request.workspace_id or not request.task_id:
                    return MaterializeSkillFilesResult(
                        success=False,
                        error="workspace_id and task_id are required for skill materialization",
                    )
                repository = WorkspaceRepository(
                    recorder=DbArtifactEventRecorder(),
                    actor=agent_artifact_actor(request, user_context),
                )
                await repository.put_files(
                    str(request.workspace_id),
                    str(request.task_id),
                    workspace_files,
                    provenance={
                        "source": "skill",
                        "skill_id": str(request.skill_id),
                        "skill_name": request.skill_name,
                    },
                    owner=request.workflow_id or None,
                )

                directory = skill_workspace_dir(request.skill_name, str(request.skill_id))
                return MaterializeSkillFilesResult(
                    success=True,
                    directory=directory,
                    paths=list(workspace_files),
                )

        except Exception as e:
            logger.error(f"Skill materialization error: {e}", exc_info=True)
            return MaterializeSkillFilesResult(
                success=False, error=f"Failed to materialize skill files: {e}"
            )

    return [
        validate_artifacts_activity,
        materialize_skill_files_activity,
    ]
