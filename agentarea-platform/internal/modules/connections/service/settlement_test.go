package service

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

type settleSpecs struct {
	memSpecs
	catalog map[string]map[string]any
}

func (s *settleSpecs) CatalogJSONSpec(_ context.Context, _ scope.Workspace, id string) (map[string]any, bool, error) {
	spec, ok := s.catalog[id]
	return spec, ok, nil
}

type settleItems map[uuid.UUID]CatalogAPIItem

func (m settleItems) CatalogAPIItem(_ context.Context, _ scope.Workspace, id uuid.UUID) (CatalogAPIItem, error) {
	it, ok := m[id]
	if !ok {
		return CatalogAPIItem{}, &domain.NotFound{Msg: "Catalog connection not found"}
	}
	return it, nil
}

type settleOut struct{ asked []netguard.Destination }

func (*settleOut) Guard() *netguard.Guard { return nil }
func (o *settleOut) Transport(d netguard.Destination) http.RoundTripper {
	o.asked = append(o.asked, d)
	return http.DefaultTransport
}

type settleFixture struct {
	svc     *Service
	ws      scope.Workspace
	insts   rtInstances
	conns   *writesStore
	specs   *settleSpecs
	items   settleItems
	secrets *memSecrets
	auth    *memAuth
	out     *settleOut
}

func newSettleFixture(t *testing.T) *settleFixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "")
	if err != nil {
		t.Fatal(err)
	}
	f := &settleFixture{ws: ws, insts: rtInstances{rows: map[string]domain.Instance{}},
		conns: &writesStore{rows: map[uuid.UUID]domain.Connection{}},
		specs: &settleSpecs{memSpecs: memSpecs{specs: map[string]catalogapi.MCPSpec{}}, catalog: map[string]map[string]any{}},
		items: settleItems{}, secrets: &memSecrets{values: map[string]string{}},
		auth: &memAuth{rows: map[uuid.UUID]domain.AuthConfig{}}, out: &settleOut{}}
	f.svc = New(Deps{DB: memDB{}, Instances: f.insts, OpenAPIWrites: f.conns, Specs: f.specs, CatalogItems: f.items,
		Secrets: f.secrets, Auth: f.auth, Out: f.out})
	return f
}

func settledDecl(path string) map[string]any {
	return map[string]any{"source": "settled", "settled": map[string]any{"fetch": map[string]any{
		"url": "https://vendor.example/" + path + "/{run}", "params": map[string]any{"run": "$.id"},
		"cost": "$.usage.total", "currency": "USD"}}}
}

func (f *settleFixture) instance(transport, specID string, jsonSpec map[string]any) string {
	id := uuid.NewString()
	f.insts.rows[id] = domain.Instance{ID: id, WorkspaceID: f.ws.ID(), CreatedBy: "owner", Name: "Vendor",
		ServerSpecID: specID, Transport: transport, JSONSpec: jsonSpec}
	return id
}

func TestSettleDeclarationOfAnMCPInstance(t *testing.T) {
	f := newSettleFixture(t)
	f.specs.catalog["vendor"] = map[string]any{"name": "com.vendor/mcp", "metadata": map[string]any{
		metaCost: map[string]any{"default": settledDecl("default"), "tools": map[string]any{"run": settledDecl("run")}}}}
	f.specs.catalog["listless"] = map[string]any{"metadata": map[string]any{metaCost: map[string]any{"tools": []any{}}}}
	f.specs.catalog["broken"] = map[string]any{"metadata": map[string]any{metaCost: "free"}}
	f.specs.catalog["bad-tools"] = map[string]any{"metadata": map[string]any{metaCost: map[string]any{"tools": "run"}}}
	ctx := context.Background()
	id := f.instance(domain.TransportURL, "vendor", nil)

	got, err := f.svc.SettledDeclaration(ctx, f.ws, "u1", id, "run")
	if err != nil || !reflect.DeepEqual(got, settledDecl("run")) {
		t.Fatalf("own tool: %v %v", got, err)
	}
	got, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", id, "other")
	if err != nil || !reflect.DeepEqual(got, settledDecl("default")) {
		t.Fatalf("default: %v %v", got, err)
	}
	for _, spec := range []string{"members-own", "listless"} {
		got, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", f.instance(domain.TransportURL, spec, nil), "run")
		if err != nil || got != nil {
			t.Fatalf("%s: %v %v", spec, got, err)
		}
	}
	for _, spec := range []string{"broken", "bad-tools"} {
		_, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", f.instance(domain.TransportURL, spec, nil), "run")
		var inv *domain.Invalid
		if !errors.As(err, &inv) {
			t.Fatalf("%s: %v", spec, err)
		}
	}
	_, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", f.instance(domain.TransportBundle, "vendor", nil), "run")
	var inv *domain.Invalid
	if !errors.As(err, &inv) {
		t.Fatalf("bundle: %v", err)
	}
	for _, gone := range []string{uuid.NewString(), "not-a-uuid"} {
		if _, err := f.svc.SettledDeclaration(ctx, f.ws, "u1", gone, "run"); !errors.Is(err, api.ErrConnectionGone) {
			t.Fatalf("%s: %v", gone, err)
		}
	}
}

func settleOpenAPIDoc() map[string]any {
	return map[string]any{
		"openapi": "3.0.0", "info": map[string]any{"title": "Vendor", "version": "1"},
		"x-agentarea-cost": settledDecl("default"),
		"paths": map[string]any{"/runs": map[string]any{
			"post": map[string]any{"operationId": "startRun", "x-agentarea-cost": settledDecl("run")},
			"get":  map[string]any{"operationId": "listRuns"},
		}},
	}
}

