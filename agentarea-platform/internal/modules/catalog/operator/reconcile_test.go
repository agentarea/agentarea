package operator

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

func TestIDsMatchThePythonOperator(t *testing.T) {
	config := WorkspaceConfigID("ws1", "agentarea", "my-cr", "openai")
	for got, want := range map[uuid.UUID]string{
		PlatformConfigID("openrouter"):                   "2178e2fa-d5c3-5731-b4bc-655efd4d86f5",
		PlatformInstanceID("openrouter", "z-ai/glm-4.6"): "d7b86a81-95f9-5c2d-8cea-9af6eaa6e62c",
		config:                               "54477ecf-d1f8-5541-b908-d7ce88d6becc",
		WorkspaceInstanceID(config, "gpt-x"): "1fc682ab-66d7-5b8b-978d-5b359ed89ffc",
		PlatformMCPInstanceID("Search"):      "0b7c1e62-ed22-5cbf-8488-31e93f055566",
	} {
		if got.String() != want {
			t.Errorf("got %s want %s", got, want)
		}
	}
}

type fakePlatform struct {
	specs     map[string]uuid.UUID
	declared  []api.DeclaredModelSpec
	items     map[string]map[string]any
	server    *api.PlatformMCPServer
	changed   bool
	providers []modelsapi.ProviderDeclaration
	defaults  []string
	mcp       []connectionsapi.DeclaredMCP
	openapi   []connectionsapi.DeclaredOpenAPI
	exits     []governanceapi.DeclaredEgressExit
}

func (f *fakePlatform) ProviderSpecID(_ context.Context, key string) (uuid.UUID, bool, error) {
	id, ok := f.specs[key]
	return id, ok, nil
}

func (f *fakePlatform) DeclareModelSpecs(_ context.Context, _ string, _ uuid.UUID, specs []api.DeclaredModelSpec) (map[string]uuid.UUID, error) {
	f.declared = append(f.declared, specs...)
	out := map[string]uuid.UUID{}
	for _, s := range specs {
		out[s.ModelName] = uuid.NewSHA1(uuid.Nil, []byte(s.ModelName))
	}
	return out, nil
}

func (f *fakePlatform) CatalogItem(_ context.Context, id string) (uuid.UUID, map[string]any, bool, error) {
	spec, ok := f.items[id]
	return uuid.NewSHA1(uuid.Nil, []byte(id)), spec, ok, nil
}

func (f *fakePlatform) DeclareMCPServer(_ context.Context, s api.PlatformMCPServer) (bool, error) {
	f.server = &s
	return f.changed, nil
}

func (f *fakePlatform) DeclareProvider(_ context.Context, d modelsapi.ProviderDeclaration) error {
	f.providers = append(f.providers, d)
	return nil
}

func (f *fakePlatform) PlatformDefaults(context.Context) ([]string, error) { return f.defaults, nil }

func (f *fakePlatform) DeclareMCP(_ context.Context, d connectionsapi.DeclaredMCP) error {
	f.mcp = append(f.mcp, d)
	return nil
}

func (f *fakePlatform) DeclareOpenAPI(_ context.Context, d connectionsapi.DeclaredOpenAPI) error {
	f.openapi = append(f.openapi, d)
	return nil
}

func (f *fakePlatform) DeclareEgressExit(_ context.Context, e governanceapi.DeclaredEgressExit) error {
	f.exits = append(f.exits, e)
	return nil
}

type secretMap map[string]string

func (s secretMap) Read(_ context.Context, namespace, name, key string) (string, error) {
	v, ok := s[namespace+"/"+name+"/"+key]
	if !ok {
		return "", errors.New("secrets \"" + name + "\" not found")
	}
	return v, nil
}

type modelList string

func (m modelList) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.URL.String() != "https://router.example/v1/models" || r.Header.Get("Authorization") != "Bearer sk" {
		return &http.Response{StatusCode: 404, Body: io.NopCloser(strings.NewReader("")), Request: r}, nil
	}
	return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(string(m))), Request: r}, nil
}

func rig(f *fakePlatform) *Reconciler {
	return New(Deps{Catalog: f, Models: f, Connections: f, Egress: f, Log: slog.New(slog.DiscardHandler),
		Secrets:      secretMap{"agentarea/keys/api": "sk", "agentarea/keys/token": " tok "},
		PlatformHTTP: &http.Client{Transport: modelList(`{"data":[{"id":"m1","name":"Model One","context_length":8000},{"id":"m2"}]}`)},
		Now:          func() time.Time { return time.Date(2026, 11, 17, 4, 0, 0, 0, time.UTC) }})
}

