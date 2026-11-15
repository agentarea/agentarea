package gateway

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

func urlRuntime(server URLServer) *fakeRuntime {
	return &fakeRuntime{
		load: func(_ context.Context, id string) (Target, error) {
			return Target{InstanceID: id, WorkspaceID: testWS, URL: &server}, nil
		},
		admit: func(context.Context, Target, string, *ColdStart) (Admission, error) {
			return Admission{}, errors.New("a url instance was admitted as a workload")
		},
	}
}

func TestURLInstanceIsProxiedWithItsOwnCredentials(t *testing.T) {
	var got *http.Request
	var body string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Clone(context.Background())
		b, _ := io.ReadAll(r.Body)
		body = string(b)
		w.Header().Set("Set-Cookie", "session=upstream")
		w.Header().Set(StartingHeader, "1")
		w.Header().Set("Mcp-Session-Id", "sess")
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()
	rt := urlRuntime(URLServer{EndpointURL: upstream.URL + "/v1/mcp?tenant=a"})
	var resolvedFor Target
	rt.urlHeaders = func(_ context.Context, t Target) (map[string]string, error) {
		resolvedFor = t
		return map[string]string{"Authorization": "Bearer instance-token", "X-Api-Key": "k"}, nil
	}
	g := newTestGateway(t, testOptions(rt))
	req := mcpRequest(http.MethodPost, `{"jsonrpc":"2.0"}`)
	req.Header.Set("Accept", "application/json, text/event-stream")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Mcp-Session-Id", "sess")
	req.Header.Set("Mcp-Protocol-Version", "2025-06-18")
	req.Header.Set("Last-Event-Id", "7")
	req.Header.Set("Authorization", "Bearer caller")
	req.Header.Set("Cookie", "caller=1")
	req.Header.Set("X-Forwarded-For", "10.0.0.9")
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
	if got.URL.Path != "/v1/mcp" || got.URL.RawQuery != "tenant=a" || body != `{"jsonrpc":"2.0"}` {
		t.Fatalf("upstream saw %s?%s body %q", got.URL.Path, got.URL.RawQuery, body)
	}
	for name, want := range map[string]string{
		"Authorization": "Bearer instance-token", "X-Api-Key": "k", "Accept": "application/json, text/event-stream",
		"Content-Type": "application/json", "Mcp-Session-Id": "sess", "Mcp-Protocol-Version": "2025-06-18", "Last-Event-Id": "7",
		"Cookie": "", "X-Forwarded-For": "", AuthHeader: "",
	} {
		if v := got.Header.Get(name); v != want {
			t.Errorf("upstream header %s = %q, want %q", name, v, want)
		}
	}
	if rec.Header().Get("Set-Cookie") != "" || rec.Header().Get(StartingHeader) != "" {
		t.Fatalf("response leaked %v", rec.Header())
	}
	if rec.Header().Get("Mcp-Session-Id") != "sess" {
		t.Fatal("the endpoint's session header was dropped")
	}
	if resolvedFor.InstanceID != testInstance || resolvedFor.WorkspaceID != testWS {
		t.Fatalf("headers resolved for %+v", resolvedFor)
	}
	if _, admits, _, _ := rt.counts(); admits != 0 {
		t.Fatal("a url instance went through admission")
	}
}

func TestURLInstanceTheGatewayCannotAuthenticateIsRefused(t *testing.T) {
	for name, server := range map[string]URLServer{
		"auth config":      {EndpointURL: "https://mcp.example.com/mcp", AuthConfigID: "6f0c1c43-5b52-4a35-9b3c-1b6a2fb5f9a1"},
		"platform managed": {EndpointURL: "https://mcp.example.com/mcp", ManagedBy: "platform"},
	} {
		t.Run(name, func(t *testing.T) {
			rt := urlRuntime(server)
			g := newTestGateway(t, testOptions(rt))
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
			if rec.Code != http.StatusConflict {
				t.Fatalf("status %d", rec.Code)
			}
			if _, _, lookups, _ := rt.counts(); lookups != 0 {
				t.Fatal("credentials were resolved for a refused instance")
			}
		})
	}
}

func TestURLInstanceEndpointMustBeHTTP(t *testing.T) {
	for _, endpoint := range []string{"ftp://mcp.example.com/mcp", "mcp.example.com/mcp", "https:///mcp", "::"} {
		rt := urlRuntime(URLServer{EndpointURL: endpoint})
		g := newTestGateway(t, testOptions(rt))
		rec := httptest.NewRecorder()
		g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
		if rec.Code != http.StatusBadGateway {
			t.Errorf("%q: status %d", endpoint, rec.Code)
		}
	}
}

func TestURLInstanceCredentialFailureIsNotProxiedWithout(t *testing.T) {
	hit := false
	upstream := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { hit = true }))
	defer upstream.Close()
	rt := urlRuntime(URLServer{EndpointURL: upstream.URL})
	rt.urlHeaders = func(context.Context, Target) (map[string]string, error) {
		return nil, errors.New("secret github_token not found")
	}
	g := newTestGateway(t, testOptions(rt))
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusBadGateway || hit {
		t.Fatalf("status %d, upstream reached %v", rec.Code, hit)
	}
}

func TestURLInstanceTheEgressPolicyBlocksIsForbidden(t *testing.T) {
	rt := urlRuntime(URLServer{EndpointURL: "http://10.1.2.3/mcp"})
	o := testOptions(rt)
	o.URLs = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return nil, &netguard.BlockedError{Host: r.URL.Hostname(), Addr: netip.MustParseAddr("10.1.2.3"), Reason: "private_address"}
	})
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status %d", rec.Code)
	}
}

func TestURLInstanceTransportFailureIsBadGateway(t *testing.T) {
	rt := urlRuntime(URLServer{EndpointURL: "http://mcp.example.com/mcp"})
	o := testOptions(rt)
	o.URLs = roundTripFunc(func(*http.Request) (*http.Response, error) { return nil, errors.New("connection reset") })
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status %d", rec.Code)
	}
}

func TestURLInstanceRedirectIsNotFollowed(t *testing.T) {
	followed := false
	target := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { followed = true }))
	defer target.Close()
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusFound)
	}))
	defer upstream.Close()
	g := newTestGateway(t, testOptions(urlRuntime(URLServer{EndpointURL: upstream.URL})))
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusFound || followed {
		t.Fatalf("status %d followed %v", rec.Code, followed)
	}
}
