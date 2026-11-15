package handlers

import (
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestValidateAnswersPerType(t *testing.T) {
	s, _ := harness(t, false, nil)
	cases := []struct {
		body, want string
	}{
		{`{"type":"docker"}`, `{"valid":true,"errors":[]}`},
		{`{"type":"bundle"}`, `{"valid":false,"errors":["bundle is not a valid MCP server instance type"]}`},
		{`{"type":"ftp"}`, `{"valid":false,"errors":["Unknown type: ftp"]}`},
		{`{"type":"url"}`, `{"valid":false,"errors":["endpoint_url is required for type=url"]}`},
	}
	for _, c := range cases {
		status, body := call(t, s, http.MethodPost, "/mcp-server-instances/validate", c.body)
		if status != http.StatusOK || body != c.want {
			t.Errorf("%s: %d %s", c.body, status, body)
		}
	}
	status, body := call(t, s, http.MethodPost, "/mcp-server-instances/validate", `{"headers":{"a":1}}`)
	if status != http.StatusUnprocessableEntity || !strings.Contains(body, `"type"`) || !strings.Contains(body, `"headers","a"`) {
		t.Fatalf("%d %s", status, body)
	}
}

func TestValidateConnectionRequiresURL(t *testing.T) {
	s, _ := harness(t, false, nil)
	status, body := call(t, s, http.MethodPost, "/mcp-server-instances/validate-connection", `{"server_id":"not-a-uuid"}`)
	if status != http.StatusOK || body != `{"valid":false,"errors":["URL is required"]}` {
		t.Fatalf("%d %s", status, body)
	}
	status, _ = call(t, s, http.MethodPost, "/mcp-server-instances/validate-connection", `[]`)
	if status != http.StatusUnprocessableEntity {
		t.Fatalf("list body: %d", status)
	}
}

func TestVerifyUnknownInstanceIsNotFound(t *testing.T) {
	s, _ := harness(t, false, nil)
	for _, route := range []string{"verify", "discover-tools"} {
		status, body := call(t, s, http.MethodPost, "/mcp-server-instances/"+uuid.NewString()+"/"+route, "")
		if status != http.StatusNotFound {
			t.Errorf("%s: %d %s", route, status, body)
		}
	}
	status, body := call(t, s, http.MethodPost, "/mcp-server-instances/"+uuid.NewString()+"/probe", "")
	if status != http.StatusBadRequest || !strings.Contains(body, "Instance not found") {
		t.Fatalf("probe: %d %s", status, body)
	}
}
