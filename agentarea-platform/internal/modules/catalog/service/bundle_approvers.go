package service

import (
	"context"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
)

// approverRefs are p's approvers as written: the approvers field, else params.approvers.
func (p BundlePolicy) approverRefs() []string {
	if len(p.Approvers) > 0 {
		return p.Approvers
	}
	v, _ := p.Params.Get("approvers")
	l, _ := v.([]any)
	out := make([]string, 0, len(l))
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// approverSet is a policy's approvers resolved in the workspace: the
// user:<id> refs a rule takes, the names a plan shows, and the refs no member answers.
type approverSet struct {
	refs, names, strangers []string
}

func approverName(m identityapi.Member) string {
	switch {
	case m.Email != nil && *m.Email != "":
		return *m.Email
	case m.DisplayName != nil && *m.DisplayName != "":
		return *m.DisplayName
	}
	return m.UserID
}

// resolveApprovers matches each approver to a member: an email by its
// address, case aside, a user:<id> by its id.
func resolveApprovers(members []identityapi.Member, approvers []string) approverSet {
	out := approverSet{refs: []string{}, names: []string{}}
	for _, a := range approvers {
		var found *identityapi.Member
		for i, m := range members {
			id, isUser := strings.CutPrefix(a, "user:")
			if (isUser && m.UserID == id) || (!isUser && m.Email != nil && strings.EqualFold(*m.Email, a)) {
				found = &members[i]
				break
			}
		}
		if found == nil {
			out.strangers = append(out.strangers, a)
			continue
		}
		out.refs = append(out.refs, "user:"+found.UserID)
		out.names = append(out.names, approverName(*found))
	}
	return out
}

// unresolvedApprovers is a policy's approvers when no workspace is read:
// each shown as written, an email standing in as a placeholder user.
func unresolvedApprovers(approvers []string) approverSet {
	out := approverSet{refs: []string{}, names: append([]string{}, approvers...)}
	for _, a := range approvers {
		if strings.HasPrefix(a, "user:") {
			out.refs = append(out.refs, a)
		} else {
			out.refs = append(out.refs, "user:"+placeholderSubjectID)
		}
	}
	return out
}

func approverProblem(key, approver string) string {
	return fmt.Sprintf("policy '%s': approver '%s' is not a member of this workspace", key, approver)
}

// withApprovers is p as its rule is written: the resolved approvers in params.
func withApprovers(p BundlePolicy, set approverSet) BundlePolicy {
	if len(p.approverRefs()) == 0 {
		return p
	}
	params := append(wirejson.Object{}, p.Params...)
	params.Set("approvers", strList(set.refs))
	p.Params = params
	return p
}

func approvedBy(names []string) string {
	if len(names) == 0 {
		return ""
	}
	return " by " + strings.Join(names, ", ")
}

func policyDetail(p BundlePolicy, names []string) string {
	if p.Subject == WorkspaceSubject {
		return fmt.Sprintf("%s %s on the workspace%s: applies to every agent in the workspace", p.Effect, p.Target, approvedBy(names))
	}
	return fmt.Sprintf("%s %s on %s%s", p.Effect, p.Target, p.Subject, approvedBy(names))
}

// approvers resolves p's approvers in the workspace the plan reads, or as written without one.
func (a *bundleAnalyzer) approvers(ctx context.Context, p BundlePolicy) (approverSet, error) {
	if len(p.approverRefs()) == 0 {
		return approverSet{refs: []string{}, names: []string{}}, nil
	}
	if a.checks == nil {
		return unresolvedApprovers(p.approverRefs()), nil
	}
	members, err := a.checks.members(ctx)
	if err != nil {
		return approverSet{}, err
	}
	return resolveApprovers(members, p.approverRefs()), nil
}

// attachApprovals puts on each agent's line the approval policies that bind it.
func (a *bundleAnalyzer) attachApprovals(b *Bundle, entities []PreviewEntity) {
	for i, e := range entities {
		if e.Kind != KindAgent {
			continue
		}
		for _, p := range b.Policies {
			if p.Effect != "approval" || (p.Subject != e.Key && p.Subject != WorkspaceSubject) {
				continue
			}
			names := a.approverNames[p.Key]
			if names == nil {
				names = []string{}
			}
			entities[i].Approvals = append(entities[i].Approvals, PreviewApproval{Policy: p.Key, Target: p.Target, Approvers: names,
				Workspace: p.Subject == WorkspaceSubject})
		}
	}
}

// approvers resolves p's approvers for its rule; one who is no member refuses the install.
func (in *bundleInstaller) approvers(ctx context.Context, p BundlePolicy) (approverSet, error) {
	if len(p.approverRefs()) == 0 {
		return approverSet{refs: []string{}, names: []string{}}, nil
	}
	members, err := in.w.members(ctx)
	if err != nil {
		return approverSet{}, err
	}
	set := resolveApprovers(members, p.approverRefs())
	if len(set.strangers) > 0 {
		msg := approverProblem(p.Key, set.strangers[0])
		return approverSet{}, installError(msg, blockIssue(p.Key, msg))
	}
	return set, nil
}
