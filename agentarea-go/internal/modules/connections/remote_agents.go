package connections

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

// RemoteAgents is what runs call remote A2A delegates through. It reads the service as last
// built, so the wallets UseWallets sets reach it.
func (m *Module) RemoteAgents() api.RemoteAgents { return remoteAgents{m} }

type remoteAgents struct{ m *Module }

func (r remoteAgents) CallRemoteAgent(ctx context.Context, call api.RemoteAgentCall) (api.RemoteAgentResult, error) {
	return r.m.svc.CallRemoteAgent(ctx, call)
}