func TestADeclaredProviderWritesItsModelsWithTheirTags(t *testing.T) {
	f := &fakePlatform{specs: map[string]uuid.UUID{"openrouter": uuid.New()}, defaults: []string{"a", "b"}}
	out := rig(f).Provider(context.Background(), "agentarea", "or", map[string]any{
		"providerKey": "openrouter", "name": "OpenRouter", "apiKeySecretRef": map[string]any{"name": "keys", "key": "api"},
		"models": []any{
			map[string]any{"modelName": "z-ai/glm-4.6", "inputCostPerToken": 0.0000004, "outputCostPerToken": "0.0000016", "tags": []any{"default"}},
			map[string]any{"modelName": "other", "contextWindow": int64(32000)},
		},
	})
	if out.Retry != 0 || out.Status["phase"] != "Synced" || out.Status["discoveredModels"] != 2 ||
		out.Status["providerConfigId"] != "2178e2fa-d5c3-5731-b4bc-655efd4d86f5" ||
		out.Status["message"] != "Synced with 2 models; warning: 2 platform models are tagged default (a, b); new agents start on a. Tag exactly one." ||
		out.Status["lastSyncedAt"] != "2026-11-17T04:00:00.000000+00:00" {
		t.Fatalf("status %+v", out)
	}
	p := f.providers[0]
	if !p.PlatformManaged || p.APIKey != "sk" || p.WorkspaceID != "platform" || !p.IsPublic || len(p.Instances) != 2 {
		t.Fatalf("declaration %+v", p)
	}
	if p.Instances[0].ID.String() != "d7b86a81-95f9-5c2d-8cea-9af6eaa6e62c" || p.Instances[0].Tags[0] != "default" || p.Instances[1].Tags == nil {
		t.Fatalf("instances %+v", p.Instances)
	}
	if m := f.declared[0]; !m.InputCostPerToken.Equal(money.MustParse("0.0000004")) || !m.OutputCostPerToken.Equal(money.MustParse("0.0000016")) || m.ContextWindow != 4096 {
		t.Fatalf("spec %+v", m)
	}
	if f.declared[1].ContextWindow != 32000 || f.declared[1].InputCostPerToken != nil {
		t.Fatalf("second spec %+v", f.declared[1])
	}
}

func TestDiscoveredModelsKeepTheirTagsAndRediscoveryNeverRetries(t *testing.T) {
	f := &fakePlatform{specs: map[string]uuid.UUID{"router": uuid.New()}}
	spec := map[string]any{"providerKey": "router", "name": "R", "discoverModels": true, "endpointUrl": "https://router.example/",
		"apiKeySecretRef": map[string]any{"name": "keys", "key": "api"}}
	out := rig(f).Provider(context.Background(), "agentarea", "r", spec)
	if out.Status["discoveredModels"] != 2 || f.declared[0].DisplayName != "Model One" || f.declared[0].ContextWindow != 8000 ||
		f.declared[1].DisplayName != "m2" || f.providers[0].Instances[0].Tags != nil {
		t.Fatalf("out %+v declared %+v", out, f.declared)
	}
	again := rig(f).Rediscover(context.Background(), "agentarea", "r", spec)
	if again == nil || again.Status["message"] != "Re-synced with 2 models" || again.Retry != 0 {
		t.Fatalf("rediscovery %+v", again)
	}
	spec["apiKeySecretRef"] = map[string]any{"name": "gone", "key": "api"}
	failedAgain := rig(f).Rediscover(context.Background(), "agentarea", "r", spec)
	if failedAgain.Retry != 0 || failedAgain.Status["message"] != `Rediscovery failed: secrets "gone" not found` || failedAgain.Status["phase"] != nil {
		t.Fatalf("failed rediscovery %+v", failedAgain)
	}
	if rig(f).Rediscover(context.Background(), "agentarea", "r", map[string]any{"providerKey": "router"}) != nil {
		t.Fatal("a resource that does not discover was rediscovered")
	}
}

func TestAProviderRefusesWhatItCannotWrite(t *testing.T) {
	f := &fakePlatform{specs: map[string]uuid.UUID{}}
	r := rig(f)
	ref := map[string]any{"name": "keys", "key": "api"}
	cases := []struct {
		spec  map[string]any
		msg   string
		retry time.Duration
	}{
		{map[string]any{"providerKey": "x", "name": "X"}, "apiKeySecretRef is required", 0},
		{map[string]any{"providerKey": "x", "name": "X", "apiKeySecretRef": map[string]any{"namespace": "other", "name": "keys", "key": "api"}},
			"apiKeySecretRef.namespace 'other' does not match this resource's own namespace 'agentarea'; cross-namespace secret references are not allowed", 0},
		{map[string]any{"providerKey": "x", "name": "X", "apiKeySecretRef": map[string]any{"name": "gone", "key": "api"}},
			`Failed to read secret: secrets "gone" not found`, SecretRetryDelay},
		{map[string]any{"providerKey": "x", "name": "X", "apiKeySecretRef": ref}, "ProviderSpec with key 'x' not found (catalog not imported yet?)", RetryDelay},
	}
	for _, c := range cases {
		out := r.Provider(context.Background(), "agentarea", "x", c.spec)
		if out.Status["phase"] != "Error" || out.Status["message"] != c.msg || out.Retry != c.retry {
			t.Errorf("got %+v want %q after %s", out, c.msg, c.retry)
		}
	}
	if len(f.providers) != 0 {
		t.Fatal("a refused provider was written")
	}
}

