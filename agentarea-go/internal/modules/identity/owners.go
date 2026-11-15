package identity

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
)

// WorkspaceOwners is who owns a workspace, read by other modules.
func (m *Module) WorkspaceOwners() api.WorkspaceOwners {
	return service.WorkspaceOwners{DB: m.d.DB, Store: store.Store{}}
}
