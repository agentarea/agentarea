package secrets

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
)

const testKey = "uRJt6kJ2k7R0nQmY1m0y9y8YJX4m0p7lq3hE5G2bq1c="

func newWS(t *testing.T) scope.Workspace {
	t.Helper()
	ws, err := scope.NewWorkspace("ws-"+uuid.NewString(), "")
	if err != nil {
		t.Fatal(err)
	}
	return ws
}

func newFactory(t *testing.T, key string) *Factory {
	t.Helper()
	f, err := NewFactory(kernel.Config{Backend: kernel.BackendDatabase, EncryptionKey: key}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return f
}

type fakeGuard struct{ allow bool }

func (g fakeGuard) CanUseSecret(context.Context, string, string) (bool, error) { return g.allow, nil }

type fakeOwners struct {
	grantErr error
	granted  []string
	revoked  []string
}

func (o *fakeOwners) GrantOwner(_ context.Context, id, _, _ string) error {
	if o.grantErr != nil {
		return o.grantErr
	}
	o.granted = append(o.granted, id)
	return nil
}
func (o *fakeOwners) Revoke(_ context.Context, id string) error {
	o.revoked = append(o.revoked, id)
	return nil
}

type fakeAudit struct {
	mu      sync.Mutex
	entries []kernel.AuditEntry
}

func (a *fakeAudit) Record(_ context.Context, _ db.Session, e kernel.AuditEntry) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.entries = append(a.entries, e)
	return nil
}

func manager(t *testing.T, d testDB, f *Factory, ws scope.Workspace) kernel.Manager {
	t.Helper()
	// A manager over a session on a connection that lives for the test.
	s, release, err := d.Read(context.Background(), ws)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(release)
	return f.Manager(s, "tester")
}

// write runs fn with a manager inside a transaction, as a caller does.
func write(t *testing.T, d testDB, f *Factory, ws scope.Workspace, fn func(m kernel.Manager) error) error {
	t.Helper()
	return d.Write(context.Background(), ws, func(_ context.Context, s db.Session) error {
		return fn(f.Manager(s, "tester"))
	})
}

func set(t *testing.T, d testDB, f *Factory, ws scope.Workspace, name, value string) {
	t.Helper()
	if err := write(t, d, f, ws, func(m kernel.Manager) error { return m.Set(context.Background(), name, value) }); err != nil {
		t.Fatal(err)
	}
}

