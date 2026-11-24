package handlers

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

type miscCodeTools struct{}

func (miscCodeTools) Names() []string { return []string{"agentarea/math"} }
func (miscCodeTools) Metadata() []service.CodeToolset {
	effect := "read"
	return []service.CodeToolset{{Name: "agentarea/math", Description: "Math", Category: "util",
		Methods: []service.CodeToolMethod{{Name: "add", DisplayName: "Add", Description: "Adds", Effect: &effect}}}}
}

type miscMCP struct{ gotID string }

func (f *miscMCP) InstanceTools(_ context.Context, _ authn.Caller, id string) ([]service.ToolsMCPInstance, error) {
	f.gotID = id
	tools := []any{
		wirejson.Object{{Key: "function", Value: wirejson.Object{{Key: "name", Value: "search"}}}},
		wirejson.Object{{Key: "name", Value: ""}},
	}
	return []service.ToolsMCPInstance{{ID: "i1", Name: "Search", Tools: tools}}, nil
}

type miscSkills struct{ err error }

func (f miscSkills) ExportSkills(context.Context, authn.Caller) ([]domain.ExportSkill, error) {
	return nil, f.err
}

type miscTriggers struct{}

func (miscTriggers) ExportTriggers(context.Context, authn.Caller) ([]service.ExportTriggerRow, error) {
	return nil, nil
}

type miscNames struct{}

func (miscNames) WorkspaceName(context.Context, authn.Caller) (string, error) { return "W", nil }

func miscServer(t *testing.T, admin error, d service.MiscDeps) http.Handler {
	t.Helper()
	svc := service.New(service.Deps{CodeTools: miscCodeTools{}, Admin: func(context.Context) error { return admin }})
	ws, err := scope.NewWorkspace("00000000-0000-0000-0000-000000000001", "ws")
	if err != nil {
		t.Fatal(err)
	}
	edge := Edge{Workspace: func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: ws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}}
	r := chi.NewRouter()
	Mount(r, httpx.NewErrors("", nil, MapError), edge, New(svc, Extras{Misc: service.NewMisc(svc, d)}))
	return r
}

func miscDo(h http.Handler, method, path string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, path, nil))
	return rec
}

func TestToolsListsCodeToolsets(t *testing.T) {
	rec := miscDo(miscServer(t, nil, service.MiscDeps{}), http.MethodGet, "/v1/workspaces/ws/agents/tools?include=code")
	want := `[{"name":"agentarea/math","type":"code","description":"Math","display_name":"agentarea/math","category":"util",` +
		`"plane":null,"group":null,"requires_user_confirmation":false,"available_methods":[{"name":"add","display_name":"Add",` +
		`"description":"Adds","effect":"read","requires_user_confirmation":false}],"input_schema":{},"mcp_instance_id":null,"mcp_instance_name":null}]`
	if rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) != want {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
}

func TestToolsListsMCPToolsOfOneInstance(t *testing.T) {
	mcp := &miscMCP{}
	rec := miscDo(miscServer(t, nil, service.MiscDeps{ToolsMCP: mcp}), http.MethodGet,
		"/v1/workspaces/ws/agents/tools?include=+mcp+&mcp_instance_id=A1B2C3D4E5F6789ABCDE123456789ABC")
	want := `[{"name":"search","type":"mcp","description":"MCP tool: search","display_name":"","category":"","plane":null,` +
		`"group":null,"requires_user_confirmation":false,"available_methods":[],"input_schema":{},"mcp_instance_id":"i1","mcp_instance_name":"Search"}]`
	if rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) != want {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	if mcp.gotID != "a1b2c3d4-e5f6-789a-bcde-123456789abc" {
		t.Errorf("instance id %q", mcp.gotID)
	}
}

func TestToolsStatuses(t *testing.T) {
	h := miscServer(t, nil, service.MiscDeps{})
	for path, want := range map[string]int{
		"/v1/workspaces/ws/agents/tools?mcp_instance_id=nope": http.StatusUnprocessableEntity,
		"/v1/workspaces/ws/agents/tools":                      http.StatusNotImplemented,
		"/v1/workspaces/ws/agents/tools?include=code":         http.StatusOK,
		"/v1/workspaces/ws/agents/tools?include=other":        http.StatusOK,
		"/v1/workspaces/ws/agents/presets":                    http.StatusNotImplemented,
	} {
		if rec := miscDo(h, http.MethodGet, path); rec.Code != want {
			t.Errorf("%s: %d %s", path, rec.Code, rec.Body)
		}
	}
	if rec := miscDo(h, http.MethodPost, "/v1/workspaces/ws/agents/some-agent/install"); rec.Code != http.StatusNotImplemented {
		t.Errorf("install: %d %s", rec.Code, rec.Body)
	}
}

func TestExportStatuses(t *testing.T) {
	full := func(skills miscSkills) service.MiscDeps {
		return service.MiscDeps{ExportWorkspaces: miscNames{}, ExportSkills: skills,
			ExportMCPs: struct{ service.ExportMCPs }{}, ExportTriggers: miscTriggers{}}
	}
	cases := []struct {
		name  string
		admin error
		d     service.MiscDeps
		code  int
		body  string
	}{
		{"not an admin", service.ErrDenied, full(miscSkills{}), http.StatusForbidden, "Permission denied"},
		{"unwired", nil, service.MiscDeps{}, http.StatusNotImplemented, "not_implemented"},
		{"value error", nil, full(miscSkills{err: &api.ExportInvalidError{Msg: "Skill x has neither a package nor a body"}}),
			http.StatusUnprocessableEntity, "Skill x has neither a package nor a body"},
		{"anything else", nil, full(miscSkills{err: errors.New("boom")}), http.StatusInternalServerError, "Internal server error"},
	}
	for _, c := range cases {
		rec := miscDo(miscServer(t, c.admin, c.d), http.MethodGet, "/v1/workspaces/ws/export")
		if rec.Code != c.code || !strings.Contains(rec.Body.String(), c.body) || strings.Contains(rec.Body.String(), "boom") {
			t.Errorf("%s: %d %s", c.name, rec.Code, rec.Body)
		}
	}
}

func TestExportTextIsAnAttachment(t *testing.T) {
	rec := httptest.NewRecorder()
	if err := exportText("a: b\n").VisitExportWorkspaceConfigV1ExportGetResponse(rec); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK || rec.Body.String() != "a: b\n" ||
		rec.Header().Get("Content-Type") != "text/plain; charset=utf-8" ||
		rec.Header().Get("Content-Disposition") != "attachment; filename=workspace_config.yaml" {
		t.Errorf("%d %v %q", rec.Code, rec.Header(), rec.Body)
	}
}
