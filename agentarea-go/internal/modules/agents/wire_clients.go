package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// ClientDeps are the ports only the client routes (registered harnesses, runner keys) need.
type ClientDeps struct {
	// ClientAPIURL is AppSettings.API_URL, the base of each client's mcp_endpoint_url.
	ClientAPIURL string
	// ClientMCPNames names visible MCP instances (connections api.Lookup); nil answers 501
	// for a client with MCP instances attached.
	ClientMCPNames service.ClientMCPNames
	// ClientConnections checks and names MCP instances and OpenAPI connections; nil answers
	// 501 for attaching them and for a client with OpenAPI connections.
	ClientConnections service.ClientConnections
	// ClientRunnerKeys issues and revokes runner keys (identity); nil answers 501.
	ClientRunnerKeys service.ClientRunnerKeys
}

func (m *Module) clients() *service.Clients {
	return service.NewClients(m.svc, service.ClientPorts{
		APIURL: m.d.ClientAPIURL, MCPNames: m.d.ClientMCPNames, Connections: m.d.ClientConnections, RunnerKeys: m.d.ClientRunnerKeys,
	})
}

// ClientsToolset is what the platform MCP clients toolset calls; nil without a full graph.
func (m *Module) ClientsToolset() api.Clients {
	if m.svc == nil {
		return nil
	}
	return handlers.ClientsToolset{Svc: m.svc, Clients: m.clients()}
}
