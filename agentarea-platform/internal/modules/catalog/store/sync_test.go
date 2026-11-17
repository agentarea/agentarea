package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

func TestUpsertProviderKeepsWhatTheEntryLeavesOut(t *testing.T) {
	ctx := context.Background()
	s := session(t, openPool(t))
	st := Sync{}
	key := "k" + uuid.NewString()[:8]
	base := "https://llm.example/v1"
	id, err := st.UpsertProvider(ctx, s, ProviderRow{Key: key, Name: "K", Type: key, IsBuiltin: true, Contract: ProviderContract{
		BaseURL: &Opt[string]{Value: base}, Transport: &Opt[string]{Value: "anthropic"},
	}}, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	again, err := st.UpsertProvider(ctx, s, ProviderRow{Key: key, Name: "K2", Type: key, IsBuiltin: true,
		Contract: ProviderContract{BaseURL: &Opt[string]{Null: true}}}, time.Now())
	if err != nil || again != id {
		t.Fatalf("%s %s %v", again, id, err)
	}
	p, ok, err := Specs{}.ProviderSpecByKey(ctx, s, key)
	if err != nil || !ok || p.Name != "K2" || p.BaseURL != nil || p.Transport != "anthropic" {
		t.Fatalf("%+v %v", p, err)
	}

	price, _ := money.Parse("0.000001")
	cw := 1000
	m := ModelRow{Provider: id, Name: "m", DisplayName: "M", Kind: "chat", ContextWindow: &cw, InputCost: &price, OutputCost: &price, Active: true}
	mid, err := st.UpsertModel(ctx, s, m, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	m.InputCost, m.DisplayName = nil, "M2"
	if again, err := st.UpsertModel(ctx, s, m, time.Now()); err != nil || again != mid {
		t.Fatalf("%s %v", again, err)
	}
	specs, err := Specs{}.ModelSpecs(ctx, s, []uuid.UUID{mid})
	if err != nil || specs[mid].DisplayName != "M2" || specs[mid].InputCostPerToken == nil {
		t.Fatalf("%+v %v", specs[mid], err)
	}
}
