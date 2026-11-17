package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

func TestIntegerColumnsRefuseWhatAnInt32CannotHold(t *testing.T) {
	s := newService(&fakeRegistries{}, true)
	_, err := s.CreateRegistry(context.Background(), ws(t), domain.NewRegistry{RegistryType: "skills", SourceType: "managed",
		Scope: "platform", Mode: "mirror", Trust: "official"}, ptr(1<<31))
	if got := valueMsg(t, err); got != "recommendation_priority must be at most 2147483647, got 2147483648" {
		t.Errorf("priority: %q", got)
	}

	v, _ := DecodeJSON([]byte(`{"agents": [{"name": "a"}, {"name": "b", "recommendation_rank": 4294967296}]}`))
	items, err := ParseSource(domain.TypeAgents, v)
	if err != nil {
		t.Fatal(err)
	}
	if *items[1].Rank != 1 {
		t.Errorf("an out-of-range rank was kept: %d", *items[1].Rank)
	}

	spec := map[string]any{"model_name": "m", "kind": "image", "max_output_tokens": json.Number("4294967296")}
	if _, err := modelRow(domain.Item{}, spec, [16]byte{}); err == nil {
		t.Error("synced model: an out-of-range max_output_tokens was accepted")
	}

	_, err = ProjectCatalogModel(store.CatalogModel{Name: "m", Spec: []byte(`{"kind": "image", "max_output_tokens": 4294967296}`)})
	if !errors.Is(err, ErrProjection) {
		t.Errorf("catalog model: %v", err)
	}
}
