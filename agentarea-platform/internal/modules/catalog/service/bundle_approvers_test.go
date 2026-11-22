package service

import (
	"context"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
)

type fakeMembers struct{ members []identityapi.Member }

func (f fakeMembers) ListMembers(context.Context, authn.Caller) ([]identityapi.Member, error) {
	return f.members, nil
}

func acmeMembers() fakeMembers {
	alice, bob := "alice@acme.com", "Bob@Acme.com"
	return fakeMembers{members: []identityapi.Member{{UserID: "u-alice", Email: &alice}, {UserID: "u-bob", Email: &bob}}}
}

const approversBundle = `
name: ops
agents:
  - {key: writer, name: Writer, model: us-model}
  - {key: reader, name: Reader, model: us-model}
policies:
  - {key: tg, subject: writer, target: "tool:mcp:telegram:*", effect: approval, approvers: [alice@acme.com, "user:u-bob"]}
  - {key: send, subject: writer, target: "tool:send", effect: approval}
  - {key: all-spend, subject: workspace, target: "tool:pay", effect: approval, approvers: [bob@acme.com]}
`

func TestApproversParseOnlyOnApprovalPolicies(t *testing.T) {
	for _, c := range []struct{ name, policy, want string }{
		{"deny", `{key: p, subject: a, target: "tool:x", effect: deny, approvers: [alice@acme.com]}`, "policy 'p': approvers apply only to an approval policy"},
		{"bad ref", `{key: p, subject: a, target: "tool:x", effect: approval, approvers: [alice]}`, "approver 'alice' must be an email or user:<id>"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, err := ParseBundle("name: x\nagents: [{key: a, name: A}]\npolicies:\n  - " + c.policy + "\n")
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("err = %v", err)
			}
		})
	}
	b, _, err := LoadBundleFolder(StrPairs{
		{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\npolicies:\n  include: policies/*.yaml\n" +
			"workspace:\n  policies:\n    pay: {target: 'tool:pay', effect: approval, approvers: [bob@acme.com]}\n"},
		{"agents/a.md", "---\nname: a\nmodel: m\n---\n"}, {"agents/b.md", "---\nname: b\nmodel: m\n---\n"},
		{"policies/tg.yaml", "name: tg\nsubject: [a, b]\ntarget: 'tool:mcp:telegram:*'\neffect: approval\napprovers: [alice@acme.com]\n"},
	})
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, p := range b.Policies {
		got = append(got, p.Key+"="+strings.Join(p.Approvers, ","))
	}
	if want := []string{"tg-a=alice@acme.com", "tg-b=alice@acme.com", "pay=bob@acme.com"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("policies = %v", got)
	}
}

func TestApproversResolveToMembersOfTheWorkspace(t *testing.T) {
	f := newDeployFixture(t)
	f.w.b.d.Members = acmeMembers()
	p := analyzeWith(t, f, approversBundle, nil)
	if len(p.Issues) != 0 {
		t.Fatalf("issues = %+v", p.Issues)
	}
	details := map[string]string{}
	var writer, reader PreviewEntity
	for _, e := range p.Entities {
		if e.Detail != nil {
			details[e.Key] = *e.Detail
		}
		switch e.Key {
		case "writer":
			writer = e
		case "reader":
			reader = e
		}
	}
	if details["tg"] != "approval tool:mcp:telegram:* on writer by alice@acme.com, Bob@Acme.com" || details["send"] != "approval tool:send on writer" ||
		details["all-spend"] != "approval tool:pay on the workspace by Bob@Acme.com: applies to every agent in the workspace" {
		t.Fatalf("details = %v", details)
	}
	want := []PreviewApproval{{Policy: "tg", Target: "tool:mcp:telegram:*", Approvers: []string{"alice@acme.com", "Bob@Acme.com"}},
		{Policy: "send", Target: "tool:send", Approvers: []string{}},
		{Policy: "all-spend", Target: "tool:pay", Approvers: []string{"Bob@Acme.com"}, Workspace: true}}
	if !reflect.DeepEqual(writer.Approvals, want) || !reflect.DeepEqual(reader.Approvals, want[2:]) {
		t.Fatalf("approvals: writer %+v, reader %+v", writer.Approvals, reader.Approvals)
	}
	dumped, _ := writer.Dump().Get("approvals")
	if l, ok := dumped.([]any); !ok || len(l) != 3 {
		t.Fatalf("dump = %v", dumped)
	}

	p = analyzeWith(t, f, strings.Replace(approversBundle, `"user:u-bob"`, `carol@acme.com, "user:u-gone"`, 1), nil)
	wantBlocks := []string{"policy 'tg': approver 'carol@acme.com' is not a member of this workspace",
		"policy 'tg': approver 'user:u-gone' is not a member of this workspace"}
	if got := blockMessages(p); !reflect.DeepEqual(got, wantBlocks) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestApproversInstallAsUserIDs(t *testing.T) {
	f := newDeployFixture(t)
	f.w.b.d.Members = acmeMembers()
	b := mustParse(t, approversBundle)
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	if _, err := in.install(context.Background(), &b, wirejson.Object{}, nil, nil); err != nil {
		t.Fatal(err)
	}
	approvers := map[string]any{}
	for _, r := range f.rules.rules {
		v, _ := r.Params.Get("approvers")
		approvers[r.Target] = v
	}
	want := map[string]any{"tool:mcp:telegram:*": []any{"user:u-alice", "user:u-bob"}, "tool:send": nil, "tool:pay": []any{"user:u-bob"}}
	if !reflect.DeepEqual(approvers, want) {
		t.Fatalf("approvers = %v", approvers)
	}
	gone := newDeployFixture(t)
	gone.w.b.d.Members = fakeMembers{}
	in = &bundleInstaller{w: gone.w, approved: map[entityRef]bool{}}
	_, err := in.install(context.Background(), &b, wirejson.Object{}, nil, nil)
	if err == nil || err.Error() != "policy 'tg': approver 'alice@acme.com' is not a member of this workspace" {
		t.Fatalf("install with an approver who left: %v", err)
	}
}

func TestApproversInsideParamsResolveLikeTheField(t *testing.T) {
	src := strings.Replace(approversBundle, `effect: approval, approvers: [alice@acme.com, "user:u-bob"]}`,
		`effect: approval, params: {approvers: [alice@acme.com, "user:u-bob"]}}`, 1)
	f := newDeployFixture(t)
	f.w.b.d.Members = acmeMembers()
	p := analyzeWith(t, f, src, nil)
	for _, e := range p.Entities {
		if e.Key == "tg" && *e.Detail != "approval tool:mcp:telegram:* on writer by alice@acme.com, Bob@Acme.com" {
			t.Fatalf("detail = %q", *e.Detail)
		}
	}
	b := mustParse(t, src)
	if v, _ := b.Policies[0].Params.Get("approvers"); !reflect.DeepEqual(v, []any{"alice@acme.com", "user:u-bob"}) {
		t.Fatalf("canonical params = %v (keeps what the author wrote)", v)
	}
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	if _, err := in.install(context.Background(), &b, wirejson.Object{}, nil, nil); err != nil {
		t.Fatal(err)
	}
	for _, r := range f.rules.rules {
		if r.Target == "tool:mcp:telegram:*" {
			if v, _ := r.Params.Get("approvers"); !reflect.DeepEqual(v, []any{"user:u-alice", "user:u-bob"}) {
				t.Fatalf("rule approvers = %v", v)
			}
		}
	}
	if _, err := ParseBundle("name: x\nagents: [{key: a, name: A}]\npolicies:\n  - {key: p, subject: a, target: 'tool:x', effect: approval, params: {approvers: [bob]}}\n"); err == nil ||
		!strings.Contains(err.Error(), "approver 'bob' must be an email or user:<id>") {
		t.Fatalf("bad ref in params: %v", err)
	}
}
