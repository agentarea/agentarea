package store

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
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
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func session(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	ws, err := scope.NewWorkspace(id, "ws-"+id[:8])
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func ptr[T any](v T) *T { return &v }

func TestRegistryVisibilityAndCopiedFields(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	now := time.Now()
	st := Registries{}
	platform, err := st.Create(ctx, s, domain.NewRegistry{
		Name: "plat-" + uuid.NewString()[:8], RegistryType: domain.TypeSkills, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	own := s.Workspace().ID()
	mine, err := st.Create(ctx, s, domain.NewRegistry{
		Name: "mine", RegistryType: domain.TypeSkills, SourceType: "github", SourceURL: "o/r",
		RecommendationPriority: 100, Scope: "workspace", WorkspaceID: &own, Mode: "mirror", Trust: "private",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	listed, err := st.ListVisible(ctx, other, false, "", "workspace")
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range listed {
		if r.ID == mine.ID {
			t.Fatal("another workspace's registry is listed")
		}
	}
	listed, err = st.ListVisible(ctx, s, false, "", "workspace")
	if err != nil || len(listed) != 1 || listed[0].ID != mine.ID {
		t.Fatalf("own workspace registries = %+v, %v", listed, err)
	}

	it, err := st.CreateItem(ctx, s, platform.ID, domain.NewItem{
		ExternalID: "x", Name: "X", Spec: json.RawMessage(`{"b":1,"a":2}`), Tags: json.RawMessage(`["featured"]`),
	}, 3, domain.Facets{SortKey: "x", Featured: true, Category: "data"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if it.RegistryPriority != 100 || !it.RegistryActive || it.RegistryTrust != "official" || it.RecommendationRank != 3 {
		t.Fatalf("item copies = %+v", it)
	}
	if n, err := st.NextRank(ctx, s, platform.ID); err != nil || n != 4 {
		t.Fatalf("next rank = %d, %v", n, err)
	}
	if err := st.SetItemCount(ctx, s, platform.ID, now); err != nil {
		t.Fatal(err)
	}
	r, _, _ := st.Get(ctx, s, platform.ID)
	if r.ItemCount != 1 {
		t.Fatalf("item_count = %d", r.ItemCount)
	}

	upd, found, err := st.Update(ctx, s, platform.ID, domain.RegistryPatch{
		IsActive:               domain.Field[*bool]{Set: true, Value: ptr(false)},
		RecommendationPriority: domain.Field[*int]{Set: true, Value: ptr(7)},
		Trust:                  domain.Field[*string]{Set: true, Value: ptr("verified")},
	}, false, now.Add(time.Second))
	if err != nil || !found || upd.IsActive || upd.RecommendationPriority != 7 {
		t.Fatalf("update = %+v %v %v", upd, found, err)
	}
	it, _, _ = st.GetItem(ctx, s, it.ID)
	if it.RegistryActive || it.RegistryPriority != 7 || it.RegistryTrust != "verified" {
		t.Fatalf("copied onto item = %+v", it)
	}

	if ok, err := st.Delete(ctx, s, platform.ID); err != nil || !ok {
		t.Fatalf("delete = %v %v", ok, err)
	}
	if _, found, _ := st.GetItem(ctx, s, it.ID); found {
		t.Fatal("item outlived its registry")
	}
}

func TestBrowseFacetsAndSearch(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback(context.Background()) })
	id := uuid.NewString()
	ws, err := scope.NewWorkspace(id, "ws-"+id[:8])
	if err != nil {
		t.Fatal(err)
	}
	s := db.NewTxSession(ws, tx)
	now := time.Now()
	st := Registries{}
	if _, err := tx.Exec(ctx, `DELETE FROM registries WHERE registry_type = 'mcp_servers'`); err != nil {
		t.Fatal(err)
	}
	r, err := st.Create(ctx, s, domain.NewRegistry{
		Name: "mcp-" + uuid.NewString()[:8], RegistryType: domain.TypeMCPServers, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	add := func(ext, sortKey, category, protocol, pricing string, featured bool) {
		t.Helper()
		if _, err := st.CreateItem(ctx, s, r.ID, domain.NewItem{
			ExternalID: ext, Name: ext, Spec: json.RawMessage(`{}`), Tags: json.RawMessage(`[]`),
		}, 0, domain.Facets{SortKey: sortKey, Category: category, Protocol: protocol, Pricing: pricing, Featured: featured}, now); err != nil {
			t.Fatal(err)
		}
	}
	add("a", "alpha", "Other", "mcp", "free", false)
	add("b", "beta", "Data", "api", "paid", true)
	add("c", "gamma", "Data", "mcp", "free", false)

	b, err := st.Browse(ctx, s, domain.BrowseFilter{RegistryType: domain.TypeMCPServers}, false, 10, 0)
	if err != nil {
		t.Fatal(err)
	}
	if b.Total != 3 || b.Items[0].ExternalID != "b" {
		t.Fatalf("recommended page = %d items, first %q", b.Total, b.Items[0].ExternalID)
	}
	if len(b.Categories) != 2 || b.Categories[0].Value != "Data" || b.Categories[1].Value != "Other" {
		t.Fatalf("categories = %+v", b.Categories)
	}
	if len(b.Protocols) != 2 || b.Protocols[0] != (domain.Facet{Value: "mcp", Count: 2}) {
		t.Fatalf("protocols = %+v", b.Protocols)
	}
	if len(b.Pricing) != 2 || b.Pricing[0] != (domain.Facet{Value: "paid", Count: 1}) {
		t.Fatalf("pricings = %+v", b.Pricing)
	}

	b, err = st.Browse(ctx, s, domain.BrowseFilter{RegistryType: domain.TypeMCPServers, Protocol: "mcp"}, true, 10, 0)
	if err != nil {
		t.Fatal(err)
	}
	if b.Total != 2 || b.Items[0].ExternalID != "a" || len(b.Protocols) != 2 {
		t.Fatalf("filtered = %+v", b)
	}

	found, err := st.Search(ctx, s, "%gamm%", "", nil, 10, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(found) != 0 {
		t.Fatalf("search matched the sort key, not the name: %+v", found)
	}
	found, err = st.Search(ctx, s, "%C%", "", nil, 10, 0)
	if err != nil || len(found) == 0 {
		t.Fatalf("search = %+v %v", found, err)
	}
}

func TestSpecs(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	now := time.Now()
	key := "p-" + uuid.NewString()[:8]
	pid := uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO provider_specs (id, provider_key, name, provider_type, requires_api_key, is_builtin, created_at, updated_at, workspace_id, created_by)
		VALUES ($1, $2, 'P', 'openai', true, true, now(), now(), 'platform', 'system')`, pid, key); err != nil {
		t.Fatal(err)
	}
	st := Specs{}
	p, found, err := st.ProviderSpecByKey(ctx, s, key)
	if err != nil || !found || p.ID != pid {
		t.Fatalf("by key = %+v %v %v", p, found, err)
	}
	price, _ := money.Parse("0.000001250000")
	n := NewModelSpec{
		ID: uuid.New(), ProviderSpecID: pid, CreatedBy: "u", ModelName: "m", DisplayName: "M",
		Kind: "chat", ContextWindow: ptr(1000), InputCostPerToken: &price, IsActive: true,
	}
	if err := st.InsertModelSpecIfAbsent(ctx, s, n, now); err != nil {
		t.Fatal(err)
	}
	n.ID = uuid.New()
	if err := st.InsertModelSpecIfAbsent(ctx, s, n, now); err != nil {
		t.Fatal(err)
	}
	m, found, err := st.ModelSpecByProviderAndName(ctx, s, pid, "m")
	if err != nil || !found {
		t.Fatalf("by name = %v %v", found, err)
	}
	if m.InputCostPerToken == nil || m.InputCostPerToken.String() != "0.000001250000" {
		t.Fatalf("price round trip = %v", m.InputCostPerToken)
	}
	if _, found, _ := st.UsableModelSpec(ctx, session(t, pool), m.ID); found {
		t.Fatal("another workspace's model spec is usable")
	}
}

func insertProvider(t *testing.T, pool *pgxpool.Pool, name string) uuid.UUID {
	t.Helper()
	id := uuid.New()
	if _, err := pool.Exec(context.Background(), `INSERT INTO provider_specs (id, provider_key, name, provider_type, requires_api_key, is_builtin, created_at, updated_at, workspace_id, created_by)
		VALUES ($1, $2, $3, 'openai', true, true, now(), now(), 'platform', 'system')`, id, "k-"+id.String()[:8], name); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestOfferedProviderSpecsHidesRetired(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	now := time.Now()
	live, retired := insertProvider(t, pool, "Live"), insertProvider(t, pool, "Retired")
	r, err := Registries{}.Create(ctx, s, domain.NewRegistry{
		Name: "llm-" + uuid.NewString()[:8], RegistryType: domain.TypeLLMProviders, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	it, err := Registries{}.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: "x", Name: "x", Spec: json.RawMessage(`{}`), Tags: json.RawMessage(`[]`)}, 0, domain.Facets{SortKey: "x"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `UPDATE registry_items SET installed_entity_id = $1, in_source = false WHERE id = $2`, retired.String(), it.ID); err != nil {
		t.Fatal(err)
	}
	has := func(ps []api.ProviderSpec, id uuid.UUID) bool {
		for _, p := range ps {
			if p.ID == id {
				return true
			}
		}
		return false
	}
	got, err := Specs{}.OfferedProviderSpecs(ctx, s, nil, nil, nil)
	if err != nil || !has(got, live) || has(got, retired) {
		t.Fatalf("offered = %v, %v", got, err)
	}
	got, err = Specs{}.OfferedProviderSpecs(ctx, s, ptr(true), []uuid.UUID{retired}, nil)
	if err != nil || !has(got, retired) {
		t.Fatalf("configured retired provider not offered: %v", err)
	}
	if got, _ := (Specs{}).OfferedProviderSpecs(ctx, s, ptr(false), nil, nil); has(got, live) {
		t.Fatal("is_builtin=false kept a builtin provider")
	}
}

func sameWall(a, b time.Time) bool {
	const f = "2006-01-02T15:04:05.000000"
	return a.Format(f) == b.UTC().Format(f)
}

func TestOwnModelSpecWrites(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	now := time.Now().Truncate(time.Microsecond)
	pid := insertProvider(t, pool, "P")
	st := Specs{}
	id := uuid.New()
	price, _ := money.Parse("0.5")
	if err := st.CreateModelSpec(ctx, s, id, pid, "u", "m", SpecFields{DisplayName: ptr("M"), ContextWindow: ptr(10), InputCostPerToken: &price}, now); err != nil {
		t.Fatal(err)
	}
	m, found, err := st.OwnModelSpec(ctx, s, id)
	if err != nil || !found || m.Kind != "chat" || !m.IsActive || m.InputCostPerToken.Cmp(price) != 0 {
		t.Fatalf("created = %+v %v %v", m, found, err)
	}
	if _, found, _ := st.OwnModelSpec(ctx, other, id); found {
		t.Fatal("another workspace reads the row")
	}
	keys, err := st.OwnModelKeys(ctx, s)
	if err != nil || !keys[ModelKey{ProviderSpecID: pid, ModelName: "m"}] {
		t.Fatalf("keys = %v %v", keys, err)
	}
	later := now.Add(time.Hour)
	if ok, err := st.UpdateModelSpec(ctx, s, id, SpecFields{DisplayName: ptr("M")}, false, later); err != nil || !ok {
		t.Fatalf("untouched update = %v %v", ok, err)
	}
	if m, _, _ = st.OwnModelSpec(ctx, s, id); !sameWall(m.UpdatedAt, now) {
		t.Fatalf("updated_at moved without a change: %v", m.UpdatedAt)
	}
	if _, err := st.UpdateModelSpec(ctx, s, id, SpecFields{IsActive: ptr(false), Kind: ptr("embedding")}, true, later); err != nil {
		t.Fatal(err)
	}
	if m, _, _ = st.OwnModelSpec(ctx, s, id); m.IsActive || m.Kind != "embedding" || !sameWall(m.UpdatedAt, later) || m.DisplayName != "M" {
		t.Fatalf("updated = %+v", m)
	}
	listed, err := st.OwnModelSpecs(ctx, s, SpecFilter{IsActive: ptr(true)})
	if err != nil || len(listed) != 0 {
		t.Fatalf("is_active filter = %v %v", listed, err)
	}
	if ok, _ := st.DeleteModelSpec(ctx, other, id); ok {
		t.Fatal("another workspace deleted the row")
	}
	if ok, err := st.DeleteModelSpec(ctx, s, id); err != nil || !ok {
		t.Fatalf("delete = %v %v", ok, err)
	}
}

func TestApplyItemWrites(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	now := time.Now()
	st := Registries{}
	r, err := st.Create(ctx, s, domain.NewRegistry{
		Name: "mcp-" + uuid.NewString()[:8], RegistryType: domain.TypeMCPServers, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	for _, n := range []string{"b", "A"} {
		if _, err := st.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: n, Name: n, Spec: json.RawMessage(`{}`), Tags: json.RawMessage(`[]`)}, 0, domain.Facets{SortKey: n}, now); err != nil {
			t.Fatal(err)
		}
	}
	items, err := st.AllItems(ctx, s, r.ID)
	if err != nil || len(items) != 2 || items[0].Name != "A" {
		t.Fatalf("all items = %+v %v", items, err)
	}
	if _, err := pool.Exec(ctx, `UPDATE registry_items SET update_available = true WHERE id = $1`, items[0].ID); err != nil {
		t.Fatal(err)
	}
	if err := st.MarkItemApplied(ctx, s, items[0].ID, "3", now); err != nil {
		t.Fatal(err)
	}
	it, _, _ := st.GetItem(ctx, s, items[0].ID)
	if it.UpdateAvailable || it.InstalledVersion == nil || *it.InstalledVersion != "3" {
		t.Fatalf("applied = %+v", it)
	}

	srv := uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO mcp_servers (id, name, description, version, tags, status, is_public, workspace_id, created_by, slug, cmd)
		VALUES ($1, 's', '', '1', '[]', 'active', false, $2, 'u', $3, '["x"]')`, srv, s.Workspace().ID(), "s-"+srv.String()[:8]); err != nil {
		t.Fatal(err)
	}
	m := MirroredServer{Description: "d", Version: "2", Tags: []byte(`["registry", "url"]`), EnvSchema: []byte(`[]`),
		Cmd: []byte("null"), JSONSpec: []byte("null"), RegistryURL: "https://reg", RemoteURL: ptr("https://mcp")}
	if ok, err := st.UpdateMirroredServer(ctx, session(t, pool), srv.String(), m, now); err != nil || ok {
		t.Fatalf("another workspace's server updated: %v %v", ok, err)
	}
	if ok, err := st.UpdateMirroredServer(ctx, s, srv.String(), m, now); err != nil || !ok {
		t.Fatalf("update = %v %v", ok, err)
	}
	var cmd, spec, tags string
	if err := pool.QueryRow(ctx, `SELECT cmd::text, json_spec::text, tags::text FROM mcp_servers WHERE id = $1`, srv).Scan(&cmd, &spec, &tags); err != nil {
		t.Fatal(err)
	}
	if cmd != "null" || spec != "null" || tags != `["registry", "url"]` {
		t.Fatalf("cmd=%s json_spec=%s tags=%s", cmd, spec, tags)
	}
}

func TestSearchFiltersBeforePagingAndSkipsInactive(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	now := time.Now()
	st := Registries{}
	tag := "t-" + uuid.NewString()[:8]
	r, err := st.Create(ctx, s, domain.NewRegistry{
		Name: "s-" + uuid.NewString()[:8], RegistryType: domain.TypeSkills, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	add := func(name, tags string) domain.Item {
		t.Helper()
		it, err := st.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: name, Name: name, Spec: json.RawMessage(`{}`), Tags: json.RawMessage(tags)},
			0, domain.Facets{SortKey: name}, now)
		if err != nil {
			t.Fatal(err)
		}
		return it
	}
	add(tag+"-a", `["other"]`)
	add(tag+"-b", `["other"]`)
	want := add(tag+"-c", `["`+tag+`"]`)
	got, err := st.Search(ctx, s, "%"+tag+"%", tag, nil, 1, 0)
	if err != nil || len(got) != 1 || got[0].ID != want.ID {
		t.Fatalf("first page of the tag = %+v %v", got, err)
	}
	if _, _, err := st.Update(ctx, s, r.ID, domain.RegistryPatch{IsActive: domain.Field[*bool]{Set: true, Value: ptr(false)}}, false, now); err != nil {
		t.Fatal(err)
	}
	if got, err := st.Search(ctx, s, "%"+tag+"%", "", nil, 10, 0); err != nil || len(got) != 0 {
		t.Fatalf("inactive registry's items found: %+v %v", got, err)
	}
}

func TestTimestampsAreUTC(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	loc := time.FixedZone("UTC+5", 5*3600)
	now := time.Date(2026, 1, 2, 3, 4, 5, 0, loc)
	r, err := Registries{}.Create(ctx, s, domain.NewRegistry{
		Name: "z-" + uuid.NewString()[:8], RegistryType: domain.TypeSkills, SourceType: "managed",
		SourceURL: "managed://catalog", RecommendationPriority: 100, Scope: "platform", Mode: "mirror", Trust: "official",
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	if got := r.CreatedAt.Format(time.DateTime); got != "2026-01-01 22:04:05" {
		t.Fatalf("created_at = %s, want the UTC wall clock", got)
	}
}
