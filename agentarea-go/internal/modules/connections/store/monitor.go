package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// ImportRow is an instance as the package import reads it, across workspaces.
type ImportRow struct {
	ID           uuid.UUID
	WorkspaceID  string
	ServerSpecID string
	Transport    string
	JSONSpec     map[string]any
	ManagedBy    *string
}

// StampLastDispatch writes one instance's last_dispatch, whatever its
// workspace; updated_at is left alone.
func (Instances) StampLastDispatch(ctx context.Context, q db.Querier, id uuid.UUID, stamp map[string]any) error {
	_, err := New(q).StampLastDispatch(ctx, StampLastDispatchParams{ID: id, LastDispatch: jsonObject(stamp)})
	return err
}

// PackageImportCandidates is the verified command instances whose
// package_import is absent, or unavailable since before.
func (Instances) PackageImportCandidates(ctx context.Context, q db.Querier, before time.Time, limit int32) ([]ImportRow, error) {
	rows, err := New(q).ListPackageImportCandidates(ctx, ListPackageImportCandidatesParams{Before: tstz(before), MaxRows: limit})
	if err != nil {
		return nil, err
	}
	out := make([]ImportRow, 0, len(rows))
	for _, r := range rows {
		spec, err := jsonMap(r.JsonSpec)
		if err != nil {
			return nil, err
		}
		out = append(out, ImportRow{ID: r.ID, WorkspaceID: r.WorkspaceID, ServerSpecID: r.ServerSpecID,
			Transport: "command", JSONSpec: spec, ManagedBy: fromText(r.ManagedBy)})
	}
	return out, nil
}

// LockForImport reads the row FOR UPDATE; q must be a transaction.
func (Instances) LockForImport(ctx context.Context, q db.Querier, id uuid.UUID) (ImportRow, bool, error) {
	r, err := New(q).LockInstanceForImport(ctx, id)
	if IsNoRows(err) {
		return ImportRow{}, false, nil
	}
	if err != nil {
		return ImportRow{}, false, err
	}
	spec, err := jsonMap(r.JsonSpec)
	if err != nil {
		return ImportRow{}, false, err
	}
	return ImportRow{ID: r.ID, WorkspaceID: r.WorkspaceID, ServerSpecID: r.ServerSpecID, Transport: r.Transport,
		JSONSpec: spec, ManagedBy: fromText(r.ManagedBy)}, true, nil
}

// SetImportedSpec replaces the spec and transport of a locked row.
func (Instances) SetImportedSpec(ctx context.Context, q db.Querier, id uuid.UUID, spec map[string]any, transport string, now time.Time) error {
	_, err := New(q).SetImportedSpec(ctx, SetImportedSpecParams{ID: id, JsonSpec: jsonObject(spec), Transport: transport, Now: naive(now)})
	return err
}
