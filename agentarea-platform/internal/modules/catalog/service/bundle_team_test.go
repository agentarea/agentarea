package service

import (
	"context"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

const teamBundle = `
name: team
agents:
  - {key: lead, name: Lead, model: us-model, delegates: [writer, researcher]}
  - {key: writer, name: Writer, model: us-model}
  - {key: researcher, name: Researcher, model: gpt-5, delegates: [writer]}
policies:
  - {key: no-send, subject: [writer, researcher], target: "tool:send", effect: deny}
  - {key: all, subject: "*", target: "tool:x", effect: deny}
`

func toolsText(in []string) string { return strings.Join(in, ",") }

func TestTeamInstallCreatesDelegatesFirst(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, teamBundle)
	if got := keysOf(b.Policies); !reflect.DeepEqual(got, []string{"no-send-writer", "no-send-researcher", "all-lead", "all-writer", "all-researcher"}) {
		t.Fatalf("policies = %v", got)
	}
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var made []string
	for _, a := range f.agents.created {
		var tools []string
		for _, tool := range a.Tools {
			id := ""
			if tool.AgentID != nil {
				id = "=" + *tool.AgentID
			}
			tools = append(tools, tool.Type+":"+tool.Name+id)
		}
		made = append(made, a.Name+" "+a.ModelID+" ["+toolsText(tools)+"]")
	}
	want := []string{"Writer model-us []", "Researcher model-gpt [agent:writer=agent-1]", "Lead model-us [agent:writer=agent-1,agent:researcher=agent-2]"}
	if !reflect.DeepEqual(made, want) {
		t.Fatalf("created = %q", made)
	}
	var rules []string
	for _, c := range f.log.calls {
		if strings.HasPrefix(c, "create rule") {
			rules = append(rules, c)
		}
	}
	wantRules := []string{
		"create rule rule-1 deny tool:send on agent:agent-1", "create rule rule-2 deny tool:send on agent:agent-2",
		"create rule rule-3 deny tool:x on agent:agent-3", "create rule rule-4 deny tool:x on agent:agent-1",
		"create rule rule-5 deny tool:x on agent:agent-2",
	}
	if !reflect.DeepEqual(rules, wantRules) {
		t.Fatalf("rules = %q", rules)
	}

	f.log.calls = nil
	changed := mustParse(t, strings.Replace(teamBundle, "delegates: [writer, researcher]", "delegates: [writer]", 1))
	_, _, err = f.install(t, &changed, &priorInstall{bundle: b, result: res}, entityRef{KindAgent, "lead"})
	if err != nil {
		t.Fatal(err)
	}
	if len(f.agents.updates) != 1 {
		t.Fatalf("updates = %+v", f.agents.updates)
	}
	u := f.agents.updates[0]
	if len(u.Tools) != 1 || u.Tools[0].Name != "writer" || *u.Tools[0].AgentID != "agent-1" ||
		!reflect.DeepEqual(managedDelegates(u.ManagedTools), []string{"writer=agent-1", "researcher=agent-2"}) {
		t.Fatalf("update = %+v", u)
	}
}

func analyzeWith(t *testing.T, f *deployFixture, src string, setup func(*bundleAnalyzer)) ImportPreview {
	t.Helper()
	b := mustParse(t, src)
	a := &bundleAnalyzer{existence: f.w, checks: f.w, shapes: fakeShapes{}, supplied: wirejson.Object{}}
	if setup != nil {
		setup(a)
	}
	p, err := a.analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func blockMessages(p ImportPreview) []string {
	var out []string
	for _, i := range p.Blocks() {
		out = append(out, i.Message)
	}
	return out
}

func TestAnalyzeRefusesPoliciesThatLoosenOrReachOut(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, `
name: loose
agents: [{key: a, name: A, model: us-model}]
policies:
  - {key: everyone, subject: workspace, target: spend, effect: cap, params: {amount_usd: 5}}
  - {key: open, subject: a, target: "tool:x", effect: allow}
  - {key: stranger, subject: b, target: "tool:x", effect: deny}
  - {key: dollars, subject: a, target: spend, effect: cap, params: {amount_usd: 5}, billing_currency: USD}
`, nil)
	want := []string{
		policySubjectRefused("everyone"), policyEffectRefused("open"), policyStranger("stranger", "b"),
		"policy 'dollars' caps spend in USD, but this workspace bills in RUB; write the amount in RUB",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks =\n%s", strings.Join(got, "\n"))
	}
	if _, err := ParseBundle("name: x\npolicies: [{key: p, target: 'tool:x', effect: deny}]\n"); err == nil ||
		!strings.Contains(err.Error(), "policies.0.subject\n  Field required") {
		t.Fatalf("policy without subject: %v", err)
	}
}

