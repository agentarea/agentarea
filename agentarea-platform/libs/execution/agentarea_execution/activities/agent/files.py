"""Sandbox files: the completion artifact barrier, and activating a skill."""

import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubRateLimitError,
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)
from agentarea_agents_sdk.skills.skill_toolset import wrap_skill_content
from agentarea_common.auth.context import UserContext
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from agentarea_tasks.domain.models import ConversationEntry
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from sqlalchemy.exc import DataError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...interfaces import ActivityDependencies
from ...models import (
    ActivateSkillRequest,
    ActivateSkillResult,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    MaterializeSkillFilesRequest,
    MaterializeSkillFilesResult,
)
from ...workflows.constants import TOKENS_PER_MESSAGE_OVERHEAD
from ...workflows.helpers import SEEN_URLS_LIMIT, external_urls
from ..artifact_validation import validate_published_artifacts
from ..heartbeat import auto_heartbeater
from .sandbox import agent_artifact_actor, sandbox_file_auth_secret

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)

SKILL_PREVIEW_CHARS = 2000


async def _put_skill_files(
    skill_service: Any,
    skill: Any,
    request: MaterializeSkillFilesRequest | ActivateSkillRequest,
    user_context: UserContext,
) -> tuple[str, list[str]]:
    """Copy a skill's package into the task's sandbox workspace; its directory and paths.

    The sandbox workspace persists for the life of the workflow, so the
    package is uploaded once at activation and stays on disk for every later
    shell call. A skill carrying only prose is still a package: its text is
    its SKILL.md, so there is one kind of skill, not two.
    """
    from agentarea_common.artifacts import DbArtifactEventRecorder, WorkspaceRepository

    from ..skill_materialization import (
        assemble_skill_bundle,
        build_skill_workspace_files,
        skill_workspace_dir,
    )

    if not request.workspace_id or not request.task_id:
        raise ValueError("workspace_id and task_id are required for skill materialization")
    bundled = list(
        (await skill_service.read_files(skill, at=getattr(request, "package", None))).items()
    )
    files = assemble_skill_bundle(None, bundled)
    workspace_files = build_skill_workspace_files(request.skill_name, str(request.skill_id), files)
    if not workspace_files:
        raise ValueError(f"Skill '{request.skill_name}' bundle contained no usable paths")
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
    return skill_workspace_dir(request.skill_name, str(request.skill_id)), list(workspace_files)


SKILL_FILES_LISTED = 50
_STORAGE_CODES = frozenset(
    {"SlowDown", "ServiceUnavailable", "InternalError", "RequestTimeout", "Throttling"}
)


def count_tokens(text: str) -> int:
    """The tokens of ``text`` by the tokenizer the model calls are metered with."""
    import litellm

    return int(litellm.token_counter(text=text)) if text else 0


def unreachable_service(error: BaseException) -> str | None:
    """The service an error says is unreachable, or None when it is not an outage.

    Only transport, storage and database connectivity are waited out; any other
    error is the skill's or the code's and is final.
    """
    seen: BaseException | None = error
    for _ in range(6):
        if seen is None:
            return None
        if isinstance(seen, ClientError):
            response = seen.response or {}
            status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0
            code = (response.get("Error") or {}).get("Code")
            if status >= 500 or code in _STORAGE_CODES:
                return "Object storage"
            return None
        if isinstance(seen, BotoConnectionError | HTTPClientError):
            return "Object storage"
        if isinstance(seen, OperationalError | InterfaceError | PoolTimeoutError):
            return "The database"
        if isinstance(seen, GitHubRateLimitError | httpx.TransportError):
            return "GitHub"
        if isinstance(seen, BotoCoreError):
            return None
        if isinstance(seen, ConnectionError | TimeoutError):
            return "A service"
        seen = seen.__cause__ or seen.__context__
    return None


