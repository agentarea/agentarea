package service

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

func TestToolPoliciesWorkspaceAndEffective(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	add := func(r domain.Rule) {
		if _, err := f.sv.CreateRule(ctx, f.caller, r); err != nil {
			t.Fatal(err)
		}
	}
	add(wsRule(f.ws, "tool:rm", "deny", obj()))
	user := wsRule(f.ws, "tool:ls", "deny", obj())
	user.SubjectType, user.SubjectID = "user", "u1"
	add(user)

	rules, pol, err := f.sv.Workspace(ctx, f.caller)
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 || rules[0].Target != "tool:rm" || rules[0].Effect != "deny" || rules[0].HasCondition || rules[0].NamesApprovers {
		t.Fatalf("rules %+v", rules)
	}
	if pol.Tools == nil || len(pol.Tools.Denied) != 1 || pol.Tools.Denied[0] != "rm" {
		t.Fatalf("workspace layer %+v", pol.Tools)
	}
	eff, err := f.sv.Effective(ctx, f.ws, "u1")
	if err != nil {
		t.Fatal(err)
	}
	if eff.Tools == nil || len(eff.Tools.Denied) != 2 {
		t.Fatalf("effective %+v", eff.Tools)
	}
}

func TestApprovalTargetsPerAgent(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	for _, r := range []struct{ agent, target string }{{"a1", "tool:x"}, {"a1", "tool:y"}, {"a2", "tool:z"}, {"a3", "tool:w"}} {
		rule := wsRule(f.ws, r.target, "approval", obj())
		rule.SubjectType, rule.SubjectID = "agent", r.agent
		if _, err := f.sv.CreateRule(ctx, f.caller, rule); err != nil {
			t.Fatal(err)
		}
	}
	got, err := f.sv.Targets(ctx, f.ws, []string{"a1", "a2", "a9"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || len(got["a1"]) != 2 || got["a2"][0] != "tool:z" {
		t.Fatalf("targets %v", got)
	}
}
