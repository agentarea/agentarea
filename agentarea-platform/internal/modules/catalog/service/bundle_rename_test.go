package service

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// The Constractio channel: a one-agent folder (agent key "agent") moved to agentarea.yaml.
func constractioLegacy() StrPairs {
	return StrPairs{
		{"agent.yaml", "name: constractio-channel\nmodel: us-model\n"},
		{"instructions.md", "Run the channel."},
		{"policies/instagram-off.yaml", "target: 'tool:instagram_post'\neffect: deny\n"},
		{"policies/telegram-publish-approval.yaml", "target: 'tool:telegram_send'\neffect: approval\n"},
	}
}

func constractioTeam(agentFront string) StrPairs {
	return StrPairs{
		{"agentarea.yaml", "name: constractio-channel\nschema_version: 1\nagents: {include: ./agents/*.md}\npolicies: {include: ./policies/*.yaml}\n"},
		{"agents/channel-host.md", "---\nname: channel-host\nmodel: us-model\n" + agentFront + "---\nRun the channel.\n"},
		{"policies/instagram-off.yaml", "name: instagram-off\nsubject: [channel-host]\ntarget: 'tool:instagram_post'\neffect: deny\n"},
		{"policies/telegram-publish-approval.yaml", "name: telegram-publish-approval\nsubject: channel-host\ntarget: 'tool:telegram_send'\neffect: approval\n"},
	}
}

func loadFolder(t *testing.T, files StrPairs) Bundle {
	t.Helper()
	b, _, err := LoadBundleFolder(files)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func planOf(t *testing.T, f *deployFixture, b Bundle, prior *priorInstall) ImportPreview {
	t.Helper()
	p, err := (&bundleAnalyzer{existence: f.w, prior: prior, shapes: fakeShapes{}, supplied: demoValues()}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func planned(p ImportPreview) []string {
	var out []string
	for _, e := range p.Entities {
		d := ""
		if e.Detail != nil {
			d = " (" + *e.Detail + ")"
		}
		out = append(out, fmt.Sprintf("%s:%s:%s%s", e.Kind, e.Key, e.Status, d))
	}
	return out
}

func TestConstractioMovesToAgentareaYAMLByRenamedFrom(t *testing.T) {
	f := newDeployFixture(t)
	legacy := loadFolder(t, constractioLegacy())
	_, first, err := f.install(t, &legacy, nil)
	if err != nil {
		t.Fatal(err)
	}
	prior := &priorInstall{bundle: legacy, result: first}

	unrenamed := planOf(t, f, loadFolder(t, constractioTeam("")), prior)
	want := "the last install was a one-agent folder whose agent is 'agent'; add renamed_from: agent to agent 'channel-host' to update " +
		"that agent in place, or this deploy creates a second agent and leaves 'agent' orphaned"
	if got := blockMessages(unrenamed); !reflect.DeepEqual(got, []string{want}) {
		t.Fatalf("blocks = %q", got)
	}

	team := loadFolder(t, constractioTeam("renamed_from: agent\n"))
	if got := keysOf(team.Policies); !reflect.DeepEqual(got, []string{"instagram-off", "telegram-publish-approval"}) {
		t.Fatalf("policies = %v: a one-agent subject keeps its key", got)
	}
	p := planOf(t, f, team, prior)
	if len(p.Blocks()) != 0 {
		t.Fatalf("blocks = %q", blockMessages(p))
	}
	wantPlan := []string{"agent:channel-host:will_update (renamed agent → channel-host)",
		"policy:instagram-off:will_update (deny tool:instagram_post on channel-host)",
		"policy:telegram-publish-approval:will_update (approval tool:telegram_send on channel-host)"}
	if got := planned(p); !reflect.DeepEqual(got, wantPlan) {
		t.Fatalf("plan =\n%s", strings.Join(got, "\n"))
	}

	f.log.calls = nil
	_, res, err := f.install(t, &team, prior, entityRef{KindAgent, "channel-host"}, entityRef{KindPolicy, "instagram-off"},
		entityRef{KindPolicy, "telegram-publish-approval"})
	if err != nil {
		t.Fatal(err)
	}
	wantResult := []string{"agent:channel-host:updated:agent-1", "policy:instagram-off:updated:rule-1", "policy:telegram-publish-approval:updated:rule-2"}
	if got := actions(res); !reflect.DeepEqual(got, wantResult) {
		t.Fatalf("result = %v", got)
	}
	for _, c := range f.log.calls {
		if strings.HasPrefix(c, "create") || strings.HasPrefix(c, "delete") {
			t.Fatalf("a rename created or deleted: %q", f.log.calls)
		}
	}

	again := planOf(t, f, team, &priorInstall{bundle: team, result: res})
	for _, e := range again.Entities {
		if e.Status != StatusUnchanged {
			t.Fatalf("the next deploy still changes %s:%s (%s)", e.Kind, e.Key, e.Status)
		}
	}
	if len(again.Issues) != 0 {
		t.Fatalf("issues after the rename = %+v", again.Issues)
	}
}

func TestRenamedFromRefusals(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, `
name: r
agents:
  - {key: a, name: A, model: us-model}
  - {key: b, name: B, model: us-model}
policies:
  - {key: p, subject: a, target: "tool:x", effect: deny}
`)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	prior := &priorInstall{bundle: first, result: res}
	cases := []struct {
		name, src string
		blocks    []string
		warns     []string
	}{
		{"unknown old key", `
name: r
agents:
  - {key: a, name: A, model: us-model}
  - {key: b, name: B, model: us-model}
  - {key: c, name: C, model: us-model, renamed_from: ghost}
policies:
  - {key: p, subject: a, target: "tool:x", effect: deny}
`, nil, []string{"agent 'c': renamed_from 'ghost' names no agent of the last install; it is created new"}},
		{"two claims", `
name: r
agents:
  - {key: c, name: C, model: us-model, renamed_from: a}
  - {key: d, name: D, model: us-model, renamed_from: a}
  - {key: b, name: B, model: us-model}
`, []string{"agents 'c' and 'd' both claim renamed_from 'a'; one old key goes to one object"}, nil},
		{"old key still declared", `
name: r
agents:
  - {key: a, name: A, model: us-model}
  - {key: c, name: C, model: us-model, renamed_from: a}
  - {key: b, name: B, model: us-model}
`, []string{"agent 'c' is renamed_from 'a', but the bundle still declares agent 'a'"}, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := planOf(t, f, mustParse(t, c.src), prior)
			var warns []string
			for _, i := range p.Issues {
				if i.Severity == SeverityWarn && !strings.Contains(i.Message, "left the bundle") {
					warns = append(warns, i.Message)
				}
			}
			if got := blockMessages(p); !reflect.DeepEqual(got, c.blocks) || !reflect.DeepEqual(warns, c.warns) {
				t.Fatalf("blocks = %q, warns = %q", got, warns)
			}
		})
	}
}

// A policy expanded over several agents hands its renamed_from to the expansion on the agent the old policy bound.
func TestRenamedFromOnAnExpandedPolicy(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, `
name: r
agents:
  - {key: a, name: A, model: us-model}
  - {key: b, name: B, model: us-model}
policies:
  - {key: p, subject: b, target: "tool:x", effect: deny}
`)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	b := mustParse(t, `
name: r
agents:
  - {key: a, name: A, model: us-model}
  - {key: b, name: B, model: us-model}
policies:
  - {key: q, subject: [a, b], target: "tool:x", effect: deny, renamed_from: p}
`)
	got := planned(planOf(t, f, b, &priorInstall{bundle: first, result: res}))
	want := []string{"agent:a:unchanged", "agent:b:unchanged", "policy:q-a:will_create (deny tool:x on a)",
		"policy:q-b:will_update (renamed p → q-b; deny tool:x on b)"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("plan =\n%s", strings.Join(got, "\n"))
	}
}

