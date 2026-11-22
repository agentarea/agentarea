package service

import (
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

const teamEntry = `name: acme-content
schema_version: 1
display_name: Acme content
description: Posts for Acme
setup:
  model: {label: Model, type: string, required: true}
  bot_token: {label: Bot token, type: secret, required: true}
defaults:
  model: ${setup.model}
  limits: {monthly_rub: 2000}
targets:
  dev: {workspace: acme-dev}
agents: {include: ./agents/*.md, exclude: ./agents/drafts/*}
mcp: {include: ./mcp/*.yaml}
skills: {include: ./skills/*/}
policies: {include: [./policies/*.yaml]}
schedules: {include: ./schedules/*.md}
`

func teamFiles() StrPairs {
	return StrPairs{
		{"agentarea.yaml", teamEntry},
		{"agents/lead.md", "---\nname: lead\ndescription: Runs the team\ndelegates: [writer, researcher]\n---\nYou lead.\n"},
		{"agents/researcher.md", "---\nname: researcher\nmodel: gpt-5\nreasoning_effort: high\nmcp: [sheets]\nskills: [pricing]\n---\nYou research.\n"},
		{"agents/writer.md", "---\nname: writer\ndisplay_name: Writer\nskills: [brand-voice, pricing]\nmcp: [telegram, sheets]\n" +
			"limits: {run_rub: 20}\nbuiltin_tools: {ask_human_form: false}\n---\nYou write posts.\n"},
		{"agents/drafts/old.md", "---\nname: old\n---\nOld.\n"},
		{"mcp/telegram.yaml", "name: telegram\njson_spec: {type: url, url: 'https://t.example/mcp'}\nbindings: {TOKEN: '${setup.bot_token}'}\n"},
		{"mcp/sheets.yaml", "name: sheets\ndisplay_name: Google Sheets\ncatalog: com.google/sheets\n"},
		{"skills/brand-voice/SKILL.md", "---\nname: brand-voice\ndescription: The voice\n---\nSpeak plainly.\n"},
		{"skills/pricing/SKILL.md", "---\nname: pricing\ndescription: Prices\n---\nSee prices.csv\n"},
		{"skills/pricing/prices.csv", "item,price\n"},
		{"schedules/mwf-posts.md", "---\nname: mwf-posts\nagent: lead\ncron: '0 9 * * 1,3,5'\n---\nWrite the posts.\n"},
		{"policies/publish-approval.yaml", "name: publish-approval\nsubject: [writer]\ntarget: 'tool:telegram_send'\neffect: deny\n"},
		{"README.md", "# Acme\n"},
	}
}

func with(files StrPairs, path, text string) StrPairs {
	out := append(StrPairs{}, files...)
	for i, f := range out {
		if f.Key == path {
			out[i].Value = text
			return out
		}
	}
	return append(out, StrPair{path, text})
}

func keysOf[T bundleSpec](items []T) []string {
	out := make([]string, len(items))
	for i, x := range items {
		out[i] = x.specKey()
	}
	return out
}

func TestLoadTeamFolder(t *testing.T) {
	b, issues, err := LoadBundleFolder(teamFiles())
	if err != nil {
		t.Fatal(err)
	}
	if b.Name != "acme-content" || b.DisplayName == nil || *b.DisplayName != "Acme content" || b.Description != "Posts for Acme" ||
		b.SchemaVersion != BundleSchemaVersion {
		t.Errorf("bundle = %q %v %q %q", b.Name, b.DisplayName, b.Description, b.SchemaVersion)
	}
	if len(b.Setup) != 2 || b.Setup[0].Key != "model" || b.Setup[1].Key != "bot_token" || b.Setup[1].Type != SetupSecret || !b.Setup[1].Required {
		t.Errorf("setup = %+v", b.Setup)
	}
	if got := keysOf(b.Agents); !reflect.DeepEqual(got, []string{"lead", "researcher", "writer"}) {
		t.Fatalf("agents = %v", got)
	}
	lead, researcher, writer := b.Agents[0], b.Agents[1], b.Agents[2]
	if lead.Name != "lead" || lead.Description != "Runs the team" || lead.Instruction != "You lead." || *lead.Model != "${setup.model}" ||
		!reflect.DeepEqual(lead.Delegates, []string{"writer", "researcher"}) || len(lead.MCPs) != 0 || len(lead.Skills) != 0 {
		t.Errorf("lead = %+v", lead)
	}
	if *researcher.Model != "gpt-5" || researcher.ReasoningEffort == nil || *researcher.ReasoningEffort != "high" ||
		!reflect.DeepEqual(researcher.MCPs, []string{"sheets"}) || !reflect.DeepEqual(researcher.Skills, []string{"pricing"}) {
		t.Errorf("researcher = %+v", researcher)
	}
	if writer.Name != "Writer" || *writer.Model != "${setup.model}" || !reflect.DeepEqual(writer.MCPs, []string{"telegram", "sheets"}) ||
		!reflect.DeepEqual(writer.Skills, []string{"brand-voice", "pricing"}) || len(writer.Delegates) != 0 {
		t.Errorf("writer = %+v", writer)
	}
	if got := keysOf(b.MCPs); !reflect.DeepEqual(got, []string{"sheets", "telegram"}) {
		t.Fatalf("mcps = %v", got)
	}
	if b.MCPs[0].Name != "Google Sheets" || b.MCPs[0].Catalog == nil || b.MCPs[1].Name != "telegram" ||
		!reflect.DeepEqual(b.MCPs[1].Bindings, StrPairs{{"TOKEN", "${setup.bot_token}"}}) {
		t.Errorf("mcps = %+v", b.MCPs)
	}
	if got := keysOf(b.Skills); !reflect.DeepEqual(got, []string{"brand-voice", "pricing"}) {
		t.Fatalf("skills = %v", got)
	}
	if b.Skills[0].SourceType != "content" || b.Skills[1].SourceType != "files" || b.Skills[1].Files == nil ||
		!reflect.DeepEqual(*b.Skills[1].Files, StrPairs{{"SKILL.md", "---\nname: pricing\ndescription: Prices\n---\nSee prices.csv\n"}, {"prices.csv", "item,price\n"}}) {
		t.Errorf("skills = %+v", b.Skills)
	}
	if len(b.Automations) != 1 || b.Automations[0].Key != "mwf-posts" || b.Automations[0].Agent != "lead" ||
		b.Automations[0].Prompt != "Write the posts." || b.Automations[0].Cron != "0 9 * * 1,3,5" || b.Automations[0].Timezone != "UTC" {
		t.Errorf("automations = %+v", b.Automations)
	}
	var policies []string
	for _, p := range b.Policies {
		cur := ""
		if p.BillingCurrency != nil {
			cur = " " + *p.BillingCurrency
		}
		params, err := wirejson.Marshal(p.Params, wirejson.Compact)
		if err != nil {
			t.Fatal(err)
		}
		policies = append(policies, p.Key+": "+p.Effect+" "+p.Target+" on "+p.Subject+" "+string(params)+cur)
	}
	want := []string{
		`publish-approval: deny tool:telegram_send on writer {}`,
		`lead-monthly-cap: cap spend on lead {"amount_usd":2000} RUB`,
		`researcher-monthly-cap: cap spend on researcher {"amount_usd":2000} RUB`,
		`writer-monthly-cap: cap spend on writer {"amount_usd":2000} RUB`,
		`writer-run-cap: cap spend on writer {"amount_usd":20,"period":"run"} RUB`,
		`writer-no-ask-human-form: deny tool:request_user_input on writer {}`,
	}
	if !reflect.DeepEqual(policies, want) {
		t.Errorf("policies =\n%s\nwant\n%s", strings.Join(policies, "\n"), strings.Join(want, "\n"))
	}
	var warns []string
	for _, i := range issues {
		if i.Severity != SeverityWarn {
			t.Errorf("issue %+v is not a warning", i)
		}
		warns = append(warns, i.Message)
	}
	wantWarns := []string{
		"README.md: ignored: no include in agentarea.yaml selects it; not deployed",
		"agents/drafts/old.md: ignored: no include in agentarea.yaml selects it; not deployed",
	}
	if !reflect.DeepEqual(warns, wantWarns) {
		t.Errorf("issues = %q", warns)
	}

	round, err := ParseBundle(mustJSON(t, b.Dump()))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(round.Dump(), b.Dump()) {
		t.Errorf("canonical dump does not round-trip:\n%v\n%v", round.Dump(), b.Dump())
	}
}

func mustJSON(t *testing.T, v any) string {
	t.Helper()
	raw, err := wirejson.Marshal(v, wirejson.Compact)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func TestLoadTeamFolderInlineAndWarnings(t *testing.T) {
	entry := "name: solo\nschema_version: 1\n" +
		"agents:\n  helper:\n    model: 11111111-1111-1111-1111-111111111111\n    instruction: Help.\n    skills: [notes]\n" +
		"skills:\n  notes:\n    content: \"---\\nname: notes\\ndescription: n\\n---\\nBody\"\n" +
		"schedules:\n  include: schedules/*.md\n"
	files := StrPairs{{"agentarea.yaml", entry}, {"schedules/daily.md", "---\nname: morning\nagent: helper\ncron: '0 9 * * *'\n---\nGo.\n"}}
	b, issues, err := LoadBundleFolder(files)
	if err != nil {
		t.Fatal(err)
	}
	if len(b.Agents) != 1 || b.Agents[0].Key != "helper" || b.Agents[0].Instruction != "Help." || len(b.Skills) != 1 || b.Skills[0].Key != "notes" ||
		len(b.Automations) != 1 || b.Automations[0].Key != "morning" {
		t.Fatalf("bundle = %+v", b)
	}
	if len(issues) != 1 || issues[0].Message != "schedules/daily.md: file name 'daily' differs from name 'morning'; the object's key is 'morning'" {
		t.Fatalf("issues = %+v", issues)
	}
}

func TestLoadTeamFolderRefusals(t *testing.T) {
	entry := func(more string) StrPairs { return with(teamFiles(), "agentarea.yaml", teamEntry+more) }
	cases := []struct {
		name  string
		files StrPairs
		want  string
	}{
		{"no includes", StrPairs{{"agentarea.yaml", "name: x\nschema_version: 1\n"}},
			"agentarea.yaml: selects no files and declares no objects; add includes, e.g. agents: {include: ./agents/*.md}"},
		{"no schema version", with(teamFiles(), "agentarea.yaml", strings.Replace(teamEntry, "schema_version: 1\n", "", 1)),
			"agentarea.yaml: schema_version is required; this platform reads schema_version: 1"},
		{"unknown schema version", with(teamFiles(), "agentarea.yaml", strings.Replace(teamEntry, "schema_version: 1", "schema_version: 2", 1)),
			"agentarea.yaml:2: schema_version 2 is not supported; this platform reads schema_version: 1"},
		{"no name", with(teamFiles(), "agentarea.yaml", strings.Replace(teamEntry, "name: acme-content\n", "", 1)),
			"agentarea.yaml: name is required: the bundle's name in the workspace"},
		{"unknown top-level key", entry("hooks: {}\n"), "agentarea.yaml:18: unknown key 'hooks'; agentarea.yaml takes name, schema_version, display_name, description, setup, " +
			"defaults, targets, agents, mcp, skills, policies, schedules, channels, streams, openapi, tasks, projects, workspace"},
		{"skills in defaults", with(teamFiles(), "agentarea.yaml", strings.Replace(teamEntry, "  limits:", "  skills: [pricing]\n  limits:", 1)),
			"agentarea.yaml:10: defaults may not carry 'skills'; list skills on each agent, where a reviewer sees the access"},
		{"unknown default", with(teamFiles(), "agentarea.yaml", strings.Replace(teamEntry, "  limits:", "  client: x\n  limits:", 1)),
			"agentarea.yaml:10: defaults take only model, reasoning_effort, reasoning_max_tokens and limits, not 'client'"},
		{"unknown agent field", with(teamFiles(), "agents/lead.md", "---\nname: lead\ntools: [x]\n---\nYou lead.\n"),
			"agents/lead.md:3: unknown agent field 'tools'; agent takes name, display_name, description, model, reasoning_effort, " +
				"reasoning_max_tokens, client, toolsets, skills, mcp, openapi, delegates, limits, builtin_tools, renamed_from"},
		{"agent without name", with(teamFiles(), "agents/lead.md", "---\ndescription: x\n---\nYou lead.\n"),
			"agents/lead.md: front matter must set name, the agent's key"},
		{"duplicate agent", with(teamFiles(), "agents/lead2.md", "---\nname: lead\n---\nAgain.\n"),
			"two agents are named 'lead': agents/lead.md and agents/lead2.md"},
		{"unknown delegate", with(teamFiles(), "agents/lead.md", "---\nname: lead\ndelegates: [editor]\n---\nYou lead.\n"),
			"agents/lead.md: agent 'lead' delegates to 'editor', which is not an agent of this bundle"},
		{"delegate cycle", with(with(teamFiles(), "agents/lead.md", "---\nname: lead\ndelegates: [writer]\n---\nx\n"),
			"agents/writer.md", "---\nname: writer\ndelegates: [lead]\n---\nx\n"),
			"agents/lead.md: agents delegate in a cycle: lead -> writer -> lead"},
		{"workspace subject", with(teamFiles(), "policies/publish-approval.yaml", "name: p\nsubject: workspace\ntarget: spend\neffect: cap\n"),
			"policies/publish-approval.yaml:2: " + policySubjectRefused("p")},
		{"allow effect", with(teamFiles(), "policies/publish-approval.yaml", "name: p\nsubject: writer\ntarget: 'tool:x'\neffect: allow\n"),
			"policies/publish-approval.yaml:4: " + policyEffectRefused("p")},
		{"policy without subject", with(teamFiles(), "policies/publish-approval.yaml", "name: p\ntarget: 'tool:x'\neffect: deny\n"),
			"policies/publish-approval.yaml: policy 'p' needs a subject: an agent key of this bundle, a list of them, or \"*\""},
		{"policy on a stranger", with(teamFiles(), "policies/publish-approval.yaml", "name: p\nsubject: [writer, editor]\ntarget: 'tool:x'\neffect: deny\n"),
			"policies/publish-approval.yaml:2: policy 'p': subject 'editor' is not an agent of this bundle"},
		{"unsupported limit", with(teamFiles(), "agents/lead.md", "---\nname: lead\nlimits: {turn_seconds: 600}\n---\nx\n"),
			"agents/lead.md:3: limits.turn_seconds is not supported yet; the runtime has no per-agent turn_seconds"},
		{"unsupported builtin tool", with(teamFiles(), "agents/lead.md", "---\nname: lead\nbuiltin_tools: {web: false}\n---\nx\n"),
			"agents/lead.md:3: builtin_tools.web is not supported yet; only ask_human_form can be switched off"},
		{"limit not a number", with(teamFiles(), "agents/lead.md", "---\nname: lead\nlimits: {monthly_rub: lots}\n---\nx\n"),
			"agents/lead.md:3: limits.monthly_rub must be a number greater than 0"},
		{"skill without name", with(teamFiles(), "skills/brand-voice/SKILL.md", "---\ndescription: x\n---\nBody\n"),
			"skills/brand-voice/SKILL.md: front matter must set name, the skill's key"},
		{"schedule without agent", with(teamFiles(), "schedules/mwf-posts.md", "---\nname: mwf-posts\ncron: '0 9 * * *'\n---\nGo.\n"),
			"schedules/mwf-posts.md: schedule 'mwf-posts' needs agent, the key of the agent it runs, or task, the saved task it runs"},
		{"claimed twice", entry("channels: {include: ./schedules/*.md}\n"),
			"schedules/mwf-posts.md: selected by both schedules and channels"},
		{"bad include", entry("channels: {include: 3}\n"), "agentarea.yaml:18: channels.include must be a glob or a list of globs"},
		{"escaping glob", entry("channels: {include: ../x/*.yaml}\n"), "agentarea.yaml:18: channels.include '../x/*.yaml' must stay inside the folder"},
		{"both layouts", with(teamFiles(), "agent.yaml", "name: x\n"),
			"agent.yaml and agentarea.yaml are both at the folder root; keep agentarea.yaml and move the agent into agents/"},
		{"bad yaml", with(teamFiles(), "mcp/sheets.yaml", "name: [\n"), "mcp/sheets.yaml: "},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := LoadBundleFolder(c.files)
			if err == nil {
				t.Fatal("loaded")
			}
			var pe *BundleParseError
			if !errors.As(err, &pe) {
				t.Fatalf("err = %T %v", err, err)
			}
			if c.name == "bad yaml" {
				if !strings.HasPrefix(err.Error(), c.want) {
					t.Fatalf("err = %q", err)
				}
				return
			}
			if err.Error() != c.want {
				t.Fatalf("err = %q\nwant  %q", err, c.want)
			}
		})
	}
}

