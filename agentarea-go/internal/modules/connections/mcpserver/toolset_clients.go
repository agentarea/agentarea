package mcpserver

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

type clientArgs struct {
	ClientID            string   `json:"client_id"`
	SkillID             string   `json:"skill_id"`
	MCPInstanceID       string   `json:"mcp_instance_id"`
	OpenAPIConnectionID string   `json:"openapi_connection_id"`
	NamespacePrefix     string   `json:"namespace_prefix"`
	AllowedTools        []string `json:"allowed_tools"`
	Toolset             string   `json:"toolset"`
	DisabledMethods     []string `json:"disabled_methods"`
}

func clientSummary(s agentsapi.ClientSummary) map[string]any {
	return map[string]any{"id": s.ID, "name": s.Name, "kind": s.Kind, "mcp_endpoint_url": s.MCPEndpointURL}
}

// prefixOrNil is `namespace_prefix or None`.
func prefixOrNil(p string) *string {
	if p == "" {
		return nil
	}
	return &p
}

// clientTools is tools/clients_toolset.py.
func clientTools(cl agentsapi.Clients) map[string]toolDef {
	withClient := func(title, effect string, fn func(ctx context.Context, c authn.Caller, in clientArgs) (any, error)) toolDef {
		return toolDef{title: title, effect: effect, idempotent: effect != effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[clientArgs](args)
			if err != nil {
				return nil, err
			}
			return fn(ctx, c, in)
		}}
	}
	done := func(key string, err error) (any, error) {
		if err != nil {
			return nil, err
		}
		return map[string]any{key: true}, nil
	}
	return map[string]toolDef{
		"list": {title: "List clients", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Limit  *int `json:"limit"`
				Offset int  `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 100
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxListed))
			clients, err := cl.List(ctx, c, limit, in.Offset)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(clients))
			for i, s := range clients {
				out[i] = clientSummary(s)
			}
			return out, nil
		}},
		"get": withClient("Get client", effectRead, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			doc, err := cl.Get(ctx, c, in.ClientID)
			if err != nil {
				return nil, notFound(err, "Client not found")
			}
			return doc, nil
		}),
		"create": {title: "Register client", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name        string  `json:"name"`
				Description *string `json:"description"`
				Kind        *string `json:"kind"`
			}](args)
			if err != nil {
				return nil, err
			}
			kind := "harness"
			if in.Kind != nil {
				kind = *in.Kind
			}
			doc, err := json.Marshal(map[string]any{"name": in.Name, "description": in.Description, "kind": kind})
			if err != nil {
				return nil, err
			}
			s, err := cl.Create(ctx, c, doc)
			if err != nil {
				return nil, err
			}
			return clientSummary(s), nil
		}},
		"update": {title: "Update client", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[clientArgs](args)
			if err != nil {
				return nil, err
			}
			doc, err := patchArgs(args, []string{"client_id"}, []string{"name", "description", "kind", "allow_domains", "sandbox"})
			if err != nil {
				return nil, err
			}
			s, err := cl.Update(ctx, c, in.ClientID, doc)
			if err != nil {
				return nil, notFound(err, "Client not found")
			}
			return clientSummary(s), nil
		}},
		"delete": withClient("Delete client", effectDestructive, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			deleted, err := cl.Delete(ctx, c, in.ClientID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}),
		"add_skill": withClient("Attach skill to client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("added", cl.AddSkill(ctx, c, in.ClientID, in.SkillID))
		}),
		"remove_skill": withClient("Detach skill from client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("removed", cl.RemoveSkill(ctx, c, in.ClientID, in.SkillID))
		}),
		"add_mcp_instance": withClient("Attach MCP instance to client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("added", cl.AddMCPInstance(ctx, c, in.ClientID, in.MCPInstanceID, prefixOrNil(in.NamespacePrefix), in.AllowedTools))
		}),
		"remove_mcp_instance": withClient("Detach MCP instance from client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("removed", cl.RemoveMCPInstance(ctx, c, in.ClientID, in.MCPInstanceID))
		}),
		"add_openapi_connection": withClient("Attach OpenAPI connection to client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("added", cl.AddOpenAPIConnection(ctx, c, in.ClientID, in.OpenAPIConnectionID, prefixOrNil(in.NamespacePrefix), in.AllowedTools))
		}),
		"remove_openapi_connection": withClient("Detach OpenAPI connection from client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("removed", cl.RemoveOpenAPIConnection(ctx, c, in.ClientID, in.OpenAPIConnectionID))
		}),
		"add_platform_toolset": withClient("Attach platform toolset to client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			ns, err := cl.AddPlatformToolset(ctx, c, in.ClientID, in.Toolset, in.DisabledMethods)
			if err != nil {
				return nil, err
			}
			return map[string]any{"added": ns}, nil
		}),
		"remove_platform_toolset": withClient("Detach platform toolset from client", effectPrivileged, func(ctx context.Context, c authn.Caller, in clientArgs) (any, error) {
			return done("removed", cl.RemovePlatformToolset(ctx, c, in.ClientID, in.Toolset))
		}),
	}
}
