package store

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

func TestMCPSpecsLookupsAndWrites(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	pws, err := scope.NewWorkspace(PlatformWorkspaceID, PlatformWorkspaceID)
	if err != nil {
		t.Fatal(err)
	}
	platform := db.NewSession(pws, pool)
	now := time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC)
	regs, st := Registries{}, MCPSpecs{}

	item := func(active bool) string {
		r, err := regs.Create(ctx, s, domain.NewRegistry{
			Name: "mcp-" + uuid.NewString()[:8], RegistryType: "mcp_servers", SourceType: "managed",
			SourceURL: "managed://x", RecommendationPriority: 10, Scope: "platform", Mode: "mirror", Trust: "official",
		}, now)
		if err != nil {
			t.Fatal(err)
		}
		it, err := regs.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: uuid.NewString(), Name: "Git Hub",
			Spec: json.RawMessage(`{"connection_type":"url","url":"https://x/mcp","n":1.50}`), Tags: json.RawMessage(`["a"]`)},
			0, domain.Facets{SortKey: "g"}, now)
		if err != nil {
			t.Fatal(err)
		}
		if !active {
			if _, _, err := regs.Update(ctx, s, r.ID, domain.RegistryPatch{IsActive: domain.Field[*bool]{Set: true, Value: ptr(false)}}, false, now); err != nil {
				t.Fatal(err)
			}
		}
		return it.ID
	}
	activeItem, inactiveItem := item(true), item(false)

	insert := func(sess db.Session, name string, itemID *string) api.MCPSpec {
		sp, err := st.Insert(ctx, sess, MCPSpecRow{ID: uuid.New(), Slug: "s-" + uuid.NewString()[:8], Status: "draft",
			CreatedBy: "u1", Now: now, MCPSpecNew: api.MCPSpecNew{Name: name, Description: "d", Version: "1.0.0",
				RegistryItemID: itemID, JSONSpec: map[string]any{"type": "url", "n": json.Number("2.50")}}})
		if err != nil {
			t.Fatal(err)
		}
		return sp
	}
	mirror := insert(platform, "mirror", &activeItem)
	deadMirror := insert(platform, "dead", &inactiveItem)
	plain := insert(platform, "plain", nil)
	own := insert(s, "own", &activeItem)

	if own.WorkspaceID != s.Workspace().ID() || own.Status != "draft" || own.IsPublic || own.Cmd != nil ||
		len(own.Tags) != 0 || own.Tags == nil || own.JSONSpec["n"] != json.Number("2.50") || !own.CreatedAt.Equal(now) {
		t.Fatalf("own = %+v", own)
	}
	if _, ok, err := st.Workspace(ctx, other, uuid.MustParse(own.ID)); err != nil || ok {
		t.Fatalf("other workspace reads own: ok=%v err=%v", ok, err)
	}
	if got, ok, err := st.Workspace(ctx, s, uuid.MustParse(own.ID)); err != nil || !ok || *got.RegistryItemID != activeItem {
		t.Fatalf("own read: %+v %v %v", got, ok, err)
	}
	if _, ok, _ := st.CatalogMirror(ctx, s, uuid.MustParse(mirror.ID)); !ok {
		t.Fatal("active mirror not found")
	}
	for _, id := range []string{deadMirror.ID, plain.ID, own.ID} {
		if _, ok, _ := st.CatalogMirror(ctx, s, uuid.MustParse(id)); ok {
			t.Fatalf("%s read as a mirror", id)
		}
	}
	if _, ok, _ := st.Platform(ctx, s, uuid.MustParse(plain.ID)); !ok {
		t.Fatal("platform row not found")
	}
	if _, ok, _ := st.Platform(ctx, s, uuid.MustParse(own.ID)); ok {
		t.Fatal("workspace row read as platform")
	}
	it, ok, err := st.CatalogItem(ctx, s, uuid.MustParse(activeItem))
	if err != nil || !ok || it.Name != "Git Hub" || it.Spec["n"] != json.Number("1.50") || len(it.Tags) != 1 {
		t.Fatalf("item = %+v %v %v", it, ok, err)
	}
	if _, ok, _ := st.CatalogItem(ctx, s, uuid.MustParse(inactiveItem)); ok {
		t.Fatal("inactive registry item found")
	}

	if taken, _ := st.SlugTaken(ctx, s, own.Slug); !taken {
		t.Fatal("own slug free")
	}
	if taken, _ := st.SlugTaken(ctx, other, own.Slug); taken {
		t.Fatal("slug taken across workspaces")
	}
	if ok, err := st.SetJSONSpec(ctx, s, uuid.MustParse(plain.ID), map[string]any{"auth_methods": []any{"oauth"}}); err != nil || ok {
		t.Fatalf("platform row written from a workspace: %v %v", ok, err)
	}
	if ok, err := st.SetJSONSpec(ctx, s, uuid.MustParse(own.ID), map[string]any{"auth_methods": []any{"oauth"}}); err != nil || !ok {
		t.Fatalf("own json_spec not written: %v %v", ok, err)
	}
	got, _, _ := st.Workspace(ctx, s, uuid.MustParse(own.ID))
	if m, _ := got.JSONSpec["auth_methods"].([]any); len(m) != 1 || m[0] != "oauth" {
		t.Fatalf("json_spec = %v", got.JSONSpec)
	}
}
