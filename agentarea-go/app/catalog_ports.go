package app

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

// platformWorkspaceID is PLATFORM_WORKSPACE_ID and PLATFORM_PRINCIPAL_ID.
const platformWorkspaceID = "platform"

// Registry credentials appear among a secret's consumers under these names
// (registry_credentials.py).
const (
	registrySecretConsumer = "registry"
	registrySecretField    = "credentials"
)

// catalogItemUses is catalog's ItemUses composed of the owners' parts:
// agents (skills, agents), connections (OpenAPI connections, MCP instances)
// and models (provider configs, model instances).
type catalogItemUses struct {
	agents      agentsapi.CatalogUses
	connections connectionsapi.CatalogUses
	models      modelsapi.SpecUses
}

var _ catalogapi.ItemUses = catalogItemUses{}

func (u catalogItemUses) MoveItemUses(ctx context.Context, tx db.Session, moves []catalogapi.ItemMove) (int, error) {
	total := 0
	for _, m := range moves {
		n, err := u.agents.MoveItem(ctx, tx, m.Old, m.New)
		if err != nil {
			return 0, err
		}
		c, err := u.connections.MoveItem(ctx, tx, m.Old, m.New, m.OldCopy, m.NewCopy)
		if err != nil {
			return 0, err
		}
		total += n + c
	}
	return total, nil
}

func (u catalogItemUses) ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	out, err := u.agents.ReferencedItems(ctx, tx, ids)
	if err != nil {
		return nil, err
	}
	conns, err := u.connections.ReferencedItems(ctx, tx, ids)
	if err != nil {
		return nil, err
	}
	for id := range conns {
		out[id] = true
	}
	return out, nil
}

func (u catalogItemUses) UsedProviderSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	return u.models.UsedProviderSpecs(ctx, tx, ids)
}

func (u catalogItemUses) UsedModelSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	return u.models.UsedModelSpecs(ctx, tx, ids)
}

func (u catalogItemUses) DropPlatformSkills(ctx context.Context, tx db.Session, ids []uuid.UUID) error {
	return u.agents.DropPlatformSkills(ctx, tx, ids)
}

// lateItemUses resolves catalogItemUses at sync time: models is built after catalog.
type lateItemUses struct{ m *moduleSet }

func (l lateItemUses) uses() catalogItemUses {
	return catalogItemUses{agents: l.m.agents.CatalogUses(), connections: l.m.connections.CatalogUses(), models: l.m.models.SpecUses()}
}

func (l lateItemUses) MoveItemUses(ctx context.Context, tx db.Session, moves []catalogapi.ItemMove) (int, error) {
	return l.uses().MoveItemUses(ctx, tx, moves)
}

func (l lateItemUses) ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	return l.uses().ReferencedItems(ctx, tx, ids)
}

func (l lateItemUses) UsedProviderSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	return l.uses().UsedProviderSpecs(ctx, tx, ids)
}

func (l lateItemUses) UsedModelSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	return l.uses().UsedModelSpecs(ctx, tx, ids)
}

func (l lateItemUses) DropPlatformSkills(ctx context.Context, tx db.Session, ids []uuid.UUID) error {
	return l.uses().DropPlatformSkills(ctx, tx, ids)
}

func workspaceOf(id string) (scope.Workspace, error) { return scope.NewWorkspace(id, id) }

// registryCredentials is registry_credentials_resolver: the value of the
// secret a registry names, read from its workspace's backend for one sync.
func registryCredentials(database db.Database, f *secrets.Factory) catalogapi.RegistryCredentials {
	return func(ctx context.Context, workspaceID, secretID string) (string, error) {
		ws, err := workspaceOf(workspaceID)
		if err != nil {
			return "", err
		}
		sess, release, err := database.Read(ctx, ws)
		if err != nil {
			return "", err
		}
		defer release()
		store := secrets.NewSession(f)
		sec, ok, err := store.Secret(ctx, sess, secretID)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", fmt.Errorf("registry credentials: secret %s is not in workspace %s", secretID, workspaceID)
		}
		value, err := store.Manager(sess, platformWorkspaceID).Get(ctx, sec.Name)
		if errors.Is(err, ksecrets.ErrNotFound) || (err == nil && value == "") {
			return "", fmt.Errorf("registry credentials: secret '%s' holds no value", sec.Name)
		}
		return value, err
	}
}

// platformSecrets is platform_secret_id and record_registry_secret_reference.
type platformSecrets struct {
	db db.Database
	f  *secrets.Factory
}

var _ catalogapi.PlatformSecrets = platformSecrets{}

func (p platformSecrets) SecretID(ctx context.Context, ref string) (string, error) {
	ws, err := workspaceOf(platformWorkspaceID)
	if err != nil {
		return "", err
	}
	sess, release, err := p.db.Read(ctx, ws)
	if err != nil {
		return "", err
	}
	defer release()
	store := secrets.NewSession(p.f)
	var sec ksecrets.Secret
	var ok bool
	if _, perr := uuid.Parse(ref); perr == nil {
		sec, ok, err = store.Secret(ctx, sess, ref)
	} else {
		sec, ok, err = store.SecretNamed(ctx, sess, ref)
	}
	if err != nil {
		return "", err
	}
	if !ok {
		return "", fmt.Errorf("credentials_secret_ref '%s' names no secret of the platform workspace", ref)
	}
	return sec.ID, nil
}

func (p platformSecrets) RecordReference(ctx context.Context, registryID string, secretID *string) error {
	ws, err := workspaceOf(platformWorkspaceID)
	if err != nil {
		return err
	}
	var refs []ksecrets.Reference
	if secretID != nil {
		refs = []ksecrets.Reference{{SecretID: *secretID, Field: registrySecretField}}
	}
	return p.db.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return secrets.NewSession(p.f).StageReferences(ctx, sess, registrySecretConsumer, registryID, refs)
	})
}
