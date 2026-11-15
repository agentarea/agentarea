package service

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
)

func agentRule(agent, target string, enabled bool, by *string) domain.Rule {
	return domain.Rule{ID: uuid.NewString(), SubjectType: "agent", SubjectID: agent, Target: target, Effect: "approval", Enabled: enabled, ManagedBy: by}
}

func targetsOf(rows []domain.Rule, owned bool) []string {
	var out []string
	for _, r := range rows {
		if managedBy(r, domain.ManagedByAgentTools) == owned {
			out = append(out, r.Target)
		}
	}
	slices.Sort(out)
	return out
}

func TestSyncAgentApprovalsOwnsOnlyTheToggleRules(t *testing.T) {
	f := newFixture(t)
	by := domain.ManagedByAgentTools
	f.rules.rows = []domain.Rule{
		agentRule("a1", "tool:old", true, &by),
		agentRule("a1", "tool:paused", false, &by),
		agentRule("a1", "tool:admin", true, nil),
		agentRule("a1", "tool:gone", true, nil),
	}
	s := db.NewTxSession(f.ws, nil)
	if err := f.sv.SyncAgentApprovals(context.Background(), s, f.caller, "a1", []string{"tool:paused", "tool:admin", "tool:new"}); err != nil {
		t.Fatal(err)
	}
	if got := targetsOf(f.rules.rows, true); !slices.Equal(got, []string{"tool:new", "tool:paused"}) {
		t.Fatalf("owned = %v", got)
	}
	if got := targetsOf(f.rules.rows, false); !slices.Equal(got, []string{"tool:admin", "tool:gone"}) {
		t.Fatalf("authored = %v", got)
	}
	for _, r := range f.rules.rows {
		if !r.Enabled {
			t.Fatalf("%s left disabled", r.Target)
		}
		if r.Target == "tool:new" && f.rules.by[r.ID] != "owner" {
			t.Fatalf("created by %q", f.rules.by[r.ID])
		}
	}
	if err := f.sv.SyncAgentApprovals(context.Background(), s, f.caller, "a1", nil); err != nil {
		t.Fatal(err)
	}
	if got := targetsOf(f.rules.rows, true); len(got) != 0 {
		t.Fatalf("owned after clearing = %v", got)
	}
}

func TestReleaseAgentApprovalsIsForAdmins(t *testing.T) {
	f := newFixture(t)
	by := domain.ManagedByAgentTools
	f.rules.rows = []domain.Rule{agentRule("a1", "tool:shell", true, nil), agentRule("a1", "tool:files", true, &by)}
	notAdmin := func(context.Context) error { return authz.ErrNotWorkspaceAdmin }
	s := db.NewTxSession(f.ws, nil)
	err := f.sv.ReleaseAgentApprovals(context.Background(), s, "a1", []string{"tool:shell", "tool:files"}, notAdmin)
	var enforced *api.ApprovalEnforcedError
	if !errors.As(err, &enforced) || !slices.Equal(enforced.Targets, []string{"tool:shell"}) ||
		enforced.Error() != "Approval for shell can only be changed by a workspace admin." {
		t.Fatalf("got %v", err)
	}
	if err := f.sv.ReleaseAgentApprovals(context.Background(), s, "a1", []string{"tool:other"}, notAdmin); err != nil {
		t.Fatalf("no conflict refused: %v", err)
	}
	if err := f.sv.ReleaseAgentApprovals(context.Background(), s, "a1", []string{"tool:shell"}, func(context.Context) error { return nil }); err != nil {
		t.Fatal(err)
	}
	if len(f.rules.rows) != 1 || f.rules.rows[0].Target != "tool:files" {
		t.Fatalf("rows = %v", f.rules.rows)
	}
	broken := errors.New("graph down")
	f.rules.rows = append(f.rules.rows, agentRule("a1", "tool:shell", true, nil))
	if err := f.sv.ReleaseAgentApprovals(context.Background(), s, "a1", []string{"tool:shell"}, func(context.Context) error { return broken }); !errors.Is(err, broken) {
		t.Fatalf("admin check failure = %v", err)
	}
}

func TestInstallPolicyLayers(t *testing.T) {
	f := newFixture(t)
	ws := f.ws.ID()
	rule := func(st, sid, target, effect string) domain.Rule {
		return domain.Rule{ID: uuid.NewString(), SubjectType: st, SubjectID: sid, Target: target, Effect: effect, Enabled: true}
	}
	ctx := context.Background()
	if err := f.sv.RequireInstallAllowed(ctx, f.caller, "r1", "community"); err != nil {
		t.Fatalf("no rules refused: %v", err)
	}
	f.rules.rows = []domain.Rule{rule("workspace", ws, "registry_trust:verified", "allow"), rule("user", "owner", "registry:r2", "deny")}
	var refused *api.InstallRefusedError
	err := f.sv.RequireInstallAllowed(ctx, f.caller, "r1", "community")
	if !errors.As(err, &refused) || refused.Reason != "registry r1 (community) is not among the registries workspace "+ws+" allows installs from" {
		t.Fatalf("allowlist: %v", err)
	}
	if err := f.sv.RequireInstallAllowed(ctx, f.caller, "r2", "verified"); !errors.As(err, &refused) || refused.Reason != "denied by registry:r2 for user owner" {
		t.Fatalf("user deny: %v", err)
	}
	if reason, no, err := f.sv.RunRefusal(ctx, f.ws, "r2", "verified"); err != nil || no {
		t.Fatalf("a run is held to the workspace's rules alone: %q %v %v", reason, no, err)
	}
	if _, no, _ := f.sv.RunRefusal(ctx, f.ws, "r1", "community"); !no {
		t.Fatal("run allowed outside the workspace allowlist")
	}
}