func TestFolderObjectsCarryRenamedFrom(t *testing.T) {
	files := with(with(with(teamFiles(), "skills/brand-voice/SKILL.md", "---\nname: brand-voice\nrenamed_from: voice\n---\nSpeak plainly.\n"),
		"mcp/sheets.yaml", "name: sheets\ncatalog: com.google/sheets\nrenamed_from: gsheets\n"),
		"schedules/mwf-posts.md", "---\nname: mwf-posts\nagent: lead\ncron: '0 9 * * 1'\nrenamed_from: posts\n---\nGo.\n")
	b := loadFolder(t, files)
	if *b.Skills[0].RenamedFrom != "voice" || *b.MCPs[0].RenamedFrom != "gsheets" || *b.Automations[0].RenamedFrom != "posts" {
		t.Fatalf("renamed_from not read: %+v %+v %+v", b.Skills[0], b.MCPs[0], b.Automations[0])
	}
	round := mustParse(t, mustJSON(t, b.Dump()))
	if *round.Skills[0].RenamedFrom != "voice" {
		t.Fatal("renamed_from lost in the canonical form")
	}
	before, err := specFingerprint(&b, b.MCPs[0], nil)
	if err != nil {
		t.Fatal(err)
	}
	b.MCPs[0].RenamedFrom = nil
	if after, _ := specFingerprint(&b, b.MCPs[0], nil); after != before {
		t.Fatal("renamed_from changes the fingerprint: dropping it later would update the object")
	}
}
