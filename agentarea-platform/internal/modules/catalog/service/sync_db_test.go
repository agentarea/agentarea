package service

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

func openSyncDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second,
	}, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

// fakeUses holds no foreign row: nothing references an item or a spec.
type fakeUses struct {
	mu    sync.Mutex
	moves []api.ItemMove
}

func (f *fakeUses) MoveItemUses(_ context.Context, _ db.Session, m []api.ItemMove) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.moves = append(f.moves, m...)
	return 0, nil
}

func (*fakeUses) ReferencedItems(context.Context, db.Session, []uuid.UUID) (map[uuid.UUID]bool, error) {
	return map[uuid.UUID]bool{}, nil
}

func (*fakeUses) UsedProviderSpecs(context.Context, db.Session, []uuid.UUID) (map[uuid.UUID]bool, error) {
	return map[uuid.UUID]bool{}, nil
}

func (*fakeUses) UsedModelSpecs(context.Context, db.Session, []uuid.UUID) (map[uuid.UUID]bool, error) {
	return map[uuid.UUID]bool{}, nil
}

func (*fakeUses) DropPlatformSkills(context.Context, db.Session, []uuid.UUID) error { return nil }

// sources serves path -> body with an ETag per body.
type sources struct {
	mu    sync.Mutex
	body  map[string]string
	etag  map[string]string
	reads int
}

func (s *sources) set(path, etag, body string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.body[path], s.etag[path] = body, etag
}

func (s *sources) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	body, ok := s.body[r.URL.Path]
	if !ok {
		http.NotFound(w, r)
		return
	}
	if e := s.etag[r.URL.Path]; e != "" {
		w.Header().Set("ETag", e)
	}
	if r.Method == http.MethodGet {
		s.reads++
	}
	_, _ = w.Write([]byte(body))
}

func syncService(t *testing.T) (*Service, *sources, *httptest.Server, *fakeUses) {
	t.Helper()
	d := openSyncDB(t)
	src := &sources{body: map[string]string{}, etag: map[string]string{}}
	ts := httptest.NewTLSServer(src)
	t.Cleanup(ts.Close)
	uses := &fakeUses{}
	svc := New(Deps{DB: d, Specs: store.Specs{}, Registries: store.Registries{}, Sync: store.Sync{}, Uses: uses,
		Fetch: fetcherFor(ts), Log: slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError})), PublicHTTPS: func(context.Context, string) bool { return true }})
	return svc, src, ts, uses
}

