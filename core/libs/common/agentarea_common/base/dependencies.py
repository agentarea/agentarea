"""FastAPI dependencies for repository factory and database operations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import UserContextDep
from ..infrastructure.database import get_db_session
from .repository_factory import RepositoryFactory


async def get_repository_factory(
    session: Annotated[AsyncSession, Depends(get_db_session)], user_context: UserContextDep
) -> RepositoryFactory:
    """FastAPI dependency to get repository factory with user context.

    This dependency creates a RepositoryFactory instance with the current
    database session and user context, enabling easy creation of workspace-scoped
    repositories throughout the application.

    Args:
        session: SQLAlchemy async session
        user_context: Current user and workspace context

    Returns:
        RepositoryFactory: Factory instance for creating repositories

    Example:
        @app.get("/agents")
        async def list_agents(factory: RepositoryFactoryDep):
            agent_repo = factory.create_repository(AgentRepository)
            return await agent_repo.list_all()
    """
    return RepositoryFactory(session, user_context)


# Type alias for easier use in endpoint dependencies
RepositoryFactoryDep = Annotated[RepositoryFactory, Depends(get_repository_factory)]
