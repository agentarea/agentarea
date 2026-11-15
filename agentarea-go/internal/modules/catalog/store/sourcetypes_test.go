package store

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

func TestSourceTypeRowsByPriorityAndActive(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := session(t, pool)
	now := time.Now()
	st := Registries{}
	slug := "st-" + uuid.NewString()[:8]
	mk := func(prio int, active bool, spec string) {
		r, err := st.Create(ctx, s, domain.NewRegistry{
			Name: "src-" + uuid.NewString()[:8], RegistryType: "source_types", SourceType: "managed",
			SourceURL: "managed://x", RecommendationPriority: prio, Scope: "platform", Mode: "mirror", Trust: "official",
		}, now)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := st.CreateItem(ctx, s, r.ID, domain.NewItem{ExternalID: slug, Name: slug, Spec: json.RawMessage(spec),
			Tags: json.RawMessage(`[]`)}, 0, domain.Facets{SortKey: slug}, now); err != nil {
			t.Fatal(err)
		}
		if !active {
			if _, _, err := st.Update(ctx, s, r.ID, domain.RegistryPatch{IsActive: domain.Field[*bool]{Set: true, Value: ptr(false)}}, false, now); err != nil {
				t.Fatal(err)
			}
		}
	}
	mk(50, true, `{"n":"low"}`)
	mk(10, true, `{"n":"high"}`)
	mk(1, false, `{"n":"inactive"}`)
	rows, err := SourceTypes{}.RowsBySlug(ctx, pool, slug)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || string(rows[0].Spec) != `{"n": "high"}` || rows[0].Slug != slug {
		t.Fatalf("rows = %+v", rows)
	}
	all, err := SourceTypes{}.Rows(ctx, pool)
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, r := range all {
		if r.Slug == slug {
			n++
		}
	}
	if n != 2 {
		t.Fatalf("all rows of slug = %d", n)
	}
}