def _files_note(directory: str, paths: list[str]) -> str:
    shown = paths[:SKILL_FILES_LISTED]
    listing = "\n".join(f"- {path}" for path in shown)
    if len(paths) > len(shown):
        listing += f"\n- ... and {len(paths) - len(shown)} more"
    return (
        f"This skill's files are in {directory}/ in your sandbox:\n{listing}\n"
        f'Run them with the shell tool, e.g. bash("python {directory}/<script>").'
    )


def skill_entry(
    name: str,
    body: str,
    *,
    max_tokens: int,
    directory: str,
    paths: list[str],
    pointer: str,
    count=count_tokens,
) -> tuple[str, bool]:
    """The activated skill's log entry, and whether it points at its SKILL.md instead.

    The entry is kept verbatim through every compaction, so it never takes
    more than ``max_tokens`` of the model's window, the file listing included.
    A larger SKILL.md is summarized: its size, where the agent reads it in
    full, and as much of its opening as fits.
    """
    notes = [
        _files_note(directory, paths),
        f"This skill's files are in {directory}/ in your sandbox.",
    ]
    notes = [*notes, ""] if directory else [""]
    for note in notes:
        content = wrap_skill_content(name, body) + (f"\n\n{note}" if note else "")
        if count(content) <= max_tokens:
            return content, False
    lead = (
        f"This skill's SKILL.md is {len(body):,} characters (about {count(body):,} tokens), "
        f"more than the {max_tokens:,} tokens its instructions may take in this run, so it "
        f"is not shown here in full. {pointer}"
    )
    for note in notes:
        suffix = f"\n\n{note}" if note else ""
        for preview_chars in (2000, 1000, 400, 0):
            opening = f"\n\nIt opens with:\n{body[:preview_chars]}\n[...]" if preview_chars else ""
            content = wrap_skill_content(name, lead + opening) + suffix
            if count(content) <= max_tokens:
                return content, True
    return wrap_skill_content(name, lead[: max(0, max_tokens * 2)]), True