func TestAWorkspaceProviderDerivesItsIDsFromTheResource(t *testing.T) {
	f := &fakePlatform{specs: map[string]uuid.UUID{"openai": uuid.New()}}
	rig(f).Provider(context.Background(), "agentarea", "my-cr", map[string]any{"providerKey": "openai", "name": "O", "workspaceId": "ws1",
		"isPublic": false, "apiKeySecretRef": map[string]any{"name": "keys", "key": "api"}, "models": []any{map[string]any{"modelName": "gpt-x"}}})
	p := f.providers[0]
	if p.PlatformManaged || p.IsPublic || p.ConfigID.String() != "54477ecf-d1f8-5541-b908-d7ce88d6becc" ||
		p.Instances[0].ID.String() != "1fc682ab-66d7-5b8b-978d-5b359ed89ffc" {
		t.Fatalf("declaration %+v", p)
	}
}

func TestAPlatformConnectionIsAnMCPServerOrAnOpenAPIConnection(t *testing.T) {
	f := &fakePlatform{changed: true, items: map[string]map[string]any{
		"acme.search": {"raw_spec": map[string]any{"metadata": map[string]any{"cost": "x"}}},
		"acme.api":    {"spec_url": "https://acme.example/openapi.json"},
		"acme.nourl":  {},
	}}
	r := rig(f)
	token := map[string]any{"name": "keys", "key": "token"}
	out := r.Connection(context.Background(), "agentarea", "c", map[string]any{"transport": "mcp", "name": "Search",
		"endpointUrl": "https://mcp.acme.example/", "catalogId": "acme.search", "tokenSecretRef": token})
	if out.Status["connectionId"] != "0b7c1e62-ed22-5cbf-8488-31e93f055566" || out.Status["mcpServerId"] != PlatformMCPServerID("Search").String() {
		t.Fatalf("mcp status %+v", out)
	}
	if f.server.JSONSpec["name"] != "acme.search" || f.server.JSONSpec["metadata"].(map[string]any)["cost"] != "x" ||
		!f.mcp[0].EndpointChanged || f.mcp[0].Token != " tok " {
		t.Fatalf("server %+v instance %+v", f.server, f.mcp)
	}
	out = r.Connection(context.Background(), "agentarea", "c", map[string]any{"transport": "openapi", "name": "Acme",
		"endpointUrl": "https://acme.example", "catalogId": "acme.api", "tokenSecretRef": token})
	if out.Status["phase"] != "Synced" || out.Status["mcpServerId"] != nil || f.openapi[0].SpecURL != "https://acme.example/openapi.json" {
		t.Fatalf("openapi %+v %+v", out, f.openapi)
	}
	for spec, want := range map[string]Outcome{
		"openapi:":           failed("catalogId is required when transport is openapi", 0),
		"openapi:acme.nourl": failed("Catalog item 'acme.nourl' has no spec_url", CatalogRetryDelay),
		"openapi:missing":    failed("Catalog item 'missing' not found (catalog not synced yet?)", CatalogRetryDelay),
		"grpc:":              failed("Unknown transport: 'grpc'", 0),
	} {
		transport, catalog, _ := strings.Cut(spec, ":")
		got := r.Connection(context.Background(), "agentarea", "c", map[string]any{"transport": transport, "name": "N",
			"catalogId": catalog, "tokenSecretRef": token})
		if got.Status["message"] != want.Status["message"] || got.Retry != want.Retry {
			t.Errorf("%s: got %+v", spec, got)
		}
	}
}

func TestAnEgressExitIsWritten(t *testing.T) {
	f := &fakePlatform{}
	out := rig(f).EgressExit(context.Background(), "agentarea", "e", map[string]any{"name": "eu", "via": "proxy-eu", "remoteDns": true})
	if out.Status["phase"] != "Synced" || out.Status["exitId"] != PlatformEgressExitID("eu").String() || !f.exits[0].RemoteDNS || f.exits[0].Description != nil {
		t.Fatalf("out %+v exits %+v", out, f.exits)
	}
}
