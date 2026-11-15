package handlers

import (
	"context"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// clientStored is a JSON column as Python reads it; nil for SQL NULL.
func clientStored(raw []byte) (any, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	return wirejson.Unmarshal(raw)
}

func clientLinksJSON(links []service.ClientLinkRef) ([]any, error) {
	out := make([]any, len(links))
	for i, l := range links {
		allowed, err := clientStored(l.AllowedTools)
		if err != nil {
			return nil, err
		}
		out[i] = wirejson.Object{{Key: "id", Value: l.ID}, {Key: "name", Value: l.Name},
			{Key: "namespace_prefix", Value: orNil(l.NamespacePrefix)}, {Key: "allowed_tools", Value: allowed}}
	}
	return out, nil
}

// clientJSON is ClientResponse.
func clientJSON(v service.ClientView) (wirejson.Object, error) {
	skills := make([]any, len(v.Skills))
	for i, s := range v.Skills {
		skills[i] = wirejson.Object{{Key: "id", Value: s.ID}, {Key: "name", Value: s.Name}}
	}
	mcp, err := clientLinksJSON(v.MCPInstances)
	if err != nil {
		return nil, err
	}
	openapi, err := clientLinksJSON(v.OpenAPIConnections)
	if err != nil {
		return nil, err
	}
	toolsets := make([]any, len(v.Toolsets))
	for i, t := range v.Toolsets {
		disabled, err := clientStored(t.DisabledMethods)
		if err != nil {
			return nil, err
		}
		toolsets[i] = wirejson.Object{{Key: "name", Value: t.Toolset}, {Key: "disabled_methods", Value: disabled}}
	}
	models, err := clientStored(v.Models)
	if err != nil {
		return nil, err
	}
	domains, err := clientStored(v.AllowDomains)
	if err != nil {
		return nil, err
	}
	if domains == nil {
		domains = []any{}
	}
	return wirejson.Object{
		{Key: "id", Value: v.ID.String()}, {Key: "workspace_id", Value: v.WorkspaceID}, {Key: "created_by", Value: v.CreatedBy},
		{Key: "name", Value: v.Name}, {Key: "description", Value: orNil(v.Description)}, {Key: "kind", Value: v.Kind},
		{Key: "skills", Value: skills}, {Key: "mcp_instances", Value: mcp}, {Key: "openapi_connections", Value: openapi},
		{Key: "platform_toolsets", Value: toolsets}, {Key: "mcp_endpoint_url", Value: v.EndpointURL},
		{Key: "models", Value: models}, {Key: "default_model", Value: orNil(v.DefaultModel)}, {Key: "allow_domains", Value: domains},
		{Key: "sandbox", Value: v.Sandbox}, {Key: "online", Value: v.Online}, {Key: "has_runner", Value: v.HasRunner},
	}, nil
}

// clientToolsetsJSON is platform_toolset_catalog().
func clientToolsetsJSON() []any {
	all := domain.ClientPlatformToolsets()
	out := make([]any, len(all))
	for i, t := range all {
		methods := make([]any, len(t.Methods))
		for j, m := range t.Methods {
			var effect any
			if m.Effect != "" {
				effect = m.Effect
			}
			methods[j] = wirejson.Object{{Key: "name", Value: m.Name}, {Key: "display_name", Value: m.DisplayName},
				{Key: "description", Value: m.Description}, {Key: "effect", Value: effect}}
		}
		out[i] = wirejson.Object{{Key: "name", Value: t.Namespace}, {Key: "display_name", Value: t.DisplayName},
			{Key: "description", Value: t.Description}, {Key: "methods", Value: methods}}
	}
	return out
}

func clientKeyJSON(k service.ClientRunnerKey) wirejson.Object {
	var last any
	if k.LastUsedAt != nil {
		last = domain.TaskDefISOZ(*k.LastUsedAt)
	}
	return wirejson.Object{{Key: "id", Value: k.ID}, {Key: "name", Value: k.Name}, {Key: "prefix", Value: k.Prefix},
		{Key: "created_by", Value: k.CreatedBy}, {Key: "created_at", Value: domain.TaskDefISOZ(k.CreatedAt)}, {Key: "last_used_at", Value: last}}
}

func (s *Server) clientOne(ctx context.Context, status int, get func() (service.ClientView, error)) (response, error) {
	v, err := get()
	if err != nil {
		return response{}, err
	}
	body, err := clientJSON(v)
	if err != nil {
		return response{}, err
	}
	return response{status: status, body: body}, nil
}

func (s *Server) ListClientsV1ClientsGet(ctx context.Context, _ gen.ListClientsV1ClientsGetRequestObject) (gen.ListClientsV1ClientsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := areaInput[clientInput](ctx)
	vs, err := s.ext.Clients.List(ctx, c, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(vs))
	for i, v := range vs {
		if out[i], err = clientJSON(v); err != nil {
			return nil, err
		}
	}
	return ok(out), nil
}

func (s *Server) CreateClientV1ClientsPost(ctx context.Context, _ gen.CreateClientV1ClientsPostRequestObject) (gen.CreateClientV1ClientsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := areaInput[clientInput](ctx)
	return s.clientOne(ctx, http.StatusCreated, func() (service.ClientView, error) {
		return s.ext.Clients.Create(ctx, c, in.name, in.description, in.kind)
	})
}

func (s *Server) ListPlatformToolsetsV1ClientsPlatformToolsetsGet(ctx context.Context, _ gen.ListPlatformToolsetsV1ClientsPlatformToolsetsGetRequestObject) (gen.ListPlatformToolsetsV1ClientsPlatformToolsetsGetResponseObject, error) {
	if _, err := caller(ctx); err != nil {
		return nil, err
	}
	return ok(clientToolsetsJSON()), nil
}

func (s *Server) GetClientV1ClientsClientIdGet(ctx context.Context, rq gen.GetClientV1ClientsClientIdGetRequestObject) (gen.GetClientV1ClientsClientIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	return s.clientOne(ctx, http.StatusOK, func() (service.ClientView, error) { return s.ext.Clients.Get(ctx, c, rq.ClientId) })
}

func (s *Server) UpdateClientV1ClientsClientIdPatch(ctx context.Context, rq gen.UpdateClientV1ClientsClientIdPatchRequestObject) (gen.UpdateClientV1ClientsClientIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := areaInput[clientInput](ctx)
	return s.clientOne(ctx, http.StatusOK, func() (service.ClientView, error) {
		return s.ext.Clients.Update(ctx, c, rq.ClientId, in.patch)
	})
}

func (s *Server) DeleteClientV1ClientsClientIdDelete(ctx context.Context, rq gen.DeleteClientV1ClientsClientIdDeleteRequestObject) (gen.DeleteClientV1ClientsClientIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.ext.Clients.Delete(ctx, c, rq.ClientId); err != nil {
		return nil, err
	}
	return noContent(), nil
}

func (s *Server) clientDo(ctx context.Context, fn func(c authn.Caller) error) (response, error) {
	c, err := caller(ctx)
	if err != nil {
		return response{}, err
	}
	if err := fn(c); err != nil {
		return response{}, err
	}
	return noContent(), nil
}

func (s *Server) AddSkillToClientV1ClientsClientIdSkillsPost(ctx context.Context, rq gen.AddSkillToClientV1ClientsClientIdSkillsPostRequestObject) (gen.AddSkillToClientV1ClientsClientIdSkillsPostResponseObject, error) {
	in := areaInput[clientInput](ctx)
	return s.clientDo(ctx, func(c authn.Caller) error { return s.ext.Clients.AddSkill(ctx, c, rq.ClientId, in.ref) })
}

func (s *Server) RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDelete(ctx context.Context, rq gen.RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteRequestObject) (gen.RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponseObject, error) {
	return s.clientDo(ctx, func(c authn.Caller) error { return s.ext.Clients.RemoveSkill(ctx, c, rq.ClientId, rq.SkillId) })
}

func (s *Server) AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPost(ctx context.Context, rq gen.AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostRequestObject) (gen.AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponseObject, error) {
	in := areaInput[clientInput](ctx)
	return s.clientDo(ctx, func(c authn.Caller) error {
		return s.ext.Clients.AddMCPInstance(ctx, c, rq.ClientId, in.ref, in.prefix, in.list)
	})
}

func (s *Server) RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDelete(ctx context.Context, rq gen.RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteRequestObject) (gen.RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponseObject, error) {
	return s.clientDo(ctx, func(c authn.Caller) error {
		return s.ext.Clients.RemoveMCPInstance(ctx, c, rq.ClientId, rq.McpInstanceId)
	})
}

func (s *Server) AddOpenapiConnectionToClientV1ClientsClientIdOpenapiConnectionsPost(ctx context.Context, rq gen.AddOpenapiConnectionToClientV1ClientsClientIdOpenapiConnectionsPostRequestObject) (gen.AddOpenapiConnectionToClientV1ClientsClientIdOpenapiConnectionsPostResponseObject, error) {
	in := areaInput[clientInput](ctx)
	return s.clientDo(ctx, func(c authn.Caller) error {
		return s.ext.Clients.AddOpenAPIConnection(ctx, c, rq.ClientId, in.ref, in.prefix, in.list)
	})
}

func (s *Server) RemoveOpenapiConnectionFromClientV1ClientsClientIdOpenapiConnectionsConnectionIdDelete(ctx context.Context, rq gen.RemoveOpenapiConnectionFromClientV1ClientsClientIdOpenapiConnectionsConnectionIdDeleteRequestObject) (gen.RemoveOpenapiConnectionFromClientV1ClientsClientIdOpenapiConnectionsConnectionIdDeleteResponseObject, error) {
	return s.clientDo(ctx, func(c authn.Caller) error {
		return s.ext.Clients.RemoveOpenAPIConnection(ctx, c, rq.ClientId, rq.ConnectionId)
	})
}

func (s *Server) AddPlatformToolsetToClientV1ClientsClientIdPlatformToolsetsPost(ctx context.Context, rq gen.AddPlatformToolsetToClientV1ClientsClientIdPlatformToolsetsPostRequestObject) (gen.AddPlatformToolsetToClientV1ClientsClientIdPlatformToolsetsPostResponseObject, error) {
	in := areaInput[clientInput](ctx)
	return s.clientDo(ctx, func(c authn.Caller) error {
		_, err := s.ext.Clients.SetToolset(ctx, c, rq.ClientId, in.ref, in.list)
		return err
	})
}

func (s *Server) RemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDelete(ctx context.Context, rq gen.RemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDeleteRequestObject) (gen.RemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDeleteResponseObject, error) {
	return s.clientDo(ctx, func(c authn.Caller) error {
		return s.ext.Clients.RemoveToolset(ctx, c, rq.ClientId, rq.Toolset)
	})
}

func (s *Server) HarnessAgentV1ClientsClientIdAgentPost(ctx context.Context, rq gen.HarnessAgentV1ClientsClientIdAgentPostRequestObject) (gen.HarnessAgentV1ClientsClientIdAgentPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.ext.Clients.HarnessAgent(ctx, c, rq.ClientId)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, false)), nil
}

