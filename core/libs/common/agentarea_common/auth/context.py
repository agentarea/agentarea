"""User context dataclass for holding user and workspace information."""

from dataclasses import dataclass


@dataclass
class UserContext:
    """User context extracted from JWT token."""

    user_id: str
    workspace_id: str
    roles: list[str] | None = None

    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.roles is None:
            self.roles = []
