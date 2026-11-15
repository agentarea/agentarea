package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

//go:generate sqlc generate

// Store reads and writes workspaces, invitations, memberships and API keys.
// workspaces is the registry of workspaces itself, and an invitation token
// names its workspace, so those statements run on a global runner.
type Store struct{}

func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.Truncate(time.Microsecond), Valid: true}
}

func nullable(t *time.Time) pgtype.Timestamp {
	if t == nil {
		return pgtype.Timestamp{}
	}
	return naive(*t)
}

func timePtr(t pgtype.Timestamp) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time
	return &v
}

func textPtr(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	v := t.String
	return &v
}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

// SlugTaken reports whether a workspace has slug.
func (Store) SlugTaken(ctx context.Context, q db.Querier, slug string) (bool, error) {
	return New(q).WorkspaceSlugTaken(ctx, slug)
}

// InsertWorkspace adds the row; created_at/updated_at take the DB default.
func (Store) InsertWorkspace(ctx context.Context, q db.Querier, w domain.Workspace) (domain.Workspace, error) {
	r, err := New(q).InsertWorkspace(ctx, InsertWorkspaceParams{ID: w.ID, Slug: w.Slug, Name: w.Name, OwnerUserID: w.OwnerUserID})
	if err != nil {
		return domain.Workspace{}, err
	}
	return domain.Workspace{ID: r.ID, Slug: r.Slug, Name: r.Name, OwnerUserID: r.OwnerUserID, LogoKey: textPtr(r.LogoKey)}, nil
}

// OwnedWorkspaceIDs are the workspaces userID owns, oldest first.
func (Store) OwnedWorkspaceIDs(ctx context.Context, q db.Querier, userID string) ([]string, error) {
	return New(q).OwnedWorkspaceIDs(ctx, userID)
}

func invitation(id uuid.UUID, created pgtype.Timestamp, ws string, email pgtype.Text, by, status string,
	expires, accepted pgtype.Timestamp, acceptedBy pgtype.Text, granted pgtype.Timestamp) domain.Invitation {
	return domain.Invitation{
		ID: id.String(), CreatedAt: created.Time, WorkspaceID: ws, Email: textPtr(email), InvitedBy: by,
		Status: status, ExpiresAt: expires.Time, AcceptedAt: timePtr(accepted),
		AcceptedByUserID: textPtr(acceptedBy), MembershipGrantedAt: timePtr(granted),
	}
}

// InsertInvitation adds a pending invitation to the session's workspace.
func (Store) InsertInvitation(ctx context.Context, s db.Session, id uuid.UUID, email *string, tokenHash, invitedBy string, expiresAt, now time.Time) (domain.Invitation, error) {
	r, err := New(s.Q()).InsertInvitation(ctx, InsertInvitationParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), Email: text(email),
		TokenHash: tokenHash, InvitedBy: invitedBy, ExpiresAt: naive(expiresAt),
	})
	if err != nil {
		return domain.Invitation{}, err
	}
	return invitation(r.ID, r.CreatedAt, r.WorkspaceID, r.Email, r.InvitedBy, r.Status, r.ExpiresAt, r.AcceptedAt, r.AcceptedByUserID, r.MembershipGrantedAt), nil
}

// InvitationByTokenHash finds an invitation of any workspace.
func (Store) InvitationByTokenHash(ctx context.Context, q db.Querier, tokenHash string) (domain.Invitation, bool, error) {
	r, err := New(q).InvitationByTokenHash(ctx, tokenHash)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Invitation{}, false, nil
	}
	if err != nil {
		return domain.Invitation{}, false, err
	}
	return invitation(r.ID, r.CreatedAt, r.WorkspaceID, r.Email, r.InvitedBy, r.Status, r.ExpiresAt, r.AcceptedAt, r.AcceptedByUserID, r.MembershipGrantedAt), true, nil
}

// MarkAccepted stamps the invitation accepted by userID.
func (Store) MarkAccepted(ctx context.Context, q db.Querier, id uuid.UUID, userID string, acceptedAt, now time.Time) error {
	return New(q).MarkInvitationAccepted(ctx, MarkInvitationAcceptedParams{
		AcceptedAt: naive(acceptedAt), UserID: pgtype.Text{String: userID, Valid: true}, Now: naive(now), ID: id,
	})
}

// AddForInvitation is add_for_invitation, inside the caller's transaction:
// the invitation is locked and must still be accepted by userID; the
// membership row is written unless one exists, and the invitation stamped.
func (Store) AddForInvitation(ctx context.Context, q db.Querier, invitationID uuid.UUID, workspaceID, userID string, grantedAt, now time.Time) (bool, error) {
	qs := New(q)
	lock, err := qs.LockInvitation(ctx, invitationID)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if lock.Status != domain.StatusAccepted || !lock.AcceptedByUserID.Valid || lock.AcceptedByUserID.String != userID {
		return false, nil
	}
	if lock.MembershipGrantedAt.Valid {
		return true, nil
	}
	exists, err := qs.MembershipExists(ctx, MembershipExistsParams{WorkspaceID: workspaceID, UserID: userID})
	if err != nil {
		return false, err
	}
	if !exists {
		err = qs.InsertMembership(ctx, InsertMembershipParams{
			ID: uuid.New(), Now: naive(now), WorkspaceID: workspaceID, UserID: userID,
			InvitationID: uuid.NullUUID{UUID: invitationID, Valid: true},
		})
		if err != nil {
			return false, err
		}
	}
	return true, qs.StampMembershipGranted(ctx, StampMembershipGrantedParams{Now: naive(grantedAt), UpdatedAt: naive(now), ID: invitationID})
}

// MembershipExists reports whether userID has a membership row in workspaceID.
func (Store) MembershipExists(ctx context.Context, q db.Querier, workspaceID, userID string) (bool, error) {
	return New(q).MembershipExists(ctx, MembershipExistsParams{WorkspaceID: workspaceID, UserID: userID})
}

// NewAPIKey is a key to insert.
type NewAPIKey struct {
	ID          uuid.UUID
	CreatedBy   string
	Name        string
	TokenHash   string
	TokenPrefix string
	ExpiresAt   *time.Time
	AgentID     *uuid.UUID
	// ClientID binds a runner's key to its client.
	ClientID *uuid.UUID
}

// InsertAPIKey adds a key to the session's workspace.
func (Store) InsertAPIKey(ctx context.Context, s db.Session, k NewAPIKey, now time.Time) (domain.APIKey, error) {
	agent := uuid.NullUUID{}
	if k.AgentID != nil {
		agent = uuid.NullUUID{UUID: *k.AgentID, Valid: true}
	}
	client := uuid.NullUUID{}
	if k.ClientID != nil {
		client = uuid.NullUUID{UUID: *k.ClientID, Valid: true}
	}
	r, err := New(s.Q()).InsertAPIKey(ctx, InsertAPIKeyParams{
		ID: k.ID, WorkspaceID: s.Workspace().ID(), CreatedBy: k.CreatedBy, Name: k.Name,
		TokenHash: k.TokenHash, TokenPrefix: k.TokenPrefix, ExpiresAt: nullable(k.ExpiresAt), AgentID: agent, ClientID: client, Now: naive(now),
	})
	if err != nil {
		return domain.APIKey{}, err
	}
	return apiKey(r.ID, r.Name, r.TokenPrefix, r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt, r.AgentID, k.CreatedBy, r.ClientID), nil
}