func TestLoadLegacyFolderWarnsDeprecated(t *testing.T) {
	_, issues, err := LoadBundleFolder(StrPairs{{"agent.yaml", "name: a\nmodel: m\n"}, {"instructions.md", "Hi"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 1 || issues[0].Severity != SeverityWarn ||
		issues[0].Message != "agent.yaml: this one-agent layout is deprecated; move to agentarea.yaml with agents/*.md (ADR-0060)" {
		t.Fatalf("issues = %+v", issues)
	}
}

func TestLegacyFolderRefusesWorkspacePolicy(t *testing.T) {
	_, _, err := LoadBundleFolder(StrPairs{{"agent.yaml", "name: a\nmodel: m\n"},
		{"policies/budget.yaml", "subject: workspace\ntarget: spend\neffect: cap\nparams: {amount_usd: 5}\n"}})
	if err == nil || !strings.HasPrefix(err.Error(), "policies/budget.yaml: policy 'budget': subject 'workspace' is refused") {
		t.Fatalf("err = %v", err)
	}
}

func TestGlobMatch(t *testing.T) {
	cases := []struct {
		pattern, path string
		want          bool
	}{
		{"./agents/*.md", "agents/a.md", true},
		{"agents/*.md", "agents/x/a.md", false},
		{"agents/**/*.md", "agents/a.md", true},
		{"agents/**/*.md", "agents/x/y/a.md", true},
		{"**/*.yaml", "a.yaml", true},
		{"**", "a/b/c", true},
		{"agents/a?.md", "agents/ab.md", true},
		{"agents/a.md", "agents/a.md", true},
		{"agents/[a].md", "agents/[a].md", true},
		{"skills/*/", "skills/x", true},
	}
	for _, c := range cases {
		re, err := globRegexp(c.pattern)
		if err != nil {
			t.Fatalf("%s: %v", c.pattern, err)
		}
		if got := re.MatchString(c.path); got != c.want {
			t.Errorf("%s ~ %s = %v", c.pattern, c.path, got)
		}
	}
}

// An agent without a body (or an inline one without instruction) runs on the platform's base prompt.
func TestLoadTeamFolderAgentWithoutInstruction(t *testing.T) {
	for _, files := range []StrPairs{
		{{"agentarea.yaml", "name: a\nschema_version: 1\nagents: {include: ./agents/*.md}\n"}, {"agents/a.md", "---\nname: a\nmodel: m\n---\n"}},
		{{"agentarea.yaml", "name: a\nschema_version: 1\nagents: {include: ./agents/*.md}\n"}, {"agents/a.md", "---\nname: a\nmodel: m\n---"}},
		{{"agentarea.yaml", "name: a\nschema_version: 1\nagents:\n  a: {model: m}\n"}},
	} {
		b, issues, err := LoadBundleFolder(files)
		if err != nil {
			t.Fatal(err)
		}
		if len(b.Agents) != 1 || b.Agents[0].Key != "a" || b.Agents[0].Instruction != "" || len(issues) != 0 {
			t.Fatalf("bundle = %+v, issues %+v", b.Agents, issues)
		}
	}
}

// What `agentarea init` writes loads as is.
func TestLoadInitTemplate(t *testing.T) {
	b, issues, err := LoadBundleFolder(StrPairs{
		{"agentarea.yaml", "name: demo\nschema_version: 1\nsetup:\n  model: {label: Model instance, required: true, help: The model instance the agents run on}\n" +
			"agents: {include: ./agents/*.md}\n"},
		{"agents/demo.md", "---\nname: demo\ndescription: \"\"\nmodel: ${setup.model}\nskills: []\nmcp: []\ndelegates: []\n---\nYou are demo.\n"},
	})
	if err != nil {
		t.Fatal(err)
	}
	a := b.Agents[0]
	if len(issues) != 0 || b.Name != "demo" || len(b.Setup) != 1 || !b.Setup[0].Required || b.Setup[0].Type != SetupString ||
		a.Key != "demo" || *a.Model != "${setup.model}" || a.Instruction != "You are demo." || len(a.Delegates) != 0 {
		t.Fatalf("bundle = %+v, issues %+v", b, issues)
	}
}
