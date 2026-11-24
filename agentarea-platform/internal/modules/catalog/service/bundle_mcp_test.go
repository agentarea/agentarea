package service

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

const keepSecret = "<kept>"

// recordingMCPs creates, updates and re-discovers MCP connections in memory.
type recordingMCPs struct {
	log   *deployLog
	names map[string]string
	// stored are the plain values each instance's environment and headers hold.
	stored   map[string]map[string]string
	n        int
	updates  map[string]catalogapi.BundleMCPUpdate
	verified []string
	// discoverErr fails every re-discovery; refuse refuses the caller every comparison and re-discovery.
	discoverErr error
	refuse      bool
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
	r.store(id, in.JSONSpec)
	r.log.add("create mcp %s %v", in.Name, in.JSONSpec)
	return catalogapi.BundleMCPCreated{InstanceID: id, SpecID: "spec-of-" + id}, nil
}
func (r *recordingMCPs) UpdateMCP(_ context.Context, _ authn.Caller, id string, u catalogapi.BundleMCPUpdate) error {
	r.updates[id] = u
	r.names[id] = u.Instance.Name
	r.store(id, u.Instance.JSONSpec)
	return nil
}

func (r *recordingMCPs) store(id string, spec map[string]any) {
	if r.stored[id] == nil {
		r.stored[id] = map[string]string{}
	}
	for _, field := range []string{"environment", "headers"} {
		values, _ := spec[field].(map[string]any)
		for k, v := range values {
			if s, ok := v.(string); ok && s != keepSecret {
				r.stored[id][k] = s
			}
		}
	}
}

func (r *recordingMCPs) SecretsMatch(_ context.Context, _ authn.Caller, id string, values map[string]string, _ *string) (map[string]bool, bool, error) {
	if r.refuse {
		return nil, false, &catalogapi.BundleRefusal{Msg: "you may not edit MCP instance " + id}
	}
	out := map[string]bool{}
	for k, v := range values {
		out[k] = r.stored[id][k] == v
	}
	return out, false, nil
}
func (r *recordingMCPs) InstancesNamed(_ context.Context, _ authn.Caller, name string) ([]string, error) {
	var ids []string
	for id, n := range r.names {
		if n == name {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	return ids, nil
}
func (r *recordingMCPs) InstanceSpecID(_ context.Context, _ authn.Caller, id string) (string, bool, error) {
	_, ok := r.names[id]
	return "spec-of-" + id, ok, nil
}
func (r *recordingMCPs) Rediscover(_ context.Context, _ authn.Caller, id string) (catalogapi.BundleDiscovery, error) {
	if r.refuse {
		return catalogapi.BundleDiscovery{}, &catalogapi.BundleRefusal{Msg: "you may not edit MCP instance " + id}
	}
	r.verified = append(r.verified, id)
	r.log.add("rediscover %s", id)
	if r.discoverErr != nil {
		return catalogapi.BundleDiscovery{}, r.discoverErr
	}
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
	mcps := &recordingMCPs{log: f.log, names: map[string]string{}, updates: map[string]catalogapi.BundleMCPUpdate{},
		stored: map[string]map[string]string{}}
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
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: prior, shapes: fakeShapes{}, supplied: supplied}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	approved := map[entityRef]bool{}
	for _, e := range p.Entities {
		if e.Status == StatusWillUpdate {
			approved[entityRef{e.Kind, e.Key}] = true
		}
	}
	in := &bundleInstaller{w: f.w, approved: approved}
	res, err := in.install(context.Background(), &b, supplied, prior, nil)
	if err == nil {
		in.rediscoverMCPs(context.Background(), &res)
	}
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

// A member who may not edit another's MCP connection cannot update it by deploying --into its bundle.
func TestRedeployOfAnMCPNeedsEditOnItAndItsSpec(t *testing.T) {
	changed := strings.Replace(mcpBundle, "search.example/mcp", "search.example/v2/mcp", 1)
	for _, c := range []struct {
		denied string
		want   string
	}{
		{"mcp_instance", "mcp 'search' would be updated, but you may not edit mcp mcp-1"},
		{"mcp_server", "mcp 'search' would be updated, but you may not edit its MCP server spec spec-of-mcp-1"},
	} {
		f, mcps, first, res := mcpFixture(t)
		f.denied[c.denied] = true
		b := mustParse(t, changed)
		p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: &priorInstall{bundle: first, result: res}, shapes: fakeShapes{},
			supplied: wirejson.Object{}}).analyze(context.Background(), &b)
		if err != nil {
			t.Fatal(err)
		}
		if got := blockMessages(p); len(got) != 1 || got[0] != c.want {
			t.Fatalf("denied %s: blocks = %q, edits asked %v", c.denied, got, f.edits)
		}
		_, _, err = redeployMCP(t, f, changed, wirejson.Object{}, &priorInstall{bundle: first, result: res})
		if err == nil || len(mcps.updates) != 0 {
			t.Fatalf("denied %s: install err %v, updates %v", c.denied, err, mcps.updates)
		}
	}
}

