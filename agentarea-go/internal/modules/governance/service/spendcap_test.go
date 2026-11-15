package service

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func TestSpendCapSetUpdateAndClear(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if got, err := f.sv.MonthlyCap(ctx, f.ws); err != nil || got != nil {
		t.Fatalf("no cap: %v %v", got, err)
	}
	amount := money.MustParse("50.00")
	if err := f.sv.SetMonthlyCap(ctx, f.caller, &amount); err != nil {
		t.Fatal(err)
	}
	if got, _ := f.sv.MonthlyCap(ctx, f.ws); got == nil || got.String() != "50.00" {
		t.Fatalf("after create: %v", got)
	}
	f.rules.rows = append(f.rules.rows, wsRule(f.ws, "spend", "cap", obj("amount_usd", "9", "period", "month")))
	f.rules.rows[1].ID = uuid.NewString()
	more := money.MustParse("75")
	if err := f.sv.SetMonthlyCap(ctx, f.caller, &more); err != nil {
		t.Fatal(err)
	}
	if len(f.rules.rows) != 1 {
		t.Fatalf("a duplicate monthly cap survived: %+v", f.rules.rows)
	}
	if got, _ := f.sv.MonthlyCap(ctx, f.ws); got.String() != "75" {
		t.Fatalf("after update: %v", got)
	}
	if err := f.sv.SetMonthlyCap(ctx, f.caller, nil); err != nil || len(f.rules.rows) != 0 {
		t.Fatalf("clear: %v %+v", err, f.rules.rows)
	}
	var actions []string
	for _, e := range f.audit.events {
		actions = append(actions, e.Action)
	}
	want := []string{"governance_policy.create", "governance_policy.update", "governance_policy.delete", "governance_policy.delete"}
	if len(actions) != len(want) {
		t.Fatalf("audit %v", actions)
	}
	for i := range want {
		if actions[i] != want[i] {
			t.Fatalf("audit %v, want %v", actions, want)
		}
	}
}

func TestSpendCapIgnoresNarrowedAndDisabledRules(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	narrowed := wsRule(f.ws, "spend", "cap", obj("amount_usd", "1", "tool", "web"))
	weekly := wsRule(f.ws, "spend", "cap", obj("amount_usd", "2", "period", "week"))
	off := wsRule(f.ws, "spend", "cap", obj("amount_usd", "3"))
	off.Enabled = false
	rub := wsRule(f.ws, "spend", "cap", obj("amount_usd", wirejson.Float(4.5), "currency", "RUB"))
	f.rules.rows = append(f.rules.rows, narrowed, weekly, off, rub)
	got, err := f.sv.MonthlyCap(ctx, f.ws)
	if err != nil || got != nil {
		t.Fatalf("a narrowed cap read as the monthly one: %v %v", got, err)
	}
	cur, err := f.sv.CapCurrencies(ctx, f.ws, "USD")
	if err != nil || len(cur) != 1 || !cur["RUB"] {
		t.Fatalf("currencies %v %v", cur, err)
	}
}
