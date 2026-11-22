package api

import (
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"strings"
)

// ToolAction is the verdict of the tool decision point.
type ToolAction string

const (
	ToolAllow           ToolAction = "allow"
	ToolDeny            ToolAction = "deny"
	ToolRequireApproval ToolAction = "require_approval"
)

// ToolDecision is ToolAuthorizationDecision; Reason reaches tool results and audit.
type ToolDecision struct {
	Action ToolAction
	Reason string
}

// Allowed reports an ALLOW verdict.
func (d ToolDecision) Allowed() bool { return d.Action == ToolAllow }

// ToolNames are a tool's other names a rule may target: Aliases are its
// canonical names (mcp:<instance>:<tool>, openapi:<connection>:<tool>,
// agent:<id>), Restricting only narrow. NameAllows is false when the tool's
// own name was chosen by whoever added its connection.
type ToolNames struct {
	Aliases     []string
	Restricting []string
	NameAllows  bool
}

// DecideToolPolicy is decide_tool_policy, the one runtime decision point:
// default allow; a denied match, an allowlist the tool falls outside of, or an
// approval rule subtract. A nil policy allows. A caller deciding many tools
// under one policy compiles it once with CompileToolRules.
func DecideToolPolicy(p *Policy, tool string, n ToolNames) ToolDecision {
	return CompileToolRules(p).Decide(tool, n)
}

// ToolRules are a policy's tool patterns compiled once.
type ToolRules struct {
	denied, allowed, escalation []*regexp.Regexp
	allowlist, approveAll       bool
	approvers                   []string
	byTool                      []ToolApprovers
	byToolPatterns              []*regexp.Regexp
}

// CompileToolRules compiles p's tool patterns as p is now; a nil policy allows.
func CompileToolRules(p *Policy) *ToolRules {
	r := &ToolRules{}
	if p == nil {
		return r
	}
	if p.Tools != nil {
		r.denied = compileAll(p.Tools.Denied)
		r.allowed, r.allowlist = compileAll(p.Tools.Allowed), p.Tools.Allowed != nil
	}
	if a := p.Approval; a != nil {
		r.approveAll = a.RequiresHumanApproval != nil && *a.RequiresHumanApproval
		r.escalation = compileAll(a.EscalationRules)
		r.approvers, r.byTool = a.Approvers, a.ApproversByTool
		r.byToolPatterns = make([]*regexp.Regexp, len(a.ApproversByTool))
		for i, e := range a.ApproversByTool {
			r.byToolPatterns[i] = CompileFnmatch(e.Tool)
		}
	}
	return r
}

// Decide is DecideToolPolicy under the compiled policy.
func (r *ToolRules) Decide(tool string, n ToolNames) ToolDecision {
	var names []string
	if n.NameAllows {
		names = append(names, tool)
	}
	names = append(names, n.Aliases...)
	restricting := append(append([]string{tool}, n.Aliases...), n.Restricting...)
	if anyMatches(restricting, r.denied) {
		return ToolDecision{ToolDeny, fmt.Sprintf("tool '%s' is denied by policy", tool)}
	}
	if r.allowlist && !anyMatches(names, r.allowed) {
		return ToolDecision{ToolDeny, fmt.Sprintf("tool '%s' is not permitted by the policy allowlist", tool)}
	}
	if r.approveAll || anyMatches(restricting, r.escalation) {
		return ToolDecision{ToolRequireApproval, fmt.Sprintf("tool '%s' requires approval", tool)}
	}
	return ToolDecision{ToolAllow, "allowed by task policy"}
}

// Approvers is ApproversForTool under the compiled policy.
func (r *ToolRules) Approvers(tool string, aliases []string) []string {
	names := append([]string{tool}, aliases...)
	for _, n := range names {
		for _, e := range r.byTool {
			if e.Tool == n && len(e.Refs) > 0 {
				return append([]string{}, e.Refs...)
			}
		}
	}
	for i, e := range r.byTool {
		if len(e.Refs) > 0 && anyMatches(names, r.byToolPatterns[i:i+1]) {
			return append([]string{}, e.Refs...)
		}
	}
	return append([]string{}, r.approvers...)
}

func compileAll(patterns []string) []*regexp.Regexp {
	out := make([]*regexp.Regexp, len(patterns))
	for i, p := range patterns {
		out[i] = CompileFnmatch(p)
	}
	return out
}

func anyMatches(names []string, res []*regexp.Regexp) bool {
	for _, re := range res {
		for _, n := range names {
			if re.MatchString(n) {
				return true
			}
		}
	}
	return false
}

// ToolMatchesAny reports whether name matches any pattern (fnmatch).
func ToolMatchesAny(name string, patterns []string) bool {
	return AnyNameMatches([]string{name}, patterns)
}

