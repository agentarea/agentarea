package service

import (
	"context"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

type fakeBundleOpenAPIs struct {
	log     *deployLog
	names   map[string]string
	n       int
	problem string
	updated map[string]catalogapi.BundleOpenAPISpec
}

func (f *fakeBundleOpenAPIs) ConnectionName(_ context.Context, _ authn.Caller, id string) (string, bool, error) {
	n, ok := f.names[id]
	return n, ok, nil
}
func (f *fakeBundleOpenAPIs) OpenAPIProblem(context.Context, authn.Caller, catalogapi.BundleOpenAPISpec) (string, error) {
	return f.problem, nil
}
func (f *fakeBundleOpenAPIs) CreateOpenAPI(_ context.Context, _ authn.Caller, s catalogapi.BundleOpenAPISpec) (string, error) {
	f.n++
	id := fmt.Sprintf("openapi-%d", f.n)
	f.names[id] = s.Name
	f.log.add("create openapi %s %s", id, openAPIText(s))
	return id, nil
}
func (f *fakeBundleOpenAPIs) UpdateOpenAPI(_ context.Context, _ authn.Caller, id string, s catalogapi.BundleOpenAPISpec) error {
	f.updated[id] = s
	f.log.add("update openapi %s %s", id, openAPIText(s))
	return nil
}
func (f *fakeBundleOpenAPIs) DeleteOpenAPI(_ context.Context, _ authn.Caller, id string) error {
	delete(f.names, id)
	f.log.add("delete openapi %s", id)
	return nil
}
func (fakeBundleOpenAPIs) HeaderIsSecret(name string) bool {
	return !strings.EqualFold(name, "accept")
}

func paramsText(ps []catalogapi.BundleOpenAPIParam) string {
	var out []string
	for _, p := range ps {
		switch {
		case p.SecretName != nil: // pragma: allowlist secret
			out = append(out, p.Name+"=secret:"+*p.SecretName)
		case p.Keep:
			out = append(out, p.Name+"=kept")
		case p.Secret:
			out = append(out, p.Name+"=secret-value:"+p.Value)
		default:
			out = append(out, p.Name+"="+p.Value)
		}
	}
	sort.Strings(out)
	return strings.Join(out, ",")
}

func openAPIText(s catalogapi.BundleOpenAPISpec) string {
	spec := "inline"
	if s.SpecURL != nil {
		spec = *s.SpecURL
	}
	return fmt.Sprintf("%s %s spec=%s headers{%s} query{%s} vars{%s}", s.Name, s.BaseURL, spec, paramsText(s.Headers), paramsText(s.Query),
		paramsText(s.Variables))
}

const openAPIBundle = `
name: ops
setup:
  - {key: tenant, label: Tenant, default: acme}
  - {key: key, label: API key, type: secret}
openapi:
  - key: crm
    name: CRM
    base_url: "https://${setup.tenant}.crm.example.com"
    spec_url: https://crm.example.com/openapi.json
    headers: {Authorization: "${secret.crm_token}", Accept: application/json}
    query: {api_key: "${setup.key}", format: json}
  - key: pets
    name: Pets
    base_url: https://pets.example.com
    spec: {openapi: 3.0.0, info: {title: Pets, version: "1"}, paths: {}}
agents:
  - {key: sales, name: Sales, model: us-model, openapi: [crm, pets]}
`

func TestLoadOpenAPIConnectionsFromAFolder(t *testing.T) {
	b, issues, err := LoadBundleFolder(StrPairs{
		{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\nopenapi:\n  include: openapi/*.yaml\n" +
			"  pets:\n    base_url: https://pets.example.com\n    spec: {openapi: 3.0.0, info: {title: Pets, version: '1'}, paths: {}}\n"},
		{"agents/sales.md", "---\nname: sales\nmodel: us-model\nopenapi: [crm, pets]\n---\nSell."},
		{"openapi/crm.yaml", "name: crm\ndisplay_name: CRM\nbase_url: https://crm.example.com\nspec_url: https://crm.example.com/openapi.json\n" +
			"headers: {Authorization: '${secret.crm_token}'}\n"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("issues = %+v", issues)
	}
	if len(b.OpenAPI) != 2 || b.OpenAPI[0].Key != "pets" || b.OpenAPI[0].Spec == nil || b.OpenAPI[1].Key != "crm" || b.OpenAPI[1].Name != "CRM" ||
		*b.OpenAPI[1].SpecURL != "https://crm.example.com/openapi.json" {
		t.Fatalf("openapi = %+v", b.OpenAPI)
	}
	if !reflect.DeepEqual(b.Agents[0].OpenAPI, []string{"crm", "pets"}) {
		t.Fatalf("agent openapi = %v", b.Agents[0].OpenAPI)
	}
	if _, err := ParseBundle("name: x\nopenapi: [{key: a, name: a, base_url: 'https://a'}]\n"); err == nil ||
		!strings.Contains(err.Error(), "openapi 'a' needs exactly one of 'spec_url' or 'spec'") {
		t.Fatalf("no spec: %v", err)
	}
}

func TestOpenAPIPlanChecksSecretsAndReferences(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, openAPIBundle, nil)
	if len(p.Issues) != 0 {
		t.Fatalf("issues = %+v", p.Issues)
	}
	var got []string
	for _, e := range p.Entities {
		if e.Kind == KindOpenAPI {
			got = append(got, fmt.Sprintf("%s:%s:%s", e.Key, e.Status, *e.Detail))
		}
	}
	want := []string{"crm:will_create:spec at https://crm.example.com/openapi.json; Authorization from secret 'crm_token'", "pets:will_create:inline spec"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("entities = %q", got)
	}
	p = analyzeWith(t, f, `
name: ops
openapi:
  - {key: crm, name: CRM, base_url: "https://crm", spec_url: "https://crm/spec", headers: {Authorization: "Bearer abc"}, query: {key: "x${secret.k}"}}
agents:
  - {key: sales, name: Sales, model: us-model, openapi: [crm, erp]}
`, nil)
	wantBlocks := []string{
		"openapi 'crm' header 'Authorization' must be ${secret.<name>} or reference ${setup.<key>}",
		"openapi 'crm' query parameter 'key' must be ${secret.<name>} alone",
		"agent 'sales' references unknown openapi connection 'erp'",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, wantBlocks) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestOpenAPIInstallWiresTheAgentAndRedeploysInPlace(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, openAPIBundle)
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	res, err := in.install(context.Background(), &b, wirejson.Object{{Key: "key", Value: "k3y"}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	wantCalls := []string{
		"create openapi openapi-1 CRM https://acme.crm.example.com spec=https://crm.example.com/openapi.json " +
			"headers{Accept=application/json,Authorization=secret:crm_token} query{api_key=secret-value:k3y,format=json} vars{}", // pragma: allowlist secret
		"create openapi openapi-2 Pets https://pets.example.com spec=inline headers{} query{} vars{}",
	}
	if got := f.log.calls[:2]; !reflect.DeepEqual(got, wantCalls) {
		t.Fatalf("calls = %q", f.log.calls)
	}
	var tools []string
	for _, tool := range f.agents.created[0].Tools {
		tools = append(tools, tool.Type+":"+tool.Name+"="+*tool.ConnectionID)
	}
	if !reflect.DeepEqual(tools, []string{"openapi:openapi-1=openapi-1", "openapi:openapi-2=openapi-2"}) {
		t.Fatalf("agent tools = %v", tools)
	}

	prior := &priorInstall{bundle: b, result: res}
	changed := mustParse(t, strings.Replace(openAPIBundle, "format: json", "format: xml", 1))
	f.log.calls = nil
	in = &bundleInstaller{w: f.w, approved: map[entityRef]bool{{KindOpenAPI, "crm"}: true}}
	if _, err := in.install(context.Background(), &changed, wirejson.Object{}, prior, nil); err != nil {
		t.Fatal(err)
	}
	want := []string{"update openapi openapi-1 CRM https://acme.crm.example.com spec=https://crm.example.com/openapi.json " +
		"headers{Accept=application/json,Authorization=secret:crm_token} query{api_key=kept,format=xml} vars{}"} // pragma: allowlist secret
	if !reflect.DeepEqual(f.log.calls, want) {
		t.Fatalf("calls = %q", f.log.calls)
	}
	if !reflect.DeepEqual(f.edits[len(f.edits)-1:], []string{"openapi_connection:openapi-1"}) {
		t.Errorf("edit checks = %v", f.edits)
	}
}