func (s *Server) IssueRunnerKeyV1ClientsClientIdRunnerKeysPost(ctx context.Context, rq gen.IssueRunnerKeyV1ClientsClientIdRunnerKeysPostRequestObject) (gen.IssueRunnerKeyV1ClientsClientIdRunnerKeysPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	k, secret, err := s.ext.Clients.IssueRunnerKey(ctx, c, rq.ClientId)
	if err != nil {
		return nil, err
	}
	body := clientKeyJSON(k)
	body.Set("key", secret)
	return response{status: http.StatusCreated, body: body}, nil
}

func (s *Server) ListRunnerKeysV1ClientsClientIdRunnerKeysGet(ctx context.Context, rq gen.ListRunnerKeysV1ClientsClientIdRunnerKeysGetRequestObject) (gen.ListRunnerKeysV1ClientsClientIdRunnerKeysGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	keys, err := s.ext.Clients.ListRunnerKeys(ctx, c, rq.ClientId)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(keys))
	for i, k := range keys {
		out[i] = clientKeyJSON(k)
	}
	return ok(out), nil
}

func (s *Server) RevokeRunnerKeyV1ClientsClientIdRunnerKeysKeyIdDelete(ctx context.Context, rq gen.RevokeRunnerKeyV1ClientsClientIdRunnerKeysKeyIdDeleteRequestObject) (gen.RevokeRunnerKeyV1ClientsClientIdRunnerKeysKeyIdDeleteResponseObject, error) {
	return s.clientDo(ctx, func(c authn.Caller) error { return s.ext.Clients.RevokeRunnerKey(ctx, c, rq.ClientId, rq.KeyId) })
}
