package store

import (
	"context"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
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

func workspace(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	slug := "ws-" + id[:8]
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, slug); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(id, slug)
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func providerSpec(t *testing.T, pool *pgxpool.Pool) string {
	t.Helper()
	id := uuid.NewString()
	if _, err := pool.Exec(context.Background(), `INSERT INTO provider_specs (id, provider_key, name, provider_type, is_builtin, workspace_id, created_by)
		VALUES ($1, $2, 'P', 'openai', true, 'platform', 'system')`, id, "p-"+id[:8]); err != nil {
		t.Fatal(err)
	}
	return id
}

func modelSpec(t *testing.T, pool *pgxpool.Pool, provider, kind string) string {
	t.Helper()
	id := uuid.NewString()
	if _, err := pool.Exec(context.Background(), `INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, is_active, workspace_id, created_by, kind, context_window)
		VALUES ($1, $2, $3, 'M', true, 'platform', 'system', $4, 1000)`, id, provider, "m-"+id[:8], kind); err != nil {
		t.Fatal(err)
	}
	return id
}

func ptr(s string) *string { return &s }

// own drops what other tests left in the shared platform workspace.
func own(s db.Session, in []domain.Instance) []domain.Instance {
	return slices.DeleteFunc(in, func(x domain.Instance) bool { return x.WorkspaceID != s.Workspace().ID() })
}

func newConfig(spec string) domain.Config {
	return domain.Config{ID: uuid.NewString(), ProviderSpecID: spec, Name: "cfg", APIKey: ptr("provider_config_x"),
		EndpointURL: ptr("https://e.example"), IsActive: true, CreatedBy: "u1"}
}

func TestConfigsAreWorkspaceScopedAndPlatformWidened(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	spec := providerSpec(t, pool)
	var st Store
	now := time.Date(2026, 1, 2, 3, 4, 5, 600000000, time.UTC)

	c := newConfig(spec)
	if err := st.InsertConfig(ctx, s, c, now); err != nil {
		t.Fatal(err)
	}
	got, ok, err := st.Config(ctx, s, uuid.MustParse(c.ID))
	if err != nil || !ok || got.Name != "cfg" || *got.APIKey != "provider_config_x" || got.WorkspaceID != s.Workspace().ID() || !got.CreatedAt.Equal(now) {
		t.Fatalf("own config: %+v %v %v", got, ok, err)
	}
	if _, ok, _ := st.Config(ctx, other, uuid.MustParse(c.ID)); ok {
		t.Fatal("another workspace read the config")
	}
	if owns, _ := st.OwnsConfig(ctx, other, uuid.MustParse(c.ID)); owns {
		t.Fatal("another workspace owns the config")
	}

	platform := uuid.NewString()
	if _, err := pool.Exec(ctx, `INSERT INTO provider_configs (id, provider_spec_id, name, is_active, is_public, workspace_id, created_by, managed_by)
		VALUES ($1, $2, 'plat', true, false, 'platform', 'system', 'platform')`, platform, spec); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := st.Config(ctx, other, uuid.MustParse(platform)); !ok {
		t.Fatal("platform config not visible")
	}
	list, err := st.Configs(ctx, other, ConfigFilter{})
	if err != nil || !slices.ContainsFunc(list, func(c domain.Config) bool { return c.ID == platform }) ||
		slices.ContainsFunc(list, func(x domain.Config) bool { return x.ID == c.ID }) {
		t.Fatalf("other list: %+v %v", list, err)
	}
	inactive := false
	list, _ = st.Configs(ctx, s, ConfigFilter{IsActive: &inactive})
	if len(list) != 0 {
		t.Fatalf("inactive filter: %+v", list)
	}
	specID := uuid.MustParse(spec)
	list, _ = st.Configs(ctx, s, ConfigFilter{ProviderSpecID: &specID})
	if len(list) != 2 {
		t.Fatalf("spec filter: %+v", list)
	}

	c.Name, c.IsActive = "renamed", false
	if ok, err := st.UpdateConfig(ctx, other, c, now); ok || err != nil {
		t.Fatalf("update from another workspace: %v %v", ok, err)
	}
	if ok, err := st.UpdateConfig(ctx, s, c, now.Add(time.Hour)); !ok || err != nil {
		t.Fatalf("update: %v %v", ok, err)
	}
	got, _, _ = st.Config(ctx, s, uuid.MustParse(c.ID))
	if got.Name != "renamed" || got.IsActive || !got.UpdatedAt.Equal(now.Add(time.Hour)) {
		t.Fatalf("updated: %+v", got)
	}
	pf := c
	pf.ID = platform
	if ok, _ := st.UpdateConfig(ctx, s, pf, now); ok {
		t.Fatal("a tenant updated the platform config")
	}
	if ok, _ := st.DeleteConfig(ctx, s, uuid.MustParse(platform)); ok {
		t.Fatal("a tenant deleted the platform config")
	}
	ids, err := st.ProviderSpecIDsWithVisibleConfigs(ctx, other)
	if err != nil || !slices.Contains(ids, specID) {
		t.Fatalf("spec ids: %v %v", ids, err)
	}
	if ok, err := st.DeleteConfig(ctx, s, uuid.MustParse(c.ID)); !ok || err != nil {
		t.Fatalf("delete: %v %v", ok, err)
	}
	if _, ok, _ := st.Config(ctx, s, uuid.MustParse(c.ID)); ok {
		t.Fatal("deleted config still read")
	}
}

func TestInstances(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	spec := providerSpec(t, pool)
	chat, embed := modelSpec(t, pool, spec, "chat"), modelSpec(t, pool, spec, "embedding")
	var st Store
	now := time.Now().UTC().Truncate(time.Microsecond)
	c := newConfig(spec)
	if err := st.InsertConfig(ctx, s, c, now); err != nil {
		t.Fatal(err)
	}
	a := domain.Instance{ID: uuid.NewString(), ProviderConfigID: c.ID, ModelSpecID: chat, Name: "a", IsActive: true, CreatedBy: "u1"}
	b := domain.Instance{ID: uuid.NewString(), ProviderConfigID: c.ID, ModelSpecID: embed, Name: "b", Description: ptr("d"), CreatedBy: "u1"}
	for _, in := range []domain.Instance{a, b} {
		if err := st.InsertInstance(ctx, s, in, now); err != nil {
			t.Fatal(err)
		}
	}
	foreign := domain.Instance{ID: uuid.NewString(), ProviderConfigID: c.ID, ModelSpecID: chat, Name: "f", CreatedBy: "u2"}
	if err := st.InsertInstance(ctx, other, foreign, now); err != nil {
		t.Fatal(err)
	}
	got, ok, err := st.Instance(ctx, s, uuid.MustParse(b.ID))
	if err != nil || !ok || got.Name != "b" || *got.Description != "d" || got.IsActive || len(got.Tags) != 0 {
		t.Fatalf("instance: %+v %v %v", got, ok, err)
	}
	if _, ok, _ := st.Instance(ctx, other, uuid.MustParse(a.ID)); ok {
		t.Fatal("another workspace read the instance")
	}
	list, err := st.Instances(ctx, s, InstanceFilter{})
	list = own(s, list)
	if err != nil || len(list) != 2 {
		t.Fatalf("list: %+v %v", list, err)
	}
	active := true
	list, _ = st.Instances(ctx, s, InstanceFilter{IsActive: &active})
	list = own(s, list)
	if len(list) != 1 || list[0].ID != a.ID {
		t.Fatalf("active: %+v", list)
	}
	list, _ = st.Instances(ctx, s, InstanceFilter{ByIDs: true, IDs: []uuid.UUID{}})
	if len(list) != 0 {
		t.Fatalf("empty ids: %+v", list)
	}
	list, _ = st.Instances(ctx, s, InstanceFilter{ByIDs: true, IDs: []uuid.UUID{uuid.MustParse(b.ID)}})
	if len(list) != 1 || list[0].ID != b.ID {
		t.Fatalf("by ids: %+v", list)
	}
	vis, err := st.VisibleInstanceSpecs(ctx, s)
	if err != nil || len(vis) < 2 || vis[uuid.MustParse(b.ID)] != uuid.MustParse(embed) || vis[uuid.MustParse(a.ID)] != uuid.MustParse(chat) {
		t.Fatalf("visible specs: %v %v", vis, err)
	}
	cfgs, err := st.ConfigsOfInstances(ctx, s, []uuid.UUID{uuid.MustParse(c.ID)})
	if err != nil || cfgs[c.ID].Name != "cfg" {
		t.Fatalf("configs of instances: %v %v", cfgs, err)
	}
	specs, err := st.InstanceSpecIDs(ctx, s, []uuid.UUID{uuid.MustParse(c.ID)})
	if err != nil || !slices.Equal(specs[c.ID], []string{chat, embed}) && !slices.Equal(specs[c.ID], []string{embed, chat}) {
		t.Fatalf("instance spec ids: %v %v", specs, err)
	}
	specs, _ = st.InstanceSpecIDs(ctx, other, []uuid.UUID{uuid.MustParse(c.ID)})
	if !slices.Equal(specs[c.ID], []string{chat}) {
		t.Fatalf("the other workspace's instance spec ids: %v", specs)
	}
	if ok, _ := st.DeleteInstance(ctx, other, uuid.MustParse(a.ID)); ok {
		t.Fatal("another workspace deleted the instance")
	}
	if ok, err := st.DeleteInstance(ctx, s, uuid.MustParse(a.ID)); !ok || err != nil {
		t.Fatalf("delete: %v %v", ok, err)
	}
}

func TestListsAreNewestFirst(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	spec := providerSpec(t, pool)
	chat := modelSpec(t, pool, spec, "chat")
	var st Store
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	var configs, instances []string
	for i := range 5 {
		c := newConfig(spec)
		if err := st.InsertConfig(ctx, s, c, base.Add(time.Duration(i)*time.Minute)); err != nil {
			t.Fatal(err)
		}
		configs = append([]string{c.ID}, configs...)
		in := domain.Instance{ID: uuid.NewString(), ProviderConfigID: c.ID, ModelSpecID: chat, Name: "i", CreatedBy: "u1"}
		if err := st.InsertInstance(ctx, s, in, base.Add(time.Duration(4-i)*time.Minute)); err != nil {
			t.Fatal(err)
		}
		instances = append(instances, in.ID)
	}
	cl, err := st.Configs(ctx, s, ConfigFilter{})
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, c := range cl {
		if c.WorkspaceID == s.Workspace().ID() {
			got = append(got, c.ID)
		}
	}
	if !slices.Equal(got, configs) {
		t.Fatalf("configs: %v, want %v", got, configs)
	}
	il, err := st.Instances(ctx, s, InstanceFilter{})
	if err != nil {
		t.Fatal(err)
	}
	il = own(s, il)
	got = got[:0]
	for _, in := range il {
		got = append(got, in.ID)
	}
	if !slices.Equal(got, instances) {
		t.Fatalf("instances: %v, want %v", got, instances)
	}
}

func TestOnlyThePlatformWorkspaceInstancesWidenReads(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	spec := providerSpec(t, pool)
	chat := modelSpec(t, pool, spec, "chat")
	var st Store
	now := time.Now().UTC().Truncate(time.Microsecond)
	platform := uuid.NewString()
	if _, err := pool.Exec(ctx, `INSERT INTO provider_configs (id, provider_spec_id, name, is_active, is_public, workspace_id, created_by, managed_by)
		VALUES ($1, $2, 'plat', true, false, 'platform', 'system', 'platform')`, platform, spec); err != nil {
		t.Fatal(err)
	}
	offered := uuid.NewString()
	if _, err := pool.Exec(ctx, `INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, is_active, is_public, workspace_id, created_by, tags)
		VALUES ($1, $2, $3, 'offered', true, false, 'platform', 'system', '[]'::jsonb)`, offered, platform, chat); err != nil {
		t.Fatal(err)
	}
	theirs := domain.Instance{ID: uuid.NewString(), ProviderConfigID: platform, ModelSpecID: chat, Name: "theirs", IsActive: true, CreatedBy: "u2"}
	if err := st.InsertInstance(ctx, other, theirs, now); err != nil {
		t.Fatal(err)
	}

	if _, ok, _ := st.Instance(ctx, s, uuid.MustParse(offered)); !ok {
		t.Fatal("the platform's instance is not visible")
	}
	if _, ok, _ := st.Instance(ctx, s, uuid.MustParse(theirs.ID)); ok {
		t.Fatal("another workspace's instance on the platform config is visible")
	}
	list, err := st.Instances(ctx, s, InstanceFilter{})
	if err != nil || slices.ContainsFunc(list, func(in domain.Instance) bool { return in.ID == theirs.ID }) ||
		!slices.ContainsFunc(list, func(in domain.Instance) bool { return in.ID == offered }) {
		t.Fatalf("list: %+v %v", list, err)
	}
	list, _ = st.Instances(ctx, s, InstanceFilter{ByIDs: true, IDs: []uuid.UUID{uuid.MustParse(theirs.ID)}})
	if len(list) != 0 {
		t.Fatalf("by ids: %+v", list)
	}
	vis, _ := st.VisibleInstanceSpecs(ctx, s)
	if _, ok := vis[uuid.MustParse(theirs.ID)]; ok {
		t.Fatal("another workspace's instance in the visible specs")
	}
	if _, ok := vis[uuid.MustParse(offered)]; !ok {
		t.Fatal("the platform's instance missing from the visible specs")
	}
	if _, ok, _ := st.Instance(ctx, other, uuid.MustParse(theirs.ID)); !ok {
		t.Fatal("the owner lost its own instance")
	}
}
