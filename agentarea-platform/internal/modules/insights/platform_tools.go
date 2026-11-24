package insights

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/handlers"
)

// PlatformNetwork is what the platform network toolset calls; it reads the
// service as last built, so the reads Use sets reach it.
func (m *Module) PlatformNetwork() api.PlatformNetwork { return platformNetwork{m} }

type platformNetwork struct{ m *Module }

func (n platformNetwork) Topology(ctx context.Context, c authn.Caller) (any, error) {
	if n.m.later == nil {
		return nil, errNotWired
	}
	return handlers.PlatformTopology(ctx, n.m.svc, c)
}
