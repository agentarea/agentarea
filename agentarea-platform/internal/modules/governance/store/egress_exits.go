package store

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

// EgressExits is the egress_exits repository (egress_exit_repository.py):
// a workspace's own exits, and nobody else's.
type EgressExits struct{}

// EgressExitChanges are the columns an update writes, by name.
type EgressExitChanges map[string]any

func egressExitPatchable() []string {
	return []string{"name", "description", "upstream_url", "username", "password_secret_id", "allow_plaintext_credentials"}
}

const egressExitColumns = `id::text, name, description, upstream_url, username, password_secret_id::text, via, remote_dns,
	allow_plaintext_credentials, managed_by, workspace_id, created_by, created_at, updated_at`

func scanEgressExit(row pgx.Row) (domain.EgressExit, error) {
	var e domain.EgressExit
	err := row.Scan(&e.ID, &e.Name, &e.Description, &e.UpstreamURL, &e.Username, &e.PasswordSecretID, &e.Via, &e.RemoteDNS,
		&e.AllowPlaintextCredentials, &e.ManagedBy, &e.WorkspaceID, &e.CreatedBy, &e.CreatedAt, &e.UpdatedAt)
	return e, err
}

// List is list_all: the session's workspace's exits, newest first.
func (EgressExits) List(ctx context.Context, s db.Session) ([]domain.EgressExit, error) {
	rows, err := s.Q().Query(ctx, `SELECT `+egressExitColumns+` FROM egress_exits WHERE workspace_id = $1 ORDER BY created_at DESC`,
		s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []domain.EgressExit{}
	for rows.Next() {
		e, err := scanEgressExit(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// Get is get_by_id in the session's workspace.
func (EgressExits) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.EgressExit, bool, error) {
	e, err := scanEgressExit(s.Q().QueryRow(ctx, `SELECT `+egressExitColumns+` FROM egress_exits WHERE id = $1 AND workspace_id = $2`,
		id, s.Workspace().ID()))
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.EgressExit{}, false, nil
	}
	return e, err == nil, err
}

// Create inserts e in the session's workspace, stamped now.
func (EgressExits) Create(ctx context.Context, s db.Session, e domain.EgressExit, now time.Time) (domain.EgressExit, error) {
	return scanEgressExit(s.Q().QueryRow(ctx, `INSERT INTO egress_exits (id, name, description, upstream_url, username,
		password_secret_id, via, remote_dns, allow_plaintext_credentials, managed_by, workspace_id, created_by, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6::uuid, $7, $8, $9, $10, $11, $12, $13, $13) RETURNING `+egressExitColumns,
		e.ID, e.Name, e.Description, e.UpstreamURL, e.Username, e.PasswordSecretID, e.Via, e.RemoteDNS,
		e.AllowPlaintextCredentials, e.ManagedBy, s.Workspace().ID(), e.CreatedBy, naive(now.UTC())))
}

// Update writes changes to the session's workspace's exit; false when it has
// no such exit.
func (EgressExits) Update(ctx context.Context, s db.Session, id uuid.UUID, changes EgressExitChanges, now time.Time) (domain.EgressExit, bool, error) {
	names := make([]string, 0, len(changes))
	for k := range changes {
		if !slices.Contains(egressExitPatchable(), k) {
			return domain.EgressExit{}, false, fmt.Errorf("egress exit column %q cannot be updated", k)
		}
		names = append(names, k)
	}
	sort.Strings(names)
	args := []any{id, s.Workspace().ID(), naive(now.UTC())}
	set := []string{"updated_at = $3"}
	for _, k := range names {
		args = append(args, changes[k])
		cast := ""
		if k == "password_secret_id" {
			cast = "::uuid"
		}
		set = append(set, k+" = $"+strconv.Itoa(len(args))+cast)
	}
	e, err := scanEgressExit(s.Q().QueryRow(ctx, `UPDATE egress_exits SET `+strings.Join(set, ", ")+
		` WHERE id = $1 AND workspace_id = $2 RETURNING `+egressExitColumns, args...))
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.EgressExit{}, false, nil
	}
	return e, err == nil, err
}

// Delete removes the session's workspace's exit; false when it has no such exit.
func (EgressExits) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	tag, err := s.Q().Exec(ctx, `DELETE FROM egress_exits WHERE id = $1 AND workspace_id = $2`, id, s.Workspace().ID())
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}
