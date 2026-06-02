from typing import Any, cast
from uuid import UUID


class BaseCrudService[T]:
    def __init__(self, repository: Any):
        self.repository = repository

    async def get(self, id: UUID) -> T | None:
        """Get an entity by ID."""
        return await self.repository.get(id)

    async def list(self) -> list[T]:
        """List all entities in the workspace.

        Returns all resources within the current workspace scope.
        Access control should be handled by authorization layer.
        """
        # Check if repository supports workspace scoping
        if hasattr(self.repository, "list_all"):
            return await self.repository.list_all()
        else:
            # Fallback for repositories that don't support workspace scoping
            return await self.repository.list()

    async def create(self, entity: T) -> T:
        """Create a new entity."""
        # Check if repository is workspace-scoped (expects kwargs)
        if hasattr(self.repository, "create") and hasattr(self.repository.create, "__code__"):
            # Extract entity attributes as kwargs for the repository
            entity_dict = cast(Any, entity).to_dict()
            return await self.repository.create(**entity_dict)
        else:
            # Fallback for repositories that expect entity objects
            return await self.repository.create(entity)

    async def update(self, entity: T) -> T:
        """Update an existing entity."""
        # Check if repository has update_from_entity (WorkspaceScopedRepository)
        if hasattr(self.repository, "update_from_entity"):
            return await self.repository.update_from_entity(entity)
        else:
            # Fallback for BaseRepository
            return await self.repository.update(entity)

    async def delete(self, id: UUID) -> bool:
        """Delete an entity by ID."""
        return await self.repository.delete(id)
