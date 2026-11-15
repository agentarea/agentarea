package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

type instanceIDArgs struct {
	InstanceID string `json:"instance_id"`
}

// specsUnserved is the refusal of a spec tool catalog has no capability for.
func specsUnserved(tool, capability string) toolDef {
	return toolDef{call: func(context.Context, authn.Caller, json.RawMessage) (any, error) {
		return nil, &toolError{"mcp_servers_" + tool + " is not served yet: catalog has no MCP server spec " + capability}
	}}
}

func connectActionJSON(a *connectionsapi.ConnectAction) map[string]any {
	out := map[string]any{"type": "connect", "url": a.URL, "message": a.Message}
	if a.ExistingConnections != nil {
		existing := make([]map[string]any, len(a.ExistingConnections))
		for i, e := range a.ExistingConnections {
			existing[i] = map[string]any{"id": e.ID, "kind": e.Kind, "name": e.Name}
		}
		out["existing_connections"] = existing
	}
	return out
}

func mcpInstanceJSON(i connectionsapi.MCPInstance) map[string]any {
	return map[string]any{
		"id": i.ID, "name": i.Name, "description": i.Description,
		"verification": i.Verification, "server_spec_id": i.ServerSpecID,
	}
}

func savedInstanceJSON(i connectionsapi.MCPInstance) map[string]any {
	out := mcpInstanceJSON(i)
	if i.ActionRequired != nil {
		out["action_required"] = connectActionJSON(i.ActionRequired)
	}
	return out
}

func instanceNotFound(err error) error {
	if errors.Is(err, connectionsapi.ErrNotFound) {
		return &toolError{"MCP server instance not found"}
	}
	return err
}

// toolName is _serialize_tool_name: the name, suffixed with its safety hint.
func toolName(tool map[string]any) string {
	name, _ := tool["name"].(string)
	if hint := domain.ToolSafetyHint(tool); hint != "" {
		return name + " (" + hint + ")"
	}
	return name
}

// toolDetail is _serialize_tool_detail: never the inputSchema.
func toolDetail(tool map[string]any) map[string]any {
	desc, ok := tool["description"]
	if !ok {
		desc = ""
	}
	out := map[string]any{"name": tool["name"], "description": desc}
	if ann, ok := tool["annotations"].(map[string]any); ok && len(ann) > 0 {
		out["annotations"] = ann
	}
	return out
}

