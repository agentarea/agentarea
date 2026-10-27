"""Task definition persistence, scoped to the caller's workspace."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.task_definitions import TaskDefinition
from .orm import TaskDefinitionORM


def _to_domain(row: TaskDefinitionORM) -> TaskDefinition:
    return TaskDefinition(
        id=row.id,
        name=row.name,
        description=row.description,
        agent_id=row.agent_id,
        parameters=row.parameters or {},
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TaskDefinitionRepository(WorkspaceScopedRepository[TaskDefinitionORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskDefinitionORM, user_context)

    async def get_definition(self, definition_id: UUID) -> TaskDefinition | None:
        row = await self.get_by_id(definition_id)
        return _to_domain(row) if row is not None else None

    async def list_definitions(
        self, *, agent_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[TaskDefinition]:
        filters: dict[str, Any] = {"agent_id": agent_id} if agent_id is not None else {}
        rows = await self.list_all(limit=limit, offset=offset, **filters)
        return [_to_domain(row) for row in rows]

    async def create_definition(
        self, *, name: str, description: str, agent_id: UUID, parameters: dict[str, Any]
    ) -> TaskDefinition:
        row = await self.create(
            name=name, description=description, agent_id=agent_id, parameters=parameters
        )
        return _to_domain(row)

    async def update_definition(self, definition_id: UUID, **changes: Any) -> TaskDefinition | None:
        row = await self.update(definition_id, **changes)
        return _to_domain(row) if row is not None else None