// CI redeploys with the same --set secret every time: that is no change, and no restart.
func TestRedeployWithTheSameSecretIsUnchanged(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	p, res2, err := redeployMCP(t, f, mcpBundle, demoValues(), &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatal(err)
	}
	if p.Entities[0].Status != StatusUnchanged || len(mcps.updates) != 0 || mcpEntity(t, res2).Action != ActionUnchanged {
		t.Fatalf("plan %+v, updates %v", p.Entities, mcps.updates)
	}
	changed := strings.Replace(mcpBundle, "search.example/mcp", "search.example/v2/mcp", 1)
	if _, _, err := redeployMCP(t, f, changed, demoValues(), &priorInstall{bundle: first, result: res}); err != nil {
		t.Fatal(err)
	}
	if h := mcps.updates["mcp-1"].Instance.JSONSpec["headers"]; !reflect.DeepEqual(h, map[string]any{"Authorization": keepSecret, "X-Region": "us"}) {
		t.Fatalf("an update re-sent an unchanged secret: %v", h)
	}
}

// Re-discovery runs once every write is done, and its failure is reported on the MCP, never failing the install.
func TestRediscoveryComesLastAndNeverFailsTheInstall(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	src := mcpBundle + "policies:\n  - {key: p, subject: a, target: \"tool:x\", effect: deny}\n"
	f.log.calls = nil
	mcps.discoverErr = errors.New("gateway unreachable")
	_, res2, err := redeployMCP(t, f, src, wirejson.Object{}, &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatalf("a failed re-discovery failed the install: %v", err)
	}
	if last := f.log.calls[len(f.log.calls)-1]; last != "rediscover mcp-1" {
		t.Fatalf("calls = %q", f.log.calls)
	}
	if d := mcpEntity(t, res2).Detail; d == nil || *d != "tools not re-discovered: gateway unreachable" {
		t.Fatalf("detail = %v", d)
	}
}

// A member without edit on the MCP who supplies its secret gets the plan's block, never a 500.
func TestASuppliedSecretOnAnMCPYouMayNotEditBlocks(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	mcps.refuse = true
	f.denied["mcp_instance"] = true
	b := mustParse(t, mcpBundle)
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: &priorInstall{bundle: first, result: res}, shapes: fakeShapes{},
		supplied: wirejson.Object{{Key: "token", Value: "n3w"}}}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatalf("analyze failed instead of blocking: %v", err)
	}
	if got := blockMessages(p); len(got) != 1 || got[0] != "mcp 'search' would be updated, but you may not edit mcp mcp-1" {
		t.Fatalf("blocks = %q", got)
	}
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{{KindMCP, "search"}: true}}
	_, err = in.install(context.Background(), &b, wirejson.Object{{Key: "token", Value: "n3w"}}, &priorInstall{bundle: first, result: res}, nil)
	var be *BundleError
	if !errors.As(err, &be) || be.Msg != "mcp 'search' would be updated, but you may not edit mcp mcp-1" || len(mcps.updates) != 0 {
		t.Fatalf("install = %v, updates %v", err, mcps.updates)
	}
}

