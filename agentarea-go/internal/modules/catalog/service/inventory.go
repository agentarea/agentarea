package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

// MCPInventory implements api.MCPInventory over the read pool.
type MCPInventory struct{ DB db.Database }

var _ api.MCPInventory = MCPInventory{}

func (i MCPInventory) MCPServers(ctx context.Context, ws scope.Workspace) ([]api.MCPServer, error) {
	s, release, err := i.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	rows, err := store.New(s.Q()).WorkspaceMCPServers(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]api.MCPServer, 0, len(rows))
	for _, r := range rows {
		out = append(out, api.MCPServer{ID: r.ID.String(), Name: r.Name})
	}
	return out, nil
}

func (i MCPInventory) MCPServerExists(ctx context.Context, ws scope.Workspace, id uuid.UUID) (bool, error) {
	s, release, err := i.DB.Read(ctx, ws)
	if err != nil {
		return false, err
	}
	defer release()
	return store.New(s.Q()).WorkspaceMCPServerExists(ctx, store.WorkspaceMCPServerExistsParams{WorkspaceID: s.Workspace().ID(), ID: id})
}
