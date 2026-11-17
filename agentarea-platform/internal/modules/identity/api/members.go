package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// Member is one member of the caller's workspace.
type Member struct {
	UserID      string
	Email       *string
	DisplayName *string
	JoinedAt    *time.Time
	IsOwner     bool
	IsYou       bool
}

// Invitation is a workspace invitation without its token.
type Invitation struct {
	ID        string
	Email     *string
	InvitedBy string
	Status    string
	ExpiresAt time.Time
	CreatedAt time.Time
}

// CreatedInvitation carries the plaintext token, returned once.
type CreatedInvitation struct {
	Invitation
	Token         string
	EmailDelivery string
}

// Workspace is a workspace as the caller sees it.
type Workspace struct {
	ID            string
	Slug          string
	Name          string
	OwnerUserID   string
	CanAdminister bool
	LogoURL       *string
}

// Members is what the members and workspaces toolsets do (members_toolset.py,
// workspaces_toolset.py). Each acts on c's workspace; invite, list and revoke
// invitations and the logo need an admin of it, remove the owner or the
// member themself. Errors render as the REST routes render them.
type Members interface {
	ListMembers(ctx context.Context, c authn.Caller) ([]Member, error)
	Invite(ctx context.Context, c authn.Caller, email *string, expiresInDays *int) (CreatedInvitation, error)
	ListInvitations(ctx context.Context, c authn.Caller) ([]Invitation, error)
	// RevokeInvitation refuses an id outside c's workspace as "Invitation not found".
	RevokeInvitation(ctx context.Context, c authn.Caller, invitationID string) error
	// RemoveMember is false while the graph still grants the ended membership.
	RemoveMember(ctx context.Context, c authn.Caller, userID string) (bool, error)
	ListWorkspaces(ctx context.Context, p authn.Principal) ([]Workspace, error)
	CreateWorkspace(ctx context.Context, p authn.Principal, name string) (Workspace, error)
	SetLogo(ctx context.Context, c authn.Caller, data []byte) (Workspace, error)
	RemoveLogo(ctx context.Context, c authn.Caller) (Workspace, error)
}
