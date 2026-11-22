package service

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

const keepSecret = "<kept>"

// recordingMCPs creates, updates and re-discovers MCP connections in memory.
type recordingMCPs struct {
	log      *deployLog
	names    map[string]string
	n        int
	updates  map[string]catalogapi.BundleMCPUpdate
	verified []string
}

func (r *recordingMCPs) InstanceName(_ context.Context, _ authn.Caller, id string) (string, bool, error) {
	name, ok := r.names[id]
	return name, ok, nil
}
func (r *recordingMCPs) CreateFromSpec(_ context.Context, _ authn.Caller, specID string, in catalogapi.BundleInstance) (catalogapi.BundleMCPCreated, error) {
	r.n++
	id := fmt.Sprintf("mcp-%d", r.n)
	r.names[id] = in.Name
	return catalogapi.BundleMCPCreated{InstanceID: id, SpecID: specID}, nil
}
func (r *recordingMCPs) CreateWithSpec(_ context.Context, _ authn.Caller, _ catalogapi.MCPSpecNew, in catalogapi.BundleInstance) (catalogapi.BundleMCPCreated, error) {
	r.n++
	id := fmt.Sprintf("mcp-%d", r.n)
	r.names[id] = in.Name
	r.log.add("create mcp %s %v", in.Name, in.JSONSpec)
	return catalogapi.BundleMCPCreated{InstanceID: id, SpecID: fmt.Sprintf("spec-%d", r.n)}, nil
}
func (r *recordingMCPs) UpdateMCP(_ context.Context, _ authn.Caller, id string, u catalogapi.BundleMCPUpdate) error {
	r.updates[id] = u
	r.names[id] = u.Instance.Name
	return nil
}
func (r *recordingMCPs) Rediscover(_ context.Context, _ authn.Caller, id string) (catalogapi.BundleDiscovery, error) {
	r.verified = append(r.verified, id)
	return catalogapi.BundleDiscovery{Status: "succeeded", Tools: 3}, nil
}
func (r *recordingMCPs) DeleteInstance(_ context.Context, _ authn.Caller, id string) error {
	delete(r.names, id)
	return nil
}
func (r *recordingMCPs) DeleteSpec(context.Context, authn.Caller, string) error { return nil }
func (r *recordingMCPs) SecretProblem(context.Context, authn.Caller, string) (string, error) {
	return "", nil
}
func (r *recordingMCPs) CarriesSecretRef(any) bool                   { return false }
func (r *recordingMCPs) SecretRef(name string) any                   { return map[string]any{"$secret": name} }
func (r *recordingMCPs) KeepSecret() any                             { return keepSecret }
func (r *recordingMCPs) ContextSecretLength() (minimum, maximum int) { return 16, 512 }
func (r *recordingMCPs) SpecTransport(catalogapi.MCPSpec) (string, bool) {
	return "url", true
}

const mcpBundle = `
name: mcpb
setup:
  - {key: token, label: Token, type: secret}
  - {key: region, label: Region, type: string}
mcps:
  - key: search
    name: Search
    json_spec: {type: url, url: "https://${setup.region}.search.example/mcp"}
    bindings: {Authorization: "${setup.token}", X-Region: "${setup.region}"}
agents:
  - {key: a, name: A, model: us-model, mcps: [search]}
`

