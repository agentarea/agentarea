package dataplane

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

const testToken = "0123456789abcdef0123456789abcdef"

type fakeBackend struct {
	mu        sync.Mutex
	created   *workload.Spec
	instances map[string]workload.Status
	deleted   []string
	reserve   workload.Reservation
}

func (f *fakeBackend) Create(_ context.Context, spec workload.Spec) (workload.Status, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.created = &spec
	return workload.Status{ID: spec.InstanceID, Name: spec.Name, Status: workload.StatusStarting, Labels: spec.Labels}, nil
}

func (f *fakeBackend) Delete(_ context.Context, id string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.deleted = append(f.deleted, id)
	return nil
}

func (f *fakeBackend) Status(_ context.Context, id string) (workload.Status, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if st, ok := f.instances[id]; ok {
		return st, nil
	}
	return workload.Status{}, workload.ErrNotFound
}

func (f *fakeBackend) Reservation(context.Context) (workload.Reservation, error) {
	return f.reserve, nil
}

func quiet() *slog.Logger { return slog.New(slog.DiscardHandler) }

func newTestHost(t *testing.T, b workload.Backend, extra func(httpx.Router) error) http.Handler {
	t.Helper()
	h, err := NewHost(HostConfig{ID: "agent-1", Token: testToken, Addr: ":0"}, b, quiet(), extra)
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func call(t *testing.T, h http.Handler, method, path, token string, body any) *httptest.ResponseRecorder {
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
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func owned(id, url string) workload.Status {
	return workload.Status{ID: id, Status: workload.StatusRunning, InternalURL: url, Labels: map[string]string{OwnerLabel: "agent-1"}}
}

func TestNewHostRefusesAShortTokenAndNoID(t *testing.T) {
	if _, err := NewHost(HostConfig{ID: "a", Token: "short"}, &fakeBackend{}, quiet(), nil); err == nil {
		t.Fatal("a short token was accepted")
	}
	if _, err := NewHost(HostConfig{Token: testToken}, &fakeBackend{}, quiet(), nil); err == nil {
		t.Fatal("a host without an id was accepted")
	}
}

func TestInstanceRoutesRejectMissingOrWrongToken(t *testing.T) {
	h := newTestHost(t, &fakeBackend{}, nil)
	for _, token := range []string{"", "wrong-token-wrong-token-wrong-to"} {
		for _, tc := range []struct{ method, path string }{
			{http.MethodPost, "/dataplane/v1/instances"},
			{http.MethodGet, "/dataplane/v1/instances/abc"},
			{http.MethodDelete, "/dataplane/v1/instances/abc"},
			{http.MethodGet, "/dataplane/v1/reservation"},
			{http.MethodPost, "/dataplane/v1/instances/abc/proxy/mcp"},
		} {
			if got := call(t, h, tc.method, tc.path, token, nil); got.Code != http.StatusUnauthorized {
				t.Errorf("%s %s with token %q: got %d, want 401", tc.method, tc.path, token, got.Code)
			}
		}
	}
}

func TestReservationReportsTheBackendsDefault(t *testing.T) {
	want := workload.Reservation{CPUMillicores: 100, MemoryBytes: 128 << 20}
	got := call(t, newTestHost(t, &fakeBackend{reserve: want}, nil), http.MethodGet, "/dataplane/v1/reservation", testToken, nil)
	if got.Code != http.StatusOK {
		t.Fatalf("got %d: %s", got.Code, got.Body)
	}
	var r workload.Reservation
	if err := json.Unmarshal(got.Body.Bytes(), &r); err != nil {
		t.Fatal(err)
	}
	if r != want {
		t.Fatalf("got %+v, want %+v", r, want)
	}
}

func TestHealthzNeedsNoToken(t *testing.T) {
	if got := call(t, newTestHost(t, &fakeBackend{}, nil), http.MethodGet, "/healthz", "", nil); got.Code != http.StatusOK {
		t.Fatalf("got %d", got.Code)
	}
}

func TestCreateStampsOwnerLabelOverCallerValue(t *testing.T) {
	b := &fakeBackend{}
	spec := workload.Spec{InstanceID: "i-1", Name: "mcp-1", ServiceName: "mcp-1", Image: "example:latest",
		Labels: map[string]string{OwnerLabel: "someone-else", "keep": "me"}}
	if got := call(t, newTestHost(t, b, nil), http.MethodPost, "/dataplane/v1/instances", testToken, spec); got.Code != http.StatusCreated {
		t.Fatalf("got %d: %s", got.Code, got.Body)
	}
	if b.created.Labels[OwnerLabel] != "agent-1" || b.created.Labels["keep"] != "me" {
		t.Fatalf("labels %v", b.created.Labels)
	}
}

func TestCreateRejectsSpecWithoutServiceName(t *testing.T) {
	b := &fakeBackend{}
	spec := workload.Spec{InstanceID: "i-1", Name: "mcp-1", Image: "example:latest"}
	if got := call(t, newTestHost(t, b, nil), http.MethodPost, "/dataplane/v1/instances", testToken, spec); got.Code != http.StatusBadRequest {
		t.Fatalf("got %d", got.Code)
	}
	if b.created != nil {
		t.Fatal("an unaddressable spec reached the backend")
	}
}

func TestUnownedInstanceIsIndistinguishableFromMissing(t *testing.T) {
	b := &fakeBackend{instances: map[string]workload.Status{
		"theirs": {ID: "theirs", Labels: map[string]string{OwnerLabel: "another-agent"}},
		"bare":   {ID: "bare"},
	}}
	h := newTestHost(t, b, nil)
	for _, id := range []string{"theirs", "bare", "absent"} {
		for _, m := range []string{http.MethodGet, http.MethodDelete} {
			if got := call(t, h, m, "/dataplane/v1/instances/"+id, testToken, nil); got.Code != http.StatusNotFound {
				t.Errorf("%s %s: got %d, want 404", m, id, got.Code)
			}
		}
		if got := call(t, h, http.MethodPost, "/dataplane/v1/instances/"+id+"/proxy/mcp", testToken, nil); got.Code != http.StatusNotFound {
			t.Errorf("proxy %s: got %d, want 404", id, got.Code)
		}
	}
	if len(b.deleted) != 0 {
		t.Fatalf("deleted %v", b.deleted)
	}
}

func TestDeleteRemovesAnOwnedInstance(t *testing.T) {
	b := &fakeBackend{instances: map[string]workload.Status{"mine": owned("mine", "")}}
	if got := call(t, newTestHost(t, b, nil), http.MethodDelete, "/dataplane/v1/instances/mine", testToken, nil); got.Code != http.StatusNoContent {
		t.Fatalf("got %d", got.Code)
	}
	if len(b.deleted) != 1 || b.deleted[0] != "mine" {
		t.Fatalf("deleted %v", b.deleted)
	}
}

func TestRouteExtensionIsServedOnlyBehindAuthentication(t *testing.T) {
	h := newTestHost(t, &fakeBackend{}, func(r httpx.Router) error {
		r.Handle("GET /extension", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) }))
		return nil
	})
	for _, token := range []string{"", "wrong-token"} {
		if got := call(t, h, http.MethodGet, "/dataplane/v1/extension", token, nil); got.Code != http.StatusUnauthorized {
			t.Fatalf("unauthenticated extension route returned %d", got.Code)
		}
	}
	if got := call(t, h, http.MethodGet, "/dataplane/v1/extension", testToken, nil); got.Code != http.StatusNoContent {
		t.Fatalf("authenticated extension route returned %d", got.Code)
	}
}

