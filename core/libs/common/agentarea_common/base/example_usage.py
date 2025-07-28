"""Example usage of RepositoryFactory in FastAPI endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .dependencies import RepositoryFactoryDep
from .repository_factory import RepositoryFactory
from ..auth.dependencies import UserContextDep
from ..auth.context import UserContext

# Example router showing how to use RepositoryFactory
router = APIRouter()


@router.get("/example-with-factory")
async def example_endpoint_with_factory(factory: RepositoryFactoryDep):
    """Example endpoint using RepositoryFactory.
    
    This shows how to use the factory to create repositories
    without manually passing session and user_context.
    """
    try:
        # Import repositories as needed
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_agents.infrastructure.repository import AgentRepository
        
        # Create repositories using the factory
        task_repo = factory.create_repository(TaskRepository)
        agent_repo = factory.create_repository(AgentRepository)
        
        # Use repositories normally
        tasks = await task_repo.list_tasks(limit=10)
        agents = await agent_repo.list_all(limit=10)
        
        return {
            "tasks_count": len(tasks),
            "agents_count": len(agents),
            "workspace_id": factory.get_user_context().workspace_id,
            "user_id": factory.get_user_context().user_id
        }
        
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Repository not available: {e}")


@router.get("/example-traditional")
async def example_endpoint_traditional(
    session: AsyncSession,  # Would need proper dependency
    user_context: UserContextDep
):
    """Example endpoint using traditional approach.
    
    This shows the old way of manually creating repositories
    for comparison with the factory approach.
    """
    try:
        # Import repositories as needed
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_agents.infrastructure.repository import AgentRepository
        
        # Create repositories manually (old way)
        task_repo = TaskRepository(session, user_context)
        agent_repo = AgentRepository(session, user_context)
        
        # Use repositories normally
        tasks = await task_repo.list_tasks(limit=10)
        agents = await agent_repo.list_all(limit=10)
        
        return {
            "tasks_count": len(tasks),
            "agents_count": len(agents),
            "workspace_id": user_context.workspace_id,
            "user_id": user_context.user_id
        }
        
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Repository not available: {e}")


class ExampleService:
    """Example service showing how to use RepositoryFactory in service layer."""
    
    def __init__(self, repository_factory: RepositoryFactory):
        """Initialize service with repository factory.
        
        Args:
            repository_factory: Factory for creating repositories
        """
        self.factory = repository_factory
    
    async def get_workspace_summary(self) -> dict:
        """Get a summary of workspace resources using multiple repositories."""
        try:
            # Import repositories as needed
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_agents.infrastructure.repository import AgentRepository
            from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
            
            # Create repositories using factory
            task_repo = self.factory.create_repository(TaskRepository)
            agent_repo = self.factory.create_repository(AgentRepository)
            mcp_repo = self.factory.create_repository(MCPServerInstanceRepository)
            
            # Get counts for each resource type
            tasks_count = await task_repo.count()
            agents_count = await agent_repo.count()
            mcp_instances_count = await mcp_repo.count()
            
            # Get user's own resources
            user_tasks_count = await task_repo.count(creator_scoped=True)
            user_agents_count = await agent_repo.count(creator_scoped=True)
            user_mcp_instances_count = await mcp_repo.count(creator_scoped=True)
            
            return {
                "workspace_id": self.factory.get_user_context().workspace_id,
                "user_id": self.factory.get_user_context().user_id,
                "workspace_totals": {
                    "tasks": tasks_count,
                    "agents": agents_count,
                    "mcp_instances": mcp_instances_count
                },
                "user_totals": {
                    "tasks": user_tasks_count,
                    "agents": user_agents_count,
                    "mcp_instances": user_mcp_instances_count
                }
            }
            
        except ImportError as e:
            return {
                "error": f"Repository not available: {e}",
                "workspace_id": self.factory.get_user_context().workspace_id,
                "user_id": self.factory.get_user_context().user_id
            }
    
    async def create_task_for_agent(self, agent_id: UUID, description: str) -> dict:
        """Create a task for an agent using multiple repositories."""
        try:
            # Import repositories and domain models
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_agents.infrastructure.repository import AgentRepository
            from agentarea_tasks.domain.models import Task
            from uuid import uuid4
            
            # Create repositories using factory
            task_repo = self.factory.create_repository(TaskRepository)
            agent_repo = self.factory.create_repository(AgentRepository)
            
            # Verify agent exists in workspace
            agent = await agent_repo.get_by_id(agent_id)
            if not agent:
                return {"error": "Agent not found in workspace"}
            
            # Create new task
            task = Task(
                id=uuid4(),
                agent_id=agent_id,
                description=description,
                parameters={},
                status="pending",
                user_id=self.factory.get_user_context().user_id,
                workspace_id=self.factory.get_user_context().workspace_id,
                metadata={}
            )
            
            created_task = await task_repo.create_task(task)
            
            return {
                "task_id": str(created_task.id),
                "agent_id": str(agent_id),
                "description": description,
                "status": created_task.status,
                "workspace_id": created_task.workspace_id
            }
            
        except ImportError as e:
            return {"error": f"Repository not available: {e}"}


# FastAPI dependency for the example service
async def get_example_service(factory: RepositoryFactoryDep) -> ExampleService:
    """Get ExampleService with repository factory."""
    return ExampleService(factory)


# Example endpoint using the service
@router.get("/workspace-summary")
async def get_workspace_summary(
    example_service: ExampleService = RepositoryFactoryDep
):
    """Get workspace summary using service with repository factory."""
    return await example_service.get_workspace_summary()