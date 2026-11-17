package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// memDB runs the closures without a database: the fakes below ignore sessions.
type memDB struct{ db.Database }

func (memDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (memDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type memAuth struct {
	rows   map[uuid.UUID]domain.AuthConfig
	linked []string
}

func (m *memAuth) List(context.Context, db.Session) ([]domain.AuthConfig, error) { return nil, nil }
func (m *memAuth) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.AuthConfig, bool, error) {
	a, ok := m.rows[id]
	return a, ok, nil
}
func (m *memAuth) OwnedByConnection(_ context.Context, _ db.Session, conn uuid.UUID) ([]domain.AuthConfig, error) {
	var out []domain.AuthConfig
	for _, a := range m.rows {
		if a.OpenAPIConnID != nil && *a.OpenAPIConnID == conn.String() {
			out = append(out, a)
		}
	}
	return out, nil
}
func (m *memAuth) Insert(_ context.Context, _ db.Session, id uuid.UUID, by string, n domain.AuthConfigNew, now time.Time) (domain.AuthConfig, error) {
	a := domain.AuthConfig{ID: id.String(), CreatedBy: by, Name: n.Name, Description: n.Description, AuthType: n.AuthType, Config: n.Config, CreatedAt: now, UpdatedAt: now}
	m.rows[id] = a
	return a, nil
}
func (m *memAuth) SetSecretKey(_ context.Context, _ db.Session, id uuid.UUID, key string, _ time.Time) error {
	a := m.rows[id]
	a.SecretKey = &key
	m.rows[id] = a
	return nil
}
func (m *memAuth) Update(_ context.Context, _ db.Session, id uuid.UUID, name, desc *string, cfg map[string]any, _ time.Time) error {
	a := m.rows[id]
	if name != nil {
		a.Name = *name
	}
	if desc != nil {
		a.Description = desc
	}
	if cfg != nil {
		a.Config = cfg
	}
	m.rows[id] = a
	return nil
}
func (m *memAuth) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := m.rows[id]
	delete(m.rows, id)
	return ok, nil
}
func (m *memAuth) LinkedInstances(context.Context, db.Session, uuid.UUID) ([]string, error) {
	return m.linked, nil
}
func (m *memAuth) LinkedConnections(context.Context, db.Session, uuid.UUID) ([]string, error) {
	return nil, nil
}

type memLinks struct {
	rows map[uuid.UUID]domain.OAuthLink
}

func (m *memLinks) Insert(_ context.Context, _ db.Session, id uuid.UUID, by string, inst uuid.UUID, tok, access string,
	prov map[string]any, exp *time.Time, now time.Time) (domain.OAuthLink, error) {
	l := domain.OAuthLink{ID: id.String(), CreatedBy: by, MCPInstanceID: inst.String(), Token: tok, AccessControl: access,
		ProviderConfig: prov, IsActive: true, ExpiresAt: exp, CreatedAt: now}
	m.rows[id] = l
	return l, nil
}
func (m *memLinks) List(context.Context, db.Session, uuid.UUID) ([]domain.OAuthLink, error) {
	return nil, nil
}
func (m *memLinks) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.OAuthLink, bool, error) {
	l, ok := m.rows[id]
	return l, ok, nil
}
func (m *memLinks) Deactivate(_ context.Context, _ db.Session, id uuid.UUID, _ time.Time) (bool, error) {
	l, ok := m.rows[id]
	l.IsActive = false
	m.rows[id] = l
	return ok, nil
}

type memConns struct {
	rows map[uuid.UUID]domain.Connection
}

func (m *memConns) List(context.Context, db.Session, ConnectionFilter, int32, int32) ([]domain.Connection, error) {
	var out []domain.Connection
	for _, c := range m.rows {
		out = append(out, c)
	}
	return out, nil
}
func (m *memConns) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	c, ok := m.rows[id]
	return c, ok, nil
}
func (m *memConns) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := m.rows[id]
	delete(m.rows, id)
	return ok, nil
}

type memInstances struct {
	InstanceStore
	ids map[uuid.UUID]bool
}

func (m memInstances) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	return domain.Instance{ID: id.String()}, m.ids[id], nil
}

