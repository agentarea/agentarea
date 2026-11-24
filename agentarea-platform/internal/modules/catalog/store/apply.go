package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

// AllItems is list_by_registry with no page: every item, by lower(name).
func (Registries) AllItems(ctx context.Context, s db.Session, registryID string) ([]domain.Item, error) {
	u, ok := parseID(registryID)
	if !ok {
		return nil, nil
	}
	rows, err := New(s.Q()).AllRegistryItems(ctx, u)
	if err != nil {
		return nil, err
	}
	return items(rows), nil
}

// MarkItemApplied clears update_available and records the applied version.
func (Registries) MarkItemApplied(ctx context.Context, s db.Session, id, installedVersion string, now time.Time) error {
	u, ok := parseID(id)
	if !ok {
		return nil
	}
	return New(s.Q()).MarkItemApplied(ctx, MarkItemAppliedParams{
		ID: u, InstalledVersion: text(&installedVersion), Now: naive(now),
	})
}

// MirroredServer is what _update_mcp_server writes onto an installed
// mcp_servers row; the JSON fields are json.dumps text.
type MirroredServer struct {
	Description    string
	DockerImageURL *string
	Version        string
	Tags           []byte
	EnvSchema      []byte
	Cmd            []byte
	RemoteURL      *string
	JSONSpec       []byte
	RegistryURL    string
}

// UpdateMirroredServer rewrites the session's workspace's server id; false
// when the workspace has no such row.
func (Registries) UpdateMirroredServer(ctx context.Context, s db.Session, id string, m MirroredServer, now time.Time) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	n, err := New(s.Q()).UpdateMirroredServer(ctx, UpdateMirroredServerParams{
		Description: m.Description, DockerImageUrl: text(m.DockerImageURL), Version: m.Version,
		Tags: m.Tags, EnvSchema: m.EnvSchema, Cmd: m.Cmd, RemoteUrl: text(m.RemoteURL), JsonSpec: m.JSONSpec,
		RegistryUrl: text(&m.RegistryURL), Now: naive(now), ID: u, WorkspaceID: s.Workspace().ID(),
	})
	return n > 0, err
}
