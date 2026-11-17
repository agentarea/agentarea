package store

import (
	"context"
	"encoding/json"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

func ids(items []api.CatalogItem) []string {
	out := make([]string, len(items))
	for i, it := range items {
		out[i] = it.ID
	}
	return out
}

func TestInstallsReadActiveVisibleItemsOnly(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	now := time.Now()
	st, in := Registries{}, Installs{}
	own := s.Workspace().ID()
	registry := func(typ, name string) domain.Registry {
		r, err := st.Create(ctx, s, domain.NewRegistry{Name: name + uuid.NewString()[:6], RegistryType: typ, SourceType: "github",
			SourceURL: "o/r", RecommendationPriority: 100, Scope: "workspace", WorkspaceID: &own, Mode: "mirror", Trust: "private"}, now)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	item := func(r domain.Registry, name, tags string) domain.Item {
		now = now.Add(time.Second)
		it, err := st.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: name, Name: name, Spec: json.RawMessage(`{"k":1}`),
			Tags: json.RawMessage(tags)}, 1, domain.Facets{SortKey: name}, now)
		if err != nil {
			t.Fatal(err)
		}
		return it
	}
	agents, retired, skills := registry(domain.TypeAgents, "a"), registry(domain.TypeAgents, "r"), registry(domain.TypeSkills, "s")
	preset, plain := item(agents, "Preset", `["preset"]`), item(agents, "Plain", `[]`)
	gone := item(retired, "Gone", `["preset"]`)
	if _, _, err := st.Update(ctx, s, retired.ID, domain.RegistryPatch{IsActive: domain.Field[*bool]{Set: true, Value: ptr(false)}}, false, now); err != nil {
		t.Fatal(err)
	}
	older := item(skills, "web-search--abc", `[]`)
	newer := item(skills, "web-search", `[]`)

	presets, err := in.AgentPresets(ctx, s)
	if err != nil || !slices.Contains(ids(presets), preset.ID) || slices.Contains(ids(presets), plain.ID) || slices.Contains(ids(presets), gone.ID) {
		t.Fatalf("presets %v: %v", ids(presets), err)
	}
	if foreign, _ := in.AgentPresets(ctx, other); slices.Contains(ids(foreign), preset.ID) {
		t.Fatal("another workspace reads this workspace's presets")
	}
	if _, ok, _ := in.Item(ctx, s, domain.TypeAgents, gone.ID); ok {
		t.Fatal("an item of a retired registry installs")
	}
	if _, ok, _ := in.Item(ctx, s, domain.TypeSkills, plain.ID); ok {
		t.Fatal("an agent item read as a skill")
	}
	if it, ok, err := in.Item(ctx, s, domain.TypeAgents, plain.ID); err != nil || !ok || it.RegistryTrust != "private" || it.RegistryWorkspaceID == nil {
		t.Fatalf("item %+v %v", it, err)
	}
	if it, ok, err := in.SkillByKey(ctx, s, "web-search"); err != nil || !ok || it.ID != newer.ID {
		t.Fatalf("by key %+v %v (older %s)", it, err, older.ID)
	}

	entity := uuid.New()
	v1, v2 := "1", "2"
	for _, v := range []*string{&v1, &v2} {
		if err := in.MarkInstalled(ctx, s, uuid.MustParse(plain.ID), entity, v); err != nil {
			t.Fatal(err)
		}
	}
	var n int
	var version string
	if err := pool.QueryRow(ctx, `SELECT count(*), max(installed_version) FROM registry_item_installs WHERE registry_item_id = $1 AND workspace_id = $2`,
		plain.ID, own).Scan(&n, &version); err != nil || n != 1 || version != "2" {
		t.Fatalf("installs %d %s %v", n, version, err)
	}

	prov, err := in.SkillProvenance(ctx, s, []uuid.UUID{uuid.MustParse(newer.ID), uuid.New()})
	if err != nil || len(prov) != 1 || prov[newer.ID].RegistryID != skills.ID {
		t.Fatalf("provenance %+v %v", prov, err)
	}
}
