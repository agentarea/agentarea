package store

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// Links is the mcp_oauth_links repository.
type Links struct{}

func linkFrom(id uuid.UUID, ws, by string, inst uuid.UUID, token, access string, provider []byte, active bool,
	expires pgtype.Timestamp, count int32, last pgtype.Timestamp, created pgtype.Timestamp) (domain.OAuthLink, error) {
	p, err := jsonMap(provider)
	if err != nil {
		return domain.OAuthLink{}, err
	}
	return domain.OAuthLink{
		ID: id.String(), WorkspaceID: ws, CreatedBy: by, MCPInstanceID: inst.String(), Token: token,
		AccessControl: access, ProviderConfig: p, IsActive: active, ExpiresAt: fromTimestampPtr(expires),
		AccessCount: count, LastAccessedAt: fromTimestampPtr(last), CreatedAt: fromTimestamp(created),
	}, nil
}

// Insert writes a new active link.
func (Links) Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, inst uuid.UUID, token, access string,
	provider map[string]any, expires *time.Time, now time.Time) (domain.OAuthLink, error) {
	var exp pgtype.Timestamp
	if expires != nil {
		exp = naive(*expires)
	}
	r, err := New(s.Q()).InsertOAuthLink(ctx, InsertOAuthLinkParams{
		ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, McpInstanceID: inst,
		Token: token, AccessControl: access, ProviderConfig: jsonObject(provider), ExpiresAt: exp, Now: naive(now),
	})
	if err != nil {
		return domain.OAuthLink{}, err
	}
	return linkFrom(r.ID, r.WorkspaceID, r.CreatedBy, r.McpInstanceID, r.Token, r.AccessControl, r.ProviderConfig,
		r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt)
}

// List is the links of one instance in the workspace.
func (Links) List(ctx context.Context, s db.Session, inst uuid.UUID) ([]domain.OAuthLink, error) {
	rows, err := New(s.Q()).ListOAuthLinksByInstance(ctx, ListOAuthLinksByInstanceParams{WorkspaceID: s.Workspace().ID(), McpInstanceID: inst})
	if err != nil {
		return nil, err
	}
	out := make([]domain.OAuthLink, 0, len(rows))
	for _, r := range rows {
		l, err := linkFrom(r.ID, r.WorkspaceID, r.CreatedBy, r.McpInstanceID, r.Token, r.AccessControl, r.ProviderConfig,
			r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt)
		if err != nil {
			return nil, err
		}
		out = append(out, l)
	}
	return out, nil
}

// Get is the link id of the workspace; false when there is none.
func (Links) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.OAuthLink, bool, error) {
	r, err := New(s.Q()).GetOAuthLink(ctx, GetOAuthLinkParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.OAuthLink{}, false, nil
	}
	if err != nil {
		return domain.OAuthLink{}, false, err
	}
	l, err := linkFrom(r.ID, r.WorkspaceID, r.CreatedBy, r.McpInstanceID, r.Token, r.AccessControl, r.ProviderConfig,
		r.IsActive, r.ExpiresAt, r.AccessCount, r.LastAccessedAt, r.CreatedAt)
	return l, err == nil, err
}

// Deactivate turns the link off; false when there is none.
func (Links) Deactivate(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) (bool, error) {
	n, err := New(s.Q()).DeactivateOAuthLink(ctx, DeactivateOAuthLinkParams{Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}
