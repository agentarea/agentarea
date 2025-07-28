"""Example showing how to migrate from direct repository creation to factory pattern.

This demonstrates the benefits of using RepositoryFactory for dependency injection.
"""

from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .repository_factory import RepositoryFactory
from ..auth.context import UserContext


# === BEFORE: Direct repository creation (current pattern) ===

async def get_task_service_old_pattern(
    db_session: AsyncSession,
    user_context: UserContext,
    event_broker,
) -> "TaskService":
    """Old pattern: Create repositories directly in service factory."""
    from agentarea_tasks.infrastructure.repository import TaskRepository
    from agentarea_agents.infrastructure.repository import AgentRepository
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager
    
    # Create repositories manually
    task_repository = TaskRepository(db_session, user_context)
    agent_repository = AgentRepository(db_session, user_context)
    
    # Create other dependencies
    task_manager = TemporalTaskManager(task_repository)
    
    return TaskService(
        task_repository=task_repository,
        event_broker=event_broker,
        task_manager=task_manager,
        agent_repository=agent_repository,
    )


# === AFTER: Using RepositoryFactory (new pattern) ===

async def get_task_service_new_pattern(
    repository_factory: RepositoryFactory,
    event_broker,
) -> "TaskService":
    """New pattern: Use factory to create repositories."""
    from agentarea_tasks.infrastructure.repository import TaskRepository
    from agentarea_agents.infrastructure.repository import AgentRepository
    from agentarea_tasks.infrastructure.orm import TaskORM
    from agentarea_agents.domain.models import Agent
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager
    
    # Create repositories using factory (user context automatically injected)
    task_repository = repository_factory.create_repository(TaskRepository)
    agent_repository = repository_factory.create_repository(AgentRepository)
    
    # Create other dependencies
    task_manager = TemporalTaskManager(task_repository)
    
    return TaskService(
        task_repository=task_repository,
        event_broker=event_broker,
        task_manager=task_manager,
        agent_repository=agent_repository,
    )


# === Service that uses multiple repositories ===

class MultiRepositoryService:
    """Example service that uses multiple repositories."""
    
    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
    
    async def complex_operation(self):
        """Example operation that needs multiple repositories."""
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_agents.infrastructure.repository import AgentRepository
        from agentarea_triggers.infrastructure.repository import TriggerRepository
        from agentarea_tasks.infrastructure.orm import TaskORM
        from agentarea_agents.domain.models import Agent
        from agentarea_triggers.infrastructure.orm import TriggerORM
        
        # Create all needed repositories with same user context
        task_repo = self.repository_factory.create_repository(TaskRepository)
        agent_repo = self.repository_factory.create_repository(AgentRepository)
        trigger_repo = self.repository_factory.create_repository(TriggerRepository)
        
        # All repositories automatically have the same user context
        # and enforce workspace isolation
        
        # Example: Get all workspace resources
        tasks = await task_repo.list_all()
        agents = await agent_repo.list_all()
        triggers = await trigger_repo.list_all()
        
        return {
            "tasks_count": len(tasks),
            "agents_count": len(agents),
            "triggers_count": len(triggers),
            "workspace_id": task_repo.user_context.workspace_id
        }


# === FastAPI dependency examples ===

# Old pattern: Multiple dependencies
async def old_endpoint(
    task_repo: Annotated["TaskRepository", Depends()],
    agent_repo: Annotated["AgentRepository", Depends()],
    trigger_repo: Annotated["TriggerRepository", Depends()],
):
    """Old pattern: Need separate dependency for each repository."""
    # Each repository dependency needs its own function
    pass


# New pattern: Single factory dependency
async def new_endpoint(
    repository_factory: Annotated[RepositoryFactory, Depends()],
):
    """New pattern: Single factory creates all repositories."""
    service = MultiRepositoryService(repository_factory)
    return await service.complex_operation()


# === Benefits of the factory pattern ===

"""
Benefits of using RepositoryFactory:

1. **Reduced Boilerplate**: 
   - Old: Need separate dependency function for each repository
   - New: Single factory creates all repositories

2. **Consistent Context**: 
   - All repositories automatically get the same user context
   - No risk of context mismatch between repositories

3. **Easier Testing**:
   - Mock single factory instead of multiple repository dependencies
   - Factory can create test repositories with test context

4. **Better Maintainability**:
   - Changes to repository constructor only affect factory
   - Services don't need to know about repository dependencies

5. **Type Safety**:
   - Factory ensures repositories are created with correct model types
   - Compile-time checking of repository/model compatibility

6. **Dependency Injection**:
   - Works seamlessly with FastAPI's DI system
   - Factory itself can be injected and configured

Example migration steps:
1. Replace individual repository dependencies with RepositoryFactoryDep
2. Update service constructors to accept factory instead of repositories
3. Use factory.create_repository() to create repositories as needed
4. Remove individual repository dependency functions
"""