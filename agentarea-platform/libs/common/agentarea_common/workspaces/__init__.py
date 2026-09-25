"""Workspace membership and invitation domain.

Lives in common because membership is cross-cutting — many libs consult it.
The public operations stay product-level even when the configured graph backend
changes.
"""

from .memberships import (
    check_workspace_membership,
    get_workspace_membership_graph,
    grant_workspace_membership,
    list_workspace_ids_for_member,
    list_workspace_member_ids,
    revoke_workspace_membership,
    workspace_membership,
)
from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .repository import (
    MEMBERSHIP_ENDED,
    WorkspaceInvitationRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from .service import (
    InvitationAddressedElsewhere,
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    LastMemberRemovalRejected,
    MembershipRemovalForbidden,
    MembershipRemovalRejected,
    OwnerRemovalRejected,
    WorkspaceInvitationService,
    WorkspaceMembershipService,
    WorkspaceMemberView,
    WorkspaceService,
    membership_removal_handler,
)
from .slug import slugify

__all__ = [
    "INVITATION_STATUS_ACCEPTED",
    "INVITATION_STATUS_PENDING",
    "INVITATION_STATUS_REVOKED",
    "MEMBERSHIP_ENDED",
    "InvitationAddressedElsewhere",
    "InvitationAlreadyAccepted",
    "InvitationExpired",
    "InvitationNotFound",
    "InvitationRevoked",
    "LastMemberRemovalRejected",
    "MembershipRemovalForbidden",
    "MembershipRemovalRejected",
    "OwnerRemovalRejected",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceInvitationRepository",
    "WorkspaceInvitationService",
    "WorkspaceMemberView",
    "WorkspaceMembership",
    "WorkspaceMembershipRepository",
    "WorkspaceMembershipService",
    "WorkspaceRepository",
    "WorkspaceService",
    "check_workspace_membership",
    "get_workspace_membership_graph",
    "grant_workspace_membership",
    "list_workspace_ids_for_member",
    "list_workspace_member_ids",
    "membership_removal_handler",
    "revoke_workspace_membership",
    "slugify",
    "workspace_membership",
]
