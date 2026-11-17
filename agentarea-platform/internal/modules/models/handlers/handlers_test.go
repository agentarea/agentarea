package handlers

import (
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeStore struct {
	service.Store
	configs map[string]domain.Config
}

func (f *fakeStore) Config(_ context.Context, _ db.Session, id uuid.UUID) (domain.Config, bool, error) {
	c, ok := f.configs[id.String()]
	return c, ok, nil
}

func (f *fakeStore) InsertConfig(_ context.Context, s db.Session, c domain.Config, now time.Time) error {
	c.WorkspaceID, c.CreatedAt, c.UpdatedAt = s.Workspace().ID(), now, now
	f.configs[c.ID] = c
	return nil
}

func (f *fakeStore) InstanceSpecIDs(context.Context, db.Session, []uuid.UUID) (map[string][]string, error) {
	return map[string][]string{}, nil
}

func (f *fakeStore) Instances(context.Context, db.Session, store.InstanceFilter) ([]domain.Instance, error) {
	return []domain.Instance{}, nil
}

func (f *fakeStore) VisibleInstanceSpecs(context.Context, db.Session) (map[uuid.UUID]uuid.UUID, error) {
	return map[uuid.UUID]uuid.UUID{}, nil
}

func (f *fakeStore) ConfigsOfInstances(context.Context, db.Session, []uuid.UUID) (map[string]domain.Config, error) {
	return map[string]domain.Config{}, nil
}

type fakeCatalog struct {
	catalogapi.Specs
	spec catalogapi.ProviderSpec
}

func (f fakeCatalog) ProviderSpec(_ context.Context, _ scope.Workspace, id uuid.UUID) (catalogapi.ProviderSpec, bool, error) {
	return f.spec, id == f.spec.ID, nil
}

func (f fakeCatalog) ProviderSpecs(context.Context, scope.Workspace, []uuid.UUID) (map[uuid.UUID]catalogapi.ProviderSpec, error) {
	return map[uuid.UUID]catalogapi.ProviderSpec{f.spec.ID: f.spec}, nil
}

func (f fakeCatalog) ModelSpecs(context.Context, scope.Workspace, []uuid.UUID) (map[uuid.UUID]catalogapi.ModelSpec, error) {
	return map[uuid.UUID]catalogapi.ModelSpec{}, nil
}

type fakeSecrets struct{ values map[string]string }

type manager struct{ f *fakeSecrets }

func (m manager) Get(_ context.Context, n string) (string, error) {
	if v, ok := m.f.values[n]; ok {
		return v, nil
	}
	return "", ksecrets.ErrNotFound
}
func (m manager) Set(_ context.Context, n, v string) error         { m.f.values[n] = v; return nil }
func (m manager) Delete(context.Context, string) (bool, error)     { return false, nil }
func (m manager) Has(context.Context, string) (bool, error)        { return false, nil }
func (m manager) ExternalRef(string) (string, bool)                { return "", false }
func (f *fakeSecrets) Manager(db.Session, string) ksecrets.Manager { return manager{f} }
func (f *fakeSecrets) Secret(context.Context, db.Session, string) (ksecrets.Secret, bool, error) {
	return ksecrets.Secret{}, false, nil
}
func (f *fakeSecrets) SecretNamed(_ context.Context, _ db.Session, n string) (ksecrets.Secret, bool, error) {
	return ksecrets.Secret{ID: "sid-" + n, Name: n}, true, nil
}
func (f *fakeSecrets) StageReferences(context.Context, db.Session, string, string, []ksecrets.Reference) error {
	return nil
}

type fakeOut struct{ guard *netguard.Guard }

func (fakeOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (fakeOut) Dialer() netguard.Dialer                          { return nil }
func (o fakeOut) Guard() *netguard.Guard                         { return o.guard }

type fixture struct {
	srv     *httptest.Server
	st      *fakeStore
	sec     *fakeSecrets
	spec    catalogapi.ProviderSpec
	icons   string
	handler *Server
}

func server(t *testing.T) *fixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	policy, _ := netguard.NewAddressPolicy(false, nil)
	f := &fixture{
		st:   &fakeStore{configs: map[string]domain.Config{}},
		sec:  &fakeSecrets{values: map[string]string{}},
		spec: catalogapi.ProviderSpec{ID: uuid.New(), ProviderKey: "openai", Name: "OpenAI", ProviderType: "openai", RequiresAPIKey: true},
	}
	svc := service.New(service.Deps{DB: fakeDB{}, Store: f.st, Catalog: fakeCatalog{spec: f.spec}, Secrets: f.sec,
		Out: fakeOut{guard: &netguard.Guard{Policy: policy}},
		Now: func() time.Time { return time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC) }})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	f.handler = New(svc)
	f.icons = t.TempDir()
	f.handler.Icons = os.DirFS(f.icons)
	r := chi.NewRouter()
	Mount(r, errs, admit, admit, f.handler)
	f.srv = httptest.NewServer(r)
	t.Cleanup(f.srv.Close)
	return f
}

