package store

import (
	"context"
	"errors"
	stdstrings "strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// Installs reads catalog items for installs and records them.
type Installs struct{}

func installItem(id uuid.UUID, name string, desc, version pgtype.Text, spec []byte, registry uuid.UUID, trust string, ws pgtype.Text) api.CatalogItem {
	return api.CatalogItem{ID: id.String(), Name: name, Description: fromText(desc), Version: fromText(version), Spec: spec,
		RegistryID: registry.String(), RegistryTrust: trust, RegistryWorkspaceID: fromText(ws)}
}

// AgentPresets is CatalogAgentPresets.
func (Installs) AgentPresets(ctx context.Context, s db.Session) ([]api.CatalogItem, error) {
	rows, err := New(s.Q()).CatalogAgentPresets(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]api.CatalogItem, len(rows))
	for i, r := range rows {
		out[i] = installItem(r.ID, r.Name, r.Description, r.Version, r.Spec, r.RegistryID, r.RegistryTrust, r.RegistryWorkspaceID)
	}
	return out, nil
}

// AgentItems is CatalogAgentItems.
func (Installs) AgentItems(ctx context.Context, s db.Session) ([]api.CatalogItem, error) {
	rows, err := New(s.Q()).CatalogAgentItems(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]api.CatalogItem, len(rows))
	for i, r := range rows {
		out[i] = installItem(r.ID, r.Name, r.Description, r.Version, r.Spec, r.RegistryID, r.RegistryTrust, r.RegistryWorkspaceID)
	}
	return out, nil
}

// Item is the visible active item of registryType with id.
func (Installs) Item(ctx context.Context, s db.Session, registryType, id string) (api.CatalogItem, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.CatalogItem{}, false, nil
	}
	r, err := New(s.Q()).CatalogItemOfType(ctx, CatalogItemOfTypeParams{RegistryType: registryType, WorkspaceID: s.Workspace().ID(), ID: u})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.CatalogItem{}, false, nil
	}
	if err != nil {
		return api.CatalogItem{}, false, err
	}
	it := installItem(r.ID, r.Name, r.Description, r.Version, r.Spec, r.RegistryID, r.RegistryTrust, r.RegistryWorkspaceID)
	it.InstalledVersion = fromText(r.InstalledVersion)
	return it, true, nil
}

// SkillByKey is CatalogSkillByKey with key's LIKE wildcards escaped.
func (Installs) SkillByKey(ctx context.Context, s db.Session, key string) (api.CatalogItem, bool, error) {
	prefix := stdstrings.NewReplacer(`%`, `\%`, `_`, `\_`).Replace(key) + "--%"
	r, err := New(s.Q()).CatalogSkillByKey(ctx, CatalogSkillByKeyParams{WorkspaceID: s.Workspace().ID(), Key: key, Prefix: prefix})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.CatalogItem{}, false, nil
	}
	if err != nil {
		return api.CatalogItem{}, false, err
	}
	return installItem(r.ID, r.Name, r.Description, r.Version, r.Spec, r.RegistryID, r.RegistryTrust, r.RegistryWorkspaceID), true, nil
}

// MarkInstalled is mark_installed.
func (Installs) MarkInstalled(ctx context.Context, s db.Session, itemID, entityID uuid.UUID, version *string) error {
	v := pgtype.Text{}
	if version != nil {
		v = pgtype.Text{String: *version, Valid: true}
	}
	return New(s.Q()).MarkItemInstalled(ctx, MarkItemInstalledParams{ID: uuid.New(), RegistryItemID: itemID,
		WorkspaceID: s.Workspace().ID(), InstalledEntityID: entityID, InstalledVersion: v})
}

// SkillVersions is versions_for.
func (Installs) SkillVersions(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]api.ItemVersions, error) {
	rows, err := New(s.Q()).SkillItemVersions(ctx, SkillItemVersionsParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[string]api.ItemVersions, len(rows))
	for _, r := range rows {
		out[r.ID.String()] = api.ItemVersions{Current: fromText(r.Version), Installed: fromText(r.InstalledVersion)}
	}
	return out, nil
}

// SkillProvenance is provenance_for.
func (Installs) SkillProvenance(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]api.ItemSource, error) {
	rows, err := New(s.Q()).SkillProvenance(ctx, SkillProvenanceParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[string]api.ItemSource, len(rows))
	for _, r := range rows {
		out[r.ID.String()] = api.ItemSource{RegistryID: r.RegistryID.String(), Trust: r.RegistryTrust}
	}
	return out, nil
}
