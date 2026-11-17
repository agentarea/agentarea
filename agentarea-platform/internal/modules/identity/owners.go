package identity

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/store"
)

// WorkspaceOwners is who owns a workspace, read by other modules.
func (m *Module) WorkspaceOwners() api.WorkspaceOwners {
	return service.WorkspaceOwners{DB: m.d.DB, Store: store.Store{}}
}

// MessengerLinks is the link handshake messenger bots run for their senders.
func (m *Module) MessengerLinks() api.MessengerLinks { return m.svc }
