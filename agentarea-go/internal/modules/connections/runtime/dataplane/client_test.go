package dataplane

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

func testClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	c, err := NewClient(ClientConfig{BaseURL: srv.URL, Token: testToken}, http.DefaultTransport)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func failing(code int) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { http.Error(w, "x", code) })
}

func TestStatusReportsMissingInstanceAsNotFound(t *testing.T) {
	if _, err := testClient(t, failing(http.StatusNotFound)).Status(context.Background(), "missing"); !errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("got %v", err)
	}
}

func TestStatusKeepsServerFailuresDistinct(t *testing.T) {
	_, err := testClient(t, failing(http.StatusInternalServerError)).Status(context.Background(), "i")
	if err == nil || errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("got %v", err)
	}
}

func TestDeleteTreatsUnknownInstanceAsRetired(t *testing.T) {
	if err := testClient(t, failing(http.StatusNotFound)).Delete(context.Background(), "missing"); err != nil {
		t.Fatal(err)
	}
	if err := testClient(t, failing(http.StatusBadGateway)).Delete(context.Background(), "i"); err == nil {
		t.Fatal("a real failure was swallowed")
	}
}

func TestClientAndHostSpeakTheSameWire(t *testing.T) {
	b := &fakeBackend{instances: map[string]workload.Status{}, reserve: workload.Reservation{CPUMillicores: 250, MemoryBytes: 1 << 28}}
	c := testClient(t, newTestHost(t, b, nil))
	ctx := context.Background()
	st, err := c.Create(ctx, workload.Spec{InstanceID: "i-1", Name: "i-1", ServiceName: "i-1", Image: "example:latest", Port: 8080})
	if err != nil || st.ID != "i-1" || st.Labels[OwnerLabel] != "agent-1" {
		t.Fatalf("create %+v %v", st, err)
	}
	b.instances["i-1"] = st
	got, err := c.Status(ctx, "i-1")
	if err != nil || got.Status != workload.StatusStarting {
		t.Fatalf("status %+v %v", got, err)
	}
	if r, err := c.Reservation(ctx); err != nil || r != b.reserve {
		t.Fatalf("reservation %+v %v", r, err)
	}
	if err := c.Ping(ctx); err != nil {
		t.Fatal(err)
	}
	if err := c.Delete(ctx, "i-1"); err != nil || len(b.deleted) != 1 {
		t.Fatalf("delete %v %v", err, b.deleted)
	}
}

func TestAuthorizeOnlyTheDataPlanesInstanceRoutes(t *testing.T) {
	c, err := NewClient(ClientConfig{BaseURL: "https://dp.example:8443/base", Token: testToken}, http.DefaultTransport)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := c.InstanceProxyURL("abc"), "https://dp.example:8443/base/dataplane/v1/instances/abc/proxy/mcp"; got != want {
		t.Fatalf("proxy url %q, want %q", got, want)
	}
	for raw, want := range map[string]bool{
		c.InstanceProxyURL("abc"):                                  true,
		"http://dp.example:8443/base/dataplane/v1/instances/a":     false,
		"https://other.example:8443/base/dataplane/v1/instances/a": false,
		"https://dp.example:8443/base/dataplane/v1/reservation":    false,
		"https://dp.example:8443/dataplane/v1/instances/a":         false,
	} {
		u, err := url.Parse(raw)
		if err != nil {
			t.Fatal(err)
		}
		req := &http.Request{URL: u, Header: http.Header{}}
		if got := c.Authorize(req); got != want || (req.Header.Get("Authorization") != "") != want {
			t.Errorf("%s: authorized=%v header=%q, want %v", raw, got, req.Header.Get("Authorization"), want)
		}
	}
}

func TestLoadClientConfigRefusesCleartextUnlessDeclaredPrivate(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_MCP_DATAPLANE_URL": "http://dp:8090", "AGENTAREA_MCP_DATAPLANE_TOKEN": testToken})
	LoadClientConfig(l)
	if l.Err() == nil {
		t.Fatal("cleartext URL accepted")
	}
	l = config.FromMap(map[string]string{"AGENTAREA_MCP_DATAPLANE_URL": "http://dp:8090/", "AGENTAREA_MCP_DATAPLANE_TOKEN": testToken, "AGENTAREA_MCP_DATAPLANE_INSECURE": "true"})
	cfg := LoadClientConfig(l)
	if err := l.Err(); err != nil || cfg.BaseURL != "http://dp:8090" {
		t.Fatalf("%+v %v", cfg, err)
	}
	l = config.FromMap(map[string]string{"AGENTAREA_MCP_DATAPLANE_URL": "https://dp", "AGENTAREA_MCP_DATAPLANE_TOKEN": "short"})
	LoadClientConfig(l)
	if l.Err() == nil {
		t.Fatal("short token accepted")
	}
}

func TestLoadHostConfigRequiresTokenAndID(t *testing.T) {
	l := config.FromMap(map[string]string{})
	LoadHostConfig(l)
	if l.Err() == nil {
		t.Fatal("empty host config accepted")
	}
	l = config.FromMap(map[string]string{"AGENTAREA_MCP_DATAPLANE_TOKEN": testToken, "AGENTAREA_MCP_DATAPLANE_ID": "dp-1"})
	cfg := LoadHostConfig(l)
	if err := l.Err(); err != nil || cfg.Addr != ":8090" || cfg.ID != "dp-1" {
		t.Fatalf("%+v %v", cfg, err)
	}
}
