package service

import (
	"errors"
	"testing"

	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func TestToolCostFollowsTheConnectorsPayersAndTheMembersOwnCost(t *testing.T) {
	rate := map[string]any{"source": "rate", "rate": map[string]any{"amount": "0.1", "currency": "USD"}}
	settled := map[string]any{"source": "settled", "settled": map[string]any{"fetch": map[string]any{
		"url": "https://vendor.example/usage", "cost": "$.cost", "currency": "USD"}}}
	refused := func(c *runsapi.ToolCost, err error) string {
		var bad *runsapi.CostDeclarationError
		if !errors.As(err, &bad) {
			t.Fatalf("not refused: %+v %v", c, err)
		}
		return bad.Msg
	}

	c, err := toolCost("acme", false, nil, nil, nil, false)
	if err != nil || c.Payer != "workspace" || c.Declaration["source"] != "unknown" {
		t.Fatalf("no declaration %+v %v", c, err)
	}
	if msg := refused(toolCost("acme", true, nil, rate, nil, true)); msg != "acme does not allow calls paid by the platform" {
		t.Fatal(msg)
	}
	c, err = toolCost("acme", true, []any{"platform"}, rate, nil, true)
	if err != nil || c.Payer != "platform" || c.Connector != "acme" || c.Declaration["source"] != "rate" {
		t.Fatalf("platform %+v %v", c, err)
	}
	if msg := refused(toolCost("connection:x", false, nil, settled, nil, false)); msg != "only a catalog entry may declare a settled cost: its URL receives the connection's credential" {
		t.Fatal(msg)
	}
	own := map[string]any{"source": "free"}
	if c, err = toolCost("acme", false, nil, rate, own, true); err != nil || c.Declaration["source"] != "free" {
		t.Fatalf("own cost %+v %v", c, err)
	}
	if msg := refused(toolCost("acme", true, []any{"platform"}, rate, own, true)); msg != "the cost of a connection the platform pays for is not set on it" {
		t.Fatal(msg)
	}
	if msg := refused(toolCost("acme", false, nil, rate, settled, true)); msg != "a connection's own cost is a rate, a reported field or free, not settled" {
		t.Fatal(msg)
	}
}