func TestSettleDeclarationOfAnOpenAPIConnection(t *testing.T) {
	f := newSettleFixture(t)
	ctx := context.Background()
	item := uuid.New()
	f.items[item] = CatalogAPIItem{ID: item, Name: "Vendor", Spec: map[string]any{"spec_content": settleOpenAPIDoc()}}
	itemID, gone := item.String(), uuid.NewString()
	platform := domain.ManagedByPlatform
	conns := map[string]domain.Connection{
		"catalog":  {RegistryItemID: &itemID, SpecContent: map[string]any{"openapi": "3.0.0", "paths": map[string]any{}}},
		"platform": {ManagedBy: &platform, SpecContent: settleOpenAPIDoc()},
		"by-hand":  {SpecContent: settleOpenAPIDoc()},
		"retired":  {RegistryItemID: &gone, SpecContent: settleOpenAPIDoc()},
	}
	ids := map[string]string{}
	for name, c := range conns {
		id := uuid.New()
		c.ID, c.WorkspaceID = id.String(), f.ws.ID()
		f.conns.rows[id] = c
		ids[name] = id.String()
	}
	for _, name := range []string{"catalog", "platform"} {
		got, err := f.svc.SettledDeclaration(ctx, f.ws, "u1", ids[name], "startRun")
		if err != nil || !reflect.DeepEqual(got, settledDecl("run")) {
			t.Fatalf("%s own: %v %v", name, got, err)
		}
		got, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", ids[name], "listRuns")
		if err != nil || !reflect.DeepEqual(got, settledDecl("default")) {
			t.Fatalf("%s default: %v %v", name, got, err)
		}
		got, err = f.svc.SettledDeclaration(ctx, f.ws, "u1", ids[name], "deleteRun")
		if err != nil || got != nil {
			t.Fatalf("%s unknown operation: %v %v", name, got, err)
		}
	}
	for _, name := range []string{"by-hand", "retired"} {
		got, err := f.svc.SettledDeclaration(ctx, f.ws, "u1", ids[name], "startRun")
		if err != nil || got != nil {
			t.Fatalf("%s: %v %v", name, got, err)
		}
	}
}

func TestSettleFetchSendsTheMCPInstanceCredential(t *testing.T) {
	f := newSettleFixture(t)
	var seen http.Header
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.Header.Clone()
		if r.Method != http.MethodGet || r.URL.Path != "/runs/r1" {
			w.WriteHeader(http.StatusTeapot)
			return
		}
		_, _ = w.Write([]byte(`{"usage":{"total":"0.25"}}`))
	}))
	t.Cleanup(srv.Close)
	remote := srv.URL + "/mcp"
	f.specs.specs["vendor"] = catalogapi.MCPSpec{ID: "vendor", RemoteURL: &remote,
		JSONSpec: map[string]any{"headers": map[string]any{"X-Plain": "p"}}}
	authID := uuid.New()
	key := "auth-secret"
	f.auth.rows[authID] = domain.AuthConfig{ID: authID.String(), CreatedBy: "owner", AuthType: "bearer", SecretKey: &key}
	f.secrets.values[key] = `{"token":"tok"}`
	id := f.instance(domain.TransportURL, "vendor", map[string]any{"env_vars": []any{"X-Vendor-Key"}})
	inst := f.insts.rows[id]
	a := authID.String()
	inst.AuthConfigID = &a
	f.insts.rows[id] = inst
	f.secrets.values[domain.InstanceSecretName(id, "X-Vendor-Key")] = "vk"

	status, body, err := f.svc.FetchSettlement(context.Background(), f.ws, "u1", id, srv.URL+"/runs/r1")
	if err != nil || status != http.StatusOK {
		t.Fatalf("%d %s %v", status, body, err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatal(err)
	}
	if seen.Get("X-Plain") != "p" || seen.Get("X-Vendor-Key") != "vk" || seen.Get("Authorization") != "Bearer tok" {
		t.Fatalf("headers %v", seen)
	}
	if !reflect.DeepEqual(f.out.asked, []netguard.Destination{netguard.Member}) {
		t.Fatalf("destinations %v", f.out.asked)
	}
}

func TestSettleFetchSendsTheOpenAPIConnectionCredentialAndPassesStatus(t *testing.T) {
	f := newSettleFixture(t)
	var seen http.Header
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.Header.Clone()
		w.WriteHeader(http.StatusNotFound)
	}))
	t.Cleanup(srv.Close)
	id := uuid.New()
	plain := "v1"
	f.conns.rows[id] = domain.Connection{ID: id.String(), WorkspaceID: f.ws.ID(), BaseURL: srv.URL,
		CustomHeaders: []domain.Header{{Name: "X-Key", Secret: true}, {Name: "X-Version", Value: &plain}}}
	f.secrets.values[domain.SecretHeaderKey(id.String(), "X-Key")] = "secret"

	status, _, err := f.svc.FetchSettlement(context.Background(), f.ws, "u1", id.String(), srv.URL+"/runs/r1")
	if err != nil || status != http.StatusNotFound {
		t.Fatalf("%d %v", status, err)
	}
	if seen.Get("X-Key") != "secret" || seen.Get("X-Version") != "v1" {
		t.Fatalf("headers %v", seen)
	}
	if _, _, err := f.svc.FetchSettlement(context.Background(), f.ws, "u1", uuid.NewString(), srv.URL); !errors.Is(err, api.ErrConnectionGone) {
		t.Fatalf("gone: %v", err)
	}
}
