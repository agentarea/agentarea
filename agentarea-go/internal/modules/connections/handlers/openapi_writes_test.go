package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
)

// oaStore keeps the rows the write routes make.
type oaStore struct {
	rows map[uuid.UUID]domain.Connection
}

func (o *oaStore) List(context.Context, db.Session, service.ConnectionFilter, int32, int32) ([]domain.Connection, error) {
	return nil, nil
}
func (o *oaStore) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	c, ok := o.rows[id]
	return c, ok, nil
}
func (o *oaStore) Delete(context.Context, db.Session, uuid.UUID) (bool, error) { return false, nil }
func (o *oaStore) Full(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	return o.Get(ctx, s, id)
}
func (o *oaStore) Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	return o.Get(ctx, s, id)
}
func (o *oaStore) Insert(_ context.Context, _ db.Session, n store.ConnectionNew) (domain.Connection, error) {
	c := domain.Connection{ID: n.ID.String(), CreatedBy: n.CreatedBy, Name: n.Name, BaseURL: n.BaseURL,
		CustomHeaders: n.CustomHeaders, CustomQuery: n.CustomQuery, URLVariables: n.URLVariables, Status: n.Status,
		CreatedAt: n.Now, UpdatedAt: n.Now}
	o.rows[n.ID] = c
	return c, nil
}
func (o *oaStore) Save(_ context.Context, _ db.Session, id uuid.UUID, r store.ConnectionRow) (bool, error) {
	c := o.rows[id]
	c.Name, c.BaseURL, c.CustomHeaders = r.Name, r.BaseURL, r.CustomHeaders
	o.rows[id] = c
	return true, nil
}
func (o *oaStore) SetDiscovery(context.Context, db.Session, uuid.UUID, json.RawMessage, json.RawMessage, time.Time) (bool, error) {
	return true, nil
}
func (o *oaStore) SetLastDispatch(context.Context, db.Session, uuid.UUID, map[string]any) (bool, error) {
	return true, nil
}

// oaGraph allows every check and answers the personal tuples it was written.
type oaGraph struct{ personal map[string]bool }

func (g oaGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return true, nil
}
func (g oaGraph) Read(_ context.Context, q authz.Query) ([]authz.Tuple, error) {
	if g.personal[q.ID] {
		return []authz.Tuple{{User: authz.EveryUser, Relation: authz.RelPersonal, Object: "resource:" + q.ID}}, nil
	}
	return nil, nil
}
func (g oaGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	for _, t := range writes {
		if t.Relation == authz.RelPersonal {
			g.personal[strings.TrimPrefix(t.Object, "resource:")] = true
		}
	}
	return nil
}

type oaOut struct{ g *netguard.Guard }

func (o oaOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (o oaOut) Guard() *netguard.Guard                           { return o.g }

func oaHarness(t *testing.T) (*httptest.Server, *oaStore, *world) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	w := &world{auths: map[uuid.UUID]domain.AuthConfig{}, conns: map[uuid.UUID]domain.Connection{}, secrets: map[string]string{}, allow: true, instances: map[uuid.UUID]bool{}}
	st := &oaStore{rows: map[uuid.UUID]domain.Connection{}}
	policy, err := netguard.NewAddressPolicy(false, nil)
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(rw, r.WithContext(authn.WithCaller(r.Context(), caller)))
			})
		},
		Admin: func(context.Context) error { return nil },
	}
	svc := service.New(service.Deps{
		DB: memDB{}, Auth: w, Links: worldLinks{w}, Connections: st, OpenAPIWrites: st, Instances: worldInstances{w: w},
		Secrets: worldSecrets{w}, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return worldCatalog{} },
		Graph: oaGraph{personal: map[string]bool{}}, Out: oaOut{&netguard.Guard{Policy: policy}},
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, edge, New(svc), Ports{OpenAPI: true})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, st, w
}