// memSecrets is the secret store: one map shared by every session.
type memSecrets struct{ values map[string]string }

func (m *memSecrets) Manager(db.Session, string) ksecrets.Manager { return memManager{m} }

type memManager struct{ s *memSecrets }

func (m memManager) Get(_ context.Context, name string) (string, error) {
	v, ok := m.s.values[name]
	if !ok {
		return "", ksecrets.ErrNotFound
	}
	return v, nil
}
func (m memManager) Set(_ context.Context, name, value string) error {
	m.s.values[name] = value
	return nil
}
func (m memManager) Delete(_ context.Context, name string) (bool, error) {
	_, ok := m.s.values[name]
	delete(m.s.values, name)
	return ok, nil
}
func (m memManager) Has(_ context.Context, name string) (bool, error) {
	_, ok := m.s.values[name]
	return ok, nil
}
func (m memManager) ExternalRef(string) (string, bool) { return "", false }

// memCatalog records the reference clears the catalog is asked for.
type memCatalog struct{ cleared []string }

func (m *memCatalog) ClearReferences(_ context.Context, typ, id string) error {
	m.cleared = append(m.cleared, typ+":"+id)
	return nil
}

// Methods the service does not call.
func (m *memCatalog) ListUser(context.Context) ([]ksecrets.Secret, error)    { return nil, nil }
func (m *memCatalog) ListVisible(context.Context) ([]ksecrets.Secret, error) { return nil, nil }
func (m *memCatalog) Get(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) GetByName(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) GetForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) GetNamedForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) Consumers(context.Context, string) ([]ksecrets.ConsumerRef, error) {
	return nil, nil
}
func (m *memCatalog) CreateUser(context.Context, string, string, *string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) RotateUser(context.Context, string, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) UpdateDescription(context.Context, string, *string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (m *memCatalog) DeleteUser(context.Context, string) error                           { return nil }
func (m *memCatalog) AddReference(context.Context, string, string, string, string) error { return nil }
func (m *memCatalog) StageReferences(context.Context, db.Session, string, string, []ksecrets.Reference) error {
	return nil
}
func (m *memCatalog) CountUser(context.Context) (int, error) { return 0, nil }

// memGraph answers personal tuples from a set of resource ids.
type memGraph struct{ personal map[string]bool }

func (g memGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return false, nil
}
func (g memGraph) Read(_ context.Context, q authz.Query) ([]authz.Tuple, error) {
	if g.personal[q.ID] {
		return []authz.Tuple{{User: authz.EveryUser, Relation: authz.RelPersonal, Object: "resource:" + q.ID}}, nil
	}
	return nil, nil
}

type fixture struct {
	svc     *Service
	auth    *memAuth
	links   *memLinks
	conns   *memConns
	secrets *memSecrets
	catalog *memCatalog
	inst    memInstances
	ws      scope.Workspace
	caller  authn.Caller
}

func newFixture(t *testing.T, personal ...string) *fixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{
		auth:    &memAuth{rows: map[uuid.UUID]domain.AuthConfig{}},
		links:   &memLinks{rows: map[uuid.UUID]domain.OAuthLink{}},
		conns:   &memConns{rows: map[uuid.UUID]domain.Connection{}},
		secrets: &memSecrets{values: map[string]string{}},
		catalog: &memCatalog{},
		inst:    memInstances{ids: map[uuid.UUID]bool{}},
		ws:      ws,
		caller:  authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws},
	}
	g := memGraph{personal: map[string]bool{}}
	for _, p := range personal {
		g.personal[p] = true
	}
	f.svc = New(Deps{
		DB: memDB{}, Auth: f.auth, Links: f.links, Connections: f.conns, Instances: f.inst,
		Secrets: f.secrets, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return f.catalog },
		Graph: g, Now: func() time.Time { return time.Unix(1_700_000_000, 0).UTC() },
	})
	return f
}