func TestDatabaseManagerStoreSemantics(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	f := newFactory(t, testKey)
	wsA, wsB := newWS(t), newWS(t)
	m := manager(t, d, f, wsA)

	if _, err := m.Get(ctx, "k"); !errors.Is(err, kernel.ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	if err := m.Set(ctx, "k", "one"); err == nil {
		t.Fatal("a write on a read session must be refused")
	}
	set(t, d, f, wsA, "k", "one")
	if v, err := m.Get(ctx, "k"); err != nil || v != "one" {
		t.Fatalf("%q %v", v, err)
	}
	set(t, d, f, wsA, "k", "two")
	if v, _ := m.Get(ctx, "k"); v != "two" {
		t.Errorf("upsert: %q", v)
	}
	if _, err := manager(t, d, f, wsB).Get(ctx, "k"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("workspace B reads workspace A's secret: %v", err)
	}

	var stored string
	if err := d.pool.QueryRow(ctx, `SELECT encrypted_value FROM encrypted_secrets WHERE workspace_id=$1 AND secret_name='k'`, wsA.ID()).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(stored, "two") || !strings.HasPrefix(stored, "gAAAA") {
		t.Errorf("stored value is not a Fernet token: %q", stored)
	}

	if ok, _ := m.Has(ctx, "k"); !ok {
		t.Error("Has false")
	}
	other := newFactory(t, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
	om := manager(t, d, other, wsA)
	if _, err := om.Get(ctx, "k"); !errors.Is(err, kernel.ErrDecrypt) {
		t.Errorf("wrong key: %v", err)
	}
	if ok, err := om.Has(ctx, "k"); err != nil || !ok {
		t.Errorf("Has must not need the plaintext: %v %v", ok, err)
	}

	for i, want := range []bool{true, false} {
		var gone bool
		err := write(t, d, f, wsA, func(m kernel.Manager) (err error) {
			gone, err = m.Delete(ctx, "k")
			return err
		})
		if err != nil || gone != want {
			t.Errorf("delete %d: %v %v", i, gone, err)
		}
	}
}

func TestSetClassifiesNewManagedRowsAndKeepsOwnershipOnRotate(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	f := newFactory(t, testKey)
	ws := newWS(t)
	inst := uuid.NewString()
	name := "mcp_instance_" + inst + "_API_KEY"
	set(t, d, f, ws, name, "v1")
	owner := func() (string, string) {
		var typ, id *string
		if err := d.pool.QueryRow(ctx, `SELECT owner_type, owner_id FROM encrypted_secrets WHERE workspace_id=$1 AND secret_name=$2`, ws.ID(), name).Scan(&typ, &id); err != nil {
			t.Fatal(err)
		}
		if typ == nil || id == nil {
			return "", ""
		}
		return *typ, *id
	}
	if typ, id := owner(); typ != "mcp_instance" || id != inst {
		t.Fatalf("owner %q %q", typ, id)
	}
	if _, err := d.pool.Exec(ctx, `UPDATE encrypted_secrets SET owner_type='agent', owner_id='x' WHERE workspace_id=$1 AND secret_name=$2`, ws.ID(), name); err != nil {
		t.Fatal(err)
	}
	set(t, d, f, ws, name, "v2")
	if typ, id := owner(); typ != "agent" || id != "x" {
		t.Errorf("rotation reverted ownership: %q %q", typ, id)
	}
}

func TestExternalRowIsNotNotFound(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	ws := newWS(t)
	if _, err := d.pool.Exec(ctx, `INSERT INTO encrypted_secrets (id, workspace_id, secret_name, external_ref, created_by)
		VALUES ($1, $2, 'ext', 'infisical://p/prod/workspaces/x/ext', 'u')`, uuid.New(), ws.ID()); err != nil {
		t.Fatal(err)
	}
	m := manager(t, d, newFactory(t, testKey), ws)
	if _, err := m.Get(ctx, "ext"); !errors.Is(err, kernel.ErrExternalValue) {
		t.Errorf("got %v", err)
	}
	if ok, err := m.Has(ctx, "ext"); err != nil || !ok {
		t.Errorf("Has: %v %v", ok, err)
	}
}

// TestDatabaseReadsRowsPythonWrote: ciphertexts DatabaseSecretManager wrote,
// recorded once, read back through encrypted_secrets.
func TestDatabaseReadsRowsPythonWrote(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	raw, err := os.ReadFile("../../../kernel/secrets/testdata/python_fernet.json")
	if err != nil {
		t.Fatal(err)
	}
	var py struct {
		Key    string `json:"key"`
		Tokens []struct {
			Plaintext string `json:"plaintext"`
			Token     string `json:"token"`
		} `json:"tokens"`
	}
	if err := json.Unmarshal(raw, &py); err != nil {
		t.Fatal(err)
	}
	ws := newWS(t)
	m := manager(t, d, newFactory(t, py.Key), ws)
	for _, c := range py.Tokens {
		name := "py-" + uuid.NewString()[:8]
		if _, err := d.pool.Exec(ctx, `INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, created_by) VALUES ($1,$2,$3,$4,'py')`,
			uuid.New(), ws.ID(), name, c.Token); err != nil {
			t.Fatal(err)
		}
		got, err := m.Get(ctx, name)
		if err != nil || got != c.Plaintext {
			t.Errorf("Go read Python's %q as %q (%v)", c.Plaintext, got, err)
		}
	}
}

func userSecrets(t *testing.T, d testDB, f *Factory, ws scope.Workspace) kernel.UserSecrets {
	t.Helper()
	s, release, err := d.Read(context.Background(), ws)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(release)
	return f.UserSecrets(s)
}

// TestUserResolverSkipsManagedRows: a reference resolves a user's row only,
// as mcp-manager's ResolveWorkspaceSecret filters owner_type IS NULL.
func TestUserResolverSkipsManagedRows(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	f := newFactory(t, testKey)
	ws := newWS(t)
	set(t, d, f, ws, "mine", "user value")
	set(t, d, f, ws, "reclassified", "connection credential")
	if _, err := d.pool.Exec(ctx, `UPDATE encrypted_secrets SET owner_type='agent', owner_id=$3 WHERE workspace_id=$1 AND secret_name=$2`,
		ws.ID(), "reclassified", uuid.NewString()); err != nil {
		t.Fatal(err)
	}
	r := kernel.NewUserResolver(userSecrets(t, d, f, ws))
	if v, err := r.Resolve(ctx, "mine"); err != nil || v != "user value" {
		t.Fatalf("%q %v", v, err)
	}
	if v, err := r.Resolve(ctx, "reclassified"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("resolved a managed row: %q %v", v, err)
	}
}

func TestInfisicalUserResolverSkipsManagedRows(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	f, _ := infisicalFactory(t)
	ws := newWS(t)
	inf := f.infisical.ForWorkspace(ws.ID())
	for _, n := range []string{"mine", "reclassified", "no-row"} {
		if err := inf.Set(ctx, n, n+" value"); err != nil {
			t.Fatal(err)
		}
	}
	for n, owner := range map[string]*string{"mine": nil, "reclassified": ptr("agent")} {
		ref, _ := inf.ExternalRef(n)
		if _, err := d.pool.Exec(ctx, `INSERT INTO encrypted_secrets (id, workspace_id, secret_name, external_ref, owner_type, created_by)
			VALUES ($1, $2, $3, $4, $5, 'u')`, uuid.New(), ws.ID(), n, ref, owner); err != nil {
			t.Fatal(err)
		}
	}
	r := kernel.NewUserResolver(userSecrets(t, d, f, ws))
	if v, err := r.Resolve(ctx, "mine"); err != nil || v != "mine value" {
		t.Fatalf("%q %v", v, err)
	}
	for _, n := range []string{"reclassified", "no-row"} {
		if v, err := r.Resolve(ctx, kernel.Ref(n)); !errors.Is(err, kernel.ErrNotFound) {
			t.Errorf("%s: resolved a value outside the user catalog: %q %v", n, v, err)
		}
	}
}

func ptr(s string) *string { return &s }

func infisicalFactory(t *testing.T) (*Factory, *fakeInfisical) {
	t.Helper()
	fake := &fakeInfisical{secrets: map[string]string{}}
	srv := httptest.NewServer(fake.handler(t))
	t.Cleanup(srv.Close)
	f, err := NewFactory(kernel.Config{Backend: kernel.BackendInfisical, Endpoint: srv.URL, ClientID: "cid", ClientSecret: "csec", ProjectID: "proj", Env: "prod"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return f, fake
}

// grantHook runs hook inside the first grant, while the first create's
// transaction is still open.
type grantHook struct {
	mu      sync.Mutex
	hook    func()
	granted []string
}

func (o *grantHook) GrantOwner(_ context.Context, _, _, owner string) error {
	o.mu.Lock()
	h := o.hook
	o.hook = nil
	o.granted = append(o.granted, owner)
	o.mu.Unlock()
	if h != nil {
		h()
	}
	return nil
}

func (o *grantHook) Revoke(context.Context, string) error { return nil }

// waitBlocked returns once a statement on encrypted_secrets waits for a row
// lock, or done closes.
func waitBlocked(t *testing.T, d testDB, done <-chan struct{}) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-done:
			return
		default:
		}
		var n int
		if err := d.pool.QueryRow(context.Background(), `SELECT count(*) FROM pg_stat_activity
			WHERE wait_event_type = 'Lock' AND query ILIKE '%encrypted_secrets%'`).Scan(&n); err != nil {
			t.Error(err)
			return
		}
		if n > 0 {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Error("the second create neither blocked nor finished")
}

// concurrentCreate starts the second create while the first holds its row
// uncommitted: the second must lose with a duplicate, never take the name.
func concurrentCreate(t *testing.T, d testDB, f *Factory, ws scope.Workspace) (owners *grantHook, secondErr error) {
	t.Helper()
	ctx := context.Background()
	owners = &grantHook{}
	audit := &fakeAudit{}
	allow := guardFunc(func() bool { return true })
	first := NewCatalog(d, f, allow, owners, audit, ws, kernel.Actor{UserID: "u1", GraphSubject: "User:u1"})
	second := NewCatalog(d, f, allow, owners, audit, ws, kernel.Actor{UserID: "u2", GraphSubject: "User:u2"})
	done := make(chan struct{})
	owners.hook = func() {
		go func() {
			defer close(done)
			_, secondErr = second.CreateUser(ctx, "shared", "second value", nil)
		}()
		waitBlocked(t, d, done)
	}
	if _, err := first.CreateUser(ctx, "shared", "first value", nil); err != nil {
		t.Fatal(err)
	}
	<-done
	var createdBy string
	var updatedBy *string
	if err := d.pool.QueryRow(ctx, `SELECT created_by, updated_by FROM encrypted_secrets WHERE workspace_id=$1 AND secret_name='shared'`,
		ws.ID()).Scan(&createdBy, &updatedBy); err != nil {
		t.Fatal(err)
	}
	if createdBy != "u1" || updatedBy != nil {
		t.Errorf("the second create rewrote the row: created_by %q updated_by %v", createdBy, updatedBy)
	}
	return owners, secondErr
}

func TestConcurrentCreatesOfOneNameKeepTheFirst(t *testing.T) {
	d := openTestDB(t)
	f := newFactory(t, testKey)
	ws := newWS(t)
	owners, err := concurrentCreate(t, d, f, ws)
	if !errors.Is(err, kernel.ErrDuplicateName) {
		t.Errorf("second create: %v", err)
	}
	if v, err := manager(t, d, f, ws).Get(context.Background(), "shared"); err != nil || v != "first value" {
		t.Errorf("value %q %v", v, err)
	}
	if strings.Join(owners.granted, ",") != "User:u1" {
		t.Errorf("owners granted: %v", owners.granted)
	}
}

func TestConcurrentCreatesOfOneNameKeepTheFirstInfisical(t *testing.T) {
	d := openTestDB(t)
	f, fake := infisicalFactory(t)
	ws := newWS(t)
	owners, err := concurrentCreate(t, d, f, ws)
	if !errors.Is(err, kernel.ErrDuplicateName) {
		t.Errorf("second create: %v", err)
	}
	fake.mu.Lock()
	v := fake.secrets["/workspaces/"+ws.ID()+"/shared"]
	fake.mu.Unlock()
	if v != "first value" {
		t.Errorf("Infisical holds %q", v)
	}
	if strings.Join(owners.granted, ",") != "User:u1" {
		t.Errorf("owners granted: %v", owners.granted)
	}
}

type catalogEnv struct {
	cat    *Catalog
	d      testDB
	ws     scope.Workspace
	owners *fakeOwners
	audit  *fakeAudit
	guard  *fakeGuard
}

func newCatalog(t *testing.T) catalogEnv {
	t.Helper()
	d := openTestDB(t)
	ws := newWS(t)
	e := catalogEnv{d: d, ws: ws, owners: &fakeOwners{}, audit: &fakeAudit{}, guard: &fakeGuard{allow: true}}
	e.cat = NewCatalog(d, newFactory(t, testKey), guardFunc(func() bool { return e.guard.allow }), e.owners, e.audit, ws, kernel.Actor{UserID: "u1", GraphSubject: "User:u1"})
	return e
}

type guardFunc func() bool

func (g guardFunc) CanUseSecret(context.Context, string, string) (bool, error) { return g(), nil }

func TestCatalogLifecycle(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	desc := "my key"

	if _, err := e.cat.CreateUser(ctx, "BAD NAME", "v", nil); !errors.Is(err, kernel.ErrInvalidName) {
		t.Errorf("invalid: %v", err)
	}
	if _, err := e.cat.CreateUser(ctx, "mcp_instance_x", "v", nil); !errors.Is(err, kernel.ErrReservedName) {
		t.Errorf("reserved: %v", err)
	}
	sec, err := e.cat.CreateUser(ctx, "api-key", "v1", &desc)
	if err != nil {
		t.Fatal(err)
	}
	if sec.Description == nil || *sec.Description != desc || sec.OwnerType != nil || sec.CreatedBy != "u1" || sec.ExternalRef != nil {
		t.Errorf("%+v", sec)
	}
	if len(e.owners.granted) != 1 || e.owners.granted[0] != sec.ID {
		t.Errorf("owner grant: %v", e.owners.granted)
	}
	if _, err := e.cat.CreateUser(ctx, "api-key", "v2", nil); !errors.Is(err, kernel.ErrDuplicateName) {
		t.Errorf("duplicate: %v", err)
	}

	f := newFactory(t, testKey)
	if v, _ := manager(t, e.d, f, e.ws).Get(ctx, "api-key"); v != "v1" {
		t.Errorf("stored %q", v)
	}

	rotated, err := e.cat.RotateUser(ctx, sec.ID, "v2")
	if err != nil {
		t.Fatal(err)
	}
	if rotated.UpdatedBy == nil || *rotated.UpdatedBy != "u1" {
		t.Errorf("updated_by: %+v", rotated)
	}
	if v, _ := manager(t, e.d, f, e.ws).Get(ctx, "api-key"); v != "v2" {
		t.Errorf("rotated %q", v)
	}
	newDesc := "renamed"
	if s, err := e.cat.UpdateDescription(ctx, sec.ID, &newDesc); err != nil || *s.Description != newDesc {
		t.Errorf("%+v %v", s, err)
	}

	var actions []string
	for _, a := range e.audit.entries {
		actions = append(actions, a.Action)
		if a.ResourceName != "api-key" {
			t.Errorf("audit names %q", a.ResourceName)
		}
		for _, c := range a.Changes {
			if c.Field == "value" && (c.Before != "***" || c.After != "***") {
				t.Errorf("audit leaks a value: %+v", c)
			}
		}
	}
	if strings.Join(actions, ",") != "secret.create,secret.rotate,secret.update" {
		t.Errorf("audit actions %v", actions)
	}

	// A reference blocks the delete; the foreign key is the guard.
	if err := e.cat.AddReference(ctx, sec.ID, "openapi_connection", "c1", "Authorization"); err != nil {
		t.Fatal(err)
	}
	if err := e.cat.AddReference(ctx, sec.ID, "openapi_connection", "c1", "Authorization"); err != nil {
		t.Fatalf("a repeated reference must be a no-op: %v", err)
	}
	var inUse *kernel.InUseError
	err = e.cat.DeleteUser(ctx, sec.ID)
	if !errors.As(err, &inUse) || len(inUse.Consumers) != 1 || inUse.Consumers[0].Field != "Authorization" {
		t.Fatalf("delete while referenced: %v", err)
	}
	if err := e.cat.ClearReferences(ctx, "openapi_connection", "c1"); err != nil {
		t.Fatal(err)
	}
	if err := e.cat.DeleteUser(ctx, sec.ID); err != nil {
		t.Fatal(err)
	}
	if len(e.owners.revoked) != 1 || e.owners.revoked[0] != sec.ID {
		t.Errorf("revoke: %v", e.owners.revoked)
	}
	if _, err := e.cat.Get(ctx, sec.ID); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("after delete: %v", err)
	}
	if n, _ := e.cat.CountUser(ctx); n != 0 {
		t.Errorf("count %d", n)
	}
}

func TestCatalogRefusesManagedRowsAndOtherWorkspaces(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	f := newFactory(t, testKey)
	inst := uuid.NewString()
	managed := "mcp_instance_" + inst + "_TOKEN"
	set(t, e.d, f, e.ws, managed, "x")
	row, err := e.cat.GetByName(ctx, managed)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := e.cat.RotateUser(ctx, row.ID, "y"); !errors.Is(err, kernel.ErrManaged) {
		t.Errorf("rotate managed: %v", err)
	} else if !strings.Contains(err.Error(), "mcp_instance "+inst) {
		t.Errorf("message: %v", err)
	}
	if err := e.cat.DeleteUser(ctx, row.ID); !errors.Is(err, kernel.ErrManaged) {
		t.Errorf("delete managed: %v", err)
	}
	if _, err := e.cat.GetNamedForUse(ctx, managed); !errors.Is(err, kernel.ErrManaged) {
		t.Errorf("reference managed: %v", err)
	}

	other := NewCatalog(e.d, f, e.guard, e.owners, e.audit, newWS(t), kernel.Actor{UserID: "u2", GraphSubject: "User:u2"})
	if _, err := other.Get(ctx, row.ID); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("another workspace reads the row: %v", err)
	}
	if _, err := other.GetByName(ctx, managed); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("another workspace reads by name: %v", err)
	}
}

