package mcpserver

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

type fakeOpenAPI struct{ *recorder }

var openAPIConn = connectionsapi.OpenAPIConnection{
	ID: "o1", Name: "Billing", BaseURL: ptr("https://billing.example"),
	CustomHeaders: []connectionsapi.NamedField{{Name: "Authorization", Secret: true}},
	URLVariables:  []string{}, Tools: []connectionsapi.OpenAPITool{{Name: "get_invoice", Description: "Fetch"}},
	Status: "active",
}

func (f fakeOpenAPI) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (connectionsapi.OpenAPIConnection, error) {
	f.saw("create %s", doc)
	return openAPIConn, nil
}
func (f fakeOpenAPI) List(_ context.Context, _ authn.Caller, search string, limit, offset int) ([]connectionsapi.OpenAPIConnection, int, error) {
	f.saw("list %q %d %d", search, limit, offset)
	return []connectionsapi.OpenAPIConnection{openAPIConn}, 7, nil
}
func (f fakeOpenAPI) Get(_ context.Context, _ authn.Caller, id string) (connectionsapi.OpenAPIConnection, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return connectionsapi.OpenAPIConnection{}, connectionsapi.ErrNotFound
	}
	return openAPIConn, nil
}
func (f fakeOpenAPI) Update(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (connectionsapi.OpenAPIConnection, error) {
	f.saw("update %s %s", id, doc)
	if id == "gone" {
		return connectionsapi.OpenAPIConnection{}, connectionsapi.ErrNotFound
	}
	return openAPIConn, nil
}
func (f fakeOpenAPI) DiscoverTools(_ context.Context, _ authn.Caller, id string) (connectionsapi.OpenAPIDiscovery, error) {
	f.saw("discover %s", id)
	return connectionsapi.OpenAPIDiscovery{ConnectionID: id, Tools: openAPIConn.Tools}, nil
}
func (f fakeOpenAPI) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return id != "gone", nil
}

func TestOpenAPIToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{OpenAPI: fakeOpenAPI{rec}}, "openapi_connections")
	runToolCases(t, ts, rec, []toolCase{
		{"openapi_connections_create", `{"name":"Billing","base_url":"https://billing.example","description":null,"auth_config_id":"","custom_headers_json":"[{\"name\":\"Authorization\",\"value\":\"x\"}]"}`,
			`create {"base_url":"https://billing.example","custom_headers":[{"name":"Authorization","value":"x"}],"name":"Billing"}`,
			`{"auth_config_id":null,"base_url":"https://billing.example","custom_headers":[{"name":"Authorization","secret":true}],"custom_query_params":[],` +
				`"description":null,"id":"o1","last_dispatch":null,"name":"Billing","spec_url":null,"status":"active","tools_count":1,"url_variables":[]}`, false},
		{"openapi_connections_create", `{"name":"B","base_url":"u","spec_content_json":"{nope"}`, "", "spec_content_json is not JSON", true},
		{"openapi_connections_list", `{}`, `list "" 100 0`, `"total":7`, false},
		{"openapi_connections_list", `{"search":"bill","limit":5,"offset":10}`, `list "bill" 5 10`, `"items":[{`, false},
		{"openapi_connections_list", `{"limit":5000}`, `list "" 1000 0`, `"total":7`, false},
		{"openapi_connections_get", `{"connection_id":"o1"}`, "get o1", `"tools":[{"description":"Fetch","name":"get_invoice"}]`, false},
		{"openapi_connections_get", `{"connection_id":"gone"}`, "", "Connection not found", true},
		{"openapi_connections_update", `{"connection_id":"o1","name":"New","auth_config_id":"","cost_json":"null"}`,
			`update o1 {"auth_config_id":null,"cost":null,"name":"New"}`, `"id":"o1"`, false},
		{"openapi_connections_update", `{"connection_id":"o1"}`, `update o1 {}`, "", false},
		{"openapi_connections_update", `{"connection_id":"gone","name":"x"}`, "", "Connection not found", true},
		{"openapi_connections_discover_tools", `{"connection_id":"o1"}`, "discover o1",
			`{"connection_id":"o1","tools":[{"description":"Fetch","name":"get_invoice"}],"tools_discovered":1}`, false},
		{"openapi_connections_delete", `{"connection_id":"o1"}`, "delete o1", `{"deleted":true}`, false},
		{"openapi_connections_delete", `{"connection_id":"gone"}`, "delete gone", `{"deleted":false}`, false},
	})
}