func TestCoreHostServesNoUsageRoute(t *testing.T) {
	if got := call(t, newTestHost(t, &fakeBackend{}, nil), http.MethodGet, "/dataplane/v1/usage", testToken, nil); got.Code != http.StatusNotFound {
		t.Fatalf("got %d", got.Code)
	}
}

func proxied(t *testing.T, h http.Handler, path string) (int, string, http.Header) {
	t.Helper()
	srv := httptest.NewServer(h)
	defer srv.Close()
	req, err := http.NewRequest(http.MethodPost, srv.URL+path, strings.NewReader(`{"jsonrpc":"2.0"}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp.StatusCode, strings.TrimSpace(string(body)), resp.Header
}

func TestProxyForwardsPathAndQueryWithoutTheHostCredential(t *testing.T) {
	var gotPath, gotQuery, gotAuth string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath, gotQuery, gotAuth = r.URL.Path, r.URL.RawQuery, r.Header.Get("Authorization")
		_, _ = w.Write([]byte("warm"))
	}))
	defer upstream.Close()
	b := &fakeBackend{instances: map[string]workload.Status{"mine": owned("mine", upstream.URL)}}
	start := time.Now()
	status, body, _ := proxied(t, newTestHost(t, b, nil), "/dataplane/v1/instances/mine/proxy/mcp?x=1")
	if status != http.StatusOK || body != "warm" {
		t.Fatalf("got %d %q", status, body)
	}
	if gotPath != "/mcp" || gotQuery != "x=1" || gotAuth != "" {
		t.Fatalf("upstream saw path=%q query=%q auth=%q", gotPath, gotQuery, gotAuth)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("a warm instance waited")
	}
}

func reservedAddress(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := l.Addr().String()
	if err := l.Close(); err != nil {
		t.Fatal(err)
	}
	return addr
}

func TestFirstRequestWaitsForAServerThatIsStillBinding(t *testing.T) {
	addr := reservedAddress(t)
	b := &fakeBackend{instances: map[string]workload.Status{"mine": owned("mine", "http://"+addr)}}
	served := make(chan struct{})
	go func() {
		time.Sleep(400 * time.Millisecond)
		l, err := net.Listen("tcp", addr)
		if err != nil {
			return
		}
		srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("served")) }), ReadHeaderTimeout: time.Second}
		defer func() { _ = srv.Close() }()
		close(served)
		_ = srv.Serve(l)
	}()
	status, body, _ := proxied(t, newTestHost(t, b, nil), "/dataplane/v1/instances/mine/proxy/mcp")
	select {
	case <-served:
	default:
		t.Fatal("answered before the server listened")
	}
	if status != http.StatusOK || body != "served" {
		t.Fatalf("got %d %q", status, body)
	}
}

func TestProxyWaitsForAStartingWorkloadToRun(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("up")) }))
	defer upstream.Close()
	b := &fakeBackend{instances: map[string]workload.Status{"mine": {ID: "mine", Status: workload.StatusStarting, Labels: map[string]string{OwnerLabel: "agent-1"}}}}
	go func() {
		time.Sleep(300 * time.Millisecond)
		b.mu.Lock()
		b.instances["mine"] = owned("mine", upstream.URL)
		b.mu.Unlock()
	}()
	if status, body, _ := proxied(t, newTestHost(t, b, nil), "/dataplane/v1/instances/mine/proxy/mcp"); status != http.StatusOK || body != "up" {
		t.Fatalf("got %d %q", status, body)
	}
}

func TestProxyRefusesAStoppedWorkload(t *testing.T) {
	st := owned("mine", "http://127.0.0.1:1")
	st.Status = workload.StatusStopped
	b := &fakeBackend{instances: map[string]workload.Status{"mine": st}}
	if status, _, _ := proxied(t, newTestHost(t, b, nil), "/dataplane/v1/instances/mine/proxy/mcp"); status != http.StatusBadGateway {
		t.Fatalf("got %d, want 502", status)
	}
}
