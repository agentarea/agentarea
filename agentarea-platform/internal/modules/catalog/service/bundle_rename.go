package service

import (
	"fmt"
	"sort"
)

// renameKinds are the kinds in the order their renames are settled: a
// policy's old subject is an agent, so agents come first.
func renameKinds() []EntityKind {
	return []EntityKind{KindAgent, KindMCP, KindOpenAPI, KindSkill, KindTask, KindProject, KindStream, KindChannel, KindAutomation, KindPolicy}
}

// renamesOf matches each renamed_from to what the last install created under
// that key: the result maps the object's new key to the old one. A claim on a
// key the last install does not have is a WARN; two objects claiming one key,
// or an old key the bundle still declares, block.
func renamesOf(b *Bundle, prior *priorInstall) (map[entityRef]string, []PreviewIssue) {
	renames := map[entityRef]string{}
	var issues []PreviewIssue
	agentKeyAfter := map[string]string{}
	for _, kind := range renameKinds() {
		declared := map[string]bool{}
		for _, s := range bundleEntities(b, kind) {
			declared[s.specKey()] = true
		}
		claims := map[string][]bundleSpec{}
		var olds []string
		for _, s := range bundleEntities(b, kind) {
			from := s.renamedFrom()
			if from == nil || *from == s.specKey() {
				continue
			}
			switch {
			case declared[*from]:
				issues = append(issues, blockIssue(s.specKey(), fmt.Sprintf("%s '%s' is renamed_from '%s', but the bundle still declares %s '%s'",
					kind, s.specKey(), *from, kind, *from)))
			case prior != nil && prior.recorded(kind, s.specKey()) != nil:
				if prior.recorded(kind, *from) != nil {
					issues = append(issues, warnIssue(s.specKey(), fmt.Sprintf("%s '%s': renamed_from '%s' is ignored: the last install has both '%s' and '%s'; "+
						"'%s' stays as an orphan", kind, s.specKey(), *from, *from, s.specKey(), *from)))
				}
			case prior == nil || prior.recorded(kind, *from) == nil:
				issues = append(issues, warnIssue(s.specKey(), fmt.Sprintf("%s '%s': renamed_from '%s' names no %s of the last install; it is created new",
					kind, s.specKey(), *from, kind)))
			default:
				if _, seen := claims[*from]; !seen {
					olds = append(olds, *from)
				}
				claims[*from] = append(claims[*from], s)
			}
		}
		sort.Strings(olds)
		for _, old := range olds {
			got := claims[old]
			if len(got) > 1 && kind == KindPolicy {
				got = onPriorSubject(got, prior, old, agentKeyAfter)
			}
			if len(got) != 1 {
				keys := make([]string, len(claims[old]))
				for i, s := range claims[old] {
					keys[i] = "'" + s.specKey() + "'"
				}
				issues = append(issues, blockIssue(claims[old][0].specKey(), fmt.Sprintf("%ss %s both claim renamed_from '%s'; one old key goes to one object",
					kind, joinAnd(keys), old)))
				continue
			}
			renames[entityRef{kind, got[0].specKey()}] = old
			if kind == KindAgent {
				agentKeyAfter[old] = got[0].specKey()
			}
		}
	}
	return renames, issues
}

// onPriorSubject keeps the expansions of a policy that bind the agent the old
// policy bound, under that agent's key now.
func onPriorSubject(claims []bundleSpec, prior *priorInstall, old string, agentKeyAfter map[string]string) []bundleSpec {
	before, ok := prior.spec(KindPolicy, old).(BundlePolicy)
	if !ok {
		return claims
	}
	subject := before.Subject
	if renamed, ok := agentKeyAfter[subject]; ok {
		subject = renamed
	}
	var out []bundleSpec
	for _, c := range claims {
		if c.(BundlePolicy).Subject == subject {
			out = append(out, c)
		}
	}
	return out
}

func joinAnd(items []string) string {
	switch len(items) {
	case 0:
		return ""
	case 1:
		return items[0]
	}
	out := items[0]
	for _, s := range items[1 : len(items)-1] {
		out += ", " + s
	}
	return out + " and " + items[len(items)-1]
}

// legacyAgentKept blocks moving a one-agent folder's install to a bundle
// whose one agent has another key and no renamed_from: it would create a
// second agent and orphan the first.
func legacyAgentKept(b *Bundle, prior *priorInstall) []PreviewIssue {
	if prior == nil || len(prior.bundle.Agents) != 1 || prior.bundle.Agents[0].Key != RootAgentKey || len(b.Agents) != 1 {
		return nil
	}
	a := b.Agents[0]
	if a.Key == RootAgentKey || a.RenamedFrom != nil || prior.owned(KindAgent, RootAgentKey) == nil {
		return nil
	}
	return []PreviewIssue{blockIssue(a.Key, fmt.Sprintf("the last install was a one-agent folder whose agent is '%s'; add renamed_from: %s to agent '%s' "+
		"to update that agent in place, or this deploy creates a second agent and leaves '%s' orphaned", RootAgentKey, RootAgentKey, a.Key, RootAgentKey))}
}

