package service

import (
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// AllAgents is the policy subject naming every agent of the bundle.
const AllAgents = "*"

// WorkspaceSubject is the subject of a workspace policy: every agent in the
// workspace, the bundle's or not. Only a workspace admin deploys one.
const WorkspaceSubject = "workspace"

func policySubjectRefused(key string) string {
	return fmt.Sprintf("policy '%s': subject 'workspace' is refused here; a policy under policies applies only to the bundle's agents "+
		"(an agent key, a list of them, or \"*\"); put a workspace-wide policy under workspace.policies in agentarea.yaml, "+
		"which only a workspace admin may deploy", key)
}

func policyEffectRefused(key string) string {
	return fmt.Sprintf("policy '%s': effect 'allow' is refused; a policy on the bundle's agents may only tighten (deny, approval, cap, safety); "+
		"a rule that loosens is a workspace policy (workspace.policies in agentarea.yaml), which only a workspace admin may deploy", key)
}

func policyStranger(key, subject string) string {
	return fmt.Sprintf("policy '%s': subject '%s' is not an agent of this bundle", key, subject)
}

// policySubjects are the agents a policy written as a list or "*" binds, nil
// when its subject is one name (or not a name at all, which the policy's own
// check reports); keyed is whether each gets its own key <key>-<agent>, which
// a list of one agent does not.
func policySubjects(o wirejson.Object, agentKeys []string) (subjects []string, keyed bool, problem string) {
	v, _ := o.Get("subject")
	switch x := v.(type) {
	case string:
		if x != AllAgents {
			return nil, false, ""
		}
		if len(agentKeys) == 0 {
			return nil, false, "subject \"*\" names every agent of the bundle, and it has none"
		}
		return agentKeys, true, ""
	case []any:
		if len(x) == 0 {
			return nil, false, "subject is an empty list; name an agent key of this bundle, a list of them, or \"*\""
		}
		out := make([]string, len(x))
		for i, s := range x {
			name, ok := s.(string)
			if !ok || name == "" {
				return nil, false, "subject must list agent keys of this bundle"
			}
			out[i] = name
		}
		return out, len(out) > 1, ""
	}
	return nil, false, ""
}

// perSubject is the policy o for one of its subjects, keyed <key>-<agent> when keyed.
func perSubject(o wirejson.Object, subject string, keyed bool) wirejson.Object {
	out := append(wirejson.Object{}, o...)
	if k, ok := o.Get("key"); ok && keyed {
		if s, ok := k.(string); ok {
			out.Set("key", s+"-"+subject)
		}
	}
	out.Set("subject", subject)
	return out
}

// policiesOf reads the policies field, one policy per agent a list or "*" names.
func policiesOf(c *checker, f fields, agents []BundleAgent) []BundlePolicy {
	out := []BundlePolicy{}
	v, ok := f.get("policies")
	if !ok {
		return out
	}
	l, ok := v.([]any)
	if !ok {
		c.add(fieldErr("list_type", "Input should be a valid list", f.at("policies")))
		return out
	}
	keys := make([]string, len(agents))
	for i, a := range agents {
		keys[i] = a.Key
	}
	for i, x := range l {
		loc := f.atList("policies", i)
		o, isObject := x.(wirejson.Object)
		var subjects []string
		var keyed bool
		if isObject {
			var problem string
			if subjects, keyed, problem = policySubjects(o, keys); problem != "" {
				c.valueError(problem, join(loc, "subject"))
				continue
			}
		}
		if subjects == nil {
			got, _ := bundlePolicyFrom(c, x, loc)
			out = append(out, got)
			continue
		}
		for _, s := range subjects {
			got, _ := bundlePolicyFrom(c, perSubject(o, s, keyed), loc)
			out = append(out, got)
		}
	}
	return out
}

// policyRefusal is why a bundle may not install p, with the field to blame; "" when it may.
func policyRefusal(p BundlePolicy) (field, msg string) {
	switch {
	case p.Subject == "workspace":
		return "subject", policySubjectRefused(p.Key)
	case p.Effect == "allow":
		return "effect", policyEffectRefused(p.Key)
	}
	return "", ""
}
