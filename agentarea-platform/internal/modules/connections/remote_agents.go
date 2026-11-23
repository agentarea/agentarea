package connections

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

// RemoteAgents is what runs call remote A2A delegates through. It reads the service as last
// built, so the wallets UseWallets sets reach it.
func (m *Module) RemoteAgents() api.RemoteAgents { return remoteAgents{m} }

type remoteAgents struct{ m *Module }

func (r remoteAgents) SendRemoteAgent(ctx context.Context, call api.RemoteAgentCall) (api.RemoteAgentResult, error) {
	return r.m.svc.SendRemoteAgent(ctx, call)
}

func (r remoteAgents) GetRemoteAgentTask(ctx context.Context, call api.RemoteTaskCall) (api.RemoteAgentResult, error) {
	return r.m.svc.GetRemoteAgentTask(ctx, call)
}

func (r remoteAgents) CancelRemoteAgentTask(ctx context.Context, call api.RemoteTaskCall) error {
	return r.m.svc.CancelRemoteAgentTask(ctx, call)
}