func TestCreateOpenAPIConnection(t *testing.T) {
	s, st, w := oaHarness(t)
	code, body := call(t, s, http.MethodPost, "/openapi-connections/",
		`{"name":"pets","base_url":"https://8.8.8.8/v1","custom_headers":[{"name":"Authorization","value":"Bearer k"}]}`)
	if code != http.StatusCreated {
		t.Fatalf("create: %d %s", code, body)
	}
	if strings.Contains(body, "Bearer k") || !strings.Contains(body, `"personal":true`) || !strings.Contains(body, `"is_owner":true`) {
		t.Fatalf("body = %s", body)
	}
	if len(st.rows) != 1 || len(w.secrets) != 1 {
		t.Fatalf("rows = %d, secrets = %v", len(st.rows), w.secrets)
	}
}

func TestCreateOpenAPIConnectionRefusals(t *testing.T) {
	s, st, _ := oaHarness(t)
	code, body := call(t, s, http.MethodPost, "/openapi-connections/", `{"base_url":"https://x","extra":1,"custom_headers":[{"name":"a b"}]}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, `"loc":["body","name"]`) ||
		!strings.Contains(body, `"loc":["body","extra"]`) || !strings.Contains(body, `"loc":["body","custom_headers",0,"name"]`) {
		t.Fatalf("422: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/openapi-connections/", `{"name":"p","base_url":"http://127.0.0.1/"}`)
	if code != http.StatusBadRequest || !strings.Contains(body, "127.0.0.1") {
		t.Fatalf("private address: %d %s", code, body)
	}
	if len(st.rows) != 0 {
		t.Fatal("a refused create wrote")
	}
}

func TestPatchOpenAPIConnection(t *testing.T) {
	s, st, _ := oaHarness(t)
	id := uuid.New()
	st.rows[id] = domain.Connection{ID: id.String(), Name: "old", BaseURL: "https://8.8.8.8", CreatedBy: "owner"}
	if code, body := call(t, s, http.MethodPatch, "/openapi-connections/"+id.String(), `{}`); code != http.StatusBadRequest || !strings.Contains(body, "No fields to update") {
		t.Fatalf("empty: %d %s", code, body)
	}
	if code, body := call(t, s, http.MethodPatch, "/openapi-connections/"+id.String(), `{"name":null}`); code != http.StatusUnprocessableEntity {
		t.Fatalf("null name: %d %s", code, body)
	}
	code, body := call(t, s, http.MethodPatch, "/openapi-connections/"+id.String(), `{"name":"new"}`)
	if code != http.StatusOK || !strings.Contains(body, `"name":"new"`) {
		t.Fatalf("rename: %d %s", code, body)
	}
}

func TestPreviewSpecRoute(t *testing.T) {
	s, _, _ := oaHarness(t)
	code, body := call(t, s, http.MethodPost, "/openapi-connections/preview-spec", `{}`)
	if code != http.StatusBadRequest || !strings.Contains(body, "Provide spec_url or spec_content") {
		t.Fatalf("empty: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/openapi-connections/preview-spec",
		`{"spec_content":{"openapi":"3.0.0","info":{"title":"T","version":"2"},"paths":{"/a":{"get":{"operationId":"getA","summary":"A"}}}}}`)
	if code != http.StatusOK || body != `{"title":"T","description":null,"base_url":null,"version":"2","tools":[{"name":"getA","description":"A"}]}` {
		t.Fatalf("preview: %d %s", code, body)
	}
}

func TestSharingRouteValidates(t *testing.T) {
	s, st, _ := oaHarness(t)
	id := uuid.New()
	st.rows[id] = domain.Connection{ID: id.String(), Name: "c", BaseURL: "https://8.8.8.8", CreatedBy: "owner"}
	if code, body := call(t, s, http.MethodPut, "/openapi-connections/"+id.String()+"/sharing", `{"shared":"yes"}`); code != http.StatusUnprocessableEntity {
		t.Fatalf("bad shared: %d %s", code, body)
	}
	if code, body := call(t, s, http.MethodPut, "/openapi-connections/"+uuid.NewString()+"/sharing", `{"shared":true}`); code != http.StatusNotFound {
		t.Fatalf("missing: %d %s", code, body)
	}
}
