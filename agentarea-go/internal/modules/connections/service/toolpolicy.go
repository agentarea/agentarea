package service

import (
	"slices"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// OpenAPIToolNames is the one identity every path into the PDP gives an
// operation: its tool name, allowed only as openapi:<connection id>:<tool>;
// the tool and operation names and the connection's name and id only deny
// it or hold it for approval.
func OpenAPIToolNames(connectionID, connectionName, operation string) (string, governanceapi.ToolNames) {
	tool := openapispec.Slugify(operation)
	var restricting []string
	for _, n := range []string{tool, operation, connectionName, connectionID} {
		if n != "" && !slices.Contains(restricting, n) {
			restricting = append(restricting, n)
		}
	}
	return tool, governanceapi.ToolNames{Aliases: []string{openapispec.ToolTarget(connectionID, tool)}, Restricting: restricting}
}

// ToolPolicy is one tool of a connection on its Tools page (MCPInstanceToolPolicy).
type ToolPolicy struct {
	Name      string
	Default   string
	Effective string
	// Reason is set when the effective verdict is stricter than the default.
	Reason *string
}

func strictness(verdict string) int {
	switch verdict {
	case "deny":
		return 2
	case "approval":
		return 1
	}
	return 0
}

func defaultVerdict(rules []WorkspaceRule, target string) string {
	deny, approval := false, false
	for _, r := range rules {
		if r.Target != target || r.HasCondition || (r.Effect == "approval" && r.NamesApprovers) {
			continue
		}
		switch r.Effect {
		case "deny":
			deny = true
		case "approval":
			approval = true
		}
	}
	switch {
	case deny:
		return "deny"
	case approval:
		return "approval"
	}
	return "allow"
}

// ToolPolicyOf is tool_policy: the default the rule on ruleTarget sets beside
// the PDP's verdict for pdpTarget, restricting names only narrowing it.
func ToolPolicyOf(name, ruleTarget, pdpTarget string, restricting []string, rules []WorkspaceRule, p governanceapi.Policy) ToolPolicy {
	def := defaultVerdict(rules, ruleTarget)
	d := governanceapi.DecideToolPolicy(&p, pdpTarget, governanceapi.ToolNames{Restricting: restricting, NameAllows: true})
	eff := "allow"
	switch d.Action {
	case governanceapi.ToolAllow:
	case governanceapi.ToolDeny:
		eff = "deny"
	case governanceapi.ToolRequireApproval:
		eff = "approval"
	}
	out := ToolPolicy{Name: name, Default: def, Effective: eff}
	if strictness(eff) > strictness(def) {
		r := d.Reason
		out.Reason = &r
	}
	return out
}