func TestCatalogUseRequiresTheGraph(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	sec, err := e.cat.CreateUser(ctx, "use-me", "v", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := e.cat.GetForUse(ctx, sec.ID); err != nil {
		t.Fatal(err)
	}
	e.guard.allow = false
	if _, err := e.cat.GetForUse(ctx, sec.ID); !errors.Is(err, kernel.ErrAccessDenied) {
		t.Errorf("denied: %v", err)
	}
	if _, err := e.cat.GetNamedForUse(ctx, "use-me"); !errors.Is(err, kernel.ErrAccessDenied) {
		t.Errorf("denied by name: %v", err)
	}
}

func TestCatalogGrantFailureLeavesNothing(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	e.owners.grantErr = errors.New("graph down")
	if _, err := e.cat.CreateUser(ctx, "orphan", "v", nil); err == nil {
		t.Fatal("expected the grant failure")
	}
	if _, err := e.cat.GetByName(ctx, "orphan"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("a secret no one may use would block its own name: %v", err)
	}
	if len(e.audit.entries) != 0 {
		t.Errorf("audit rows for a failed create: %v", e.audit.entries)
	}
}

func TestCatalogListVisibleOrderAndSurfacing(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	f := newFactory(t, testKey)
	task := uuid.NewString()
	for _, n := range []string{
		"task-input/" + task + "/pw",
		"a2a_push_token:" + task + ":cfg",
		"provider_config_" + uuid.NewString(),
		"mcp_instance_" + uuid.NewString() + "_A",
	} {
		set(t, e.d, f, e.ws, n, "x")
	}
	for _, n := range []string{"zeta", "alpha"} {
		if _, err := e.cat.CreateUser(ctx, n, "x", nil); err != nil {
			t.Fatal(err)
		}
	}
	visible, err := e.cat.ListVisible(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, s := range visible {
		names = append(names, s.Name)
	}
	if len(names) != 4 || names[0] != "alpha" || names[1] != "zeta" {
		t.Errorf("user secrets must come first, by name: %v", names)
	}
	for _, n := range names {
		if strings.HasPrefix(n, "task-input/") || strings.HasPrefix(n, "a2a_push_token:") {
			t.Errorf("machine-generated secret surfaced: %s", n)
		}
	}
	users, _ := e.cat.ListUser(ctx)
	if len(users) != 2 {
		t.Errorf("ListUser: %d", len(users))
	}
}

func TestStageReferencesRunsInTheCallersTransaction(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	sec, err := e.cat.CreateUser(ctx, "staged", "v", nil)
	if err != nil {
		t.Fatal(err)
	}
	boom := errors.New("consumer row failed")
	err = e.d.Write(ctx, e.ws, func(ctx context.Context, s db.Session) error {
		if err := e.cat.StageReferences(ctx, s, "mcp_instance", "i1", []kernel.Reference{{SecretID: sec.ID, Field: "API_KEY"}}); err != nil {
			return err
		}
		return boom
	})
	if !errors.Is(err, boom) {
		t.Fatal(err)
	}
	if refs, _ := e.cat.Consumers(ctx, sec.ID); len(refs) != 0 {
		t.Errorf("a rolled-back consumer left references: %v", refs)
	}
	err = e.d.Write(ctx, e.ws, func(ctx context.Context, s db.Session) error {
		return e.cat.StageReferences(ctx, s, "mcp_instance", "i1", []kernel.Reference{{SecretID: sec.ID, Field: "API_KEY"}})
	})
	if err != nil {
		t.Fatal(err)
	}
	if refs, _ := e.cat.Consumers(ctx, sec.ID); len(refs) != 1 {
		t.Errorf("references: %v", refs)
	}
}

func TestResolveOwnerNames(t *testing.T) {
	e := newCatalog(t)
	ctx := context.Background()
	s, release, err := e.d.Read(ctx, e.ws)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	got, err := ResolveOwnerNames(ctx, s, []OwnerKey{{"agent", uuid.NewString()}, {"agent", "not-a-uuid"}, {"task", uuid.NewString()}})
	if err != nil || len(got) != 0 {
		t.Errorf("%v %v", got, err)
	}
}