func platformRegistry(t *testing.T, svc *Service, typ, src string) domain.Registry {
	t.Helper()
	r, err := svc.CreateRegistry(context.Background(), platformWorkspace(), domain.NewRegistry{
		Name: "t-" + uuid.NewString()[:8], RegistryType: typ, SourceType: "url", SourceURL: src,
		Scope: "platform", Mode: "mirror", Trust: "official",
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func registryNow(t *testing.T, svc *Service, id string) domain.Registry {
	t.Helper()
	r, ok, err := svc.PlatformRegistry(context.Background(), platformWorkspace(), id)
	if err != nil || !ok {
		t.Fatalf("registry %s: %v %v", id, ok, err)
	}
	return r
}

func TestSyncStoresTheVersionedEtagAndSkipsAnUnchangedSource(t *testing.T) {
	svc, src, ts, _ := syncService(t)
	ctx := context.Background()
	k := "p" + uuid.NewString()[:8]
	src.set("/providers.json", `"v1"`, `{"providers": [{"provider_key": "`+k+`a", "name": "A", "transport": "openai"},
		{"provider_key": "`+k+`b", "name": "B"}]}`)
	r := platformRegistry(t, svc, domain.TypeLLMProviders, ts.URL+"/providers.json")

	st, err := svc.SyncRegistry(ctx, r.ID, false)
	if err != nil || st.NewSpecs != 2 || st.Total != 2 {
		t.Fatalf("first sync %+v %v", st, err)
	}
	if got := registryNow(t, svc, r.ID); got.SourceEtag == nil || *got.SourceEtag != SyncFormat+`:"v1"` || got.ItemCount != 2 {
		t.Fatalf("stored %+v", got)
	}
	reads := src.reads
	st, err = svc.SyncRegistry(ctx, r.ID, false)
	if err != nil || !st.SourceUnchanged || st.Unchanged != 2 || src.reads != reads {
		t.Fatalf("unchanged sync %+v %v (reads %d -> %d)", st, err, reads, src.reads)
	}
	if st, err = svc.SyncRegistry(ctx, r.ID, true); err != nil || st.SourceUnchanged || src.reads != reads+1 {
		t.Fatalf("forced sync %+v %v", st, err)
	}

	src.set("/providers.json", `"v2"`, `{"providers": [{"provider_key": "`+k+`a", "name": "A2", "transport": "anthropic"}]}`)
	st, err = svc.SyncRegistry(ctx, r.ID, false)
	if err != nil || st.Applied != 1 || st.Deleted != 1 || st.OutOfSource == nil || *st.OutOfSource != 0 {
		t.Fatalf("changed sync %+v %v", st, err)
	}
	spec, ok, err := svc.Specs().ProviderSpecByKey(ctx, platformWorkspace(), k+"a")
	if err != nil || !ok || spec.Name != "A2" {
		t.Fatalf("applied provider %+v %v %v", spec, ok, err)
	}
	if _, ok, _ := svc.Specs().ProviderSpecByKey(ctx, platformWorkspace(), k+"b"); ok {
		t.Fatal("the unused dropped provider stayed")
	}
}

func TestASourceTypeTakesEveryContentChangeAndItsVersionStaysOutOfTheSpec(t *testing.T) {
	svc, src, ts, _ := syncService(t)
	ctx := context.Background()
	slug := "tg" + uuid.NewString()[:6]
	index := func(version, summary string) string {
		return `{"source_types": [{"slug": "` + slug + `", "name": "TG", "delivery": "webhook"` + version +
			`, "event": {"kind": "telegram.update"` + summary + `}}]}`
	}
	stored := func() map[string]any {
		t.Helper()
		rows, err := SourceTypes{DB: svc.d.DB}.SourceTypeRowsBySlug(ctx, slug)
		if err != nil || len(rows) != 1 {
			t.Fatalf("rows %+v %v", rows, err)
		}
		return plainSpec(rows[0].Spec)
	}
	src.set("/st.json", `"a"`, index("", ""))
	r := platformRegistry(t, svc, domain.TypeSourceTypes, ts.URL+"/st.json")
	if _, err := svc.SyncRegistry(ctx, r.ID, false); err != nil {
		t.Fatal(err)
	}

	src.set("/st.json", `"b"`, index("", `, "summary": ["{body:message.text}"]`))
	if _, err := svc.SyncRegistry(ctx, r.ID, false); err != nil {
		t.Fatal(err)
	}
	if got := fmt.Sprint(mapping(stored()["event"])["summary"]); got != "[{body:message.text}]" {
		t.Fatalf("same-version change not stored: %s", got)
	}

	src.set("/st.json", `"c"`, index(`, "version": "1.1.0"`, `, "summary": ["{body:message.caption}"]`))
	if _, err := svc.SyncRegistry(ctx, r.ID, false); err != nil {
		t.Fatal(err)
	}
	spec := stored()
	if _, ok := spec["version"]; ok {
		t.Fatalf("version stored in the spec: %v", spec)
	}
	if got := fmt.Sprint(mapping(spec["event"])["summary"]); got != "[{body:message.caption}]" {
		t.Fatalf("bumped change not stored: %s", got)
	}
}

func TestASkippedItemLeavesTheSourceUnreadAndRecordsWhy(t *testing.T) {
	svc, src, ts, _ := syncService(t)
	ctx := context.Background()
	src.set("/models.json", `"m1"`, `{"models": [{"provider_key": "nobody-`+uuid.NewString()[:8]+`", "model_name": "m"}]}`)
	r := platformRegistry(t, svc, domain.TypeLLMModels, ts.URL+"/models.json")
	st, err := svc.SyncRegistry(ctx, r.ID, false)
	if err != nil || st.Skipped != 1 || !strings.Contains(st.SkippedItems[0].Reason, "sync llm_providers registry first") {
		t.Fatalf("%+v %v", st, err)
	}
	if got := registryNow(t, svc, r.ID); got.SourceEtag != nil {
		t.Fatalf("etag stored after a skip: %s", *got.SourceEtag)
	}

	src.set("/models.json", `"m2"`, `not: [valid`)
	_, err = svc.SyncRegistry(ctx, r.ID, false)
	if err == nil || SyncErrorMessage(err) != "the source is not a valid JSON or YAML index" {
		t.Fatalf("broken source: %v", err)
	}
	if got := registryNow(t, svc, r.ID); got.LastSyncError == nil || *got.LastSyncError != "the source is not a valid JSON or YAML index" {
		t.Fatalf("recorded %v", got.LastSyncError)
	}
}

func TestADroppedMCPServerMovesToTheSiblingThatStillPublishesIt(t *testing.T) {
	svc, src, ts, uses := syncService(t)
	ctx := context.Background()
	id := "io.test/" + uuid.NewString()[:8]
	index := `{"servers": [{"registry_id": "` + id + `", "connection_type": "url", "name": "Srv",
		"json_spec": {"url": "https://mcp.example/x", "transport": "streamable-http"}}]}`
	src.set("/a.json", `"a1"`, index)
	src.set("/b.json", `"b1"`, index)
	a := platformRegistry(t, svc, domain.TypeMCPServers, ts.URL+"/a.json")
	b := platformRegistry(t, svc, domain.TypeMCPServers, ts.URL+"/b.json")
	for _, r := range []domain.Registry{a, b} {
		if st, err := svc.SyncRegistry(ctx, r.ID, false); err != nil || st.NewSpecs != 1 {
			t.Fatalf("sync %s: %+v %v", r.Name, st, err)
		}
	}
	src.set("/a.json", `"a2"`, `{"servers": [{"registry_id": "other-`+uuid.NewString()[:8]+`", "connection_type": "url",
		"json_spec": {"url": "https://mcp.example/y"}}]}`)
	st, err := svc.SyncRegistry(ctx, a.ID, false)
	if err != nil || st.NewSpecs != 1 || st.Deleted != 1 {
		t.Fatalf("drop %+v %v", st, err)
	}
	if len(uses.moves) != 1 || uses.moves[0].OldCopy == nil || uses.moves[0].NewCopy == nil || *uses.moves[0].OldCopy == *uses.moves[0].NewCopy {
		t.Fatalf("moves %+v", uses.moves)
	}
}

func TestReconcileCreatesSyncsAndRetires(t *testing.T) {
	svc, src, ts, _ := syncService(t)
	ctx := context.Background()
	name := "rc-" + uuid.NewString()[:8]
	src.set("/agents.json", "", `{"agents": [{"name": "helper"}]}`)
	res, err := svc.Reconcile(ctx, api.ReconcileOptions{Manifest: []map[string]any{
		{"name": name + "-gone", "active": false},
		{"name": name, "source_url": ts.URL + "/agents.json", "recommendation_priority": 5},
	}})
	if err != nil || len(res.Succeeded) != 2 || len(res.Failed) != 0 {
		t.Fatalf("%+v %v", res, err)
	}
	var r domain.Registry
	if err := svc.read(ctx, platformWorkspace(), func(sess db.Session) (err error) {
		r, _, err = store.Sync{}.PlatformByName(ctx, sess, name)
		return err
	}); err != nil || r.RegistryType != domain.TypeAgents || r.ItemCount != 1 || r.RecommendationPriority != 5 {
		t.Fatalf("created %+v %v", r, err)
	}
	res, err = svc.Reconcile(ctx, api.ReconcileOptions{Manifest: []map[string]any{{"name": name, "active": false}}})
	if err != nil || len(res.Succeeded) != 1 {
		t.Fatalf("retire %+v %v", res, err)
	}
	if got := registryNow(t, svc, r.ID); got.IsActive {
		t.Fatal("retired registry still active")
	}
	if n, err := svc.countItems(ctx, r.ID); err != nil || n != 0 {
		t.Fatalf("items left %d %v", n, err)
	}
}

func (s *Service) countItems(ctx context.Context, id string) (int, error) {
	var n int
	err := s.read(ctx, platformWorkspace(), func(sess db.Session) (err error) {
		n, err = s.d.Sync.CountItems(ctx, sess, id)
		return err
	})
	return n, err
}

type noSecrets struct{ cleared []string }

func (*noSecrets) GetForUse(context.Context, string) (ksecrets.Secret, error) {
	return ksecrets.Secret{}, nil
}
func (*noSecrets) AddReference(context.Context, string, string, string, string) error { return nil }
func (n *noSecrets) ClearReferences(_ context.Context, _, consumerID string) error {
	n.cleared = append(n.cleared, consumerID)
	return nil
}

func TestAWorkspaceRegistrySyncsOverHTTPSAndIsDeletedWhenNothingStays(t *testing.T) {
	svc, src, ts, _ := syncService(t)
	ctx := context.Background()
	sec := &noSecrets{}
	svc.d.Secrets = func(scope.Workspace, ksecrets.Actor) SecretUse { return sec }
	wsID := uuid.NewString()
	ws, _ := scope.NewWorkspace(wsID, "ws-"+wsID[:8])
	src.set("/mine.json", `"w1"`, `{"agents": [{"name": "a"}, {"name": "b"}]}`)
	var r domain.Registry
	if err := svc.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) (err error) {
		r, err = store.Registries{}.Create(ctx, sess, domain.NewRegistry{Name: "mine", RegistryType: domain.TypeAgents,
			SourceType: "url", SourceURL: ts.URL + "/mine.json", RecommendationPriority: 100, Scope: "workspace",
			WorkspaceID: &wsID, Mode: "upstream", Trust: "private"}, time.Now())
		return err
	}); err != nil {
		t.Fatal(err)
	}
	if st, err := svc.SyncRegistry(ctx, r.ID, false); err != nil || st.NewSpecs != 2 {
		t.Fatalf("%+v %v", st, err)
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	status, kept, err := svc.RemoveWorkspaceRegistry(ctx, c, r.ID)
	if err != nil || status != "deleted" || kept != 0 || len(sec.cleared) != 1 {
		t.Fatalf("%s %d %v %v", status, kept, err, sec.cleared)
	}
	if _, ok, _ := svc.WorkspaceRegistry(ctx, ws, r.ID); ok {
		t.Fatal("registry still there")
	}
}
