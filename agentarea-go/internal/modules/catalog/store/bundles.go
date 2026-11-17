package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Bundles is the installed_bundles rows: what each install of a bundle did.
type Bundles struct{}

// BundleRow is an installed_bundles row as a deploy reads it.
type BundleRow struct {
	ID            string
	Canonical     []byte
	InstallResult []byte
}

// BundleRecord is what an install records of the bundle.
type BundleRecord struct {
	Name, Description, SchemaVersion, Status string
	DisplayName                              *string
	Canonical, InstallResult                 []byte
}

// ByName is the session workspace's record of the bundle, the oldest one when there are several.
func (Bundles) ByName(ctx context.Context, s db.Session, name string) (BundleRow, bool, error) {
	r, err := New(s.Q()).GetInstalledBundleByName(ctx, GetInstalledBundleByNameParams{WorkspaceID: s.Workspace().ID(), Name: name})
	if errors.Is(err, pgx.ErrNoRows) {
		return BundleRow{}, false, nil
	}
	if err != nil {
		return BundleRow{}, false, err
	}
	return BundleRow{ID: r.ID.String(), Canonical: r.Canonical, InstallResult: r.InstallResult}, true, nil
}

// Insert records a first install.
func (Bundles) Insert(ctx context.Context, s db.Session, createdBy string, r BundleRecord, now time.Time) (string, error) {
	id, err := New(s.Q()).InsertInstalledBundle(ctx, InsertInstalledBundleParams{ID: uuid.New(), Now: naive(now),
		WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: r.Name, DisplayName: text(r.DisplayName),
		Description: pgtype.Text{String: r.Description, Valid: true}, SchemaVersion: r.SchemaVersion, Status: r.Status,
		Canonical: r.Canonical, InstallResult: r.InstallResult})
	return id.String(), err
}

// Update records a redeploy over the row id.
func (Bundles) Update(ctx context.Context, s db.Session, id string, r BundleRecord, now time.Time) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return New(s.Q()).UpdateInstalledBundle(ctx, UpdateInstalledBundleParams{DisplayName: text(r.DisplayName),
		Description: pgtype.Text{String: r.Description, Valid: true}, SchemaVersion: r.SchemaVersion, Status: r.Status,
		Canonical: r.Canonical, InstallResult: r.InstallResult, Now: naive(now), ID: u,
		WorkspaceID: s.Workspace().ID()})
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
