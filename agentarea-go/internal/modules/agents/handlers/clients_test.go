package handlers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// clientGraph allows checks on the ids in allow.
type clientGraph struct{ allow map[string]bool }

func (g clientGraph) Check(_ context.Context, _, _, _, id string) (bool, error) {
	return g.allow[id], nil
}
func (g clientGraph) ListObjects(context.Context, string, string, string) ([]string, error) {
	return nil, nil
}
func (g clientGraph) Write(context.Context, []authz.Tuple, []authz.Tuple) error { return nil }

func clientServer(t *testing.T, allow map[string]bool, cred authn.CredentialKind) http.Handler {
	t.Helper()
	svc := service.New(service.Deps{Graph: clientGraph{allow: allow}})
	scopeErrors := func(err error) (*httpx.Error, bool) {
		var se *authn.ScopeRequiredError
		if errors.As(err, &se) {
			return httpx.Forbidden(se.Error()), true
		}
		return nil, false
	}
	errs := httpx.NewErrors("http://api.test", slog.New(slog.DiscardHandler), MapError, scopeErrors)
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "u1", Credential: &authn.Credential{Kind: cred}}, Workspace: ws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}
	r := chi.NewRouter()
	Mount(r, errs, Edge{Workspace: admit}, New(svc, Extras{
		Clients:  service.NewClients(svc, service.ClientPorts{}),
		TaskDefs: service.NewTaskDefs(svc, service.TaskDefPorts{}),
	}))
	return r
}

func clientDo(t *testing.T, h http.Handler, method, path, body string) (int, string) {
	t.Helper()
	var rd io.Reader
	if body != "" {
		rd = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, "/v1/workspaces/acme"+path, rd)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

func TestClientRoutesCheckThePermissionBeforeTheBody(t *testing.T) {
	id := uuid.NewString()
	h := clientServer(t, nil, authn.KindSession)
	code, body := clientDo(t, h, http.MethodPatch, "/clients/"+id, `{"name":null,"extra":1}`)
	if code != http.StatusForbidden || !strings.Contains(body, "Permission denied") {
		t.Errorf("%d %s", code, body)
	}
	code, body = clientDo(t, h, http.MethodPatch, "/clients/not-a-uuid", `{}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, `"msg":"Input should be a valid UUID"`) {
		t.Errorf("%d %s", code, body)
	}
	code, body = clientDo(t, h, http.MethodPut, "/task-definitions/"+id, `{"nope":1}`)
	if code != http.StatusForbidden {
		t.Errorf("task definition edit %d %s", code, body)
	}
}

func TestClientUpdateBodyIsValidatedOnceAllowed(t *testing.T) {
	id := uuid.NewString()
	h := clientServer(t, map[string]bool{id: true}, authn.KindSession)
	code, body := clientDo(t, h, http.MethodPatch, "/clients/"+id, `{"name":null,"allow_domains":["ok.org","bad host"],"extra":1}`)
	if code != http.StatusUnprocessableEntity {
		t.Fatalf("%d %s", code, body)
	}
	for _, want := range []string{"may be omitted, but not set to null", `not a host name: 'bad host'`, "extra_forbidden"} {
		if !strings.Contains(body, want) {
			t.Errorf("missing %q in %s", want, body)
		}
	}
}

func TestClientPlatformToolsets(t *testing.T) {
	id := uuid.NewString()
	h := clientServer(t, map[string]bool{id: true}, authn.KindSession)
	code, body := clientDo(t, h, http.MethodGet, "/clients/platform-toolsets", "")
	if code != http.StatusOK || !strings.HasPrefix(body, `[{"name":"agentarea/agents","display_name":"Agent Management",`) {
		t.Errorf("%d %.120s", code, body)
	}
	code, body = clientDo(t, h, http.MethodPost, "/clients/"+id+"/platform-toolsets", `{"name":"runs","disabled_methods":["nope"]}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, "Toolset 'agentarea/runs' has no method(s) nope") {
		t.Errorf("%d %s", code, body)
	}
}

func TestClientRunnerKeysNeedTheCredentialsScope(t *testing.T) {
	id := uuid.NewString()
	h := clientServer(t, map[string]bool{id: true}, authn.KindAPIKey)
	code, body := clientDo(t, h, http.MethodPost, "/clients/"+id+"/runner-keys", "")
	if code != http.StatusForbidden || !strings.Contains(body, "This credential cannot issue runner keys") {
		t.Errorf("%d %s", code, body)
	}
}

func TestTaskDefBodies(t *testing.T) {
	var in input
	var errs []httpx.FieldError
	taskDefCreateBody(decode(t, `{"name":"  ","description":"x","agent_id":null,"parameters":{"session":1},"x":1}`), &in, &errs)
	types := map[string]bool{}
	for _, e := range errs {
		types[e.Type+":"+e.Msg] = true
	}
	for _, want := range []string{"value_error:Value error, must not be blank", "uuid_type:UUID input should be a string, bytes or UUID object",
		"value_error:Value error, session is set by the trigger that received the event and cannot be supplied", "extra_forbidden:Extra inputs are not permitted"} {
		if !types[want] {
			t.Errorf("missing %s in %v", want, errs)
		}
	}
	errs, in = nil, input{}
	taskDefCreateBody(decode(t, `{"name":" N ","description":"d","agent_id":"`+uuid.NewString()+`","parameters":{"a":1.0}}`), &in, &errs)
	ti := in.area.(taskDefInput)
	if len(errs) != 0 || ti.create.Name != "N" || string(ti.create.Parameters) != `{"a": 1.0}` {
		t.Errorf("%v %+v %s", errs, ti.create, ti.create.Parameters)
	}
	errs, in = nil, input{}
	taskDefUpdateBody(decode(t, `{"name":null,"parameters":null,"agent_id":null}`), &in, &errs)
	if len(errs) != 3 || errs[0].Msg != "Value error, may be omitted, but not set to null" {
		t.Errorf("null is refused: %v", errs)
	}
	errs, in = nil, input{}
	taskDefUpdateBody(decode(t, `{"description":" x "}`), &in, &errs)
	if p := in.area.(taskDefInput).patch; len(errs) != 0 || p.Name != nil || *p.Description != "x" || p.Parameters != nil {
		t.Errorf("left out stays: %v %+v", errs, p)
	}
}

func TestClientAssociationBodyBoundsThePrefix(t *testing.T) {
	var in input
	var errs []httpx.FieldError
	clientAssociationBody(true)(decode(t, `{"id":"x","namespace_prefix":"`+strings.Repeat("p", 65)+`","allowed_tools":["a",1]}`), &in, &errs)
	if len(errs) != 2 || errs[0].Type != "string_too_long" || errs[1].Type != "string_type" {
		t.Errorf("%v", errs)
	}
}

func TestClientRemoveToolsetTakesTheRestOfThePath(t *testing.T) {
	r := chi.NewRouter()
	var got string
	r.Delete("/c/{client_id}/platform-toolsets/*", func(w http.ResponseWriter, r *http.Request) {
		got = chi.URLParam(r, "*")
		if r.URL.RawPath != "" {
			got = "escaped:" + got
		}
	})
	r.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodDelete, "/c/x/platform-toolsets/agentarea/runs", nil))
	if got != "agentarea/runs" {
		t.Errorf("%q", got)
	}
}