// AnyNameMatches reports whether any name matches any pattern.
func AnyNameMatches(names, patterns []string) bool {
	return anyMatches(names, compileAll(patterns))
}

// CallerCanApprove is caller_can_approve: empty approvers lets any member
// approve; otherwise the caller must be listed as user:<id>.
func CallerCanApprove(approvers []string, callerUserID string) bool {
	if len(approvers) == 0 {
		return true
	}
	if callerUserID == "" {
		return false
	}
	for _, a := range approvers {
		if a == "user:"+callerUserID {
			return true
		}
	}
	return false
}

// ApproversForTool is approvers_for_tool: a per-tool key naming the tool
// exactly wins, then one matching it as a pattern (in written order), then the
// global list; empty means any member.
func ApproversForTool(p *Policy, tool string, aliases []string) []string {
	if p == nil || p.Approval == nil {
		return []string{}
	}
	return CompileToolRules(p).Approvers(tool, aliases)
}

// Fnmatch is Python's fnmatch.fnmatch on POSIX: *, ?, [seq] and [!seq],
// case sensitive, * matching any character including / and :. A caller
// matching one pattern against many names compiles it once with CompileFnmatch.
func Fnmatch(name, pattern string) bool {
	return CompileFnmatch(pattern).MatchString(name)
}

// neverMatches is fnmatch's (?!): RE2 has no lookahead.
const neverMatches = `[^\x00-\x{10FFFF}]`

// CompileFnmatch is pattern as the regexp Fnmatch matches with; a pattern that
// does not compile matches nothing.
func CompileFnmatch(pattern string) *regexp.Regexp {
	re, err := regexp.Compile(fnmatchRegexp(pattern))
	if err != nil {
		slog.Warn("tool pattern does not compile; it matches nothing", "pattern", pattern, "error", err)
		return regexp.MustCompile(`^` + neverMatches + `$`)
	}
	return re
}

// fnmatchRegexp is CPython's fnmatch.translate, written for RE2.
func fnmatchRegexp(pat string) string {
	var b strings.Builder
	b.WriteString(`(?s)^`)
	rs := []rune(pat)
	n := len(rs)
	for i := 0; i < n; {
		c := rs[i]
		i++
		switch c {
		case '*':
			b.WriteString(`.*`)
		case '?':
			b.WriteString(`.`)
		case '[':
			j := i
			if j < n && rs[j] == '!' {
				j++
			}
			if j < n && rs[j] == ']' {
				j++
			}
			for j < n && rs[j] != ']' {
				j++
			}
			if j >= n {
				b.WriteString(`\[`)
				continue
			}
			b.WriteString(bracket(rs, i, j))
			i = j + 1
		default:
			b.WriteString(regexp.QuoteMeta(string(c)))
		}
	}
	b.WriteString(`$`)
	return b.String()
}

// bracket is translate's [seq] for rs[i:j], the characters between the
// brackets: empty ranges such as z-a are dropped, an empty set never matches,
// a negated empty set matches any character.
func bracket(rs []rune, i, j int) string {
	var chunks [][]rune
	if !slices.Contains(rs[i:j], '-') {
		chunks = [][]rune{rs[i:j]}
	} else {
		k := i + 1
		if rs[i] == '!' {
			k = i + 2
		}
		for {
			off := -1
			if k < j {
				off = slices.Index(rs[k:j], '-')
			}
			if off < 0 {
				break
			}
			k += off
			chunks = append(chunks, rs[i:k])
			i = k + 1
			k += 3
		}
		if chunk := rs[i:j]; len(chunk) > 0 {
			chunks = append(chunks, chunk)
		} else {
			last := len(chunks) - 1
			chunks[last] = append(slices.Clone(chunks[last]), '-')
		}
		for k := len(chunks) - 1; k > 0; k-- {
			prev, cur := chunks[k-1], chunks[k]
			if len(prev) > 0 && len(cur) > 0 && prev[len(prev)-1] > cur[0] {
				chunks[k-1] = append(slices.Clone(prev[:len(prev)-1]), cur[1:]...)
				chunks = slices.Delete(chunks, k, k+1)
			}
		}
	}
	parts := make([]string, len(chunks))
	for k, ch := range chunks {
		var sb strings.Builder
		for _, r := range ch {
			switch r {
			case '\\', '-', '[', ']', '&', '~', '|', '^':
				sb.WriteByte('\\')
			}
			sb.WriteRune(r)
		}
		parts[k] = sb.String()
	}
	stuff := strings.Join(parts, "-")
	switch {
	case stuff == "":
		return neverMatches
	case stuff == "!":
		return `.`
	case strings.HasPrefix(stuff, "!"):
		return "[^" + stuff[1:] + "]"
	}
	return "[" + stuff + "]"
}
