package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

func workspace(id, slug, name, owner string, logo pgtype.Text) domain.Workspace {
	return domain.Workspace{ID: id, Slug: slug, Name: name, OwnerUserID: owner, LogoKey: textPtr(logo)}
}

// GetWorkspace reads a workspace by id.
func (Store) GetWorkspace(ctx context.Context, q db.Querier, id string) (domain.Workspace, bool, error) {
	r, err := New(q).GetWorkspace(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Workspace{}, false, nil
	}
	if err != nil {
		return domain.Workspace{}, false, err
	}
	return workspace(r.ID, r.Slug, r.Name, r.OwnerUserID, r.LogoKey), true, nil
}

// ListWorkspacesForUser is the workspaces userID owns or is a member of,
// oldest first.
func (Store) ListWorkspacesForUser(ctx context.Context, q db.Querier, userID string, memberIDs []string) ([]domain.Workspace, error) {
	if memberIDs == nil {
		memberIDs = []string{}
	}
	rows, err := New(q).ListWorkspacesForUser(ctx, ListWorkspacesForUserParams{UserID: userID, MemberIds: memberIDs})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Workspace, 0, len(rows))
	for _, r := range rows {
		out = append(out, workspace(r.ID, r.Slug, r.Name, r.OwnerUserID, r.LogoKey))
	}
	return out, nil
}

// SetLogoKey sets or clears the workspace's logo key.
func (Store) SetLogoKey(ctx context.Context, q db.Querier, id string, key *string, now time.Time) error {
	return New(q).SetWorkspaceLogo(ctx, SetWorkspaceLogoParams{LogoKey: text(key), Now: naive(now), ID: id})
}

// ListPendingInvitations is the session workspace's pending invitations, newest first.
func (Store) ListPendingInvitations(ctx context.Context, s db.Session) ([]domain.Invitation, error) {
	rows, err := New(s.Q()).ListPendingInvitations(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]domain.Invitation, 0, len(rows))
	for _, r := range rows {
		out = append(out, invitation(r.ID, r.CreatedAt, r.WorkspaceID, r.Email, r.InvitedBy, r.Status, r.ExpiresAt, r.AcceptedAt, r.AcceptedByUserID, r.MembershipGrantedAt))
	}
	return out, nil
}

// InvitationByID reads an invitation of any workspace.
func (Store) InvitationByID(ctx context.Context, q db.Querier, id uuid.UUID) (domain.Invitation, bool, error) {
	r, err := New(q).GetInvitation(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Invitation{}, false, nil
	}
	if err != nil {
		return domain.Invitation{}, false, err
	}
	return invitation(r.ID, r.CreatedAt, r.WorkspaceID, r.Email, r.InvitedBy, r.Status, r.ExpiresAt, r.AcceptedAt, r.AcceptedByUserID, r.MembershipGrantedAt), true, nil
}

// RevokeInvitation marks one of the session workspace's invitations revoked.
func (Store) RevokeInvitation(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) error {
	return New(s.Q()).RevokeInvitation(ctx, RevokeInvitationParams{Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID()})
}

// ListMemberships is the workspace's membership rows, oldest first.
func (Store) ListMemberships(ctx context.Context, q db.Querier, workspaceID string) ([]domain.MembershipRow, error) {
	rows, err := New(q).ListMemberships(ctx, workspaceID)
	if err != nil {
		return nil, err
	}
	out := make([]domain.MembershipRow, 0, len(rows))
	for _, r := range rows {
		m := domain.MembershipRow{UserID: r.UserID, CreatedAt: r.CreatedAt.Time}
		if r.InvitationID.Valid {
			id := r.InvitationID.UUID.String()
			m.InvitationID = &id
		}
		out = append(out, m)
	}
	return out, nil
}

// MembershipUserIDs are the users with a membership row in the workspace.
func (Store) MembershipUserIDs(ctx context.Context, q db.Querier, workspaceID string) ([]string, error) {
	return New(q).MembershipUserIDs(ctx, workspaceID)
}

// AddMembership writes a membership row with no invitation.
func (Store) AddMembership(ctx context.Context, q db.Querier, workspaceID, userID string, now time.Time) error {
	return New(q).InsertMembership(ctx, InsertMembershipParams{ID: uuid.New(), Now: naive(now), WorkspaceID: workspaceID, UserID: userID})
}

// EndMembership is the SQL of WorkspaceMembershipRepository.end on the
// session's transaction: the row goes, the invitations that could bring the
// user back are revoked (the one they joined through, and every pending one
// addressed to emails or to an address they joined through, compared by
// address), and their API keys in the workspace are deactivated.
func (Store) EndMembership(ctx context.Context, s db.Session, userID string, emails []string, address func(string) string, now time.Time) error {
	qs := New(s.Q())
	ws := s.Workspace().ID()
	if err := qs.DeleteMembership(ctx, DeleteMembershipParams{WorkspaceID: ws, UserID: userID}); err != nil {
		return err
	}
	joined, err := qs.EmailsJoinedThrough(ctx, EmailsJoinedThroughParams{WorkspaceID: ws, UserID: pgtype.Text{String: userID, Valid: true}})
	if err != nil {
		return err
	}
	addresses := map[string]bool{}
	for _, e := range append(append([]string{}, emails...), joined...) {
		if e != "" {
			addresses[address(e)] = true
		}
	}
	pending, err := qs.PendingAddressedInvitations(ctx, ws)
	if err != nil {
		return err
	}
	for _, p := range pending {
		if addresses[address(p.Email)] {
			if err := qs.RevokeInvitation(ctx, RevokeInvitationParams{Now: naive(now), ID: p.ID, WorkspaceID: ws}); err != nil {
				return err
			}
		}
	}
	if err := qs.RevokeInvitationsAcceptedBy(ctx, RevokeInvitationsAcceptedByParams{Now: naive(now), WorkspaceID: ws, UserID: pgtype.Text{String: userID, Valid: true}}); err != nil {
		return err
	}
	return qs.DeactivateUserAPIKeys(ctx, DeactivateUserAPIKeysParams{Now: naive(now), WorkspaceID: ws, CreatedBy: userID})
}

