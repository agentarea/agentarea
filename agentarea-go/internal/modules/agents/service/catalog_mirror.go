package service

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// CatalogMirror is CatalogMirror: it stores the package of every item of a
// mirror-mode skills registry as the registry syncs, so an install reads no network.
type CatalogMirror struct{ K *Skills }

var _ catalogapi.ContentMirror = CatalogMirror{}

// ErrPrivateMirror is a GitHub-pointer item of a registry read with credentials.
var ErrPrivateMirror = errors.New("mirroring a GitHub-pointer skill of a registry with credentials is not ported: only public repositories are read")

// Open is one sync's mirror. Once GitHub answers that the rate limit is spent
// it is not asked again in this sync; those items fail, the next sync retries them.
func (m CatalogMirror) Open(_ context.Context, _ string, workspaceID *string, token string) (catalogapi.ItemMirror, error) {
	if m.K.items == nil {
		return nil, m.K.unwiredCatalog()
	}
	if _, err := m.K.store(); err != nil {
		return nil, err
	}
	var limited error
	return func(ctx context.Context, spec map[string]any) (map[string]any, error) {
		if limited != nil {
			return nil, limited
		}
		if src, ok := spec["source"].(map[string]any); ok && src["type"] == "github" && token != "" {
			return nil, ErrPrivateMirror
		}
		p, err := m.K.catalogPackage(ctx, spec, workspaceID)
		var gh *domain.SkillGitHubError
		if errors.As(err, &gh) && gh.Kind == domain.SkillGitHubRateLimited {
			limited = err
		}
		if err != nil {
			return nil, err
		}
		out := map[string]any{"s3_path": p.s3Path, "source_url": nil}
		if p.sourceURL != nil {
			out["source_url"] = *p.sourceURL
		}
		if p.treeSHA != nil {
			out["tree_sha"] = *p.treeSHA
		}
		return out, nil
	}, nil
}
