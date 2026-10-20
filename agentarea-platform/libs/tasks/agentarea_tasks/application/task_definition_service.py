"""Saved tasks: create, read, change, delete, and run one on demand."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.auth.permission import require_permission

from ..domain.models import AgentTask, TaskProvenance
from ..domain.task_definitions import (
    TaskDefinition,
    TaskDefinitionNotFoundError,
    TaskDefinitionValidationError,
)
from ..infrastructure.task_definition_repository import TaskDefinitionRepository
from ..schemas.dto import RunCreate, TaskDefinitionCreate, TaskDefinitionUpdate

if TYPE_CHECKING:
    from agentarea_common.base.repository_factory import RepositoryFactory

    from ..task_service import TaskService


class TaskDefinitionService:
    """Task definitions of the caller's workspace, and runs started from them."""

    def __init__(self, repository_factory: "RepositoryFactory", task_service: "TaskService"):
        from agentarea_agents.infrastructure.repository import AgentRepository

        self.repository_factory = repository_factory
        self.repository = repository_factory.create_repository(TaskDefinitionRepository)
        self.agent_repository = repository_factory.create_repository(AgentRepository)
        self.task_service = task_service

    async def _require_agent(self, agent_id: UUID) -> None:
        if await self.agent_repository.get(agent_id) is None:
            raise TaskDefinitionValidationError(
                f"Agent {agent_id} does not exist in this workspace"
            )

    @audited("task_definition.create", resource_type="task_definition")
    async def create(self, payload: TaskDefinitionCreate) -> TaskDefinition:
        await self._require_agent(payload.agent_id)
        return await self.repository.create_definition(
            name=payload.name,
            description=payload.description,
            agent_id=payload.agent_id,
            parameters=payload.parameters,
        )

    async def get(self, definition_id: UUID) -> TaskDefinition:
        definition = await self.repository.get_definition(definition_id)
        if definition is None:
            raise TaskDefinitionNotFoundError(definition_id)
        return definition

    async def list(self, *, agent_id: UUID | None = None, limit: int = 100) -> list[TaskDefinition]:
        return await self.repository.list_definitions(agent_id=agent_id, limit=limit)

    @audited(
        "task_definition.update", resource_type="task_definition", resource_id_param="definition_id"
    )
    async def update(self, definition_id: UUID, payload: TaskDefinitionUpdate) -> TaskDefinition:
        await self.get(definition_id)
        changes: dict[str, Any] = {
            field: value
            for field, value in payload.model_dump(exclude_unset=True).items()
            if value is not None
        }
        if "agent_id" in changes:
            await self._require_agent(changes["agent_id"])
        if not changes:
            return await self.get(definition_id)
        updated = await self.repository.update_definition(definition_id, **changes)
        if updated is None:
            raise TaskDefinitionNotFoundError(definition_id)
        return updated

    @audited(
        "task_definition.delete", resource_type="task_definition", resource_id_param="definition_id"
    )
    async def delete(self, definition_id: UUID) -> bool:
        return await self.repository.delete(definition_id)

    async def run(
        self,
        definition_id: UUID,
        *,
        parameters: dict[str, Any] | None = None,
        created_via: str = "api",
    ) -> AgentTask:
        """Start a run of the definition's agent, asked the definition's text.

        The caller must be allowed to run the agent; ``parameters`` are merged
        over the definition's own for this run only.
        """
        definition = await self.get(definition_id)
        user_context = self.repository_factory.user_context
        await require_permission("execute", "agent", str(definition.agent_id), user_context)
        payload = RunCreate(
            agent_id=definition.agent_id,
            description=definition.description,
            parameters={**definition.parameters, **(parameters or {})},
        )
        provenance = TaskProvenance.started_by(user_context.user_id, via_api_key=False)
        return await self.task_service.start_run(
            payload,
            workspace_id=user_context.workspace_id,
            user_id=user_context.user_id,
            created_via=created_via,
            provenance=provenance.model_copy(update={"task_definition_id": definition.id}),
        )
