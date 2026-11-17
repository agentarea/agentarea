package domain

import (
	"fmt"
	"regexp"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// ToolAction is the verdict of the tool-call policy decision.
type ToolAction string

const (
	ToolAllow           ToolAction = "allow"
	ToolDeny            ToolAction = "deny"
	ToolRequireApproval ToolAction = "require_approval"
)

// Workflow built-in tool names (agentarea_governance.domain.tool_calls).
const (
	ToolCompletion         = "completion"
	ToolTaskComplete       = "task_complete"
	ToolRequestUserInput   = "request_user_input"
	ToolRecallHistory      = "recall_history"
	ToolReadToolOutput     = "read_tool_output"
	ToolActivateToolSource = "activate_tool_source"
	ToolActivateSkill      = "activate_skill"
	ToolLoadTools          = "load_tools"
	ToolWait               = "wait"
)

// Unmetered reports a call that does not consume the tool-call quota.
func Unmetered(name string) bool { return name == ToolCompletion || name == ToolTaskComplete }

// ControlFlowTool reports a workflow tool policy never gates.
func ControlFlowTool(name string) bool {
	switch name {
	case ToolCompletion, ToolTaskComplete, ToolRequestUserInput, ToolRecallHistory, ToolReadToolOutput,
		ToolActivateToolSource, ToolActivateSkill, ToolLoadTools, ToolWait:
		return true
	}
	return false
}

// MeteredToolCallCount counts the calls that consume the governed quota.
func MeteredToolCallCount(names []string) int {
	n := 0
	for _, name := range names {
		if !Unmetered(name) {
			n++
		}
	}
	return n
}

// ToolNames are a model-facing tool's names for the PDP: Aliases may satisfy
// an allowlist and narrow, Restricting may only deny or hold for approval.
type ToolNames struct {
	Aliases     []string
	Restricting []string
	NameAllows  bool
}

// DelegateToolName turns an agent name into its delegation tool name.
func DelegateToolName(agentName string) string {
	s := regexp.MustCompile(`[^a-zA-Z0-9_]`).ReplaceAllString(agentName, "_")
	s = strings.Trim(regexp.MustCompile(`_+`).ReplaceAllString(s, "_"), "_")
	if s == "" || (s[0] >= '0' && s[0] <= '9') {
		s = "agent_" + s
	}
	return "delegate_to_" + s
}

// NamesFor gives every name a policy rule may give a tool (tool_policy_names).
// A connection's tool is allowed only by its connection's id; a delegate only
// by its agent.
func NamesFor(cfg *api.RunConfig, tool string) ToolNames {
	configNames := configAliases(cfg, tool)
	if b, ok := cfg.Bindings[tool]; ok && b.Source != "code" {
		restricting := dedupeExcept(append(slices.Clone(b.RestrictingNames), configNames...), append(slices.Clone(b.PolicyNames), tool))
		return ToolNames{Aliases: slices.Clone(b.PolicyNames), Restricting: restricting, NameAllows: false}
	}
	if d, ok := cfg.Delegates[tool]; ok {
		var aliases []string
		if d.AgentID != "" {
			aliases = []string{"agent:" + d.AgentID}
		}
		return ToolNames{Aliases: aliases, Restricting: configNames, NameAllows: false}
	}
	if b, ok := cfg.Bindings[tool]; ok {
		return ToolNames{Aliases: slices.Clone(b.PolicyNames), Restricting: dedupeExcept(append(slices.Clone(b.RestrictingNames), configNames...), []string{tool}), NameAllows: true}
	}
	return ToolNames{Restricting: configNames, NameAllows: true}
}

func configAliases(cfg *api.RunConfig, tool string) []string {
	var out []string
	for _, c := range cfg.Agent.Tools {
		switch c.Type {
		case "agent":
			if DelegateToolName(c.Name) == tool {
				out = append(out, c.Name)
			}
		case "code":
			if i := strings.LastIndex(c.Name, "/"); c.Name[i+1:] == tool {
				out = append(out, c.Name)
			}
		case "openapi":
			ops := openAPIOperationsFor(c, tool)
			resolved := slices.Contains(cfg.OpenAPIOperationTools[c.Name], tool)
			if len(ops) == 0 && !resolved {
				continue
			}
			out = append(out, ops...)
			out = append(out, c.Name)
			if c.Settings.OpenAPIConnectionID != "" {
				out = append(out, c.Settings.OpenAPIConnectionID)
			}
		}
	}
	return dedupeExcept(out, []string{tool})
}

func openAPIOperationsFor(c api.ToolConfig, tool string) []string {
	re := regexp.MustCompile(`[^a-zA-Z0-9_-]`)
	var ops []string
	for _, op := range c.Settings.AllowedTools {
		if re.ReplaceAllString(op, "_") == tool {
			ops = append(ops, op)
		}
	}
	return ops
}

func dedupeExcept(names, except []string) []string {
	var out []string
	for _, n := range names {
		if n == "" || slices.Contains(except, n) || slices.Contains(out, n) {
			continue
		}
		out = append(out, n)
	}
	return out
}

// DecideToolPolicy is the task-policy part of the tool PDP (decide_tool_policy):
// default allow, then denied, the allowlist and the approval rules subtract.
func DecideToolPolicy(p api.Policy, tool string, n ToolNames) (ToolAction, string) {
	var names []string
	if n.NameAllows {
		names = append(names, tool)
	}
	names = append(names, n.Aliases...)
	restricting := append(append([]string{tool}, n.Aliases...), n.Restricting...)
	if p.Tools != nil {
		if AnyNameMatches(restricting, p.Tools.Denied) {
			return ToolDeny, fmt.Sprintf("tool '%s' is denied by policy", tool)
		}
		if p.Tools.Allowed != nil && !AnyNameMatches(names, p.Tools.Allowed) {
			return ToolDeny, fmt.Sprintf("tool '%s' is not permitted by the policy allowlist", tool)
		}
	}
	if a := p.Approval; a != nil {
		if (a.RequiresHumanApproval != nil && *a.RequiresHumanApproval) || AnyNameMatches(restricting, a.EscalationRules) {
			return ToolRequireApproval, fmt.Sprintf("tool '%s' requires approval", tool)
		}
	}
	return ToolAllow, "allowed by task policy"
}

// ToolMatchesAny reports whether a tool name matches any policy pattern (fnmatch).
func ToolMatchesAny(name string, patterns []string) bool {
	for _, p := range patterns {
		if Fnmatch(name, p) {
			return true
		}
	}
	return false
}

// AnyNameMatches reports whether any of a tool's names matches any pattern.
func AnyNameMatches(names, patterns []string) bool {
	for _, n := range names {
		if ToolMatchesAny(n, patterns) {
			return true
		}
	}
	return false
}

// Fnmatch is Python's fnmatch.fnmatch on POSIX: *, ?, [seq] and [!seq], case
// sensitive, with * matching any character including a slash.
func Fnmatch(name, pattern string) bool {
	return regexp.MustCompile(fnmatchRegexp(pattern)).MatchString(name)
}

func fnmatchRegexp(pat string) string {
	var b strings.Builder
	b.WriteString(`(?s)^`)
	rs := []rune(pat)
	for i := 0; i < len(rs); i++ {
		c := rs[i]
		switch c {
		case '*':
			b.WriteString(`.*`)
		case '?':
			b.WriteString(`.`)
		case '[':
			j := i + 1
			if j < len(rs) && rs[j] == '!' {
				j++
			}
			if j < len(rs) && rs[j] == ']' {
				j++
			}
			for j < len(rs) && rs[j] != ']' {
				j++
			}
			if j >= len(rs) {
				b.WriteString(`\[`)
				continue
			}
			stuff := string(rs[i+1 : j])
			i = j
			if strings.HasPrefix(stuff, "!") {
				stuff = "^" + stuff[1:]
			} else if strings.HasPrefix(stuff, "^") {
				stuff = `\` + stuff
			}
			stuff = strings.ReplaceAll(stuff, `\`, `\\`)
			if strings.HasPrefix(stuff, `\\^`) {
				stuff = `\^` + stuff[3:]
			}
			b.WriteString("[" + stuff + "]")
		default:
			b.WriteString(regexp.QuoteMeta(string(c)))
		}
	}
	b.WriteString(`$`)
	return b.String()
}

// ApproversForTool are the subjects allowed to approve a tool: per-tool
// approvers win, then the global list, then none (any member).
func ApproversForTool(p api.Policy, tool string, aliases []string) []string {
	a := p.Approval
	if a == nil {
		return []string{}
	}
	names := append([]string{tool}, aliases...)
	for _, n := range names {
		if refs := a.ApproversByTool[n]; len(refs) > 0 {
			return slices.Clone(refs)
		}
	}
	keys := make([]string, 0, len(a.ApproversByTool))
	for k := range a.ApproversByTool {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	for _, k := range keys {
		if refs := a.ApproversByTool[k]; len(refs) > 0 && AnyNameMatches(names, []string{k}) {
			return slices.Clone(refs)
		}
	}
	return append([]string{}, a.Approvers...)
}

// CallerCanApprove: empty approvers lets any member approve; otherwise the
// caller must be listed as user:<id>.
func CallerCanApprove(approvers []string, callerUserID string) bool {
	if len(approvers) == 0 {
		return true
	}
	return callerUserID != "" && slices.Contains(approvers, "user:"+callerUserID)
}

// QuestionsAvailable: request_user_input is offered unless the return route
// cannot ask or policy denies it.
func QuestionsAvailable(p api.Policy, allowQuestions bool) bool {
	var denied []string
	if p.Tools != nil {
		denied = p.Tools.Denied
	}
	return allowQuestions && !ToolMatchesAny(ToolRequestUserInput, denied)
}