func (f *fixture) call(t *testing.T, method, path, body string) (*http.Response, string) {
	t.Helper()
	url := f.srv.URL + path
	if !strings.HasPrefix(path, "/v1/pricing") {
		url = f.srv.URL + "/v1/workspaces/acme" + path
	}
	req, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp, string(raw)
}

func TestPricingCurrency(t *testing.T) {
	f := server(t)
	resp, body := f.call(t, http.MethodGet, "/v1/pricing/currency", "")
	if resp.StatusCode != 200 || body != `{"currency":"USD"}` {
		t.Fatalf("%d %s", resp.StatusCode, body)
	}
}

func TestCreateConfigRendersPythonShapeWithoutTheKey(t *testing.T) {
	f := server(t)
	resp, body := f.call(t, http.MethodPost, "/provider-configs/",
		`{"provider_spec_id":"`+f.spec.ID.String()+`","name":"  Mine  ","api_key":"  sk-live  "}`)
	if resp.StatusCode != 200 {
		t.Fatalf("%d %s", resp.StatusCode, body)
	}
	var got map[string]any
	_ = json.Unmarshal([]byte(body), &got)
	id := got["id"].(string)
	want := `{"id":"` + id + `","provider_spec_id":"` + f.spec.ID.String() + `","name":"Mine","endpoint_url":null,"workspace_id":"` +
		got["workspace_id"].(string) + `","created_by":"owner","is_active":true,"is_public":false,"created_at":"2026-01-02T03:04:05Z",` +
		`"updated_at":"2026-01-02T03:04:05Z","managed_by":null,"requires_api_key":true,"provider_spec_name":"OpenAI","provider_spec_key":"openai","model_instance_ids":[]}`
	if body != want {
		t.Fatalf("body\n%s\nwant\n%s", body, want)
	}
	if f.sec.values["provider_config_"+id] != "sk-live" || strings.Contains(body, "sk-live") {
		t.Fatalf("secret %v", f.sec.values)
	}
}

func TestValidationIsOne422(t *testing.T) {
	f := server(t)
	spec := f.spec.ID.String()
	for _, c := range []struct{ method, path, body, want string }{
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + spec + `","name":"   "}`, `"msg":"Value error, name cannot be empty or whitespace"`},
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + spec + `","name":"x","color":1}`, `"type":"extra_forbidden"`},
		{http.MethodPost, "/provider-configs/", `{"name":"x"}`, `"loc":["body","provider_spec_id"]`},
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + spec + `","name":"x","api_key":"k","api_key_secret_id":"` + uuid.NewString() + `"}`, `Provide either api_key or api_key_secret_id, not both`},
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + spec + `","name":"x","endpoint_url":"ftp://h"}`, `endpoint_url must be an http or https URL with a host`},
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + spec + `","name":"x","endpoint_url":"https://h/v1?x=1"}`, `endpoint_url must not contain a query string or fragment`},
		{http.MethodGet, "/provider-configs/nope", ``, `"type":"uuid_parsing"`},
		{http.MethodGet, "/provider-configs/?is_active=maybe", ``, `"type":"bool_parsing"`},
		{http.MethodGet, "/model-instances/?kind=audio", ``, `"type":"enum"`},
		{http.MethodPost, "/model-instances/bulk", `{"items":[]}`, `"type":"too_short"`},
		{http.MethodPost, "/model-instances/", `{"provider_config_id":"x","model_spec_id":"` + spec + `","name":"n"}`, `"type":"uuid_parsing"`},
		{http.MethodPost, "/model-instances/test", `{"model_spec_id":"` + spec + `"}`, `"loc":["body","provider_config_id"]`},
	} {
		resp, body := f.call(t, c.method, c.path, c.body)
		if resp.StatusCode != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s %s %s: %d %s", c.method, c.path, c.body, resp.StatusCode, body)
		}
	}
}