func TestAnalyzeBlocksBadDelegation(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, `
name: loop
agents:
  - {key: a, name: A, model: us-model, delegates: [b]}
  - {key: b, name: B, model: us-model, delegates: [a, ghost]}
`, nil)
	want := []string{"agents delegate in a cycle: a -> b -> a", "agent 'b' delegates to 'ghost', which is not an agent of this bundle"}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestAnalyzeResolvesModelByName(t *testing.T) {
	f := newDeployFixture(t)
	f.w.b.d.ModelNames = fakeModelNames{instances: []modelsapi.InstanceName{
		{ID: "11111111-1111-1111-1111-111111111111", Name: "Team model", ModelName: "claude-sonnet-5-5"},
		{ID: "22222222-2222-2222-2222-222222222222", Name: "Cheap", ModelName: "gpt-5"},
		{ID: "33333333-3333-3333-3333-333333333333", Name: "Cheaper", ModelName: "gpt-5"},
	}}
	p := analyzeWith(t, f, `
name: models
agents:
  - {key: by-name, name: A, model: Team model}
  - {key: by-model, name: B, model: claude-sonnet-5-5}
  - {key: by-id, name: C, model: 44444444-4444-4444-4444-444444444444}
  - {key: ambiguous, name: D, model: gpt-5}
  - {key: unknown, name: E, model: llama}
`, nil)
	want := []string{
		"agent 'ambiguous': model 'gpt-5' names 2 model instances here: 'Cheap' (gpt-5, 22222222-2222-2222-2222-222222222222), " +
			"'Cheaper' (gpt-5, 33333333-3333-3333-3333-333333333333); give the instance's id or a name only one of them has",
		"agent 'unknown': model 'llama' names no active chat model instance in this workspace; the workspace has " +
			"'Team model' (claude-sonnet-5-5), 'Cheap' (gpt-5), 'Cheaper' (gpt-5)",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks =\n%s", strings.Join(got, "\n"))
	}
	var checked []string
	for _, c := range f.agents.checked {
		checked = append(checked, c.ModelID)
	}
	if !reflect.DeepEqual(checked, []string{"11111111-1111-1111-1111-111111111111", "11111111-1111-1111-1111-111111111111",
		"44444444-4444-4444-4444-444444444444"}) {
		t.Fatalf("checked models = %v", checked)
	}
}

