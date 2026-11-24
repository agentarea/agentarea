package service

import (
	"testing"

	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

func TestToolPolicyOfDefaultBesideEffective(t *testing.T) {
	rules := []WorkspaceRule{
		{Target: "tool:gh__push", Effect: "approval"},
		{Target: "tool:gh__push", Effect: "deny", HasCondition: true},
		{Target: "tool:gh__read", Effect: "approval", NamesApprovers: true},
		{Target: "tool:gh__rm", Effect: "deny"},
	}
	p := governanceapi.Policy{Tools: &governanceapi.Tools{Denied: []string{"gh__wipe"}}}
	for _, c := range []struct {
		tool, def, eff string
		reason         bool
	}{
		{"push", "approval", "allow", false},
		{"read", "allow", "allow", false},
		{"rm", "deny", "allow", false},
		{"wipe", "allow", "deny", true},
	} {
		got := ToolPolicyOf(c.tool, "tool:gh__"+c.tool, "gh__"+c.tool, nil, rules, governanceapi.CompileToolRules(&p))
		if got.Default != c.def || got.Effective != c.eff || (got.Reason != nil) != c.reason {
			t.Errorf("%s: %+v", c.tool, got)
		}
	}
	held := governanceapi.Policy{Approval: &governanceapi.Approval{EscalationRules: []string{"gh__*"}}}
	if got := ToolPolicyOf("push", "tool:gh__push", "gh__push", nil, nil, governanceapi.CompileToolRules(&held)); got.Effective != "approval" || got.Reason == nil {
		t.Fatalf("held %+v", got)
	}
}
