package connections

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/handlers"
)

// PlatformOpenAPI, PlatformMCPServers and PlatformConnectorTools serve the
// openapi_connections, mcp_servers and tools toolsets. Each reads the service
// as last built, and the workspace slugs from the toolset providers, on every call.
func (m *Module) PlatformOpenAPI() api.PlatformOpenAPI { return platformOpenAPI{m} }

func (m *Module) PlatformMCPServers() api.PlatformMCPServers { return platformMCPServers{m} }

func (m *Module) PlatformConnectorTools() api.PlatformConnectorTools {
	return platformConnectorTools{m}
}

type platformOpenAPI struct{ m *Module }

func (p platformOpenAPI) h() handlers.OpenAPIToolset { return handlers.OpenAPIToolset{Svc: p.m.svc} }

func (p platformOpenAPI) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.OpenAPIConnection, error) {
	return p.h().Create(ctx, c, doc)
}

func (p platformOpenAPI) List(ctx context.Context, c authn.Caller, search string, limit, offset int) ([]api.OpenAPIConnection, int, error) {
	return p.h().List(ctx, c, search, limit, offset)
}

func (p platformOpenAPI) Get(ctx context.Context, c authn.Caller, id string) (api.OpenAPIConnection, error) {
	return p.h().Get(ctx, c, id)
}

func (p platformOpenAPI) Update(ctx context.Context, c authn.Caller, id string, doc json.RawMessage) (api.OpenAPIConnection, error) {
	return p.h().Update(ctx, c, id, doc)
}

func (p platformOpenAPI) DiscoverTools(ctx context.Context, c authn.Caller, id string) (api.OpenAPIDiscovery, error) {
	return p.h().DiscoverTools(ctx, c, id)
}

func (p platformOpenAPI) Delete(ctx context.Context, c authn.Caller, id string) (bool, error) {
	return p.h().Delete(ctx, c, id)
}

type platformMCPServers struct{ m *Module }

func (p platformMCPServers) h() handlers.MCPServersToolset {
	return handlers.MCPServersToolset{Svc: p.m.svc, Slugs: p.m.providers().Slugs}
}

func (p platformMCPServers) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.MCPInstance, error) {
	return p.h().Create(ctx, c, doc)
}

func (p platformMCPServers) Update(ctx context.Context, c authn.Caller, id string, doc json.RawMessage) (api.MCPInstance, error) {
	return p.h().Update(ctx, c, id, doc)
}

func (p platformMCPServers) List(ctx context.Context, c authn.Caller) ([]api.MCPInstance, error) {
	return p.h().List(ctx, c)
}

func (p platformMCPServers) Get(ctx context.Context, c authn.Caller, id string) (api.MCPInstance, error) {
	return p.h().Get(ctx, c, id)
}

func (p platformMCPServers) Delete(ctx context.Context, c authn.Caller, id string) (bool, error) {
	return p.h().Delete(ctx, c, id)
}

func (p platformMCPServers) Verify(ctx context.Context, c authn.Caller, id string) (any, *api.ConnectAction, error) {
	return p.h().Verify(ctx, c, id)
}

type platformConnectorTools struct{ m *Module }

func (p platformConnectorTools) h() handlers.ConnectorToolsToolset {
	return handlers.ConnectorToolsToolset{Svc: p.m.svc, Slugs: p.m.providers().Slugs}
}

func (p platformConnectorTools) Searchable(ctx context.Context, c authn.Caller, connector *string) ([]api.Connector, error) {
	return p.h().Searchable(ctx, c, connector)
}

func (p platformConnectorTools) Call(ctx context.Context, c authn.Caller, connector, tool string, args json.RawMessage, confirm bool) (api.ConnectorCall, error) {
	return p.h().Call(ctx, c, connector, tool, args, confirm)
}

func (p platformMCPServers) GetSpec(ctx context.Context, c authn.Caller, id string) (api.MCPSpec, error) {
	return p.h().GetSpec(ctx, c, id)
}

func (p platformMCPServers) CreateSpec(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.MCPSpec, error) {
	return p.h().CreateSpec(ctx, c, doc)
}

func (p platformMCPServers) UpdateSpec(ctx context.Context, c authn.Caller, id string, doc json.RawMessage) (api.MCPSpec, error) {
	return p.h().UpdateSpec(ctx, c, id, doc)
}

func (p platformMCPServers) DeleteSpec(ctx context.Context, c authn.Caller, id string) (bool, error) {
	return p.h().DeleteSpec(ctx, c, id)
}

func (p platformMCPServers) ListSpecs(ctx context.Context, c authn.Caller, q api.SpecListing) ([]api.MCPSpec, int, error) {
	return p.h().ListSpecs(ctx, c, q)
}
