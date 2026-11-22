package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// Bundles is the installed_bundles rows: what each install of a bundle did.
type Bundles struct{}

// BundleRow is an installed_bundles row as a deploy reads it.
type BundleRow struct {
	ID, Name, CreatedBy string
	UpdatedBy           *string
	UpdatedAt           time.Time
	// Source is where the folder came from, as the CLI sent it; nil when it sent nothing.
	Source        []byte
	Canonical     []byte
	InstallResult []byte
}

// BundleResult is what one install recorded it did.
type BundleResult struct {
	ID, Name      string
	InstallResult []byte
}

// BundleRecord is what an install records of the bundle; a nil Source keeps the one recorded.
type BundleRecord struct {
	Name, Description, SchemaVersion, Status string
	DisplayName                              *string
	Canonical, InstallResult, Source         []byte
}

func bundleRow(r InstalledBundle) BundleRow {
	return BundleRow{ID: r.ID.String(), Name: r.Name, CreatedBy: r.CreatedBy, UpdatedBy: fromText(r.UpdatedBy),
		UpdatedAt: fromTimestamp(r.UpdatedAt), Source: r.Source, Canonical: r.Canonical, InstallResult: r.InstallResult}
}

// ByID is the session workspace's install id; false when there is none.
func (Bundles) ByID(ctx context.Context, s db.Session, id string) (BundleRow, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return BundleRow{}, false, nil
	}
	r, err := New(s.Q()).GetInstalledBundle(ctx, GetInstalledBundleParams{WorkspaceID: s.Workspace().ID(), ID: u})
	if errors.Is(err, pgx.ErrNoRows) {
		return BundleRow{}, false, nil
	}
	if err != nil {
		return BundleRow{}, false, err
	}
	return bundleRow(r), true, nil
}

// ByName are the session workspace's installs named name, oldest first.
func (Bundles) ByName(ctx context.Context, s db.Session, name string) ([]BundleRow, error) {
	rows, err := New(s.Q()).ListInstalledBundlesByName(ctx, ListInstalledBundlesByNameParams{WorkspaceID: s.Workspace().ID(), Name: name})
	if err != nil {
		return nil, err
	}
	out := make([]BundleRow, len(rows))
	for i, r := range rows {
		out[i] = bundleRow(r)
	}
	return out, nil
}

// Results are what every install of the session workspace recorded, oldest first.
func (Bundles) Results(ctx context.Context, s db.Session) ([]BundleResult, error) {
	rows, err := New(s.Q()).ListInstalledBundleResults(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]BundleResult, len(rows))
	for i, r := range rows {
		out[i] = BundleResult{ID: r.ID.String(), Name: r.Name, InstallResult: r.InstallResult}
	}
	return out, nil
}

// Insert records a first install.
func (Bundles) Insert(ctx context.Context, s db.Session, createdBy string, r BundleRecord, now time.Time) (string, error) {
	id, err := New(s.Q()).InsertInstalledBundle(ctx, InsertInstalledBundleParams{ID: uuid.New(), Now: naive(now),
		WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: r.Name, DisplayName: text(r.DisplayName),
		Description: pgtype.Text{String: r.Description, Valid: true}, SchemaVersion: r.SchemaVersion, Status: r.Status,
		Canonical: r.Canonical, InstallResult: r.InstallResult, Source: r.Source})
	return id.String(), err
}

// Update records a redeploy over the row id, by updatedBy; the bundle's name
// may have changed. False when the row is gone or was written after seen.
func (Bundles) Update(ctx context.Context, s db.Session, id, updatedBy string, seen time.Time, r BundleRecord, now time.Time) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).UpdateInstalledBundle(ctx, UpdateInstalledBundleParams{Name: r.Name, DisplayName: text(r.DisplayName),
		Description: pgtype.Text{String: r.Description, Valid: true}, SchemaVersion: r.SchemaVersion, Status: r.Status,
		Canonical: r.Canonical, InstallResult: r.InstallResult, Now: naive(now), UpdatedBy: text(&updatedBy), Source: r.Source,
		ID: u, WorkspaceID: s.Workspace().ID(), SeenUpdatedAt: naive(seen)})
	return n == 1, err
}

// CatalogMCPByExternalID is the catalog MCP item published under externalID the
// workspace sees, the first in browse order.
func (MCPSpecs) CatalogMCPByExternalID(ctx context.Context, s db.Session, externalID string) (CatalogMCPItem, bool, error) {
	r, err := New(s.Q()).CatalogMCPItemByExternalID(ctx, CatalogMCPItemByExternalIDParams{WorkspaceID: s.Workspace().ID(), ExternalID: externalID})
	if errors.Is(err, pgx.ErrNoRows) {
		return CatalogMCPItem{}, false, nil
	}
	if err != nil {
		return CatalogMCPItem{}, false, err
	}
	it, err := catalogMCPItemFrom(CatalogMCPItemRow(r))
	return it, err == nil, err
}