def make_files_activities(
    dependencies: ActivityDependencies, container: ActivityServiceContainer
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
            manager_url=dependencies.settings.mcp.MANAGER_URL,
            auth_secret=sandbox_file_auth_secret(dependencies),
        )

    @activity.defn(name="activate_skill_activity")
    @auto_heartbeater
    async def activate_skill_activity(request: ActivateSkillRequest) -> ActivateSkillResult:
        """Activate a skill for a run: its SKILL.md goes into the task log, never into history.

        The install policy decides first, for an installed skill too. The body
        is read from the package the run was configured with (a catalog
        package from the in-process cache), the package is put in the sandbox,
        and the entry the model reads is written at the position the workflow
        reserved, under the id it chose, so a retry writes it once. Only an
        unreachable service (object storage, the database, GitHub) is retried;
        anything else is final and the model hears it as a tool error.
        """
        try:
            return await _activate_skill(request)
        except ApplicationError:
            raise
        except Exception as exc:
            service = unreachable_service(exc)
            if service is None:
                logger.error("Activating skill %s failed", request.skill_name, exc_info=True)
                raise ApplicationError(
                    f"Skill '{request.skill_name}' could not be activated: {exc}",
                    type="SkillActivationFailed",
                    non_retryable=True,
                ) from exc
            logger.warning(
                "%s is unreachable for skill %s", service, request.skill_name, exc_info=True
            )
            raise ApplicationError(
                f"{service} is unreachable: {exc}", {"service": service}, type="ServiceUnreachable"
            ) from exc

    async def _activate_skill(request: ActivateSkillRequest) -> ActivateSkillResult:
        name = request.skill_name
        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            skill_service = await ctx.get_skill_service()
            try:
                skill = await skill_service.get_with_catalog(request.skill_id, to_run=True)
            except CatalogInstallRefusedError as exc:
                raise ApplicationError(
                    f"Skill '{name}' cannot be activated: {exc}",
                    type="SkillActivationRefused",
                    non_retryable=True,
                ) from exc
            if skill is None:
                raise ApplicationError(
                    f"Skill '{name}' no longer exists", type="SkillNotFound", non_retryable=True
                )
            try:
                body = await skill_service.read_skill_md(skill, at=request.package)
            except (GitHubSourceGoneError, GitHubTreeMismatchError, ValueError) as exc:
                raise ApplicationError(
                    f"Skill '{name}' cannot be read: {exc}",
                    type="SkillUnreadable",
                    non_retryable=True,
                ) from exc

            directory, paths = "", []
            try:
                directory, paths = await _put_skill_files(
                    skill_service, skill, request, user_context
                )
            except Exception:
                # The instructions stand on their own; the agent works without the files.
                logger.warning(
                    "Could not put the files of skill %s in the sandbox", name, exc_info=True
                )

            if directory:
                pointer = (
                    f"Read it in full from {directory}/SKILL.md with the shell tool, e.g. "
                    f'bash("cat {directory}/SKILL.md").'
                )
            else:
                pointer = (
                    f'Read it with read_tool_output("{request.tool_call_id}"), or search it '
                    f'with read_tool_output("{request.tool_call_id}", grep="pattern").'
                )
            content, summarized = skill_entry(
                name,
                body,
                max_tokens=request.max_tokens,
                directory=directory,
                paths=paths,
                pointer=pointer,
            )
            if summarized and not directory:
                from ...workflows.context_store import ContextStore

                await ContextStore(request.workspace_id, request.task_id).store_output(
                    request.tool_call_id, body
                )

            entry = ConversationEntry(
                seq=request.seq,
                event_id=UUID(request.event_id),
                kind="message",
                role="tool",
                content=content,
                tool_call_id=request.tool_call_id,
                name="activate_skill",
                iteration=request.iteration,
                execution_id=request.execution_id,
            )
            try:
                await ctx.task_log().append(
                    UUID(request.task_id), [entry], execution_id=request.execution_id
                )
            except LookupError as gone:
                raise ApplicationError(str(gone), type="TaskNotFound", non_retryable=True) from gone
            except (DataError, IntegrityError) as refused:
                raise ApplicationError(
                    f"the task log refused skill '{name}': {refused.orig}",
                    type="TaskLogRejected",
                    non_retryable=True,
                ) from refused

        return ActivateSkillResult(
            chars=len(content),
            est_tokens=count_tokens(content) + TOKENS_PER_MESSAGE_OVERHEAD,
            summarized=summarized,
            urls=external_urls([SimpleNamespace(role="tool", content=body)])[:SEEN_URLS_LIMIT],
        )

    @activity.defn(name="materialize_skill_files_activity")
    async def materialize_skill_files_activity(
        request: MaterializeSkillFilesRequest,
    ) -> MaterializeSkillFilesResult:
        """Copy a skill's package into the sandbox (runs whose activation predates the log)."""
        try:
            if not request.workspace_id:
                raise ValueError("skill materialization requires a workspace_id")
            user_context = create_user_context(request.user_context_data)
            async with ActivityContext(container, user_context) as ctx:
                skill_service = await ctx.get_skill_service()
                skill = await skill_service.get_with_catalog(request.skill_id, to_run=True)
                if not skill:
                    return MaterializeSkillFilesResult(
                        success=False, error=f"Skill {request.skill_id} not found"
                    )
                directory, paths = await _put_skill_files(
                    skill_service, skill, request, user_context
                )
                return MaterializeSkillFilesResult(success=True, directory=directory, paths=paths)

        except Exception as e:
            logger.error(f"Skill materialization error: {e}", exc_info=True)
            return MaterializeSkillFilesResult(
                success=False, error=f"Failed to materialize skill files: {e}"
            )

    return [
        validate_artifacts_activity,
        activate_skill_activity,
        materialize_skill_files_activity,
    ]
