"""Example demonstrating how to use the RepositoryFactory pattern.

This example shows how services can use the RepositoryFactory to create
workspace-scoped repositories with proper user context injection.
"""

from typing import List
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .repository_factory import RepositoryFactory
from .workspace_scoped_repository import WorkspaceScopedRepository
from ..auth.context import UserContext


# Example domain model (would be in your domain layer)
class ExampleEntity:
    def __init__(self, id: UUID, name: str, description: str = None):
        self.id = id
        self.name = name
        self.description = description


# Example repository (would be in your infrastructure layer)
class ExampleRepository(WorkspaceScopedRepository):
    """Example repository using WorkspaceScopedRepository."""
    
    def __init__(self, session: AsyncSession, model_class, user_context: UserContext):
        super().__init__(session, model_class, user_context)
    
    async def find_by_name(self, name: str):
        """Custom method to find entity by name."""
        return await self.find_one_by(name=name)
    
    async def get_user_created_entities(self) -> List:
        """Get entities created by the current user."""
        return await self.list_all(creator_scoped=True)


# Example service using the factory pattern
class ExampleService:
    """Example service demonstrating factory pattern usage."""
    
    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
    
    async def create_entity(self, name: str, description: str = None) -> ExampleEntity:
        """Create a new entity using the factory-created repository."""
        # Create repository instance with user context
        repo = self.repository_factory.create_repository(ExampleRepository)
        
        # Use the repository (user context is automatically injected)
        entity_orm = await repo.create(name=name, description=description)
        
        # Convert to domain model
        return ExampleEntity(
            id=entity_orm.id,
            name=entity_orm.name,
            description=entity_orm.description
        )
    
    async def get_entity(self, entity_id: UUID) -> ExampleEntity:
        """Get an entity by ID (workspace-scoped)."""
        repo = self.repository_factory.create_repository(ExampleRepository)
        entity_orm = await repo.get_by_id(entity_id)
        
        if not entity_orm:
            return None
        
        return ExampleEntity(
            id=entity_orm.id,
            name=entity_orm.name,
            description=entity_orm.description
        )
    
    async def list_workspace_entities(self) -> List[ExampleEntity]:
        """List all entities in the current workspace."""
        repo = self.repository_factory.create_repository(ExampleRepository)
        entity_orms = await repo.list_all()
        
        return [
            ExampleEntity(id=orm.id, name=orm.name, description=orm.description)
            for orm in entity_orms
        ]
    
    async def list_my_entities(self) -> List[ExampleEntity]:
        """List entities created by the current user."""
        repo = self.repository_factory.create_repository(ExampleRepository)
        entity_orms = await repo.get_user_created_entities()
        
        return [
            ExampleEntity(id=orm.id, name=orm.name, description=orm.description)
            for orm in entity_orms
        ]


# FastAPI endpoint example
async def example_endpoint_with_factory(
    repository_factory: RepositoryFactory = Depends()  # Would use RepositoryFactoryDep
):
    """Example FastAPI endpoint using the repository factory."""
    service = ExampleService(repository_factory)
    
    # Create an entity
    entity = await service.create_entity("Example Entity", "Created via factory")
    
    # List all workspace entities
    workspace_entities = await service.list_workspace_entities()
    
    # List only user's entities
    my_entities = await service.list_my_entities()
    
    return {
        "created_entity": entity,
        "workspace_entities_count": len(workspace_entities),
        "my_entities_count": len(my_entities)
    }


# Alternative pattern: Direct factory usage in endpoints
async def direct_factory_usage_example(
    repository_factory: RepositoryFactory = Depends()  # Would use RepositoryFactoryDep
):
    """Example of using the factory directly in an endpoint."""
    # Create repository directly
    repo = repository_factory.create_repository(ExampleRepository)
    
    # Use repository methods
    entities = await repo.list_all()
    my_entities = await repo.list_all(creator_scoped=True)
    
    return {
        "all_workspace_entities": len(entities),
        "my_entities": len(my_entities),
        "user_context": {
            "user_id": repo.user_context.user_id,
            "workspace_id": repo.user_context.workspace_id
        }
    }


# Benefits of the factory pattern:
"""
1. **Automatic Context Injection**: User context is automatically injected into repositories
2. **Consistent Interface**: All repositories follow the same creation pattern
3. **Easy Testing**: Factory can be mocked for unit tests
4. **Workspace Isolation**: All repositories automatically enforce workspace boundaries
5. **Type Safety**: Factory ensures repositories are created with correct types
6. **Dependency Injection**: Works seamlessly with FastAPI's DI system

Usage in your services:
1. Accept RepositoryFactory as a dependency
2. Use factory.create_repository(RepositoryClass, ModelClass) to create repositories
3. Repositories automatically have user context and workspace filtering
4. No need to manually pass user context to each repository
"""