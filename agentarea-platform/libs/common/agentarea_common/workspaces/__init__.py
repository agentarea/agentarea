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
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .repository import WorkspaceInvitationRepository, WorkspaceMembershipRepository
from .service import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    WorkspaceInvitationService,
    WorkspaceMembershipService,
)

__all__ = [
    "INVITATION_STATUS_ACCEPTED",
    "INVITATION_STATUS_PENDING",
    "INVITATION_STATUS_REVOKED",
    "InvitationAlreadyAccepted",
    "InvitationExpired",
    "InvitationNotFound",
    "InvitationRevoked",
    "WorkspaceInvitation",
    "WorkspaceInvitationRepository",
    "WorkspaceInvitationService",
    "WorkspaceMembership",
    "WorkspaceMembershipRepository",
    "WorkspaceMembershipService",
]
