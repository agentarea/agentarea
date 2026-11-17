package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

type noSpecs struct{ service.SpecStore }

func (noSpecs) ProviderSpec(context.Context, db.Session, uuid.UUID) (api.ProviderSpec, bool, error) {
	return api.ProviderSpec{}, false, nil
}

func (noSpecs) ProviderSpecByKey(context.Context, db.Session, string) (api.ProviderSpec, bool, error) {
	return api.ProviderSpec{}, false, nil
}

func (noSpecs) OwnModelSpec(context.Context, db.Session, uuid.UUID) (api.ModelSpec, bool, error) {
	return api.ModelSpec{}, false, nil
}

func (noSpecs) ModelSpecByProviderAndName(context.Context, db.Session, uuid.UUID, string) (api.ModelSpec, bool, error) {
	return api.ModelSpec{}, false, nil
}

func (noSpecs) CatalogModel(context.Context, db.Session, uuid.UUID) (store.CatalogModel, bool, error) {
	return store.CatalogModel{}, false, nil
}

type noSecrets struct{}

func (noSecrets) GetForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, &ksecrets.NotFoundError{Message: "Secret not found"}
}
func (noSecrets) AddReference(context.Context, string, string, string, string) error { return nil }
func (noSecrets) ClearReferences(context.Context, string, string) error              { return nil }

func specServer(t *testing.T, admin bool) *httptest.Server {
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
	gate := func(context.Context) error {
		if admin {
			return nil
		}
		return &service.ForbiddenError{Detail: "Only a workspace admin may perform this action"}
	}
	svc := service.New(service.Deps{
		DB: fakeDB{}, Specs: noSpecs{}, Registries: &fakeStore{registries: map[string]domain.Registry{}}, Authority: authority(true),
		Secrets: func(scope.Workspace, ksecrets.Actor) service.SecretUse { return noSecrets{} },
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc, nil, nil, gate))
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s
}

func TestAdminGateRefusesBeforeValidation(t *testing.T) {
	s := specServer(t, false)
	for _, c := range []struct{ method, path string }{
		{http.MethodPost, "/model-specs/"},
		{http.MethodPost, "/model-specs/upsert"},
		{http.MethodPatch, "/model-specs/nope"},
		{http.MethodDelete, "/model-specs/nope"},
		{http.MethodPost, "/workspace-registries"},
		{http.MethodPatch, "/workspace-registries/nope"},
	} {
		status, body := call(t, s, c.method, c.path, `[]`)
		if status != http.StatusForbidden || !strings.Contains(body, "Only a workspace admin may perform this action") {
			t.Errorf("%s %s: %d %s", c.method, c.path, status, body)
		}
	}
}

func TestModelSpecValidation(t *testing.T) {
	s := specServer(t, true)
	pid := uuid.NewString()
	for _, c := range []struct{ body, want string }{
		{`{}`, `"loc":["body","provider_spec_id"]`},
		{`{"provider_spec_id":1,"model_name":"m","display_name":"M","context_window":1}`, `"type":"uuid_type"`},
		{`{"provider_spec_id":"` + pid + `","model_name":"m","display_name":"M","kind":"audio","context_window":1}`, `"type":"enum"`},
		{`{"provider_spec_id":"` + pid + `","model_name":"m","display_name":"M","context_window":0}`, `"type":"greater_than"`},
		{`{"provider_spec_id":"` + pid + `","model_name":"m","display_name":"M","context_window":1,"input_cost_per_token":true}`,
			`"msg":"Value error, True is not a money amount"`},
		{`{"provider_spec_id":"` + pid + `","model_name":"m","display_name":"M","context_window":1,"input_cost_per_token":"-1"}`,
			`"type":"greater_than_equal"`},
		{`{"provider_spec_id":"` + pid + `","model_name":"m","display_name":"M"}`, `"msg":"Value error, a chat model requires context_window"`},
	} {
		status, body := call(t, s, http.MethodPost, "/model-specs/", c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s: %d %s", c.body, status, body)
		}
	}
}

func TestSpecNotFounds(t *testing.T) {
	s := specServer(t, true)
	for _, c := range []struct{ method, path, body, want string }{
		{http.MethodGet, "/provider-specs/" + uuid.NewString(), ``, "Provider specification not found"},
		{http.MethodGet, "/provider-specs/by-key/openai", ``, "Provider specification not found"},
		{http.MethodGet, "/model-specs/" + uuid.NewString(), ``, "Model specification not found"},
		{http.MethodGet, "/model-specs/by-provider/" + uuid.NewString() + "/gpt", ``, "Model specification 'gpt' not found for provider"},
		{http.MethodPatch, "/model-specs/" + uuid.NewString(), `{}`, "Model specification not found"},
	} {
		status, body := call(t, s, c.method, c.path, c.body)
		if status != http.StatusNotFound || !strings.Contains(body, `"detail":"`+c.want+`"`) {
			t.Errorf("%s %s: %d %s", c.method, c.path, status, body)
		}
	}
}

func TestWorkspaceRegistryWrites(t *testing.T) {
	s := specServer(t, true)
	status, body := call(t, s, http.MethodPost, "/workspace-registries", `{"name":"x","source_type":"url","source_url":"https://x","scope":"platform"}`)
	if status != http.StatusUnprocessableEntity || !strings.Contains(body, `"type":"extra_forbidden","loc":["body","scope"]`) {
		t.Fatalf("%d %s", status, body)
	}
	status, body = call(t, s, http.MethodPost, "/workspace-registries", `{"name":"x","source_type":"url","source_url":"https://x","credentials_secret_id":"`+uuid.NewString()+`"}`)
	if status != http.StatusNotFound || !strings.Contains(body, `"detail":"Secret not found"`) {
		t.Fatalf("%d %s", status, body)
	}
	status, body = call(t, s, http.MethodPatch, "/workspace-registries/"+uuid.NewString(), `{"name":"y"}`)
	if status != http.StatusNotFound || !strings.Contains(body, `"detail":"Registry not found"`) {
		t.Fatalf("%d %s", status, body)
	}
}

func TestProviderListsNeedModels(t *testing.T) {
	s := specServer(t, true)
	status, _ := call(t, s, http.MethodGet, "/provider-specs/", ``)
	if status == http.StatusOK {
		t.Fatal("provider list mounted without models' spec use")
	}
}
