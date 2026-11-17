package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// Toolsets is the service as identity/api.Members.
type Toolsets struct{ S *Service }

var _ api.Members = Toolsets{}

func invitationOut(i domain.Invitation) api.Invitation {
	return api.Invitation{ID: i.ID, Email: i.Email, InvitedBy: i.InvitedBy, Status: i.Status, ExpiresAt: i.ExpiresAt, CreatedAt: i.CreatedAt}
}

func workspaceOut(v WorkspaceView) api.Workspace {
	return api.Workspace{ID: v.ID, Slug: v.Slug, Name: v.Name, OwnerUserID: v.OwnerUserID, CanAdminister: v.CanAdminister, LogoURL: v.LogoURL}
}

func (t Toolsets) ListMembers(ctx context.Context, c authn.Caller) ([]api.Member, error) {
	ms, err := t.S.ListMembers(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]api.Member, 0, len(ms))
	for _, m := range ms {
		out = append(out, api.Member{UserID: m.UserID, Email: m.Email, DisplayName: m.DisplayName, JoinedAt: m.JoinedAt, IsOwner: m.IsOwner, IsYou: m.UserID == c.UserID})
	}
	return out, nil
}

func (t Toolsets) Invite(ctx context.Context, c authn.Caller, email *string, days *int) (api.CreatedInvitation, error) {
	if err := t.S.requireAdmin(ctx, &c); err != nil {
		return api.CreatedInvitation{}, err
	}
	inv, err := t.S.CreateInvitation(ctx, c, email, days)
	if err != nil {
		return api.CreatedInvitation{}, err
	}
	return api.CreatedInvitation{Invitation: invitationOut(inv.Invitation), Token: inv.Token, EmailDelivery: string(inv.EmailDelivery)}, nil
}

func (t Toolsets) ListInvitations(ctx context.Context, c authn.Caller) ([]api.Invitation, error) {
	invs, err := t.S.ListInvitations(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]api.Invitation, 0, len(invs))
	for _, i := range invs {
		out = append(out, invitationOut(i.Invitation))
	}
	return out, nil
}

func (t Toolsets) RevokeInvitation(ctx context.Context, c authn.Caller, id string) error {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	_, err = t.S.RevokeInvitation(ctx, c, parsed)
	return err
}

func (t Toolsets) RemoveMember(ctx context.Context, c authn.Caller, userID string) (bool, error) {
	return t.S.RemoveMember(ctx, c, userID)
}

func (t Toolsets) ListWorkspaces(ctx context.Context, p authn.Principal) ([]api.Workspace, error) {
	vs, err := t.S.ListWorkspaces(ctx, p)
	if err != nil {
		return nil, err
	}
	out := make([]api.Workspace, 0, len(vs))
	for _, v := range vs {
		out = append(out, workspaceOut(v))
	}
	return out, nil
}

func (t Toolsets) CreateWorkspace(ctx context.Context, p authn.Principal, name string) (api.Workspace, error) {
	if err := authn.EnsureScope(p, authn.ScopeWorkspaces, "create workspaces"); err != nil {
		return api.Workspace{}, err
	}
	name = pyStrip(name)
	if name == "" {
		return api.Workspace{}, domain.ErrEmptyWorkspaceName
	}
	w, err := t.S.CreateWorkspace(ctx, p.UserID, name)
	if err != nil {
		return api.Workspace{}, err
	}
	return api.Workspace{ID: w.ID, Slug: w.Slug, Name: w.Name, OwnerUserID: w.OwnerUserID, CanAdminister: true}, nil
}

func (t Toolsets) SetLogo(ctx context.Context, c authn.Caller, data []byte) (api.Workspace, error) {
	v, err := t.S.SetLogo(ctx, c, data)
	return workspaceOut(v), err
}

func (t Toolsets) RemoveLogo(ctx context.Context, c authn.Caller) (api.Workspace, error) {
	v, err := t.S.RemoveLogo(ctx, c)
	return workspaceOut(v), err
}
