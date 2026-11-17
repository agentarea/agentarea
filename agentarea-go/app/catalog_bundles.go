package app

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog"
)

// catalogBundles are the owners a bundle deploy writes through; the edit
// check is the one each entity's own update route makes.
func catalogBundles(d coreDeps, m *moduleSet) catalog.BundleDeps {
	perms := authz.NewPermissions(d.Graph, d.Log)
	return catalog.BundleDeps{DB: d.DB, Agents: m.agents.Bundles(), MCPs: m.connections.Bundles(), Triggers: m.streams.Bundles(),
		Rules: m.governance.Bundles(), Models: m.models.Resolver(),
		MayEdit: func(ctx context.Context, c authn.Caller, resourceType, id string) (bool, error) {
			return perms.Check(ctx, c.GraphSubject(), "edit", resourceType, id)
		}}
}
