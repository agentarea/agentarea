package mcpserver

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

type fakeMCPServers struct{ *recorder }

var (
	connectLink = &connectionsapi.ConnectAction{URL: "https://app/w/acme/connect/i1", Message: "Open this link to connect Jira",
		ExistingConnections: []connectionsapi.CatalogConnection{{ID: "i0", Kind: "mcp", Name: "Old Jira"}}}
	jira = connectionsapi.MCPInstance{ID: "i1", Name: "Jira", Verification: map[string]any{"status": "failed"}, ServerSpecID: "s1",
		Tools: []any{
			map[string]any{"name": "list_issues", "description": "List", "annotations": map[string]any{"readOnlyHint": true}},
			map[string]any{"name": "drop", "annotations": map[string]any{"destructive_hint": true}},
			map[string]any{"name": "plain", "description": "Plain"},
		}}
)

func (f fakeMCPServers) GetSpec(_ context.Context, _ authn.Caller, id string) (connectionsapi.MCPSpec, error) {
	f.saw("spec %s", id)
	if id == "gone" {
		return connectionsapi.MCPSpec{}, connectionsapi.ErrNotFound
	}
	return connectionsapi.MCPSpec{ID: id, Name: "Jira", Version: "1.0.0", Status: "active", EnvSchema: []any{}}, nil
}
func (f fakeMCPServers) CreateSpec(_ context.Context, _ authn.Caller, doc json.RawMessage) (connectionsapi.MCPSpec, error) {
	f.saw("create spec %s", doc)
	return connectionsapi.MCPSpec{ID: "s2", Name: "x", Version: "1.0.0", Status: "draft"}, nil
}
func (f fakeMCPServers) UpdateSpec(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (connectionsapi.MCPSpec, error) {
	f.saw("update spec %s %s", id, doc)
	if id == "gone" {
		return connectionsapi.MCPSpec{}, connectionsapi.ErrNotFound
	}
	return connectionsapi.MCPSpec{ID: id, Name: "y", Version: "1.0.0", Status: "active"}, nil
}
func (f fakeMCPServers) DeleteSpec(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete spec %s", id)
	return id != "gone", nil
}
func (f fakeMCPServers) ListSpecs(_ context.Context, _ authn.Caller, q connectionsapi.SpecListing) ([]connectionsapi.MCPSpec, int, error) {
	f.saw("list specs %v %v %d %d", q.Tag != nil, q.IsPublic != nil, q.Limit, q.Offset)
	return []connectionsapi.MCPSpec{{ID: "s1", Name: "Jira", Version: "1.0.0", Status: "active"}}, 7, nil
}
func (f fakeMCPServers) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (connectionsapi.MCPInstance, error) {
	f.saw("create %s", doc)
	out := jira
	out.ActionRequired = connectLink
	return out, nil
}
func (f fakeMCPServers) Update(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (connectionsapi.MCPInstance, error) {
	f.saw("update %s %s", id, doc)
	if id == "gone" {
		return connectionsapi.MCPInstance{}, connectionsapi.ErrNotFound
	}
	return jira, nil
}
func (f fakeMCPServers) List(context.Context, authn.Caller) ([]connectionsapi.MCPInstance, error) {
	f.saw("list")
	return []connectionsapi.MCPInstance{jira}, nil
}
func (f fakeMCPServers) Get(_ context.Context, _ authn.Caller, id string) (connectionsapi.MCPInstance, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return connectionsapi.MCPInstance{}, connectionsapi.ErrNotFound
	}
	return jira, nil
}
func (f fakeMCPServers) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return id != "gone", nil
}
func (f fakeMCPServers) Verify(_ context.Context, _ authn.Caller, id string) (any, *connectionsapi.ConnectAction, error) {
	f.saw("verify %s", id)
	if id == "locked" {
		return map[string]any{"status": "failed", "schema_version": 1}, &connectionsapi.ConnectAction{URL: "u", Message: "m"}, nil
	}
	return map[string]any{"status": "succeeded"}, nil, nil
}

func TestMCPServersToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{MCPServers: fakeMCPServers{rec}}, "mcp_servers")
	runToolCases(t, ts, rec, []toolCase{
		{"mcp_servers_create_spec", `{"name":"x","description":"y","tags":["a"],"cmd_json":"[\"run\"]"}`,
			`create spec {"cmd":["run"],"description":"y","docker_image_url":null,"is_public":false,"name":"x","registry_url":null,"remote_url":null,"tags":["a"],"version":"1.0.0"}`,
			`{"description":"","docker_image_url":null,"id":"s2","is_public":false,"name":"x","remote_url":null,"status":"draft","tags":[],"version":"1.0.0"}`, false},
		{"mcp_servers_create_spec", `{"name":"x","description":"y","cmd_json":"[oops"}`, "", "cmd_json is not JSON", true},
		{"mcp_servers_update_spec", `{"spec_id":"s1"}`, "", "no fields to update", true},
		{"mcp_servers_update_spec", `{"spec_id":"s1","name":"y","is_public":true}`, `update spec s1 {"is_public":true,"name":"y"}`, `"name":"y"`, false},
		{"mcp_servers_update_spec", `{"spec_id":"gone","status":"active"}`, "", "MCP server spec not found", true},
		{"mcp_servers_delete_spec", `{"spec_id":"s1"}`, "delete spec s1", `{"deleted":true}`, false},
		{"mcp_servers_delete_spec", `{"spec_id":"gone"}`, "delete spec gone", `{"deleted":false}`, false},
		{"mcp_servers_list_specs", `{"limit":0}`, "", "limit must be between 1 and 100, got 0", true},
		{"mcp_servers_list_specs", `{"offset":-1}`, "", "offset must not be negative, got -1", true},
		{"mcp_servers_list_specs", `{"tag":"x","offset":5}`, "list specs true false 100 5", `"total":7`, false},
		{"mcp_servers_get_spec", `{"spec_id":"s1"}`, "spec s1",
			`{"description":"","docker_image_url":null,"env_schema":[],"id":"s1","is_public":false,"name":"Jira","registry_url":null,"remote_url":null,"status":"active","tags":[],"version":"1.0.0"}`, false},
		{"mcp_servers_get_spec", `{"spec_id":"gone"}`, "", "MCP server spec not found", true},
		{"mcp_servers_create", `{"name":"Jira","json_spec_json":"","server_spec_id":"7b0c5f3e-8a0e-4d61-9a43-1f1f0f4c9b11"}`,
			`create {"json_spec":{},"name":"Jira","server_spec_id":"7b0c5f3e-8a0e-4d61-9a43-1f1f0f4c9b11"}`,
			`"action_required":{"existing_connections":[{"id":"i0","kind":"mcp","name":"Old Jira"}],"message":"Open this link to connect Jira","type":"connect","url":"https://app/w/acme/connect/i1"}`, false},
		{"mcp_servers_create", `{"name":"Jira","json_spec_json":"{\"headers\":{}}","server_spec_id":"7B0C5F3E8A0E4D619A431F1F0F4C9B11","description":"d"}`,
			`create {"description":"d","json_spec":{"headers":{}},"name":"Jira","server_spec_id":"7b0c5f3e-8a0e-4d61-9a43-1f1f0f4c9b11"}`, `"id":"i1"`, false},
		{"mcp_servers_create", `{"name":"Jira","json_spec_json":"","server_spec_id":"jira"}`, "", "server_spec_id must be a UUID, got 'jira'", true},
		{"mcp_servers_update", `{"instance_id":"i1","name":null,"description":"d","cost_json":"null"}`, `update i1 {"cost":null,"description":"d"}`,
			`{"description":null,"id":"i1","name":"Jira","server_spec_id":"s1","verification":{"status":"failed"}}`, false},
		{"mcp_servers_update", `{"instance_id":"gone"}`, `update gone {}`, "MCP server instance not found", true},
		{"mcp_servers_list", `{}`, "list", `[{"description":null,"id":"i1","name":"Jira","server_spec_id":"s1","verification":{"status":"failed"}}]`, false},
		{"mcp_servers_get", `{"instance_id":"i1"}`, "get i1",
			`"tool_count":3,"tools":["list_issues (read-only)","drop (destructive)","plain"],"verification"`, false},
		{"mcp_servers_get", `{"instance_id":"i1","tools":["plain","drop","nope"]}`, "get i1",
			`"tool_details":[{"description":"Plain","name":"plain"},{"annotations":{"destructive_hint":true},"description":"","name":"drop"}],"tools":["list_issues (read-only)","drop (destructive)","plain"],"unknown_tools":["nope"]`, false},
		{"mcp_servers_get", `{"instance_id":"gone"}`, "", "MCP server instance not found", true},
		{"mcp_servers_delete_instance", `{"instance_id":"i1"}`, "delete i1", `{"deleted":true}`, false},
		{"mcp_servers_verify", `{"instance_id":"i1"}`, "verify i1", `{"status":"succeeded"}`, false},
		{"mcp_servers_verify", `{"instance_id":"locked"}`, "verify locked",
			`{"action_required":{"message":"m","type":"connect","url":"u"},"schema_version":1,"status":"failed"}`, false},
	})
}
