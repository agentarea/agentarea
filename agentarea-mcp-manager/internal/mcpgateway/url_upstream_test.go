package mcpgateway

import (
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/egress"
)

const urlInstanceID = "5f0c8e4e-7a43-4a8e-9b51-2b9f6f3f1c11"

type secretResolverStub struct {
	mu     sync.Mutex
	values map[string]string
	err    error
	asked  [][]string
}

func (s *secretResolverStub) ResolveInstanceEnvVars(instanceID string, names []string) (map[string]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if instanceID != urlInstanceID {
		return nil, errors.New("resolved for the wrong instance")
	}
	s.asked = append(s.asked, append([]string(nil), names...))
	if s.err != nil {
		return nil, s.err
	}
	resolved := map[string]string{}
	for _, name := range names {
		resolved[name] = s.values[name]
	}
	return resolved, nil
}

func (s *secretResolverStub) Close() error { return nil }

func urlGateway(t *testing.T, server *URLServer, secrets *secretResolverStub, allowlist []string) (*Gateway, *gatewayRepositoryStub, *runtimeStub) {
	t.Helper()
	policy, err := egress.NewPolicy(false, allowlist)
	if err != nil {
		t.Fatal(err)
	}
	repository := &gatewayRepositoryStub{target: &Target{InstanceID: urlInstanceID, WorkspaceID: "ws-url", URL: server}}
	runtime := &runtimeStub{}
	gateway, err := New(repository, runtime, Policy{
		RequestLeaseTTL: 3 * time.Second,
		StartupTimeout:  time.Second,
		IdleTimeout:     time.Minute,
		SweepInterval:   time.Second,
		AuthSecret:      testGatewaySecret,
	}, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, URLUpstream{Secrets: secrets, Egress: policy})
	if err != nil {
		t.Fatal(err)
	}
	return gateway, repository, runtime
}

func urlRequest() *http.Request {
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+urlInstanceID+"/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"events/list"}`))
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	return request
}

func assertNoLifecycle(t *testing.T, repository *gatewayRepositoryStub, runtime *runtimeStub) {
	t.Helper()
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if repository.starting != 0 || repository.started != 0 || repository.finished != 0 || repository.failed != 0 || runtime.ensured != 0 {
		t.Fatalf("lifecycle touched for a URL instance: starting=%d started=%d finished=%d failed=%d ensured=%d",
			repository.starting, repository.started, repository.finished, repository.failed, runtime.ensured)
	}
}