// renamed is the prior install with each renamed object under its new key,
// in what it recorded and in the specs and references it declared.
func (p *priorInstall) renamed(renames map[entityRef]string) *priorInstall {
	if p == nil || len(renames) == 0 {
		return p
	}
	newKey := map[entityRef]string{}
	for to, from := range renames {
		newKey[entityRef{to.kind, from}] = to.key
	}
	key := func(kind EntityKind, k string) string {
		if n, ok := newKey[entityRef{kind, k}]; ok {
			return n
		}
		return k
	}
	keys := func(kind EntityKind, l []string) []string {
		out := make([]string, len(l))
		for i, k := range l {
			out[i] = key(kind, k)
		}
		return out
	}
	out := &priorInstall{bundle: p.bundle, result: p.result}
	out.result.Entities = make([]InstalledEntity, len(p.result.Entities))
	for i, e := range p.result.Entities {
		e.Key = key(e.Kind, e.Key)
		out.result.Entities[i] = e
	}
	b := &out.bundle
	b.MCPs = append([]BundleMCP{}, p.bundle.MCPs...)
	for i := range b.MCPs {
		b.MCPs[i].Key = key(KindMCP, b.MCPs[i].Key)
	}
	b.Skills = append([]BundleSkill{}, p.bundle.Skills...)
	for i := range b.Skills {
		b.Skills[i].Key = key(KindSkill, b.Skills[i].Key)
	}
	b.Agents = append([]BundleAgent{}, p.bundle.Agents...)
	for i, a := range b.Agents {
		b.Agents[i].Key = key(KindAgent, a.Key)
		b.Agents[i].MCPs, b.Agents[i].Skills, b.Agents[i].Delegates = keys(KindMCP, a.MCPs), keys(KindSkill, a.Skills), keys(KindAgent, a.Delegates)
		b.Agents[i].OpenAPI = keys(KindOpenAPI, a.OpenAPI)
	}
	b.Tasks = append([]BundleTask{}, p.bundle.Tasks...)
	for i, t := range b.Tasks {
		b.Tasks[i].Key, b.Tasks[i].Agent = key(KindTask, t.Key), key(KindAgent, t.Agent)
	}
	b.Projects = append([]BundleProject{}, p.bundle.Projects...)
	for i, pr := range b.Projects {
		b.Projects[i].Key = key(KindProject, pr.Key)
		b.Projects[i].Agents, b.Projects[i].MCPs, b.Projects[i].Skills = keys(KindAgent, pr.Agents), keys(KindMCP, pr.MCPs), keys(KindSkill, pr.Skills)
	}
	b.OpenAPI = append([]BundleOpenAPI{}, p.bundle.OpenAPI...)
	for i := range b.OpenAPI {
		b.OpenAPI[i].Key = key(KindOpenAPI, b.OpenAPI[i].Key)
	}
	b.Channels = append([]BundleChannel{}, p.bundle.Channels...)
	for i, ch := range b.Channels {
		b.Channels[i].Key, b.Channels[i].Agent = key(KindChannel, ch.Key), key(KindAgent, ch.Agent)
	}
	b.Streams = append([]BundleStream{}, p.bundle.Streams...)
	for i, st := range b.Streams {
		b.Streams[i].Key = key(KindStream, st.Key)
		for _, w := range []*[]BundleStreamWriter{&b.Streams[i].Processors, &b.Streams[i].Forwards} {
			*w = append([]BundleStreamWriter{}, *w...)
			for j := range *w {
				(*w)[j].Outputs = keys(KindStream, (*w)[j].Outputs)
			}
		}
	}
	b.Automations = append([]BundleAutomation{}, p.bundle.Automations...)
	for i, a := range b.Automations {
		b.Automations[i].Key, b.Automations[i].Agent = key(KindAutomation, a.Key), key(KindAgent, a.Agent)
		if a.On != nil {
			on := *a.On
			on.Stream = key(KindStream, on.Stream)
			b.Automations[i].On = &on
		}
	}
	b.Policies = append([]BundlePolicy{}, p.bundle.Policies...)
	for i, pol := range b.Policies {
		b.Policies[i].Key, b.Policies[i].Subject = key(KindPolicy, pol.Key), key(KindAgent, pol.Subject)
	}
	return out
}
