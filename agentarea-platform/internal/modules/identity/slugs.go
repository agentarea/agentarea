package identity

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/store"
)

// WorkspaceSlugs is what other modules read about a workspace's slug.
func (m *Module) WorkspaceSlugs() api.WorkspaceSlugs {
	return service.WorkspaceSlugs{DB: m.d.DB, Store: store.Store{}}
}