func TestCreateStoresCredentialsByReference(t *testing.T) {
	f := newFixture(t)
	a, err := f.svc.CreateAuthConfig(context.Background(), f.caller, domain.AuthConfigNew{
		Name: "k", AuthType: "api_key", Config: map[string]any{"header_name": "X"},
		Credentials: map[string]any{"header_value": "secret-value"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if a.SecretKey == nil || *a.SecretKey != "mcp_auth_cred:"+a.ID {
		t.Fatalf("secret key = %v", a.SecretKey)
	}
	if got := f.secrets.values[*a.SecretKey]; got != `{"header_value":"secret-value"}` {
		t.Fatalf("stored credentials = %q", got)
	}
}

func TestCreateRefusesCatalogAndBadInput(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	_, err := f.svc.CreateAuthConfig(ctx, f.caller, domain.AuthConfigNew{Name: "m", AuthType: "oauth2",
		Config: map[string]any{"credential_mode": "managed", "token_url": "https://t"}, Credentials: map[string]any{"access_token": "x"}})
	var inv *domain.Invalid
	if !errors.As(err, &inv) || len(f.auth.rows) != 0 {
		t.Fatalf("managed config: err=%v rows=%d", err, len(f.auth.rows))
	}
	_, err = f.svc.CreateAuthConfig(ctx, f.caller, domain.AuthConfigNew{Name: "b", AuthType: "digest",
		Config: map[string]any{}, Credentials: map[string]any{"token": "t"}})
	if !errors.As(err, &inv) || inv.Msg != "Invalid auth_type 'digest'. Must be one of {'api_key', 'bearer', 'oauth2'}" {
		t.Fatalf("auth type: %v", err)
	}
}

func TestUpdateCatalogConfigOnlyByReconnecting(t *testing.T) {
	f := newFixture(t)
	id := uuid.New()
	f.auth.rows[id] = domain.AuthConfig{ID: id.String(), AuthType: "oauth2", Name: "c",
		Config: map[string]any{"credential_mode": "managed", "platform_oauth_issuer": "https://i", "token_url": "https://t"}}
	name := "renamed"
	if _, err := f.svc.UpdateAuthConfig(context.Background(), f.caller, id, domain.AuthConfigPatch{Name: &name}); err != nil {
		t.Fatalf("name-only change refused: %v", err)
	}
	_, err := f.svc.UpdateAuthConfig(context.Background(), f.caller, id, domain.AuthConfigPatch{Config: map[string]any{"token_url": "https://x"}})
	var inv *domain.Invalid
	if !errors.As(err, &inv) {
		t.Fatalf("config change on a catalog config: %v", err)
	}
}

func TestDeleteAuthConfigClearsReferencesAfterRow(t *testing.T) {
	f := newFixture(t)
	id := uuid.New()
	key := "mcp_auth_cred:" + id.String()
	f.auth.rows[id] = domain.AuthConfig{ID: id.String(), SecretKey: &key}
	f.secrets.values[key] = "{}"
	if err := f.svc.DeleteAuthConfig(context.Background(), f.caller, id); err != nil {
		t.Fatal(err)
	}
	if _, ok := f.secrets.values[key]; ok || len(f.auth.rows) != 0 {
		t.Fatal("credentials or row survived the delete")
	}
	if len(f.catalog.cleared) != 1 || f.catalog.cleared[0] != "mcp_auth_config:"+id.String() {
		t.Fatalf("cleared = %v", f.catalog.cleared)
	}
}

func TestDeleteAuthConfigInUseIsConflict(t *testing.T) {
	f := newFixture(t)
	id := uuid.New()
	f.auth.rows[id] = domain.AuthConfig{ID: id.String()}
	f.auth.linked = []string{"inst-1"}
	err := f.svc.DeleteAuthConfig(context.Background(), f.caller, id)
	var linked *domain.Linked
	if !errors.As(err, &linked) || linked.Msg != "Cannot delete auth config "+id.String()+": linked to connections ['inst-1']" {
		t.Fatalf("err = %v", err)
	}
	if len(f.auth.rows) != 1 {
		t.Fatal("a linked config was deleted")
	}
}

func TestDeleteConnectionOwnedRemovesSecrets(t *testing.T) {
	f := newFixture(t)
	connID := uuid.New()
	f.conns.rows[connID] = domain.Connection{ID: connID.String(), CustomHeaders: []domain.Header{{Name: "X-Key", Secret: true}, {Name: "Accept"}},
		URLVariables: []string{"tenant"}}
	authID := uuid.New()
	key := "mcp_auth_cred:" + authID.String()
	f.auth.rows[authID] = domain.AuthConfig{ID: authID.String(), SecretKey: &key, OpenAPIConnID: strPtr(connID.String())}
	f.secrets.values["openapi:"+connID.String()+":header:X-Key"] = "v"
	f.secrets.values["openapi:"+connID.String()+":url_var:tenant"] = "t"
	f.secrets.values[key] = "{}"
	if err := f.svc.DeleteConnection(context.Background(), f.caller, connID); err != nil {
		t.Fatal(err)
	}
	if len(f.secrets.values) != 0 || len(f.conns.rows) != 0 {
		t.Fatalf("secrets=%v rows=%d", f.secrets.values, len(f.conns.rows))
	}
	if len(f.catalog.cleared) != 1 {
		t.Fatalf("cleared = %v", f.catalog.cleared)
	}
}

func TestDeletePlatformConnectionTouchesNoSecret(t *testing.T) {
	f := newFixture(t)
	connID := uuid.New()
	platform := "platform"
	f.conns.rows[connID] = domain.Connection{ID: connID.String(), ManagedBy: &platform, CustomHeaders: []domain.Header{{Name: "X", Secret: true}}}
	f.secrets.values["openapi:"+connID.String()+":header:X"] = "platform-credential"
	err := f.svc.DeleteConnection(context.Background(), f.caller, connID)
	var nf *domain.NotFound
	if !errors.As(err, &nf) || nf.Msg != "Connection not found" {
		t.Fatalf("err = %v", err)
	}
	if f.secrets.values["openapi:"+connID.String()+":header:X"] != "platform-credential" || len(f.conns.rows) != 1 {
		t.Fatal("a platform connection's credential or row was touched")
	}
}

func TestGetConnectionSharing(t *testing.T) {
	f := newFixture(t)
	connID := uuid.New()
	f.conns.rows[connID] = domain.Connection{ID: connID.String(), CreatedBy: "owner"}
	f.svc = New(Deps{DB: memDB{}, Connections: f.conns, Auth: f.auth, Secrets: f.secrets,
		Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return f.catalog },
		Graph:   memGraph{personal: map[string]bool{connID.String(): true}}})
	v, err := f.svc.GetConnection(context.Background(), f.caller, connID)
	if err != nil {
		t.Fatal(err)
	}
	if !v.Sharing.Personal || !v.Sharing.IsOwner {
		t.Fatalf("sharing = %+v", v.Sharing)
	}
}

func TestCreateLinkNeedsVisibleInstanceAndValidAccess(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	inst := uuid.New()
	days := 7
	_, err := f.svc.CreateLink(ctx, f.caller, inst, "workspace", nil, nil)
	var nf *domain.NotFound
	if !errors.As(err, &nf) {
		t.Fatalf("missing instance: %v", err)
	}
	f.inst.ids[inst] = true
	_, err = f.svc.CreateLink(ctx, f.caller, inst, "world", nil, nil)
	var inv *domain.Invalid
	if !errors.As(err, &inv) {
		t.Fatalf("bad access: %v", err)
	}
	l, err := f.svc.CreateLink(ctx, f.caller, inst, "public", map[string]any{}, &days)
	if err != nil {
		t.Fatal(err)
	}
	if len(l.Token) != 43 || l.ExpiresAt == nil || !l.ExpiresAt.Equal(time.Unix(1_700_000_000, 0).UTC().Add(7*24*time.Hour)) {
		t.Fatalf("link = %+v", l)
	}
}

func TestRevokeMissingLinkIsNotFound(t *testing.T) {
	f := newFixture(t)
	err := f.svc.RevokeLink(context.Background(), f.caller, uuid.New())
	var nf *domain.NotFound
	if !errors.As(err, &nf) || nf.Msg != "OAuth link not found" {
		t.Fatalf("err = %v", err)
	}
}

func strPtr(s string) *string { return &s }
