"""User context dataclass for holding user and workspace information."""

from dataclasses import dataclass


@dataclass
class UserContext:
    """User context extracted from JWT token."""

    user_id: str
    workspace_id: str
    accessible_workspaces: list[str] | None = None
    email: str | None = None
    # Set when the principal itself is a Client (agent-proxy), e.g. an OAuth2
    # client-credentials token; the gateway trusts it over URL scoping.
    client_id: str | None = None

    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.accessible_workspaces is None:
            self.accessible_workspaces = [self.workspace_id]
