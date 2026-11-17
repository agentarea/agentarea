package agents

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// SkillDeps are the ports only the skill routes (skills, packages, GitHub import, catalog update) need.
// Packages live in Deps.Blob (the artifacts bucket); nil Blob answers 501 for every route that reads one.
type SkillDeps struct {
	// SkillNet carries the GitHub import out through the Vendor destination; nil answers 501 for it.
	SkillNet netguard.Clients
	// SkillCatalog moves installs between catalog versions (update, rollback, repin);
	// nil is service.CatalogSkills over CatalogItems.
	SkillCatalog service.SkillCatalog
	// SkillInstallPolicy is the catalog install policy over GitHub imports; nil answers 501 for them.
	SkillInstallPolicy service.SkillInstallPolicy
	// CatalogItems are the catalog's skill and agent items; nil answers 501 for installing one and refuses runs of installed skills.
	CatalogItems service.CatalogItems
}

var errSkillNoGraph = errors.New("agents: the graph passed to agents.New is not a full authz.Graph")

func (m *Module) skills() *service.Skills {
	if m.svc == nil {
		return nil
	}
	p := service.SkillPorts{Blob: m.d.Blob, Catalog: m.d.SkillCatalog, Items: m.d.CatalogItems, InstallPolicy: m.d.SkillInstallPolicy}
	if m.d.SkillNet != nil {
		p.GitHub = m.d.SkillNet.Transport(netguard.Vendor)
	}
	k := service.NewSkills(m.svc, p)
	if p.Catalog == nil && p.Items != nil {
		k.UseCatalog(service.CatalogSkills{K: k})
	}
	return k
}

// SkillsToolset is what the platform MCP skills toolset calls; nil without a full graph.
func (m *Module) SkillsToolset() api.Skills {
	if m.svc == nil {
		return nil
	}
	return service.SkillToolset{K: m.skills()}
}

// RunSkills is what a run reads of skills: the ones it offers and their packages; nil without a full graph.
func (m *Module) RunSkills() api.RunSkills {
	if m.svc == nil {
		return nil
	}
	return service.RunSkills{K: m.skills()}
}

// SkillsMoveBodiesToPackages is `agentarea-api skills move-bodies-to-packages`.
func (m *Module) SkillsMoveBodiesToPackages(ctx context.Context) (moved, failed int, err error) {
	if m.svc == nil {
		return 0, 0, errSkillNoGraph
	}
	return m.skills().MoveBodiesToPackages(ctx)
}

// SkillsMoveOwnCopiesToPackages is `agentarea-api skills move-own-copies-to-packages`.
func (m *Module) SkillsMoveOwnCopiesToPackages(ctx context.Context) (moved, failed int, err error) {
	if m.svc == nil {
		return 0, 0, errSkillNoGraph
	}
	return m.skills().MoveOwnCopiesToPackages(ctx)
}

// SkillsDeleteMovedOwnCopies is `agentarea-api skills delete-moved-own-copies`;
// minAge zero is service.SkillMovedCopyMinAge.
func (m *Module) SkillsDeleteMovedOwnCopies(ctx context.Context, dryRun bool, minAge time.Duration) (prefixes, objects int, err error) {
	if m.svc == nil {
		return 0, 0, errSkillNoGraph
	}
	if minAge == 0 {
		minAge = service.SkillMovedCopyMinAge
	}
	return m.skills().DeleteMovedOwnCopies(ctx, dryRun, minAge)
}

// SkillsRepinCatalogInstalls is `agentarea-api skills repin-catalog-installs`.
func (m *Module) SkillsRepinCatalogInstalls(ctx context.Context, dryRun bool) ([]service.SkillJobResult, error) {
	if m.svc == nil {
		return nil, errSkillNoGraph
	}
	return m.skills().RepinCatalogInstalls(ctx, dryRun)
}

// SkillsRefreshStubInstalls is `agentarea-api skills refresh-stub-installs`.
func (m *Module) SkillsRefreshStubInstalls(ctx context.Context, dryRun bool) ([]service.SkillJobResult, error) {
	if m.svc == nil {
		return nil, errSkillNoGraph
	}
	return m.skills().RefreshStubInstalls(ctx, dryRun)
}

// CatalogMirror stores a mirror-mode skills registry's packages as it syncs;
// it reads the catalog ports at sync time, after Use.
func (m *Module) CatalogMirror() catalogapi.ContentMirror { return lateMirror{m: m} }

type lateMirror struct{ m *Module }

func (l lateMirror) Open(ctx context.Context, registryID string, workspaceID *string, token string) (catalogapi.ItemMirror, error) {
	if l.m.svc == nil {
		return nil, errSkillNoGraph
	}
	return service.CatalogMirror{K: l.m.skills()}.Open(ctx, registryID, workspaceID, token)
}
