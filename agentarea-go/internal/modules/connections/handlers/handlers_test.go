package handlers

import (
	"context"
	"encoding/json"
	"io"
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
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

type memDB struct{ db.Database }

func (memDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (memDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

// world is the in-memory state the routes read and write.
type world struct {
	auths     map[uuid.UUID]domain.AuthConfig
	conns     map[uuid.UUID]domain.Connection
	secrets   map[string]string
	allow     bool
	instances map[uuid.UUID]bool
}

func (w *world) List(context.Context, db.Session) ([]domain.AuthConfig, error) {
	var out []domain.AuthConfig
	for _, a := range w.auths {
		out = append(out, a)
	}
	return out, nil
}
func (w *world) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.AuthConfig, bool, error) {
	a, ok := w.auths[id]
	return a, ok, nil
}
func (w *world) OwnedByConnection(context.Context, db.Session, uuid.UUID) ([]domain.AuthConfig, error) {
	return nil, nil
}
func (w *world) Insert(_ context.Context, _ db.Session, id uuid.UUID, by string, n domain.AuthConfigNew, now time.Time) (domain.AuthConfig, error) {
	a := domain.AuthConfig{ID: id.String(), CreatedBy: by, Name: n.Name, Description: n.Description, AuthType: n.AuthType, Config: n.Config, CreatedAt: now, UpdatedAt: now}
	w.auths[id] = a
	return a, nil
}
func (w *world) SetSecretKey(_ context.Context, _ db.Session, id uuid.UUID, key string, _ time.Time) error {
	a := w.auths[id]
	a.SecretKey = &key
	w.auths[id] = a
	return nil
}
func (w *world) Update(context.Context, db.Session, uuid.UUID, *string, *string, map[string]any, time.Time) error {
	return nil
}
func (w *world) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := w.auths[id]
	delete(w.auths, id)
	return ok, nil
}
func (w *world) LinkedInstances(context.Context, db.Session, uuid.UUID) ([]string, error) {
	return nil, nil
}
func (w *world) LinkedConnections(context.Context, db.Session, uuid.UUID) ([]string, error) {
	return nil, nil
}

func (w *world) Connection(_ context.Context, _ db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	c, ok := w.conns[id]
	return c, ok, nil
}
func (w *world) ListConnections(context.Context, db.Session, service.ConnectionFilter, int32, int32) ([]domain.Connection, error) {
	var out []domain.Connection
	for _, c := range w.conns {
		out = append(out, c)
	}
	return out, nil
}

type worldLinks struct{ w *world }

func (l worldLinks) Insert(context.Context, db.Session, uuid.UUID, string, uuid.UUID, string, string, map[string]any, *time.Time, time.Time) (domain.OAuthLink, error) {
	return domain.OAuthLink{}, nil
}
func (l worldLinks) List(context.Context, db.Session, uuid.UUID) ([]domain.OAuthLink, error) {
	return nil, nil
}
func (l worldLinks) Get(context.Context, db.Session, uuid.UUID) (domain.OAuthLink, bool, error) {
	return domain.OAuthLink{}, false, nil
}
func (l worldLinks) Deactivate(context.Context, db.Session, uuid.UUID, time.Time) (bool, error) {
	return false, nil
}

type worldInstances struct {
	service.InstanceStore
	w *world
}

func (i worldInstances) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	return domain.Instance{ID: id.String()}, i.w.instances[id], nil
}

// worldConns adapts the connection reads to service.ConnectionStore.
type worldConns struct{ *world }

func (c worldConns) List(ctx context.Context, s db.Session, f service.ConnectionFilter, l, o int32) ([]domain.Connection, error) {
	return c.ListConnections(ctx, s, f, l, o)
}
func (c worldConns) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	return c.Connection(ctx, s, id)
}
func (c worldConns) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := c.conns[id]
	delete(c.conns, id)
	return ok, nil
}

type worldSecrets struct{ w *world }

func (s worldSecrets) Manager(db.Session, string) ksecrets.Manager { return worldManager(s) }

type worldManager struct{ w *world }

func (m worldManager) Get(_ context.Context, name string) (string, error) {
	return m.w.secrets[name], nil
}
func (m worldManager) Set(_ context.Context, name, value string) error {
	m.w.secrets[name] = value
	return nil
}
func (m worldManager) Delete(_ context.Context, name string) (bool, error) {
	_, ok := m.w.secrets[name]
	delete(m.w.secrets, name)
	return ok, nil
}
func (m worldManager) Has(_ context.Context, name string) (bool, error) {
	_, ok := m.w.secrets[name]
	return ok, nil
}
func (m worldManager) ExternalRef(string) (string, bool) { return "", false }

type worldCatalog struct{}

