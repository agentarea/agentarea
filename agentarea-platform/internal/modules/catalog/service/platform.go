package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// PlatformPrincipal is the created_by of every row the operator writes.
const PlatformPrincipal = "platform"

// PlatformWorkspace is the workspace platform rows live in.
const PlatformWorkspace = "platform"

// Platform implements api.PlatformDeclarations.
type Platform struct{ s *Service }

var _ api.PlatformDeclarations = Platform{}

// Platform is the operator's writes.
func (s *Service) Platform() Platform { return Platform{s: s} }

func (p Platform) ProviderSpecID(ctx context.Context, key string) (uuid.UUID, bool, error) {
	ws, err := scope.NewWorkspace(PlatformWorkspace, "")
	if err != nil {
		return uuid.Nil, false, err
	}
	spec, ok, err := p.s.Specs().ProviderSpecByKey(ctx, ws, key)
	return spec.ID, ok, err
}

func (p Platform) DeclareModelSpecs(ctx context.Context, workspaceID string, providerSpecID uuid.UUID, specs []api.DeclaredModelSpec) (map[string]uuid.UUID, error) {
	ws, err := scope.NewWorkspace(workspaceID, "")
	if err != nil {
		return nil, err
	}
	out := make(map[string]uuid.UUID, len(specs))
	err = p.s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		now := p.s.d.Now()
		for _, m := range specs {
			id, err := store.Platform{}.DeclareModelSpec(ctx, sess, providerSpecID, PlatformPrincipal, m, now)
			if err != nil {
				return err
			}
			out[m.ModelName] = id
		}
		return nil
	})
	return out, err
}

func (p Platform) CatalogItem(ctx context.Context, externalID string) (uuid.UUID, map[string]any, bool, error) {
	q, release, err := p.s.d.DB.Global().Read(ctx)
	if err != nil {
		return uuid.Nil, nil, false, err
	}
	defer release()
	return store.Platform{}.CatalogItem(ctx, q, externalID)
}

func (p Platform) DeclareMCPServer(ctx context.Context, m api.PlatformMCPServer) (changed bool, err error) {
	ws, err := scope.NewWorkspace(PlatformWorkspace, "")
	if err != nil {
		return false, err
	}
	err = p.s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		slug := func() (string, error) {
			return scope.UniqueSlug(scope.EntitySlug(m.Name), func(c string) (bool, error) {
				return store.Platform{}.MCPSlugTaken(ctx, sess, c)
			})
		}
		changed, err = store.Platform{}.DeclareMCPServer(ctx, sess, m, slug, PlatformPrincipal, p.s.d.Now())
		return err
	})
	return changed, err
}
