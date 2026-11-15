package service

import (
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func TestQuantizeRoundsHalfEven(t *testing.T) {
	for in, want := range map[string]string{"1.005": "1.00", "1.015": "1.02", "2.5": "2.50", "-0.125": "-0.12", "0": "0.00"} {
		if got := Quantize(money.MustParse(in), 2).String(); got != want {
			t.Fatalf("quantize %s = %s, want %s", in, got, want)
		}
	}
}

func TestPctOfCap(t *testing.T) {
	if PctOfCap(money.MustParse("5"), nil) != nil {
		t.Fatal("no cap gave a percentage")
	}
	zero := money.MustParse("0")
	if PctOfCap(money.MustParse("5"), &zero) != nil {
		t.Fatal("a zero cap gave a percentage")
	}
	capUSD := money.MustParse("30")
	if p := PctOfCap(money.MustParse("10"), &capUSD); p == nil || *p != 33.33 {
		t.Fatalf("10 of 30 = %v", p)
	}
}

func TestProjectMonthEndUsesLastSevenFullDays(t *testing.T) {
	now := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	byDay := map[string]money.Decimal{"2026-11-20": money.MustParse("100")}
	for i := 1; i <= 7; i++ {
		byDay[now.AddDate(0, 0, -i).Format(time.DateOnly)] = money.MustParse("1")
	}
	if got := ProjectMonthEnd(money.MustParse("10"), byDay, now).String(); got != "21.00" {
		t.Fatalf("projection %s, want 10 + 11 days at 1/day", got)
	}
}

func TestTaskCost(t *testing.T) {
	for raw, want := range map[string]string{`"1.50"`: "1.50", `2`: "2", `0.1`: "0.1", `1e-7`: "1E-7"} {
		d, err := TaskCost(raw)
		if err != nil || d == nil || d.String() != want {
			t.Fatalf("%s = %v %v, want %s", raw, d, err, want)
		}
	}
	for _, raw := range []string{"", "null"} {
		if d, err := TaskCost(raw); d != nil || err != nil {
			t.Fatalf("%q = %v %v", raw, d, err)
		}
	}
	for _, raw := range []string{`"abc"`, `true`, `{}`, `[1]`} {
		if _, err := TaskCost(raw); !errors.Is(err, ErrUnreadableCost) {
			t.Fatalf("%s read as an amount", raw)
		}
	}
}

func TestNotCoveredOnlyWithACap(t *testing.T) {
	by := map[string]money.Decimal{"": money.MustParse("1"), "USD": money.MustParse("2"), "RUB": money.MustParse("3"), "EUR": money.MustParse("0")}
	if got := NotCovered(by, nil); len(got) != 0 {
		t.Fatalf("without a cap: %v", got)
	}
	got := NotCovered(by, map[string]bool{"USD": true})
	if len(got) != 1 || got[0].Currency != "RUB" || got[0].Amount.String() != "3" {
		t.Fatalf("got %v", got)
	}
}

func TestDaySeriesFillsMissingDaysWithZero(t *testing.T) {
	start := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	got := DaySeries(start, 3, map[string]money.Decimal{"2026-11-02": money.MustParse("4.5")})
	if len(got) != 3 || got[0].Date != "2026-11-01" || got[0].USD.String() != "0" || got[1].USD.String() != "4.5" {
		t.Fatalf("got %+v", got)
	}
}

func TestCutCountsCharacters(t *testing.T) {
	if got := Cut("приветмир", 6); got != "привет" {
		t.Fatalf("got %q", got)
	}
}

func TestSelectPeopleKeepsTheOwner(t *testing.T) {
	members := make([]string, 0, MaxPeople+5)
	for i := range MaxPeople + 5 {
		members = append(members, fmt.Sprintf("a%03d", i))
	}
	selected, total := SelectPeople(members, "zz-owner")
	if total != MaxPeople+6 || len(selected) != MaxPeople || !slices.Contains(selected, "zz-owner") || !slices.IsSorted(selected) {
		t.Fatalf("total %d selected %d", total, len(selected))
	}
}

func edgeIDs(t Topology) []string {
	out := make([]string, len(t.Edges))
	for i, e := range t.Edges {
		out[i] = e.ID
	}
	return out
}

func TestBuildTopologyEdges(t *testing.T) {
	tools := json.RawMessage(`[{"type":"agent","settings":{"agent_id":"a2"}},{"type":"agent","settings":{"agent_id":"gone"}},
		{"type":"openapi","name":"Billing","settings":{}},{"type":"mcp","server_id":"m1"},{"type":"mcp","tool_server_id":"m1"}]`)
	topo := BuildTopology(GraphInput{
		Agents: []GraphAgent{{ID: "a1", Name: "One", Status: "active", Tools: tools,
			Skills: []GraphRef{{ID: "s-egress", Name: "Web"}, {ID: "s-local", Name: "Notes"}}}, {ID: "a2", Name: "Two", Status: "active"}},
		Skills:    []GraphSkill{{ID: "s-egress", Name: "Web", NetworkScope: ScopeEgress}, {ID: "s-local", Name: "Notes", NetworkScope: "none"}},
		Instances: []GraphInstance{{ID: "m1", Name: "", ToolCount: 2, JSONSpec: map[string]any{"endpoint_url": "https://Mcp.Example.com/x?token=1"}}},
		OpenAPI:   []GraphOpenAPI{{ID: "o1", Name: "Billing", Status: "active"}},
		Triggers:  []GraphTrigger{{ID: "t1", Name: "Daily", AgentID: "a1", Type: "cron", Active: true}},
	})
	want := []string{"a1-s-egress-has_skill", "a1-a2-delegates_to", "a1-o1-uses_openapi", "a1-m1-uses_mcp", "a1-t1-has_trigger"}
	if got := edgeIDs(topo); !slices.Equal(got, want) {
		t.Fatalf("edges %v, want %v", got, want)
	}
	if topo.DeploymentMode != "oss" || len(topo.Governance) != 0 {
		t.Fatalf("oss overlay: %s %v", topo.DeploymentMode, topo.Governance)
	}
	for _, n := range topo.Nodes {
		if n.Type == NodeSkill && n.ID != "s-egress" {
			t.Fatalf("a non-egress skill is a node: %s", n.ID)
		}
		if n.ID == "m1" {
			host, _ := n.Metadata.Get("endpoint_host")
			if n.Label != "m1" || host != "mcp.example.com" {
				t.Fatalf("mcp node %+v", n)
			}
		}
		if n.ID == "a1" {
			if c, _ := n.Metadata.Get("embedded_skills_count"); c != 1 {
				t.Fatalf("embedded skills %v", c)
			}
		}
	}
	if e := BuildTopology(GraphInput{Enterprise: true}); e.DeploymentMode != "enterprise" || len(e.Governance) == 0 {
		t.Fatalf("enterprise overlay: %+v", e)
	}
}
