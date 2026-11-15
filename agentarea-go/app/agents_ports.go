package app

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	agentsdomain "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
)

// agentLoans is connections' binding and loans as agents asks for them; an
// MCP name that binds to no one connection is agents' invalid_mcp_tool.
type agentLoans struct{ l connectionsapi.Loans }

var _ agentsservice.Connections = agentLoans{}

func newAgentLoans(l connectionsapi.Loans) agentsservice.Connections {
	if l == nil {
		return nil
	}
	return agentLoans{l: l}
}

func (a agentLoans) BindMCPName(ctx context.Context, c authn.Caller, name string, refuseUnbound bool) (string, error) {
	id, err := a.l.BindMCPName(ctx, c, name, refuseUnbound)
	var ne *connectionsapi.MCPNameError
	if errors.As(err, &ne) {
		return "", &agentsdomain.InvalidError{Code: agentsdomain.CodeInvalidMCPTool, Detail: ne.Detail}
	}
	return id, err
}

func (a agentLoans) Lend(ctx context.Context, connectionID, agentID string) error {
	return a.l.Lend(ctx, connectionID, agentID)
}

func (a agentLoans) Withdraw(ctx context.Context, connectionID, agentID string) error {
	return a.l.Withdraw(ctx, connectionID, agentID)
}

// clientRunnerKeys is identity's runner keys as agents' client routes ask for them.
type clientRunnerKeys struct{ k identityapi.RunnerKeys }

var _ agentsservice.ClientRunnerKeys = clientRunnerKeys{}

func runnerKeyOf(k identityapi.RunnerKey) agentsservice.ClientRunnerKey {
	return agentsservice.ClientRunnerKey{ID: k.ID, Name: k.Name, Prefix: k.Prefix, CreatedBy: k.CreatedBy, CreatedAt: k.CreatedAt,
		LastUsedAt: k.LastUsedAt, ClientID: k.ClientID, Active: k.Active}
}

func (r clientRunnerKeys) Issue(ctx context.Context, c authn.Caller, clientID, name string) (agentsservice.ClientRunnerKey, string, error) {
	k, secret, err := r.k.Issue(ctx, c, clientID, name)
	return runnerKeyOf(k), secret, err
}

func (r clientRunnerKeys) List(ctx context.Context, c authn.Caller, clientID string) ([]agentsservice.ClientRunnerKey, error) {
	keys, err := r.k.List(ctx, c, clientID)
	if err != nil {
		return nil, err
	}
	out := make([]agentsservice.ClientRunnerKey, 0, len(keys))
	for _, k := range keys {
		out = append(out, runnerKeyOf(k))
	}
	return out, nil
}

func (r clientRunnerKeys) Get(ctx context.Context, c authn.Caller, keyID string) (agentsservice.ClientRunnerKey, bool, error) {
	k, ok, err := r.k.Get(ctx, c, keyID)
	return runnerKeyOf(k), ok, err
}

func (r clientRunnerKeys) Revoke(ctx context.Context, c authn.Caller, keyID string) error {
	return r.k.Revoke(ctx, c, keyID)
}
