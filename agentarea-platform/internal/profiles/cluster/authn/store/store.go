// Package store reads api_keys and workspaces for authentication, over the
// tables Python owns (no schema of its own).
package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	authn "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authn"
)

// Store implements authn.Store over the primary pool.
type Store struct {
	q db.Querier
}

var _ authn.Store = (*Store)(nil)

// New reads and writes through q, which must reach the primary.
func New(q db.Querier) *Store { return &Store{q: q} }

const apiKeyByHash = `
SELECT id::text, workspace_id, created_by, is_active, expires_at, last_accessed_at,
       agent_id::text, client_id::text
FROM api_keys
WHERE token_hash = $1`

// APIKeyByHash finds a key of any workspace: the key names its workspace.
func (s *Store) APIKeyByHash(ctx context.Context, tokenHash string) (authn.APIKey, bool, error) {
	var (
		k                 authn.APIKey
		expires, accessed pgtype.Timestamp
		agentID, clientID pgtype.Text
	)
	err := s.q.QueryRow(ctx, apiKeyByHash, tokenHash).Scan(
		&k.ID, &k.WorkspaceID, &k.CreatedBy, &k.IsActive, &expires, &accessed, &agentID, &clientID)
	if errors.Is(err, pgx.ErrNoRows) {
		return authn.APIKey{}, false, nil
	}
	if err != nil {
		return authn.APIKey{}, false, err
	}
	k.ExpiresAt = naiveUTC(expires)
	k.LastAccessedAt = naiveUTC(accessed)
	k.AgentID = agentID.String
	k.ClientID = clientID.String
	return k, true, nil
}

func naiveUTC(ts pgtype.Timestamp) *time.Time {
	if !ts.Valid {
		return nil
	}
	t := ts.Time
	utc := time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC)
	return &utc
}

const recordAPIKeyUse = `
UPDATE api_keys SET access_count = access_count + $2, last_accessed_at = $3
WHERE id = $1::uuid`

// RecordAPIKeyUse adds uses and stamps last_accessed_at with at (naive UTC).
func (s *Store) RecordAPIKeyUse(ctx context.Context, keyID string, uses int, at time.Time) error {
	stamp := pgtype.Timestamp{Time: naiveWall(at), Valid: true}
	_, err := s.q.Exec(ctx, recordAPIKeyUse, keyID, uses, stamp)
	return err
}

// naiveWall drops the location, keeping the UTC wall clock, as Python's
// datetime.utcnow() is written to a timestamp without time zone.
func naiveWall(t time.Time) time.Time {
	u := t.UTC().Truncate(time.Microsecond)
	return time.Date(u.Year(), u.Month(), u.Day(), u.Hour(), u.Minute(), u.Second(), u.Nanosecond(), time.UTC)
}

const workspaceByID = `SELECT id, slug, owner_user_id FROM workspaces WHERE id = $1`

const workspaceBySlug = `SELECT id, slug, owner_user_id FROM workspaces WHERE slug = $1`

func (s *Store) one(ctx context.Context, query, arg string) (authn.Workspace, bool, error) {
	var w authn.Workspace
	err := s.q.QueryRow(ctx, query, arg).Scan(&w.ID, &w.Slug, &w.OwnerUserID)
	if errors.Is(err, pgx.ErrNoRows) {
		return authn.Workspace{}, false, nil
	}
	if err != nil {
		return authn.Workspace{}, false, err
	}
	return w, true, nil
}

// WorkspaceByID is WorkspaceRepository.get.
func (s *Store) WorkspaceByID(ctx context.Context, id string) (authn.Workspace, bool, error) {
	return s.one(ctx, workspaceByID, id)
}

// WorkspaceBySlug is WorkspaceRepository.get_by_slug.
func (s *Store) WorkspaceBySlug(ctx context.Context, slug string) (authn.Workspace, bool, error) {
	return s.one(ctx, workspaceBySlug, slug)
}

const ownedOrNamed = `
SELECT id, slug, owner_user_id FROM workspaces
WHERE owner_user_id = $1
   OR ($2::text IS NOT NULL AND slug = $2)
   OR ($3::text IS NOT NULL AND id = $3)
ORDER BY created_at ASC`

// OwnedOrNamed is WorkspaceRepository.list_owned_or_named.
func (s *Store) OwnedOrNamed(ctx context.Context, userID, slug, id string) ([]authn.Workspace, error) {
	rows, err := s.q.Query(ctx, ownedOrNamed, userID, nullable(slug), nullable(id))
	if err != nil {
		return nil, err
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (authn.Workspace, error) {
		var w authn.Workspace
		err := row.Scan(&w.ID, &w.Slug, &w.OwnerUserID)
		return w, err
	})
	if err != nil {
		return nil, err
	}
	return out, nil
}

func nullable(s string) pgtype.Text { return pgtype.Text{String: s, Valid: s != ""} }
