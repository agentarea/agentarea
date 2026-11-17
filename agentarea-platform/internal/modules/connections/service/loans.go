package service

import (
	"context"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// NamedStore reads MCP server instances by name (store.Lookup).
type NamedStore interface {
	MCPInstancesNamed(ctx context.Context, s db.Session, name string) ([]store.NamedInstance, error)
}

// Loans implements api.Loans over the read pool and the graph.
type Loans struct {
	DB    db.Database
	Store NamedStore
	Graph authz.Writer
}

var _ api.Loans = Loans{}

// BindMCPName is the name half of AgentService._bind_mcp_tools.
func (l Loans) BindMCPName(ctx context.Context, c authn.Caller, name string, refuseUnbound bool) (string, error) {
	s, release, err := l.DB.Read(ctx, c.Workspace)
	if err != nil {
		return "", err
	}
	matches, err := l.Store.MCPInstancesNamed(ctx, s, name)
	release()
	if err != nil || len(matches) == 0 {
		return "", err
	}
	m := matches[0]
	if len(matches) == 1 && ((m.ManagedBy != nil && *m.ManagedBy == domain.ManagedByPlatform) || m.CreatedBy == c.UserID) {
		return m.ID.String(), nil
	}
	if !refuseUnbound {
		return "", nil
	}
	reason := fmt.Sprintf("the MCP connection named '%s' was added by someone else", name)
	if len(matches) > 1 {
		reason = fmt.Sprintf("%d MCP connections here are named '%s'", len(matches), name)
	}
	return "", &api.MCPNameError{Detail: reason + "; name the one to use by its id."}
}

// Lend is lend_connection.
func (l Loans) Lend(ctx context.Context, connectionID, agentID string) error {
	return authz.LendConnection(ctx, l.Graph, connectionID, agentID)
}

// Withdraw is withdraw_connection.
func (l Loans) Withdraw(ctx context.Context, connectionID, agentID string) error {
	return authz.WithdrawConnection(ctx, l.Graph, connectionID, agentID)
}
