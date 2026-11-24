package service

import (
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
)

func workspaceFolder(entry string, more ...StrPair) StrPairs {
	return append(StrPairs{{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\n" + entry},
		{"agents/triage.md", "---\nname: triage\nmodel: us-model\n---\n"}}, more...)
}

func TestLoadWorkspacePolicies(t *testing.T) {
	b, issues, err := LoadBundleFolder(workspaceFolder(`workspace:
  policies:
    include: workspace/*.yaml
    web-ok:
      target: "tool:web_search"
      effect: allow
`, StrPair{"workspace/spend.yaml", "name: spend\ntarget: spend\neffect: cap\nparams: {amount_usd: 100}\n"}))
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("issues = %+v", issues)
	}
	var got []string
	for _, p := range b.Policies {
		got = append(got, p.Key+":"+p.Subject+":"+p.Effect+":"+p.Target)
	}
	if want := []string{"web-ok:workspace:allow:tool:web_search", "spend:workspace:cap:spend"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("policies = %v", got)
	}
}

func TestLoadWorkspacePoliciesRefusals(t *testing.T) {
	for _, c := range []struct{ name, entry, want string }{
		{"subject", "workspace:\n  policies:\n    p: {subject: triage, target: 'tool:x', effect: deny}\n",
			"a workspace policy applies to every agent in the workspace; drop subject"},
		{"unknown key", "workspace:\n  agents: {}\n", "workspace takes only policies, not 'agents'"},
		{"not a mapping", "workspace: [1]\n", "workspace must be a mapping"},
		{"agent policy on the workspace", "policies:\n  p: {subject: workspace, target: 'tool:x', effect: deny}\n",
			"put a workspace-wide policy under workspace.policies in agentarea.yaml"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := LoadBundleFolder(workspaceFolder(c.entry))
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}

const workspacePolicyBundle = `
name: ops
agents: [{key: a, name: A, model: us-model}]
policies:
  - {key: web-ok, subject: workspace, target: "tool:web_search", effect: allow}
  - {key: open, subject: a, target: "tool:x", effect: allow}
`

func TestWorkspacePolicyNeedsAnAdmin(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, workspacePolicyBundle, nil)
	if got := blockMessages(p); !reflect.DeepEqual(got, []string{policyEffectRefused("open")}) {
		t.Fatalf("blocks as an admin = %q", got)
	}
	var detail string
	for _, e := range p.Entities {
		if e.Key == "web-ok" {
			detail = *e.Detail
		}
	}
	if detail != "allow tool:web_search on the workspace: applies to every agent in the workspace" {
		t.Errorf("detail = %q", detail)
	}
	f.notAdmin = true
	p = analyzeWith(t, f, workspacePolicyBundle, nil)
	want := []string{"policy 'web-ok' applies to every agent in the workspace; only a workspace admin may deploy it", policyEffectRefused("open")}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks as a member = %q", got)
	}
}

func TestWorkspacePolicyInstallsOnTheWorkspace(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, strings.Replace(workspacePolicyBundle, `"tool:x", effect: allow`, `"tool:x", effect: deny`, 1))
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var rules []string
	for _, c := range f.log.calls {
		if strings.HasPrefix(c, "create rule") {
			rules = append(rules, c)
		}
	}
	want := []string{"create rule rule-1 allow tool:web_search on workspace:" + f.w.c.Workspace.ID(), "create rule rule-2 deny tool:x on agent:agent-1"}
	if !reflect.DeepEqual(rules, want) {
		t.Fatalf("rules = %q", rules)
	}
	if d := res.Entities[1].Detail; d == nil || *d != "allow tool:web_search on the workspace: applies to every agent in the workspace" {
		t.Errorf("detail = %v", d)
	}
	f.notAdmin = true
	f.log.calls = nil
	if _, _, err := f.install(t, &b, nil); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("install as a member: %v", err)
	}
}
