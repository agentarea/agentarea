"""Context manager for handling user and workspace context."""

from contextvars import ContextVar

from .context import UserContext

# Context variable to store the current user context
_user_context: ContextVar[UserContext | None] = ContextVar("user_context", default=None)


class ContextManager:
    """Manager for user and workspace context."""

    @staticmethod
    def set_context(user_context: UserContext) -> None:
        """Set the current user context.

        Args:
            user_context: UserContext to set as current
        """
        _user_context.set(user_context)

    @staticmethod
    def get_context() -> UserContext | None:
        """Get the current user context.

        Returns:
            Current UserContext or None if not set
        """
        return _user_context.get()

    @staticmethod
    def clear_context() -> None:
        """Clear the current user context."""
        _user_context.set(None)

    @staticmethod
    def get_user_id() -> str | None:
        """Get the current user ID.

        Returns:
            Current user_id or None if context not set
        """
        context = _user_context.get()
        return context.user_id if context else None

    @staticmethod
    def get_workspace_id() -> str | None:
        """Get the current workspace ID.

        Returns:
            Current workspace_id or None if context not set
        """
        context = _user_context.get()
        return context.workspace_id if context else None