// Re-discovery covers what this deploy created or updated, and an unchanged MCP only when the caller may edit it.
func TestRediscoveryOfAnMCPYouMayNotEdit(t *testing.T) {
	f, mcps, first, res := mcpFixture(t)
	f.denied["mcp_instance"] = true
	_, res2, err := redeployMCP(t, f, mcpBundle, wirejson.Object{}, &priorInstall{bundle: first, result: res})
	if err != nil {
		t.Fatal(err)
	}
	if d := mcpEntity(t, res2).Detail; d == nil || *d != "tools not re-discovered: you may not edit it" || len(mcps.verified) != 0 {
		t.Fatalf("detail %v, verified %v", d, mcps.verified)
	}
	created := mustParse(t, strings.ReplaceAll(strings.Replace(mcpBundle, "key: search", "key: search2", 1), "[search]", "[search2]"))
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	got, err := in.install(context.Background(), &created, demoValues(), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	mcps.refuse = true
	in.rediscoverMCPs(context.Background(), &got)
	if d := mcpEntity(t, got).Detail; d == nil || *d != "tools not re-discovered: you may not edit it" {
		t.Fatalf("created mcp detail %v", d)
	}
}

const existingBundle = `
name: ex
mcps:
  - {key: sentry, name: cx-sentry, existing: true}
agents:
  - {key: a, name: A, model: us-model, mcps: [sentry]}
`

func existingFixture(t *testing.T) (*deployFixture, *recordingMCPs) {
	t.Helper()
	f := newDeployFixture(t)
	mcps := &recordingMCPs{log: f.log, names: map[string]string{"inst-sentry": "cx-sentry"}, updates: map[string]catalogapi.BundleMCPUpdate{},
		stored: map[string]map[string]string{}}
	f.w.b.d.MCPs = mcps
	return f, mcps
}

func TestAnExistingMCPIsLinkedNeverWritten(t *testing.T) {
	f, mcps := existingFixture(t)
	p, res, err := redeployMCP(t, f, existingBundle, wirejson.Object{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range p.Issues {
		if i.Severity == "block" {
			t.Fatalf("blocked: %+v", i)
		}
	}
	if p.Entities[0].Kind != KindMCP || p.Entities[0].Status != StatusAlreadyExists {
		t.Fatalf("plan = %+v", p.Entities)
	}
	e := mcpEntity(t, res)
	if e.Action != ActionReused || *e.ID != "inst-sentry" || len(mcps.names) != 1 || len(mcps.updates) != 0 || len(mcps.verified) != 0 {
		t.Fatalf("entity %+v, names %v, updates %v, verified %v", e, mcps.names, mcps.updates, mcps.verified)
	}
	tools := f.agents.created[0].Tools
	if len(tools) != 1 || tools[0].Type != "mcp" || tools[0].Name != "inst-sentry" {
		t.Fatalf("agent tools = %+v", tools)
	}

	b := mustParse(t, existingBundle)
	_, res2, err := redeployMCP(t, f, existingBundle, wirejson.Object{}, &priorInstall{bundle: b, result: res})
	if err != nil {
		t.Fatal(err)
	}
	if e := mcpEntity(t, res2); e.Action != ActionReused || *e.ID != "inst-sentry" || len(mcps.updates) != 0 {
		t.Fatalf("redeploy entity %+v, updates %v", e, mcps.updates)
	}
}

func TestAnExistingMCPTheWorkspaceLacksBlocks(t *testing.T) {
	f, mcps := existingFixture(t)
	mcps.names["inst-2"] = "cx-sentry"
	for src, want := range map[string]string{
		strings.Replace(existingBundle, "cx-sentry", "cx-missing", 1): "names no MCP connection of this workspace called 'cx-missing'",
		existingBundle: "names 2 MCP connections called 'cx-sentry'",
	} {
		b := mustParse(t, src)
		p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, shapes: fakeShapes{}}).analyze(context.Background(), &b)
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, i := range p.Issues {
			found = found || (i.Severity == "block" && strings.Contains(i.Message, want))
		}
		if !found {
			t.Fatalf("%q: issues %+v", want, p.Issues)
		}
	}
}

func TestAnExistingMCPTakesOnlyItsName(t *testing.T) {
	src := strings.Replace(existingBundle, "existing: true}", "existing: true, catalog: x}", 1)
	if _, err := ParseBundle(src); err == nil || !strings.Contains(err.Error(), "existing connection") {
		t.Fatalf("err = %v", err)
	}
}

func TestAnExistingMCPAnotherBundleOwnsIsLinked(t *testing.T) {
	f, _ := existingFixture(t)
	b := mustParse(t, existingBundle)
	owner := otherInstall{id: "inst-9", name: "stubs", result: InstallResult{BundleName: "stubs", Entities: []InstalledEntity{
		{Kind: KindMCP, Key: "s", Name: "cx-sentry", Action: ActionCreated, ID: strp("inst-sentry")}}}}
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, shapes: fakeShapes{}, others: []otherInstall{owner}}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range p.Issues {
		if i.Severity == SeverityBlock {
			t.Fatalf("blocked: %+v", i)
		}
	}
}
