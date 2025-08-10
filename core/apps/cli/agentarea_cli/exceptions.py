"""Custom exceptions for AgentArea CLI."""

from agentarea_common.exceptions import WorkspaceError


class AgentAreaError(WorkspaceError):
    """Base exception for AgentArea CLI errors."""
    pass


class AuthenticationError(AgentAreaError):
    """Raised when authentication fails."""
    pass


class ConfigurationError(AgentAreaError):
    """Raised when configuration is invalid."""
    pass


class APIError(AgentAreaError):
    """Raised when API request fails."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


class ValidationError(AgentAreaError):
    """Raised when input validation fails."""
    pass