func apiKey(id uuid.UUID, name, prefix string, active bool, expires pgtype.Timestamp, count int32, last, created pgtype.Timestamp, agent uuid.NullUUID, createdBy string, client uuid.NullUUID) domain.APIKey {
	k := domain.APIKey{
		ID: id.String(), Name: name, TokenPrefix: prefix, IsActive: active, ExpiresAt: timePtr(expires),
		AccessCount: int(count), LastAccessedAt: timePtr(last), CreatedAt: created.Time, CreatedBy: createdBy,
	}
	if agent.Valid {
		a := agent.UUID.String()
		k.AgentID = &a
	}
	if client.Valid {
		c := client.UUID.String()
		k.ClientID = &c
	}
	return k
}

// APIKeyByID reads one of the session workspace's keys, of any flavour.
func (Store) APIKeyByID(ctx context.Context, s db.Session, id uuid.UUID) (domain.APIKey, bool, error) {
	r, err := New(s.Q()).GetAPIKey(ctx, GetAPIKeyParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.APIKey{}, false, nil
	}
	if err != nil {
		return domain.APIKey{}, false, err
	}
	return apiKey(r.ID, r.Name, r.TokenPrefix, r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt, r.AgentID, r.CreatedBy, r.ClientID), true, nil
}

// ListAPIKeys is the session workspace's keys of every flavour, newest
// first, narrowed to a creator and an agent when given.
func (Store) ListAPIKeys(ctx context.Context, s db.Session, createdBy *string, agentID *uuid.UUID) ([]domain.APIKey, error) {
	p := ListAPIKeysParams{WorkspaceID: s.Workspace().ID(), CreatedBy: text(createdBy)}
	if agentID != nil {
		p.AgentID = uuid.NullUUID{UUID: *agentID, Valid: true}
	}
	rows, err := New(s.Q()).ListAPIKeys(ctx, p)
	if err != nil {
		return nil, err
	}
	out := make([]domain.APIKey, 0, len(rows))
	for _, r := range rows {
		out = append(out, apiKey(r.ID, r.Name, r.TokenPrefix, r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt, r.AgentID, r.CreatedBy, r.ClientID))
	}
	return out, nil
}

// ListClientAPIKeys is the session workspace's keys bound to a client, revoked ones included, newest first.
func (Store) ListClientAPIKeys(ctx context.Context, s db.Session, clientID uuid.UUID) ([]domain.APIKey, error) {
	rows, err := New(s.Q()).ListClientAPIKeys(ctx, ListClientAPIKeysParams{WorkspaceID: s.Workspace().ID(), ClientID: uuid.NullUUID{UUID: clientID, Valid: true}})
	if err != nil {
		return nil, err
	}
	out := make([]domain.APIKey, 0, len(rows))
	for _, r := range rows {
		out = append(out, apiKey(r.ID, r.Name, r.TokenPrefix, r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt, r.AgentID, r.CreatedBy, r.ClientID))
	}
	return out, nil
}

// DeactivateAPIKey revokes one of the session workspace's keys; the row stays.
func (Store) DeactivateAPIKey(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) error {
	return New(s.Q()).DeactivateAPIKey(ctx, DeactivateAPIKeyParams{Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id})
}

// ListExternalIdentities is the user's live links, oldest first.
func (Store) ListExternalIdentities(ctx context.Context, q db.Querier, userID string) ([]domain.ExternalIdentity, error) {
	rows, err := New(q).ListExternalIdentities(ctx, userID)
	if err != nil {
		return nil, err
	}
	out := make([]domain.ExternalIdentity, 0, len(rows))
	for _, r := range rows {
		out = append(out, domain.ExternalIdentity{ID: r.ID.String(), Provider: r.Provider, ExternalID: r.ExternalID, CreatedAt: r.CreatedAt.Time})
	}
	return out, nil
}

// RevokeExternalIdentity unlinks one of the user's live links; false when it
// is not theirs or not live.
func (Store) RevokeExternalIdentity(ctx context.Context, q db.Querier, userID string, id uuid.UUID, now time.Time) (bool, error) {
	n, err := New(q).RevokeExternalIdentity(ctx, RevokeExternalIdentityParams{Now: naive(now), ID: id, UserID: userID})
	return n > 0, err
}

// ExternalIdentityHolder is the user a live account is linked to.
func (Store) ExternalIdentityHolder(ctx context.Context, q db.Querier, provider, externalID string) (string, bool, error) {
	u, err := New(q).ExternalIdentityHolder(ctx, ExternalIdentityHolderParams{Provider: provider, ExternalID: externalID})
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	return u, err == nil, err
}

// InsertExternalIdentity links an account to a user.
func (Store) InsertExternalIdentity(ctx context.Context, q db.Querier, userID, provider, externalID, method string, now time.Time) (domain.ExternalIdentity, error) {
	r, err := New(q).InsertExternalIdentity(ctx, InsertExternalIdentityParams{
		ID: uuid.New(), Now: naive(now), UserID: userID, Provider: provider, ExternalID: externalID, Method: method,
	})
	if err != nil {
		return domain.ExternalIdentity{}, err
	}
	return domain.ExternalIdentity{ID: r.ID.String(), Provider: r.Provider, ExternalID: r.ExternalID, CreatedAt: r.CreatedAt.Time}, nil
}