// asObject is v as a JSON object.
func asObject(v any) (map[string]any, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	out := map[string]any{}
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// mcpServerTools is tools/mcp_servers_toolset.py.
func mcpServerTools(m connectionsapi.PlatformMCPServers) map[string]toolDef {
	createSpec := specsUnserved("create_spec", "writes")
	createSpec.title, createSpec.effect = "Create MCP server spec", effectWrite
	updateSpec := specsUnserved("update_spec", "writes")
	updateSpec.title, updateSpec.effect, updateSpec.idempotent = "Update MCP server spec", effectWrite, true
	deleteSpec := specsUnserved("delete_spec", "writes")
	deleteSpec.title, deleteSpec.effect, deleteSpec.idempotent = "Delete MCP server spec", effectDestructive, true
	listing := specsUnserved("list_specs", "listing")
	return map[string]toolDef{
		"create_spec": createSpec,
		"update_spec": updateSpec,
		"delete_spec": deleteSpec,
		"list_specs": {title: "List MCP server specs", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
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
			if limit < 1 || limit > 100 {
				return nil, &toolError{fmt.Sprintf("limit must be between 1 and 100, got %d", limit)}
			}
			if in.Offset < 0 {
				return nil, &toolError{fmt.Sprintf("offset must not be negative, got %d", in.Offset)}
			}
			return listing.call(ctx, c, args)
		}},
		"get_spec": {title: "Get MCP server spec", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SpecID string `json:"spec_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			s, err := m.GetSpec(ctx, c, in.SpecID)
			if errors.Is(err, connectionsapi.ErrNotFound) {
				return nil, &toolError{"MCP server spec not found"}
			}
			if err != nil {
				return nil, err
			}
			tags := s.Tags
			if tags == nil {
				tags = []any{}
			}
			return map[string]any{
				"id": s.ID, "name": s.Name, "description": s.Description, "version": s.Version,
				"tags": tags, "is_public": s.IsPublic, "remote_url": s.RemoteURL,
				"docker_image_url": s.DockerImageURL, "status": s.Status,
				"env_schema": s.EnvSchema, "registry_url": s.RegistryURL,
			}, nil
		}},
		"create": {title: "Create MCP server instance", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name         string  `json:"name"`
				JSONSpecJSON string  `json:"json_spec_json"`
				ServerSpecID string  `json:"server_spec_id"`
				Description  *string `json:"description"`
				AuthConfigID *string `json:"auth_config_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			specID, err := uuid.Parse(in.ServerSpecID)
			if err != nil {
				return nil, &toolError{"server_spec_id must be a UUID, got " + domain.PyRepr(in.ServerSpecID)}
			}
			fields := map[string]any{"name": in.Name, "server_spec_id": specID.String(), "json_spec": map[string]any{}}
			if in.Description != nil {
				fields["description"] = *in.Description
			}
			if in.AuthConfigID != nil {
				fields["auth_config_id"] = *in.AuthConfigID
			}
			doc, err := toolDocumentOf(fields, jsonArg{"json_spec", "json_spec_json", in.JSONSpecJSON})
			if err != nil {
				return nil, err
			}
			inst, err := m.Create(ctx, c, doc)
			if err != nil {
				return nil, err
			}
			return savedInstanceJSON(inst), nil
		}},
		"update": {title: "Update MCP server instance", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				InstanceID   string  `json:"instance_id"`
				Name         *string `json:"name"`
				Description  *string `json:"description"`
				JSONSpecJSON string  `json:"json_spec_json"`
				CostJSON     string  `json:"cost_json"`
			}](args)
			if err != nil {
				return nil, err
			}
			fields := map[string]any{}
			if in.Name != nil {
				fields["name"] = *in.Name
			}
			if in.Description != nil {
				fields["description"] = *in.Description
			}
			doc, err := toolDocumentOf(fields,
				jsonArg{"json_spec", "json_spec_json", in.JSONSpecJSON},
				jsonArg{"cost", "cost_json", in.CostJSON})
			if err != nil {
				return nil, err
			}
			inst, err := m.Update(ctx, c, in.InstanceID, doc)
			if err != nil {
				return nil, instanceNotFound(err)
			}
			return savedInstanceJSON(inst), nil
		}},
		"list": {title: "List MCP server instances", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			instances, err := m.List(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(instances))
			for i, inst := range instances {
				out[i] = mcpInstanceJSON(inst)
			}
			return out, nil
		}},
		"get": {title: "Get MCP server instance", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				InstanceID string    `json:"instance_id"`
				Tools      *[]string `json:"tools"`
			}](args)
			if err != nil {
				return nil, err
			}
			inst, err := m.Get(ctx, c, in.InstanceID)
			if err != nil {
				return nil, instanceNotFound(err)
			}
			out := mcpInstanceJSON(inst)
			out["last_dispatch"] = inst.LastDispatch
			tools := domain.ToolMaps(inst.Tools)
			names := make([]string, len(tools))
			byName := map[string]map[string]any{}
			for i, t := range tools {
				names[i] = toolName(t)
				if n, _ := t["name"].(string); n != "" {
					byName[n] = t
				}
			}
			out["tools"] = names
			out["tool_count"] = len(inst.Tools)
			if in.Tools != nil {
				details := []map[string]any{}
				var unknown []string
				for _, requested := range *in.Tools {
					if t, ok := byName[requested]; ok {
						details = append(details, toolDetail(t))
					} else {
						unknown = append(unknown, requested)
					}
				}
				out["tool_details"] = details
				if len(unknown) > 0 {
					out["unknown_tools"] = unknown
				}
			}
			if inst.ActionRequired != nil {
				out["action_required"] = connectActionJSON(inst.ActionRequired)
			}
			return out, nil
		}},
		"delete_instance": {title: "Delete MCP server instance", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[instanceIDArgs](args)
			if err != nil {
				return nil, err
			}
			deleted, err := m.Delete(ctx, c, in.InstanceID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}},
		"verify": {title: "Verify MCP server instance", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[instanceIDArgs](args)
			if err != nil {
				return nil, err
			}
			result, action, err := m.Verify(ctx, c, in.InstanceID)
			if err != nil || action == nil {
				return result, err
			}
			out, err := asObject(result)
			if err != nil {
				return nil, err
			}
			out["action_required"] = connectActionJSON(action)
			return out, nil
		}},
	}
}