func (worldCatalog) ClearReferences(context.Context, string, string) error { return nil }
func (worldCatalog) ListUser(context.Context) ([]ksecrets.Secret, error)   { return nil, nil }
func (worldCatalog) ListVisible(context.Context) ([]ksecrets.Secret, error) {
	return nil, nil
}
func (worldCatalog) Get(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) GetByName(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) GetForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) GetNamedForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) Consumers(context.Context, string) ([]ksecrets.ConsumerRef, error) {
	return nil, nil
}
func (worldCatalog) CreateUser(context.Context, string, string, *string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) RotateUser(context.Context, string, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) UpdateDescription(context.Context, string, *string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (worldCatalog) DeleteUser(context.Context, string) error                           { return nil }
func (worldCatalog) AddReference(context.Context, string, string, string, string) error { return nil }
func (worldCatalog) StageReferences(context.Context, db.Session, string, string, []ksecrets.Reference) error {
	return nil
}
func (worldCatalog) CountUser(context.Context) (int, error) { return 0, nil }

// worldGraph allows every check when w.allow is set (the owner's delete).
type worldGraph struct{ w *world }

func (g worldGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return g.w.allow, nil
}
func (g worldGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }

// harness serves the routes; admin toggles the admin check.
func harness(t *testing.T, admin bool, seed func(*world)) (*httptest.Server, *world) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	w := &world{auths: map[uuid.UUID]domain.AuthConfig{}, conns: map[uuid.UUID]domain.Connection{}, secrets: map[string]string{}, allow: true, instances: map[uuid.UUID]bool{}}
	if seed != nil {
		seed(w)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(rw, r.WithContext(authn.WithCaller(r.Context(), caller)))
			})
		},
		Admin: func(context.Context) error {
			if admin {
				return nil
			}
			return httpx.HTTPError(http.StatusForbidden, authz.NotAdminDetail)
		},
	}
	svc := service.New(service.Deps{
		DB: memDB{}, Auth: w, Links: worldLinks{w}, Connections: worldConns{w}, Instances: worldInstances{w: w},
		Secrets: worldSecrets{w}, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return worldCatalog{} },
		Graph: worldGraph{w},
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, edge, New(svc), Ports{OpenAPI: true})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, w
}

func call(t *testing.T, s *httptest.Server, method, path, body string) (int, string) {
	t.Helper()
	req, err := http.NewRequest(method, s.URL+"/v1/workspaces/acme"+path, strings.NewReader(body))
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
	return resp.StatusCode, string(raw)
}

func TestAdminRoutesRefuseMembers(t *testing.T) {
	s, _ := harness(t, false, nil)
	if code, _ := call(t, s, http.MethodGet, "/mcp-auth-configs/", ""); code != http.StatusForbidden {
		t.Fatalf("auth configs for a member: %d", code)
	}
	if code, _ := call(t, s, http.MethodPost, "/mcp-oauth-links/", `{"mcp_instance_id":"`+uuid.NewString()+`"}`); code != http.StatusForbidden {
		t.Fatalf("link create for a member: %d", code)
	}
}