func TestURLInstanceIsProxiedWithItsOwnCredentials(t *testing.T) {
	var seen *http.Request
	var body string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		seen = request.Clone(request.Context())
		raw, _ := io.ReadAll(request.Body)
		body = string(raw)
		w.Header().Set("Set-Cookie", "session=upstream")
		w.Header().Set(StartingHeader, "1")
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("data: {}\n\n"))
	}))
	defer upstream.Close()

	secrets := &secretResolverStub{values: map[string]string{"X-Api-Key": "from-the-secret-store"}}
	gateway, repository, runtime := urlGateway(t, &URLServer{
		EndpointURL: upstream.URL + "/v1/mcp?tenant=acme",
		Headers:     map[string]string{"X-Api-Key": "plain-value", "X-Region": "eu"},
		EnvVars:     []string{"X-Api-Key"},
	}, secrets, []string{"127.0.0.1"})
	observer := &requestObserverStub{}
	gateway.SetRequestObserver(observer)

	request := urlRequest()
	request.Header.Set("Authorization", "Bearer caller-supplied")
	request.Header.Set("Cookie", "caller=1")
	request.Header.Set("Accept", "application/json, text/event-stream")
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Last-Event-ID", "41")
	request.Header.Set("Mcp-Session-Id", "session-7")
	request.Header.Set("Mcp-Method", "events/list")
	request.Header.Set("X-Caller-Private", "internal")
	recorder := httptest.NewRecorder()

	gateway.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK || recorder.Body.String() != "data: {}\n\n" {
		t.Fatalf("response = %d %q", recorder.Code, recorder.Body.String())
	}
	if seen == nil {
		t.Fatal("upstream was never called")
	}
	if seen.URL.Path != "/v1/mcp" || seen.URL.RawQuery != "tenant=acme" {
		t.Fatalf("upstream URL = %s?%s, want the endpoint as given", seen.URL.Path, seen.URL.RawQuery)
	}
	if body != `{"jsonrpc":"2.0","id":1,"method":"events/list"}` {
		t.Fatalf("upstream body = %q", body)
	}
	want := map[string]string{
		"X-Api-Key":      "from-the-secret-store",
		"X-Region":       "eu",
		"Accept":         "application/json, text/event-stream",
		"Content-Type":   "application/json",
		"Last-Event-Id":  "41",
		"Mcp-Session-Id": "session-7",
		"Mcp-Method":     "events/list",
	}
	for name, value := range want {
		if got := seen.Header.Get(name); got != value {
			t.Errorf("upstream %s = %q, want %q", name, got, value)
		}
	}
	for _, name := range []string{"Authorization", "Cookie", "X-Caller-Private", "X-Agentarea-Manager-Authorization", "X-Forwarded-For", "X-Forwarded-Host"} {
		if got := seen.Header.Get(name); got != "" {
			t.Errorf("upstream received %s = %q", name, got)
		}
	}
	if got := recorder.Header().Get("Set-Cookie"); got != "" {
		t.Errorf("upstream Set-Cookie reached the caller: %q", got)
	}
	if got := recorder.Header().Get(StartingHeader); got != "" {
		t.Errorf("upstream spoofed the gateway's starting marker: %q", got)
	}
	assertNoLifecycle(t, repository, runtime)
	started, completed := observer.snapshot()
	if len(started) != 1 || len(completed) != 1 {
		t.Fatalf("observer saw %d starts and %d completions, want one each", len(started), len(completed))
	}
	if started[0].InstanceID != urlInstanceID || started[0].WorkspaceID != "ws-url" || completed[0].StatusCode != http.StatusOK {
		t.Fatalf("observer saw %+v / %+v", started[0], completed[0])
	}
}

func TestURLInstanceWithoutSecretNamesAsksTheStoreNothing(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer upstream.Close()
	secrets := &secretResolverStub{}
	gateway, _, _ := urlGateway(t, &URLServer{EndpointURL: upstream.URL}, secrets, []string{"127.0.0.1"})

	recorder := httptest.NewRecorder()
	gateway.ServeHTTP(recorder, urlRequest())

	if recorder.Code != http.StatusAccepted {
		t.Fatalf("status = %d %q", recorder.Code, recorder.Body.String())
	}
	if len(secrets.asked) != 0 {
		t.Fatalf("secret store asked for %v", secrets.asked)
	}
}

// Proxying without the credential would reach the server as an anonymous
// client; the gateway refuses instead and says why.
func TestURLInstanceTheGatewayCannotAuthenticateIsRefused(t *testing.T) {
	for name, tc := range map[string]struct {
		server URLServer
		reason string
	}{
		"auth config":      {URLServer{AuthConfigID: "0c7f5a0e-0000-4000-8000-000000000001"}, "auth config"},
		"platform-managed": {URLServer{ManagedBy: "platform"}, "platform-managed"},
	} {
		t.Run(name, func(t *testing.T) {
			hit := false
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { hit = true }))
			defer upstream.Close()
			tc.server.EndpointURL = upstream.URL
			observer := &requestObserverStub{}
			gateway, repository, runtime := urlGateway(t, &tc.server, &secretResolverStub{}, []string{"127.0.0.1"})
			gateway.SetRequestObserver(observer)

			recorder := httptest.NewRecorder()
			gateway.ServeHTTP(recorder, urlRequest())

			if recorder.Code != http.StatusConflict || !strings.Contains(recorder.Body.String(), tc.reason) {
				t.Fatalf("response = %d %q, want 409 naming %q", recorder.Code, recorder.Body.String(), tc.reason)
			}
			if hit {
				t.Fatal("upstream was called without the instance's credentials")
			}
			assertNoLifecycle(t, repository, runtime)
			if _, completed := observer.snapshot(); len(completed) != 1 || completed[0].StatusCode != http.StatusConflict {
				t.Fatalf("observer completions = %+v", completed)
			}
		})
	}
}

