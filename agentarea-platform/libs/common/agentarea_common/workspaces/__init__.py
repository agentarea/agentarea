"""Workspace membership and invitation domain.

Lives in common because membership is cross-cutting — many libs will
eventually consult it. Authz/permissions (Keto integration, role
presets, per-resource grants) are NOT here; they're a separate layer
that will be added in a future PR.
"""

from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    WORKSPACE_TYPE_PERSONAL,
    WORKSPACE_TYPE_SHARED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .repository import (
    WorkspaceInvitationRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from .service import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    WorkspaceInvitationService,
    WorkspaceMembershipService,
    WorkspaceService,
)
from .slug import slugify

__all__ = [
    "INVITATION_STATUS_ACCEPTED",
    "INVITATION_STATUS_PENDING",
    "INVITATION_STATUS_REVOKED",
    "WORKSPACE_TYPE_PERSONAL",
    "WORKSPACE_TYPE_SHARED",
    "InvitationAlreadyAccepted",
    "InvitationExpired",
    "InvitationNotFound",
    "InvitationRevoked",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceInvitationRepository",
    "WorkspaceInvitationService",
    "WorkspaceMembership",
    "WorkspaceMembershipRepository",
    "WorkspaceMembershipService",
    "WorkspaceRepository",
    "WorkspaceService",
    "slugify",
]
