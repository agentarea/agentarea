"""Repository factory for dependency injection with user context."""

from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.context import UserContext
from .workspace_scoped_repository import WorkspaceScopedRepository

T = TypeVar("T", bound=WorkspaceScopedRepository)


class RepositoryFactory:
    """Factory for creating workspace-scoped repositories with user context.

    This factory ensures that all repositories are properly initialized with
    the current user context for workspace-scoped data isolation.
    """

    def __init__(self, session: AsyncSession, user_context: UserContext):
        """Initialize the repository factory.

        Args:
            session: SQLAlchemy async session
            user_context: Current user and workspace context
        """
        self.session = session
        self.user_context = user_context

    def create_repository(self, repository_class: type[T]) -> T:
        """Create a repository instance with user context.

        Args:
            repository_class: The repository class to instantiate

        Returns:
            Repository instance with user context injected
        """
        return repository_class(session=self.session, user_context=self.user_context)