func mcpFixture(t *testing.T) (*deployFixture, *recordingMCPs, Bundle, InstallResult) {
	t.Helper()
	f := newDeployFixture(t)
	mcps := &recordingMCPs{log: f.log, names: map[string]string{}, updates: map[string]catalogapi.BundleMCPUpdate{}}
	f.w.b.d.MCPs = mcps
	b := mustParse(t, mcpBundle)
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	res, err := in.install(context.Background(), &b, demoValues(), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(mcps.verified) != 0 {
		t.Fatalf("a first install re-discovered %v; creating verifies", mcps.verified)
	}
	return f, mcps, b, res
}

func redeployMCP(t *testing.T, f *deployFixture, src string, supplied wirejson.Object, prior *priorInstall) (ImportPreview, InstallResult, error) {
	t.Helper()
	b := mustParse(t, src)
	p, err := (&bundleAnalyzer{existence: f.w, prior: prior, shapes: fakeShapes{}, supplied: supplied}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	approved := map[entityRef]bool{}
	for _, e := range p.Entities {
		if e.Status == StatusWillUpdate {
			approved[entityRef{e.Kind, e.Key}] = true
		}
	}
	res, err := (&bundleInstaller{w: f.w, approved: approved}).install(context.Background(), &b, supplied, prior, nil)
	return p, res, err
}

func mcpEntity(t *testing.T, r InstallResult) InstalledEntity {
	t.Helper()
	for _, e := range r.Entities {
		if e.Kind == KindMCP {
			return e
		}
	}
	t.Fatalf("no mcp in %+v", r.Entities)
	return InstalledEntity{}
}

func TestRedeployUpdatesAChangedMCPAndKeepsItsSecret(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	changed := strings.Replace(mcpBundle, "search.example/mcp", "search.example/v2/mcp", 1)
	p, res2, err := redeployMCP(t, f, changed, wirejson.Object{{Key: "region", Value: "us"}}, &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range p.Entities {
		if e.Kind == KindMCP && (e.Status != StatusWillUpdate || e.Detail != nil) {
			t.Fatalf("plan for the mcp = %+v", e)
		}
	}
	for _, i := range p.Issues {
		if strings.Contains(i.Message, "not updated on redeploy") {
			t.Fatalf("still warns: %+v", i)
		}
	}
	u, ok := mcps.updates["mcp-1"]
	if !ok || u.Spec == nil || *u.Spec.RemoteURL != "https://us.search.example/v2/mcp" || u.SetContextSecret {
		t.Fatalf("update = %+v", u)
	}
	headers := u.Instance.JSONSpec["headers"]
	if !reflect.DeepEqual(headers, map[string]any{"Authorization": keepSecret, "X-Region": "us"}) {
		t.Fatalf("headers = %v", headers)
	}
	e := mcpEntity(t, res2)
	if e.Action != ActionUpdated || *e.ID != "mcp-1" || e.Detail == nil || *e.Detail != "tools re-discovered: 3" ||
		!reflect.DeepEqual(mcps.verified, []string{"mcp-1"}) {
		t.Fatalf("entity = %+v, verified %v", e, mcps.verified)
	}
}

func TestRedeployRediscoversAnUnchangedMCP(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	p, res2, err := redeployMCP(t, f, mcpBundle, wirejson.Object{}, &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatal(err)
	}
	if p.Entities[0].Kind != KindMCP || p.Entities[0].Status != StatusUnchanged {
		t.Fatalf("plan = %+v", p.Entities)
	}
	e := mcpEntity(t, res2)
	if len(mcps.updates) != 0 || e.Action != ActionUnchanged || *e.Detail != "tools re-discovered: 3" ||
		!reflect.DeepEqual(mcps.verified, []string{"mcp-1"}) {
		t.Fatalf("updates %v, entity %+v", mcps.updates, e)
	}
}

func TestRedeployWritesANewlySuppliedSecret(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	p, _, err := redeployMCP(t, f, mcpBundle, wirejson.Object{{Key: "token", Value: "n3w"}}, &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatal(err)
	}
	if p.Entities[0].Status != StatusWillUpdate {
		t.Fatalf("plan = %+v", p.Entities)
	}
	if h := mcps.updates["mcp-1"].Instance.JSONSpec["headers"]; !reflect.DeepEqual(h, map[string]any{"Authorization": "n3w", "X-Region": "us"}) {
		t.Fatalf("headers = %v", h)
	}
}

func TestRedeployRefusesAnMCPThatChangesWhatItIs(t *testing.T) {
	f, _, first, res := mcpFixture(t)
	for _, c := range []struct{ from, to, want string }{
		{"json_spec: {type: url, url: \"https://${setup.region}.search.example/mcp\"}", "catalog: com.example/search",
			"mcp 'search' changes from its own spec to catalog server 'com.example/search', which a redeploy cannot apply; give it a new key"},
		{"json_spec: {type: url, url: \"https://${setup.region}.search.example/mcp\"}", "json_spec: {type: command, command: npx, args: [search]}",
			"mcp 'search' changes transport from url to command, which a redeploy cannot apply; give it a new key"},
	} {
		b := mustParse(t, strings.Replace(mcpBundle, c.from, c.to, 1))
		p, err := (&bundleAnalyzer{existence: f.w, prior: &priorInstall{bundle: first, result: res}, shapes: fakeShapes{},
			supplied: wirejson.Object{}}).analyze(context.Background(), &b)
		if err != nil {
			t.Fatal(err)
		}
		if got := blockMessages(p); len(got) != 1 || got[0] != c.want {
			t.Fatalf("blocks = %q", got)
		}
	}
}
