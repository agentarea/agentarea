package api

import (
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"strings"
	"sync"
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
// approval rule subtract. A nil policy allows.
func DecideToolPolicy(p *Policy, tool string, n ToolNames) ToolDecision {
	var names []string
	if n.NameAllows {
		names = append(names, tool)
	}
	names = append(names, n.Aliases...)
	restricting := append(append([]string{tool}, n.Aliases...), n.Restricting...)
	if p != nil && p.Tools != nil {
		if AnyNameMatches(restricting, p.Tools.Denied) {
			return ToolDecision{ToolDeny, fmt.Sprintf("tool '%s' is denied by policy", tool)}
		}
		if p.Tools.Allowed != nil && !AnyNameMatches(names, p.Tools.Allowed) {
			return ToolDecision{ToolDeny, fmt.Sprintf("tool '%s' is not permitted by the policy allowlist", tool)}
		}
	}
	if p != nil && p.Approval != nil {
		a := p.Approval
		if (a.RequiresHumanApproval != nil && *a.RequiresHumanApproval) || AnyNameMatches(restricting, a.EscalationRules) {
			return ToolDecision{ToolRequireApproval, fmt.Sprintf("tool '%s' requires approval", tool)}
		}
	}
	return ToolDecision{ToolAllow, "allowed by task policy"}
}

// ToolMatchesAny reports whether name matches any pattern (fnmatch).
func ToolMatchesAny(name string, patterns []string) bool {
	for _, p := range patterns {
		if Fnmatch(name, p) {
			return true
		}
	}
	return false
}

// AnyNameMatches reports whether any name matches any pattern.
func AnyNameMatches(names, patterns []string) bool {
	for _, n := range names {
		if ToolMatchesAny(n, patterns) {
			return true
		}
	}
	return false
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
	a := p.Approval
	names := append([]string{tool}, aliases...)
	for _, n := range names {
		for _, e := range a.ApproversByTool {
			if e.Tool == n && len(e.Refs) > 0 {
				return append([]string{}, e.Refs...)
			}
		}
	}
	for _, e := range a.ApproversByTool {
		if len(e.Refs) > 0 && AnyNameMatches(names, []string{e.Tool}) {
			return append([]string{}, e.Refs...)
		}
	}
	return append([]string{}, a.Approvers...)
}

// Fnmatch is Python's fnmatch.fnmatch on POSIX: *, ?, [seq] and [!seq],
// case sensitive, * matching any character including / and :.
func Fnmatch(name, pattern string) bool {
	return compiled(pattern).MatchString(name)
}

//nolint:gochecknoglobals // a cache of compiled patterns, like fnmatch's lru_cache
var patterns sync.Map

// neverMatches is fnmatch's (?!): RE2 has no lookahead.
const neverMatches = `[^\x00-\x{10FFFF}]`

func compiled(pattern string) *regexp.Regexp {
	if re, ok := patterns.Load(pattern); ok {
		return re.(*regexp.Regexp)
	}
	re, err := regexp.Compile(fnmatchRegexp(pattern))
	if err != nil {
		slog.Warn("tool pattern does not compile; it matches nothing", "pattern", pattern, "error", err)
		re = regexp.MustCompile(`^` + neverMatches + `$`)
	}
	patterns.Store(pattern, re)
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
