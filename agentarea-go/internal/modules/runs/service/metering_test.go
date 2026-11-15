package service

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func declared(decl map[string]any, payer string) *connection {
	return &connection{id: "c1", connector: "acme", tool: "search", payer: payer, cost: &api.ToolCost{Payer: payer, Connector: "acme", Declaration: decl}}
}

func TestToolCallIsMeteredByTheRateOnAnArgument(t *testing.T) {
	s := New(Deps{Pricing: eurPricing{}, Log: quiet()})
	conn := declared(map[string]any{
		"source": "rate", "unit": "phrase",
		"rate": map[string]any{"amount": "0.5", "currency": "EUR", "quantity": map[string]any{"arg": "num_phrases", "default": 50}},
	}, "workspace")
	in := ToolCall{TaskID: "t1", ToolCallID: "c1", ToolName: "search", Args: map[string]any{"num_phrases": float64(4)}}
	b, refusal := s.beforeCall(context.Background(), testPrincipal(), in, conn)
	if refusal != "" || !b.converted || b.amount.String() != "2.0" {
		t.Fatalf("before %+v refusal %q", b, refusal)
	}
	u, ok := s.connectionLine(context.Background(), in, conn, ToolOutput{Success: true}, b)
	if !ok || u.amount.String() != "2.0" || u.quantity.String() != "4" || u.unit != "phrase" || u.source != "rate" || !u.estimate {
		t.Fatalf("line %+v", u)
	}
	in.Args = nil
	if b, _ := s.beforeCall(context.Background(), testPrincipal(), in, conn); b.amount.String() != "25.0" {
		t.Fatalf("default quantity: %+v", b)
	}
}

func TestToolCallIsMeteredFromItsResponse(t *testing.T) {
	s := New(Deps{Pricing: eurPricing{}, Log: quiet()})
	in := ToolCall{TaskID: "t1", ToolCallID: "c1", ToolName: "search"}
	counted := declared(map[string]any{
		"source": "rate", "exact": true, "rate": map[string]any{"amount": "0.1", "currency": "EUR", "quantity": map[string]any{"count": "$.items"}},
	}, "workspace")
	b, _ := s.beforeCall(context.Background(), testPrincipal(), in, counted)
	out := ToolOutput{Success: true, MeteredBody: map[string]any{"items": []any{1, 2, 3}}}
	if u, ok := s.connectionLine(context.Background(), in, counted, out, b); !ok || u.amount.String() != "0.3" || u.estimate {
		t.Fatalf("counted line %+v", u)
	}
	reported := declared(map[string]any{"source": "reported", "reported": map[string]any{"meta": "cost", "path": "$.usd", "currency": "EUR"}}, "workspace")
	b, _ = s.beforeCall(context.Background(), testPrincipal(), in, reported)
	out = ToolOutput{Success: true, MeteredMeta: map[string]any{"cost": map[string]any{"usd": 1.25}}}
	if u, ok := s.connectionLine(context.Background(), in, reported, out, b); !ok || u.amount.String() != "1.25" || u.source != "reported" {
		t.Fatalf("reported line %+v", u)
	}
	if _, ok := s.connectionLine(context.Background(), in, reported, ToolOutput{Success: true}, b); ok {
		t.Fatal("a call its declaration cannot meter records no line")
	}
}

func TestPlatformCallHoldsTheRateAndRefusesAnUnknownCost(t *testing.T) {
	bill := &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: dec("3"), Currency: "EUR"}}
	s := New(Deps{Pricing: eurPricing{}, Billing: bill, Log: quiet()})
	in := ToolCall{TaskID: "t1", ToolCallID: "c1", ToolName: "search", Args: map[string]any{"n": "3"}}
	conn := declared(map[string]any{"source": "rate", "rate": map[string]any{"amount": "1", "currency": "EUR", "quantity": map[string]any{"arg": "n"}}}, "platform")
	b, refusal := s.beforeCall(context.Background(), testPrincipal(), in, conn)
	if refusal != "" || b.holdID != "h1" || bill.authed[0].Quantity.String() != "3" || bill.authed[0].VendorCost.String() != "3" {
		t.Fatalf("before %+v refusal %q authed %+v", b, refusal, bill.authed)
	}
	if _, refusal := s.beforeCall(context.Background(), testPrincipal(), in, declared(map[string]any{"source": "unknown"}, "platform")); refusal != "acme#search runs on the platform's key but its connector declares no cost" {
		t.Fatalf("refusal %q", refusal)
	}
	in.Args = nil
	if _, refusal := s.beforeCall(context.Background(), testPrincipal(), in, conn); refusal != "the cost of this call cannot be known: argument n is missing and declares no default" {
		t.Fatalf("refusal %q", refusal)
	}
}

func TestFlatToolCostStillChargesItsPrice(t *testing.T) {
	s := New(Deps{Pricing: eurPricing{}, Log: quiet()})
	conn := &connection{id: "c1", connector: "acme", tool: "search", payer: "workspace", cost: &api.ToolCost{VendorCost: money.MustParse("0.4"), VendorCurrency: "EUR"}}
	in := ToolCall{TaskID: "t1", ToolCallID: "c1", ToolName: "search"}
	b, _ := s.beforeCall(context.Background(), testPrincipal(), in, conn)
	if u, ok := s.connectionLine(context.Background(), in, conn, ToolOutput{Success: true}, b); !ok || u.amount.String() != "0.4" || u.estimate || u.unit != "call" {
		t.Fatalf("line %+v", u)
	}
}

func TestSettledCostKeepsItsSettleParams(t *testing.T) {
	m, err := parseCostModel(map[string]any{
		"source": "settled", "estimate": map[string]any{"amount": "0.05", "currency": "USD"},
		"settled": map[string]any{"fetch": map[string]any{
			"url": "https://api.example.com/runs/{run_id}", "params": map[string]any{"run_id": "$.data.id"},
			"cost": "$.data.usd", "currency": "USD",
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	c, err := meterCost(m, nil, map[string]any{"data": map[string]any{"id": "r9"}}, nil)
	if err != nil || c.settleParams["run_id"] != "r9" || c.vendorCost.String() != "0.05" || c.exact {
		t.Fatalf("cost %+v err %v", c, err)
	}
	if _, err := parseCostModel(map[string]any{"source": "settled", "settled": map[string]any{"fetch": map[string]any{"url": "https://x/{a}", "cost": "$.c", "currency": "USD"}}}); err == nil || costReason(err) != "settled.fetch.url names ['a'] that params do not read" {
		t.Fatalf("err %v", err)
	}
}

func TestARetriedPlatformCallReusesItsHold(t *testing.T) {
	bill := &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: dec("1"), Currency: "EUR"}}
	s := New(Deps{Pricing: eurPricing{}, Billing: bill, Log: quiet()})
	in := ToolCall{TaskID: "t1", ToolCallID: "c1", ToolName: "search", Attempt: 1}
	conn := declared(map[string]any{"source": "rate", "rate": map[string]any{"amount": "1", "currency": "EUR"}}, "platform")
	s.beforeCall(context.Background(), testPrincipal(), in, conn)
	in.Attempt = 2
	s.beforeCall(context.Background(), testPrincipal(), in, conn)
	if len(bill.authed) != 2 || bill.authed[0].IdempotencyKey != bill.authed[1].IdempotencyKey || bill.authed[0].IdempotencyKey != "hold:t1:c1" {
		t.Fatalf("a retry of the call held under a new key: %+v", bill.authed)
	}
}