func TestAnalyzeBlocksWhatAnotherBundleOwns(t *testing.T) {
	f := newDeployFixture(t)
	f.agents.live["skill-9"] = true
	others := []otherInstall{{id: "inst-2", name: "other", result: InstallResult{Entities: []InstalledEntity{
		{Kind: KindSkill, Key: "notes", Name: "Writer", Action: ActionCreated, ID: strp("skill-9")},
		{Kind: KindAgent, Key: "gone", Name: "Demo", Action: ActionCreated, ID: strp("agent-gone")},
	}}}}
	p := analyzeWith(t, f, demoBundle, func(a *bundleAnalyzer) { a.others, a.supplied = others, demoValues() })
	want := []string{"skill 'Writer' belongs to bundle 'other' (install inst-2); a bundle owns what it creates, so give this one another name or deploy it from that bundle"}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestPlanDigestNamesTheInstallRevision(t *testing.T) {
	f := newDeployFixture(t)
	digest := func(r *installRevision) string {
		p := analyzeWith(t, f, demoBundle, func(a *bundleAnalyzer) { a.revision, a.supplied = r, demoValues() })
		return *p.PlanDigest
	}
	fresh := digest(nil)
	a := digest(&installRevision{id: "inst-1", updatedAt: "2026-11-22T10:00:00Z"})
	b := digest(&installRevision{id: "inst-1", updatedAt: "2026-11-22T10:00:01Z"})
	c := digest(&installRevision{id: "inst-2", updatedAt: "2026-11-22T10:00:00Z"})
	if fresh == a || a == b || a == c || a != digest(&installRevision{id: "inst-1", updatedAt: "2026-11-22T10:00:00Z"}) {
		t.Fatalf("digests %s %s %s %s", fresh, a, b, c)
	}
}

func TestValidateRequestsTakeTheInstallTarget(t *testing.T) {
	files := wirejson.Member{Key: "files", Value: wirejson.Object{{Key: "agentarea.yaml", Value: "name: a"}}}
	origin := wirejson.Member{Key: "origin", Value: wirejson.Object{{Key: "git_remote", Value: "git@x:y.git"}, {Key: "git_commit", Value: "abc"}}}
	req, errs := ValidateAnalyzeRequest(wirejson.Object{files, {Key: "into", Value: "inst-1"}, origin})
	if errs != nil || *req.Target.Into != "inst-1" || *req.Target.Origin.GitCommit != "abc" || req.Target.Origin.Path != nil {
		t.Fatalf("analyze = %+v, %v", req.Target, errs)
	}
	_, errs = ValidateAnalyzeRequest(wirejson.Object{files, {Key: "into", Value: " "}, {Key: "origin", Value: wirejson.Object{{Key: "host", Value: "x"}}}})
	if len(errs) != 2 || !reflect.DeepEqual(errs[0].Loc, []any{"body", "into"}) || errs[1].Type != "extra_forbidden" ||
		!reflect.DeepEqual(errs[1].Loc, []any{"body", "origin", "host"}) {
		t.Fatalf("errors = %+v", errs)
	}
	install, errs := ValidateInstallRequest(wirejson.Object{{Key: "bundle", Value: wirejson.Object{{Key: "name", Value: "x"}}},
		{Key: "plan_digest", Value: "d"}, {Key: "install_id", Value: "inst-1"}})
	if errs != nil || *install.Target.Into != "inst-1" {
		t.Fatalf("install = %+v, %v", install.Target, errs)
	}
	install, errs = ValidateInstallRequest(wirejson.Object{{Key: "bundle", Value: wirejson.Object{{Key: "name", Value: "x"}}},
		{Key: "plan_digest", Value: "d"}, {Key: "install_id", Value: nil}})
	if errs != nil || install.Target.Into != nil {
		t.Fatalf("install = %+v, %v", install.Target, errs)
	}
}

func TestAnalyzeWarnsOfOrphans(t *testing.T) {
	f := newDeployFixture(t)
	b, prior := redeploy(t, f)
	b.Policies = nil
	p, err := (&bundleAnalyzer{existence: f.w, prior: prior, shapes: fakeShapes{}, supplied: demoValues()}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Issues) != 1 || p.Issues[0].Severity != SeverityWarn ||
		p.Issues[0].Message != "policy 'cap' left the bundle; it stays in the workspace as an orphan, not deleted" {
		t.Fatalf("issues = %+v", p.Issues)
	}
}

func managedDelegates(tools []catalogapi.BundleTool) []string {
	var out []string
	for _, t := range tools {
		if t.Type == "agent" {
			out = append(out, t.Name+"="+deref(t.AgentID))
		}
	}
	return out
}
