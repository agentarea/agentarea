package dataplane

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
)

const testToken = "0123456789abcdef0123456789abcdef"

// fakeBackend records what the agent asked of it.
type fakeBackend struct {
	backends.Backend
	created   *backends.InstanceSpec
	instances map[string]*backends.InstanceStatus
	deleted   []string
}

func (f *fakeBackend) CreateInstance(_ context.Context, spec *backends.InstanceSpec) (*backends.InstanceResult, error) {
	f.created = spec
	return &backends.InstanceResult{ID: spec.InstanceID, Name: spec.Name, Status: "running"}, nil
}

func (f *fakeBackend) GetInstanceStatus(_ context.Context, id string) (*backends.InstanceStatus, error) {
	if status, ok := f.instances[id]; ok {
		return status, nil
	}
	return nil, errNotFound{}
}

func (f *fakeBackend) ListInstances(context.Context) ([]*backends.InstanceStatus, error) {
	out := make([]*backends.InstanceStatus, 0, len(f.instances))
	for _, status := range f.instances {
		out = append(out, status)
	}
	return out, nil
}

func (f *fakeBackend) DeleteInstance(_ context.Context, id string) error {
	f.deleted = append(f.deleted, id)
	return nil
}

type errNotFound struct{}

func (errNotFound) Error() string { return "not found" }

func newTestServer(backend backends.Backend) *gin.Engine {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := &Config{AgentID: "agent-1", AuthToken: testToken, ListenAddr: ":0"}
	NewServer(cfg, backend, logger).Routes(router)
	return router
}

func request(t *testing.T, router *gin.Engine, method, path, token string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		reader = bytes.NewReader(encoded)
	}
	req := httptest.NewRequest(method, path, reader)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	return recorder
}

func TestInstanceRoutesRejectMissingToken(t *testing.T) {
	router := newTestServer(&fakeBackend{instances: map[string]*backends.InstanceStatus{}})

	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/dataplane/v1/instances"},
		{http.MethodPost, "/dataplane/v1/instances"},
		{http.MethodGet, "/dataplane/v1/instances/abc"},
		{http.MethodDelete, "/dataplane/v1/instances/abc"},
	} {
		if got := request(t, router, tc.method, tc.path, "", nil); got.Code != http.StatusUnauthorized {
			t.Errorf("%s %s without a token: got %d, want 401", tc.method, tc.path, got.Code)
		}
	}
}

func TestInstanceRoutesRejectWrongToken(t *testing.T) {
	router := newTestServer(&fakeBackend{instances: map[string]*backends.InstanceStatus{}})

	got := request(t, router, http.MethodGet, "/dataplane/v1/instances", "wrong-token-wrong-token-wrong-to", nil)
	if got.Code != http.StatusUnauthorized {
		t.Fatalf("got %d, want 401", got.Code)
	}
}

func TestHealthzNeedsNoToken(t *testing.T) {
	router := newTestServer(&fakeBackend{})

	if got := request(t, router, http.MethodGet, "/healthz", "", nil); got.Code != http.StatusOK {
		t.Fatalf("got %d, want 200", got.Code)
	}
}

// The label is what makes ownership survive a restart, and a caller must not be
// able to set it: doing so would let one control plane adopt another's
// containers.
func TestCreateStampsOwnerLabelOverCallerValue(t *testing.T) {
	backend := &fakeBackend{instances: map[string]*backends.InstanceStatus{}}
	router := newTestServer(backend)

	spec := backends.InstanceSpec{
		InstanceID: "i-1",
		Name:       "mcp-1",
		Image:      "example:latest",
		Labels:     map[string]string{OwnerLabel: "someone-else", "keep": "me"},
	}
	if got := request(t, router, http.MethodPost, "/dataplane/v1/instances", testToken, spec); got.Code != http.StatusCreated {
		t.Fatalf("got %d, want 201: %s", got.Code, got.Body.String())
	}

	if backend.created.Labels[OwnerLabel] != "agent-1" {
		t.Errorf("owner label = %q, want agent-1", backend.created.Labels[OwnerLabel])
	}
	if backend.created.Labels["keep"] != "me" {
		t.Error("unrelated caller labels must survive")
	}
}

func TestUnownedInstanceIsIndistinguishableFromMissing(t *testing.T) {
	backend := &fakeBackend{instances: map[string]*backends.InstanceStatus{
		"theirs": {ID: "theirs", Labels: map[string]string{OwnerLabel: "another-agent"}},
		"bare":   {ID: "bare"},
	}}
	router := newTestServer(backend)

	for _, id := range []string{"theirs", "bare", "absent"} {
		if got := request(t, router, http.MethodGet, "/dataplane/v1/instances/"+id, testToken, nil); got.Code != http.StatusNotFound {
			t.Errorf("GET %s: got %d, want 404", id, got.Code)
		}
		if got := request(t, router, http.MethodDelete, "/dataplane/v1/instances/"+id, testToken, nil); got.Code != http.StatusNotFound {
			t.Errorf("DELETE %s: got %d, want 404", id, got.Code)
		}
	}

	if len(backend.deleted) != 0 {
		t.Errorf("deleted %v; an agent must not touch instances it does not own", backend.deleted)
	}
}

func TestListReturnsOnlyOwnedInstances(t *testing.T) {
	backend := &fakeBackend{instances: map[string]*backends.InstanceStatus{
		"mine":   {ID: "mine", Labels: map[string]string{OwnerLabel: "agent-1"}},
		"theirs": {ID: "theirs", Labels: map[string]string{OwnerLabel: "another-agent"}},
		"bare":   {ID: "bare"},
	}}
	router := newTestServer(backend)

	got := request(t, router, http.MethodGet, "/dataplane/v1/instances", testToken, nil)
	if got.Code != http.StatusOK {
		t.Fatalf("got %d, want 200", got.Code)
	}

	var payload struct {
		Instances []*backends.InstanceStatus `json:"instances"`
	}
	if err := json.Unmarshal(got.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Instances) != 1 || payload.Instances[0].ID != "mine" {
		t.Fatalf("listed %+v, want only the owned instance", payload.Instances)
	}
}
