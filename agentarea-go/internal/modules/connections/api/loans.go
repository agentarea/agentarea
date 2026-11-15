package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// Loans binds an agent's MCP tools to connections and lends connections to
// agents (AgentService._bind_mcp_tools, _sync_connection_loans).
type Loans interface {
	// BindMCPName is the id of the one MCP connection named name that is the
	// caller's or the platform's; "" when none carries the name. A name several
	// connections carry, or only someone else's, is an *MCPNameError when
	// refuseUnbound, else "".
	BindMCPName(ctx context.Context, c authn.Caller, name string, refuseUnbound bool) (string, error)
	// Lend lets the agent call through the connection, whoever runs it.
	Lend(ctx context.Context, connectionID, agentID string) error
	// Withdraw takes the loan back.
	Withdraw(ctx context.Context, connectionID, agentID string) error
}

// MCPNameError is an MCP tool name that does not bind to one connection (InvalidMcpToolError).
type MCPNameError struct{ Detail string }

func (e *MCPNameError) Error() string { return e.Detail }
