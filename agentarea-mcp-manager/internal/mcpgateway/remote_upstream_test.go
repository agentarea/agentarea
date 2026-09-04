package mcpgateway

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

const testRemoteToken = "0123456789012345678901234567890123456789"

func testRemote(base string) *RemoteUpstream {
	return &RemoteUpstream{BaseURL: base, Token: testRemoteToken}
}

// In remote mode the container has no address in this network, so the upstream
// must be the data plane's per-instance proxy path. Using the local service URL
// resolved nothing and every MCP request failed.
func TestInstanceProxyURLAddressesTheDataPlane(t *testing.T) {
	got := testRemote("https://mcp-dp.example.com/").InstanceProxyURL("abc-123")
	want := "https://mcp-dp.example.com/dataplane/v1/instances/abc-123/proxy/mcp"
	if got != want {
		t.Fatalf("InstanceProxyURL() = %q, want %q", got, want)
	}
}

func TestNewProviderRuntimeRejectsHalfConfiguredRemote(t *testing.T) {
	for name, remote := range map[string]*RemoteUpstream{
		"no token": {BaseURL: "https://mcp-dp.example.com"},
		"no url":   {Token: testRemoteToken},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := NewProviderRuntime(
				selectorStub{provider: &runtimeProviderStub{}},
				&runtimeBackendStub{},
				&config.Config{Environment: "dataplane"},
				testImagePolicy(t),
				time.Second,
				remote,
			)
			if err == nil {
				t.Fatal("NewProviderRuntime() error = nil, want a refusal to start half-configured")
			}
		})
	}
}

// The machine credential belongs to this control plane: the real proxy attaches
// it to the outgoing hop, replacing whatever the caller sent, so a caller can
// neither read it nor smuggle its own credential to the data plane.
func TestRemoteHopCarriesTheMachineCredential(t *testing.T) {
	var seen string
	dataPlane := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		seen = request.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("proxied"))
	}))
	defer dataPlane.Close()

	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{
		InstanceID: instanceID,
		JSONSpec:   map[string]any{"type": "docker"},
	}}
	remote := testRemote(dataPlane.URL)
	runtime := &runtimeStub{endpoint: remote.InstanceProxyURL(instanceID)}
	gateway := testGateway(t, repository, runtime)
	gateway.remote = remote

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader("{}"))
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	request.Header.Set("Authorization", "Bearer caller-supplied")

	gateway.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK || recorder.Body.String() != "proxied" {
		t.Fatalf("response = %d %q", recorder.Code, recorder.Body.String())
	}
	if seen != "Bearer "+testRemoteToken {
		t.Fatalf("data plane saw Authorization %q, want the machine credential", seen)
	}
}

// Without a remote upstream the caller's own Authorization passes through
// untouched: a local MCP server may authenticate its clients itself.
func TestLocalHopLeavesCallerCredentialAlone(t *testing.T) {
	var seen string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		seen = request.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{
		InstanceID: instanceID,
		JSONSpec:   map[string]any{"type": "docker"},
	}}
	runtime := &runtimeStub{endpoint: upstream.URL + "/mcp"}

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader("{}"))
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	request.Header.Set("Authorization", "Bearer caller-supplied")

	testGateway(t, repository, runtime).ServeHTTP(recorder, request)

	if seen != "Bearer caller-supplied" {
		t.Fatalf("upstream saw Authorization %q, want the caller's own", seen)
	}
}

// Anything that is not exactly the configured data plane is proxied without the
// credential rather than handed one it must never see.
func TestOtherUpstreamsNeverReceiveTheCredential(t *testing.T) {
	gateway := &Gateway{remote: testRemote("https://mcp-dp.example.com")}
	for name, raw := range map[string]string{
		"another host":   "https://evil.example.com/dataplane/v1/instances/abc-123/proxy/mcp",
		"another scheme": "http://mcp-dp.example.com/dataplane/v1/instances/abc-123/proxy/mcp",
		"another path":   "https://mcp-dp.example.com/admin",
		"in-cluster":     "http://mcp-abc-123.agentarea.svc.cluster.local:8000/mcp",
	} {
		t.Run(name, func(t *testing.T) {
			target, err := url.Parse(raw)
			if err != nil {
				t.Fatal(err)
			}
			if gateway.isRemoteUpstream(target, nil) {
				t.Fatalf("isRemoteUpstream(%q) = true; the credential would leak", raw)
			}
		})
	}
}

func TestLocalDeploymentsHaveNoRemoteHop(t *testing.T) {
	gateway := &Gateway{}
	target, err := url.Parse("http://mcp-abc.agentarea.svc.cluster.local:8000/mcp")
	if err != nil {
		t.Fatal(err)
	}
	if gateway.isRemoteUpstream(target, nil) {
		t.Fatal("isRemoteUpstream() = true without a configured data plane")
	}
}
