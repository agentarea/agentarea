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
    # Workspaces this principal may ADMINISTER (policy, spend, access grants),
    # as opposed to merely write entities in. Resolved per request from
    # ownership; ``None`` means "not resolved", which denies rather than allows.
    admin_workspaces: list[str] | None = None
    email: str | None = None
    # Set when the principal itself is a Client (agent-proxy), e.g. an OAuth2
    # client-credentials token; the gateway trusts it over URL scoping.
    client_id: str | None = None
    # The handle the request named the workspace by (``/v1/workspaces/{slug}``).
    # ``None`` for contexts minted outside HTTP, which name it by id.
    workspace_slug: str | None = None

    def __post_init__(self):
        """Refuse a context that names no principal or no workspace."""
        if not self.user_id:
            raise ValueError(
                "user_id is required; refusing to build a UserContext without a principal"
            )
        if not self.workspace_id:
            raise ValueError(
                "workspace_id is required; refusing to build a UserContext without a workspace"
            )


class WorkspaceUnreachableError(PermissionError):
    """The principal may not act in the workspace it named.

    Raised alike for a workspace that does not exist and one the principal
    cannot reach, so the refusal does not reveal which workspaces exist.
    """


class WorkspaceBoundCredentialError(PermissionError):
    """A credential confined to one workspace was used to act beyond it."""


@dataclass
class UserPrincipal:
    """An authenticated user before any workspace has been selected.

    Carries no ``workspace_id`` on purpose: authentication says who is calling,
    never where. The workspace comes from the request -- the URL slug, or the
    entity an id-addressed route acts on -- and :meth:`enter` is the only way to
    turn a principal into a :class:`UserContext`.
    """

    user_id: str
    email: str | None = None
    client_id: str | None = None
    # An API key acts only in the workspace it was issued for.
    bound_workspace_id: str | None = None
    # ``None`` until resolved per request; ``[]`` means resolved and none.
    accessible_workspaces: list[str] | None = None
    admin_workspaces: list[str] | None = None

    def __post_init__(self):
        """Refuse a principal that names nobody."""
        if not self.user_id:
            raise ValueError("user_id is required; refusing to build a principal without one")

    def enter(self, workspace_id: str, workspace_slug: str) -> "UserContext":
        """The context for acting in ``workspace_id``, which must be reachable."""
        if workspace_id not in (self.accessible_workspaces or []):
            raise WorkspaceUnreachableError(f"No accessible workspace '{workspace_slug}'")
        return UserContext(
            user_id=self.user_id,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            accessible_workspaces=list(self.accessible_workspaces or []),
            admin_workspaces=(
                None if self.admin_workspaces is None else list(self.admin_workspaces)
            ),
            email=self.email,
            client_id=self.client_id,
        )


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
