"""Principals: who a call is being made as.

A principal is never inferred. Either a real user authenticated, or a named
piece of platform infrastructure declared itself; code that can do neither
must raise rather than invent one.
"""

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
        if not self.user_id:
            raise ValueError(
                "user_id is required; refusing to build a UserContext without a principal"
            )
        if not self.workspace_id:
            raise ValueError(
                "workspace_id is required; refusing to build a UserContext without a workspace"
            )
        if self.accessible_workspaces is None:
            self.accessible_workspaces = [self.workspace_id]


@dataclass(frozen=True)
class ServicePrincipal:
    """Platform infrastructure acting with no user behind it.

    Carries neither ``user_id`` nor ``workspace_id`` on purpose. Code used to
    write ``UserContext(user_id="system", workspace_id="system")`` to satisfy a
    constructor, and every workspace-scoped query then ran against a "system"
    tenant that does not exist. Without those attributes that mistake is no
    longer expressible: a ServicePrincipal can only be used where the absence of
    a workspace is the point, and workspace-scoped repositories reject it.
    """

    service: str
    reason: str

    def __post_init__(self):
        """Reject a principal that names neither itself nor its justification."""
        if not self.service:
            raise ValueError("service is required to identify the infrastructure principal")
        if not self.reason:
            raise ValueError(
                f"reason is required: state why {self.service or 'this service'} needs "
                "to act without a user"
            )


Principal = UserContext | ServicePrincipal