func TestURLInstanceAtAPrivateAddressNeedsTheAllowlist(t *testing.T) {
	hits := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		hits++
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	refused, _, _ := urlGateway(t, &URLServer{EndpointURL: upstream.URL}, &secretResolverStub{}, nil)
	recorder := httptest.NewRecorder()
	refused.ServeHTTP(recorder, urlRequest())
	if recorder.Code != http.StatusForbidden || !strings.Contains(recorder.Body.String(), "private address") {
		t.Fatalf("without an allowlist: %d %q, want 403 naming the private address", recorder.Code, recorder.Body.String())
	}
	if hits != 0 {
		t.Fatal("a member's URL reached loopback without an allowlist entry")
	}

	allowed, _, _ := urlGateway(t, &URLServer{EndpointURL: upstream.URL}, &secretResolverStub{}, []string{"127.0.0.0/8"})
	recorder = httptest.NewRecorder()
	allowed.ServeHTTP(recorder, urlRequest())
	if recorder.Code != http.StatusOK || hits != 1 {
		t.Fatalf("with an allowlist entry: %d %q, hits=%d", recorder.Code, recorder.Body.String(), hits)
	}
}

func TestURLInstanceRedirectIsNotFollowed(t *testing.T) {
	followed := false
	elsewhere := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { followed = true }))
	defer elsewhere.Close()
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		http.Redirect(w, request, elsewhere.URL+"/steal", http.StatusTemporaryRedirect)
	}))
	defer upstream.Close()
	gateway, _, _ := urlGateway(t, &URLServer{EndpointURL: upstream.URL}, &secretResolverStub{}, []string{"127.0.0.1"})

	recorder := httptest.NewRecorder()
	gateway.ServeHTTP(recorder, urlRequest())

	if recorder.Code != http.StatusTemporaryRedirect || followed {
		t.Fatalf("status = %d followed = %v, want the redirect returned unfollowed", recorder.Code, followed)
	}
}

func TestURLInstanceSecretFailureIsNotProxiedWithout(t *testing.T) {
	hit := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { hit = true }))
	defer upstream.Close()
	gateway, _, _ := urlGateway(t, &URLServer{EndpointURL: upstream.URL, EnvVars: []string{"X-Api-Key"}},
		&secretResolverStub{err: errors.New("store unavailable")}, []string{"127.0.0.1"})

	recorder := httptest.NewRecorder()
	gateway.ServeHTTP(recorder, urlRequest())

	if recorder.Code != http.StatusBadGateway || hit {
		t.Fatalf("status = %d hit = %v, want 502 and no upstream call", recorder.Code, hit)
	}
}

func TestURLInstanceEndpointMustBeHTTP(t *testing.T) {
	for _, endpoint := range []string{"", "file:///etc/passwd", "ftp://example.com/mcp", "https:///no-host"} {
		gateway, _, _ := urlGateway(t, &URLServer{EndpointURL: endpoint}, &secretResolverStub{}, nil)
		recorder := httptest.NewRecorder()
		gateway.ServeHTTP(recorder, urlRequest())
		if recorder.Code != http.StatusBadGateway {
			t.Errorf("endpoint %q: status = %d, want 502", endpoint, recorder.Code)
		}
	}
}

func TestNewRequiresASecretResolverForURLInstances(t *testing.T) {
	_, err := New(&gatewayRepositoryStub{}, &runtimeStub{}, Policy{
		RequestLeaseTTL: 3 * time.Second,
		StartupTimeout:  time.Second,
		IdleTimeout:     time.Minute,
		SweepInterval:   time.Second,
		AuthSecret:      testGatewaySecret,
	}, slog.New(slog.NewTextHandler(io.Discard, nil)), nil, URLUpstream{})
	if err == nil {
		t.Fatal("New() accepted a gateway that cannot resolve URL instance credentials")
	}
}