func TestErrorsRenderAsPythonRaisesThem(t *testing.T) {
	f := server(t)
	platform := domain.ManagedByPlatform
	id := uuid.NewString()
	f.st.configs[id] = domain.Config{ID: id, ProviderSpecID: f.spec.ID.String(), Name: "Hosted", WorkspaceID: "platform", ManagedBy: &platform}
	for _, c := range []struct {
		method, path, body string
		status             int
		want               string
	}{
		{http.MethodGet, "/provider-configs/" + uuid.NewString(), "", 404, `"detail":"Provider configuration not found"`},
		{http.MethodGet, "/model-instances/" + uuid.NewString(), "", 404, `"detail":"Model instance not found"`},
		{http.MethodPatch, "/provider-configs/" + id, `{"name":"x"}`, 403, `"code":"permission_denied","detail":"Provider configuration 'Hosted' is supplied by the platform and cannot be modified."`},
		{http.MethodPost, "/provider-configs/" + id + "/discover", "", 403, `"detail":"Model discovery is not available for platform-supplied providers."`},
		{http.MethodPost, "/model-instances/test", `{"provider_config_id":"` + id + `","model_spec_id":"` + uuid.NewString() + `"}`, 403, `"detail":"Testing is not available for platform-supplied providers."`},
		{http.MethodPost, "/provider-configs/", `{"provider_spec_id":"` + f.spec.ID.String() + `","name":"x","endpoint_url":"http://10.0.0.1"}`, 400, `"code":"bad_request","detail":"` + service.EndpointNotAllowed + `"`},
	} {
		resp, body := f.call(t, c.method, c.path, c.body)
		if resp.StatusCode != c.status || !strings.Contains(body, c.want) {
			t.Errorf("%s %s: %d %q", c.method, c.path, resp.StatusCode, body)
		}
	}
	resp, body := f.call(t, http.MethodGet, "/provider-configs/"+id, "")
	if resp.StatusCode != 200 || !strings.Contains(body, `"endpoint_url":null`) || !strings.Contains(body, `"managed_by":"platform"`) {
		t.Fatalf("platform config read: %d %s", resp.StatusCode, body)
	}
}

func TestProviderLogo(t *testing.T) {
	f := server(t)
	resp, body := f.call(t, http.MethodGet, "/provider-configs/admin/openai/logo", "")
	if resp.StatusCode != 404 || !strings.Contains(body, `"detail":"Provider logo not found"`) {
		t.Fatalf("no icons: %d %s", resp.StatusCode, body)
	}
	if err := os.WriteFile(filepath.Join(f.icons, "openai.svg"), []byte("<svg/>"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(f.icons, "default.svg"), []byte("<svg id=d/>"), 0o600); err != nil {
		t.Fatal(err)
	}
	resp, body = f.call(t, http.MethodGet, "/provider-configs/admin/OpenAI/logo", "")
	if resp.StatusCode != 200 || body != "<svg/>" || resp.Header.Get("Content-Type") != "image/svg+xml" || resp.Header.Get("Cache-Control") != "public, max-age=3600" {
		t.Fatalf("logo: %d %s %v", resp.StatusCode, body, resp.Header)
	}
	if _, body = f.call(t, http.MethodGet, "/provider-configs/admin/other/logo", ""); body != "<svg id=d/>" {
		t.Fatalf("default: %s", body)
	}
	if resp, body = f.call(t, http.MethodGet, "/provider-configs/admin/a.b/logo", ""); resp.StatusCode != 400 || !strings.Contains(body, `"detail":"Invalid provider key"`) {
		t.Fatalf("invalid: %d %s", resp.StatusCode, body)
	}
	if resp, body = f.call(t, http.MethodGet, "/provider-configs/admin/openai%0A/logo", ""); resp.StatusCode != 400 {
		t.Fatalf("a trailing newline is not a provider key: %d %s", resp.StatusCode, body)
	}
}

func (f *fakeStore) Instance(context.Context, db.Session, uuid.UUID) (domain.Instance, bool, error) {
	return domain.Instance{}, false, nil
}

func TestProviderLogosAreTheServedIcons(t *testing.T) {
	if _, err := fs.Stat(New(nil).Icons, "openai.svg"); err != nil {
		t.Fatal(err)
	}
}
