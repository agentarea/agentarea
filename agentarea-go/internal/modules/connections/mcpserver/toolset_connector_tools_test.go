package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

type fakeConnectorTools struct{ *recorder }

func (f fakeConnectorTools) Searchable(_ context.Context, _ authn.Caller, connector *string) ([]connectionsapi.Connector, error) {
	f.saw("searchable %v", connector != nil)
	return []connectionsapi.Connector{
		{ID: "i1", Name: "Jira", Tools: []connectionsapi.ConnectorTool{
			{Name: "list_issues", Description: "List issues", Hint: "read-only"},
			{Name: "delete_issue", Description: "Remove an issue", Hint: "destructive", InputSchema: map[string]any{"type": "object", "required": []any{"id"}}},
		}},
		{ID: "o1", Name: "Billing", Tools: []connectionsapi.ConnectorTool{{Name: "get_invoice", Description: "Fetch an issue invoice", Title: "Invoice"}}},
	}, nil
}

func (f fakeConnectorTools) Call(_ context.Context, _ authn.Caller, connector, tool string, args json.RawMessage, confirm bool) (connectionsapi.ConnectorCall, error) {
	f.saw("call %s %s %s %v", connector, tool, args, confirm)
	switch connector {
	case "none":
		return connectionsapi.ConnectorCall{}, connectionsapi.ErrNoConnector
	case "twin":
		return connectionsapi.ConnectorCall{}, &connectionsapi.AmbiguousConnectorError{IDs: []string{"i1", "i2"}}
	case "unknown":
		return connectionsapi.ConnectorCall{}, &connectionsapi.UnknownToolError{Connector: "Jira", Names: []string{"list_issues", "get_issue", "delete_repo"}}
	case "broken":
		return connectionsapi.ConnectorCall{}, &connectionsapi.ToolCallFailedError{Connector: "Jira", Err: errors.New("upstream timed out")}
	case "locked":
		return connectionsapi.ConnectorCall{ConnectorID: "i1", Connector: "Jira", ActionRequired: &connectionsapi.ConnectAction{URL: "https://app/connect", Message: "Open this link"}}, nil
	case "careful":
		return connectionsapi.ConnectorCall{Connector: "Jira", Tool: tool, ConfirmationRequired: true}, nil
	}
	return connectionsapi.ConnectorCall{ConnectorID: "i1", Connector: "Jira", Tool: tool,
		Content: []map[string]any{{"type": "text", "text": "done"}}, IsError: true}, nil
}

func TestConnectorToolsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{ConnectorTools: fakeConnectorTools{rec}}, "tools")
	runToolCases(t, ts, rec, []toolCase{
		{"tools_search", `{"query":"delete_issue"}`, "searchable false",
			`{"results":[{"connector":"Jira","connector_id":"i1","description":"Remove an issue","hint":"destructive","inputSchema":{"required":["id"],"type":"object"},"tool":"delete_issue"},` +
				`{"connector":"Jira","connector_id":"i1","description":"List issues","hint":"read-only","inputSchema":{"type":"object"},"tool":"list_issues"},` +
				`{"connector":"Billing","connector_id":"o1","description":"Fetch an issue invoice","hint":null,"inputSchema":{"type":"object"},"tool":"get_invoice"}],"searched_connectors":2}`, false},
		{"tools_search", `{"query":"invoice","connector":"Billing"}`, "searchable true", `"hint":null,"inputSchema":{"type":"object"},"tool":"get_invoice"`, false},
		{"tools_search", `{"query":"issue","limit":1}`, "", `"tool":"delete_issue"}],"searched_connectors":2}`, false},
		{"tools_search", `{"query":"x","limit":51}`, "", "limit must be between 1 and 50, got 51", true},
		{"tools_call", `{"connector":"Jira","tool":"list_issues"}`, "call Jira list_issues {} false",
			`{"connector":"Jira","connector_id":"i1","content":[{"text":"done","type":"text"}],"is_error":true,"tool":"list_issues"}`, false},
		{"tools_call", `{"connector":"Jira","tool":"x","arguments":{"a":1},"confirm":true}`, `call Jira x {"a":1} true`, "", false},
		{"tools_call", `{"connector":"none","tool":"x"}`, "", "No connector named 'none'", true},
		{"tools_call", `{"connector":"twin","tool":"x"}`, "",
			`{"error": "Connector name 'twin' is ambiguous; pass one of its ids", "connector_ids": ["i1", "i2"]}`, true},
		{"tools_call", `{"connector":"unknown","tool":"get_isue"}`, "",
			`{"error": "Jira has no tool 'get_isue'", "suggestions": ["get_issue", "list_issues"]}`, true},
		{"tools_call", `{"connector":"broken","tool":"x"}`, "", "Calling x on Jira failed: upstream timed out", true},
		{"tools_call", `{"connector":"locked","tool":"x"}`, "",
			`{"action_required":{"message":"Open this link","type":"connect","url":"https://app/connect"},"connector":"Jira","connector_id":"i1"}`, false},
		{"tools_call", `{"connector":"careful","tool":"drop"}`, "",
			`{"confirmation_required":true,"connector":"Jira","message":"This tool is marked destructive. Ask the user to confirm, then call again with confirm=true.","tool":"drop"}`, false},
	})
}

func TestCloseMatchesIsDifflibs(t *testing.T) {
	names := []string{"list_issues", "create_issue", "get_issue", "delete_repo", "list_isssues_all"}
	for word, want := range map[string][]string{
		"list_isues": {"list_issues", "list_isssues_all", "get_issue"},
		"issue":      {"get_issue", "list_issues"},
		"get_isue":   {"get_issue", "create_issue", "list_issues"},
		"zzz":        {},
	} {
		if got := closeMatches(word, names, 5, 0.6); !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: %v, want %v", word, got, want)
		}
	}
}

func TestPyJSONIsJSONDumps(t *testing.T) {
	got, err := pyJSON(map[string]any{"error": "Jira has no tool 'zzé<'", "suggestions": []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if want := "{\"error\": \"Jira has no tool 'zz\\u00e9<'\", \"suggestions\": []}"; got != want {
		t.Fatalf("%s, want %s", got, want)
	}
}