func TestCreateAuthConfigValidatesThenReturnsNoCredentials(t *testing.T) {
	s, w := harness(t, true, nil)
	code, body := call(t, s, http.MethodPost, "/mcp-auth-configs/", `{"auth_type":"api_key","config":{"header_name":"X"}}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, `"loc":["body","name"]`) {
		t.Fatalf("missing name: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/mcp-auth-configs/",
		`{"name":"k","auth_type":"api_key","config":{"header_name":"X"},"credentials":{"header_value":"hunter2"}}`)
	if code != http.StatusCreated {
		t.Fatalf("create: %d %s", code, body)
	}
	if strings.Contains(body, "hunter2") || strings.Contains(body, "credentials") {
		t.Fatalf("response carries the credential: %s", body)
	}
	var got map[string]any
	if err := json.Unmarshal([]byte(body), &got); err != nil {
		t.Fatal(err)
	}
	if len(w.secrets) != 1 {
		t.Fatalf("secrets stored = %d", len(w.secrets))
	}
	if code, _ := call(t, s, http.MethodGet, "/mcp-auth-configs/not-a-uuid", ""); code != http.StatusUnprocessableEntity {
		t.Fatalf("bad id: %d", code)
	}
	id := uuid.New()
	if code, body := call(t, s, http.MethodGet, "/mcp-auth-configs/"+id.String(), ""); code != http.StatusNotFound || !strings.Contains(body, "MCP auth config not found") {
		t.Fatalf("missing config: %d %s", code, body)
	}
}

func TestCreateAuthConfigRefusesBadType(t *testing.T) {
	s, _ := harness(t, true, nil)
	code, body := call(t, s, http.MethodPost, "/mcp-auth-configs/", `{"name":"k","auth_type":"digest","credentials":{"token":"t"}}`)
	if code != http.StatusBadRequest || !strings.Contains(body, "Invalid auth_type 'digest'") {
		t.Fatalf("%d %s", code, body)
	}
}

func TestOpenAPIListMasksSecretsAndHidesPlatformTopology(t *testing.T) {
	own, platform := uuid.New(), uuid.New()
	plat := "platform"
	val := "Bearer-literal"
	s, _ := harness(t, false, func(w *world) {
		w.conns[own] = domain.Connection{ID: own.String(), Name: "mine", BaseURL: "https://api.example.test", CreatedBy: "owner",
			CustomHeaders: []domain.Header{{Name: "X-Key", Secret: true}, {Name: "Accept", Value: &val}},
			Status:        "active", AvailableTools: []domain.Tool{{Name: "get", Description: "d", InputSchema: map[string]any{"type": "object"}}}}
		w.conns[platform] = domain.Connection{ID: platform.String(), Name: "shared", BaseURL: "http://gateway.internal", ManagedBy: &plat, Status: "active"}
	})
	code, body := call(t, s, http.MethodGet, "/openapi-connections/", "")
	if code != http.StatusOK {
		t.Fatalf("list: %d %s", code, body)
	}
	if strings.Contains(body, "gateway.internal") {
		t.Fatalf("platform base URL leaks: %s", body)
	}
	var rows []map[string]any
	if err := json.Unmarshal([]byte(body), &rows); err != nil {
		t.Fatal(err)
	}
	for _, r := range rows {
		if r["name"] != "mine" {
			if r["base_url"] != nil {
				t.Fatalf("platform row base_url = %v", r["base_url"])
			}
			continue
		}
		if r["base_url"] != "https://api.example.test" || r["is_owner"] != true || r["personal"] != false {
			t.Fatalf("own row = %v", r)
		}
		headers := r["custom_headers"].([]any)
		secret := headers[0].(map[string]any)
		if secret["secret"] != true || secret["value"] != nil {
			t.Fatalf("secret header exposed: %v", secret)
		}
		plain := headers[1].(map[string]any)
		if plain["value"] != "Bearer-literal" {
			t.Fatalf("plain header = %v", plain)
		}
	}
	if code, _ := call(t, s, http.MethodGet, "/openapi-connections/"+uuid.NewString(), ""); code != http.StatusNotFound {
		t.Fatalf("missing connection: %d", code)
	}
	if code, _ := call(t, s, http.MethodGet, "/openapi-connections/?limit=0", ""); code != http.StatusUnprocessableEntity {
		t.Fatalf("limit 0: %d", code)
	}
}

func TestDeleteOpenAPIConnection(t *testing.T) {
	id := uuid.New()
	s, w := harness(t, false, func(w *world) {
		w.conns[id] = domain.Connection{ID: id.String(), Name: "gone", CustomHeaders: []domain.Header{{Name: "X", Secret: true}}}
		w.secrets["openapi:"+id.String()+":header:X"] = "v"
	})
	if code, body := call(t, s, http.MethodDelete, "/openapi-connections/"+id.String(), ""); code != http.StatusNoContent {
		t.Fatalf("delete: %d %s", code, body)
	}
	if len(w.conns) != 0 || len(w.secrets) != 0 {
		t.Fatalf("rows=%d secrets=%d", len(w.conns), len(w.secrets))
	}
	s2, _ := harness(t, false, func(w *world) { w.allow = false })
	if code, _ := call(t, s2, http.MethodDelete, "/openapi-connections/"+id.String(), ""); code != http.StatusForbidden {
		t.Fatalf("delete without the permission: %d", code)
	}
}

func TestOAuthLinkCreateAcceptsTheRequestShape(t *testing.T) {
	inst := uuid.New()
	s, _ := harness(t, true, func(w *world) { w.instances[inst] = true })
	code, body := call(t, s, http.MethodPost, "/mcp-oauth-links/",
		`{"mcp_instance_id":"`+inst.String()+`","access_control":"public","provider_config":{"provider":"x"},"expires_in_days":7}`)
	if code != http.StatusCreated {
		t.Fatalf("create: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/mcp-oauth-links/",
		`{"mcp_instance_id":"`+inst.String()+`","access_control":"world"}`)
	if code != http.StatusBadRequest || !strings.Contains(body, "Invalid access_control 'world'") {
		t.Fatalf("bad access: %d %s", code, body)
	}
}

func TestOAuthLinkValidation(t *testing.T) {
	s, _ := harness(t, true, nil)
	code, body := call(t, s, http.MethodPost, "/mcp-oauth-links/", `{"mcp_instance_id":"`+uuid.NewString()+`","expires_in_days":0}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, "greater than or equal to 1") {
		t.Fatalf("days 0: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/mcp-oauth-links/", `{"mcp_instance_id":"`+uuid.NewString()+`"}`)
	if code != http.StatusNotFound || !strings.Contains(body, "not found") {
		t.Fatalf("no instance: %d %s", code, body)
	}
}
