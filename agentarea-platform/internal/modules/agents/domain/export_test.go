package domain

import (
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

func TestExportBundleKey(t *testing.T) {
	cases := [][4]string{
		{"agent", "Test Agent", "a1b2-C3", "agent_test_agent_a1b2c3"},
		{"skill", "!!!", "", "skill_resource"},
		{"mcp", "  My--MCP  ", "x", "mcp_my_mcp_x"},
		{"agent", strings.Repeat("ab_", 30), "1", "agent_" + strings.TrimRight(strings.Repeat("ab_", 30)[:64], "_") + "_1"},
	}
	for _, c := range cases {
		if got := ExportBundleKey(c[0], c[1], c[2]); got != c[3] {
			t.Errorf("ExportBundleKey(%q,%q,%q) = %q, want %q", c[0], c[1], c[2], got, c[3])
		}
	}
	if got := ExportSetupKey("--"); got != "setup_value" {
		t.Errorf("ExportSetupKey = %q", got)
	}
}

func TestExportCredentialNames(t *testing.T) {
	for name, want := range map[string]bool{
		"SERVICE_TOKEN": true, "--api-key": true, "PGPASSWORD": true, "key": true, "Code": true,
		"x-signature": true, "MODE": false, "ROOT": false, "keyboard": false, "--read-only": false,
	} {
		if got := ExportIsCredentialName(name); got != want {
			t.Errorf("ExportIsCredentialName(%q) = %v", name, got)
		}
	}
}

func TestExportURLCarriesCredentials(t *testing.T) {
	for u, want := range map[string]bool{
		"https://mcp.example.test/sse?api_key=CANARY":                       true,
		"https://user:CANARY@mcp.example.test/sse":                          true,
		"https://user:@h.test/":                                             true,
		"https://user@h.test/":                                              false,
		"https://mcp.example.test/api/mcp/s/CANARYx9aB3cD4eF5gH6iJ7kL8/mcp": true,
		"https://mcp.example.test/mcp?format=json":                          false,
		"https://mcp.example.test/mcp?token=":                               false,
		"https://mcp.example.test/mcp?to%6Ben=x":                            true,
		"https://[::1/x":                                                    true,
		"https://[::1]:80/x":                                                false,
		"https://[1.2.3.4]/x":                                               true,
		"https://docs.example.test/schema.json":                             false,
		"https://h.test/" + strings.Repeat("a", 30):                         false,
	} {
		if got := ExportURLCarriesCredentials(u); got != want {
			t.Errorf("ExportURLCarriesCredentials(%q) = %v", u, got)
		}
	}
}

func TestExportBundleScreensMCPCredentials(t *testing.T) {
	inst := ExportMCP{ID: "a1b2c3d4-e5f6-789a-bcde-123456789abc", Name: "Postgres", EnvVars: []string{"PGPASSWORD"}, Spec: YAMLMap{
		{"type", "command"}, {"command", "npx"},
		{"args", []any{
			"-y", "@modelcontextprotocol/server-postgres", "postgresql://app:CANARY_URL@db.internal:5432/app",
			"--api-key=CANARY_FLAG", "--token", "CANARY_NEXT", "--header", "Authorization: Bearer CANARY_HEADER",
			"--read-only", "https://docs.example.test/schema.json",
		}},
		{"environment", YAMLMap{{"MODE", "readonly"}, {"ROOT", "/data"}, {"SERVICE_TOKEN", "CANARY_ENV_NAME"},
			{"UPSTREAM", "https://user:CANARY_ENV_URL@upstream.test"}}},
		{"env_vars", []any{"PGPASSWORD"}},
	}}
	b, err := ExportBundle(ExportInput{WorkspaceSlug: "ws", WorkspaceName: "W", MCPs: []ExportMCP{inst}}, func(string, ...any) {})
	if err != nil {
		t.Fatal(err)
	}
	text := SafeDumpYAML(b)
	if strings.Contains(text, "CANARY") {
		t.Fatalf("credential leaked:\n%s", text)
	}
	mcps, _ := yamlGet(b, "mcps")
	m := mcps.([]any)[0].(YAMLMap)
	spec, _ := yamlGet(m, "json_spec")
	args, _ := yamlGet(spec.(YAMLMap), "args")
	a := args.([]any)
	k := "mcp_postgres_a1b2c3d4e5f6789abcde123456789abc"
	want := []any{"-y", "@modelcontextprotocol/server-postgres", "${setup.setup_" + k + "_arg_2}",
		"--api-key=${setup.setup_" + k + "_arg_3}", "--token", "${setup.setup_" + k + "_arg_5}", "--header",
		"Authorization: ${setup.setup_" + k + "_arg_7}", "--read-only", "https://docs.example.test/schema.json"}
	for i := range want {
		if a[i] != want[i] {
			t.Errorf("args[%d] = %v, want %v", i, a[i], want[i])
		}
	}
	env, _ := yamlGet(spec.(YAMLMap), "environment")
	if SafeDumpYAML(env) != "MODE: readonly\nROOT: /data\n" {
		t.Errorf("environment = %q", SafeDumpYAML(env))
	}
	if _, ok := yamlGet(spec.(YAMLMap), "env_vars"); ok {
		t.Error("env_vars is not a transport field")
	}
	bindings, _ := yamlGet(m, "bindings")
	var names []string
	for _, it := range bindings.(YAMLMap) {
		names = append(names, it.Key)
	}
	if strings.Join(names, ",") != "PGPASSWORD,SERVICE_TOKEN,UPSTREAM" {
		t.Errorf("bindings = %v", names)
	}
	setup, _ := yamlGet(b, "setup")
	if n := len(setup.([]any)); n != 7 {
		t.Errorf("setup fields = %d, want 7", n)
	}
}

func TestExportBundleSecretReferenceAndContextSecret(t *testing.T) {
	b, err := ExportBundle(ExportInput{WorkspaceSlug: "ws", MCPs: []ExportMCP{{ID: "1", Name: "GitHub", ContextSigning: true, Spec: YAMLMap{
		{"type", "url"}, {"endpoint_url", "https://api.example.test/mcp"},
		{"headers", YAMLMap{{"Authorization", YAMLMap{{"secret_name", "gh-token"}}}}},
	}}}}, func(string, ...any) {})
	if err != nil {
		t.Fatal(err)
	}
	mcps, _ := yamlGet(b, "mcps")
	want := "- key: mcp_github_1\n  name: GitHub\n  json_spec:\n    type: url\n    endpoint_url: https://api.example.test/mcp\n" +
		"  bindings:\n    Authorization: ${secret.gh-token}\n  context_secret: ${setup.setup_mcp_github_1_context_secret}\n"
	if got := SafeDumpYAML(mcps); got != want {
		t.Fatalf("got:\n%s\nwant:\n%s", got, want)
	}
}

func TestExportBundleErrors(t *testing.T) {
	noop := func(string, ...any) {}
	cases := []struct {
		in   ExportInput
		want string
	}{
		{ExportInput{Agents: []ExportAgent{{ID: "a", Name: "Agent", Tools: []ExportTool{{Type: "mcp", Name: "deleted-connection", HasName: true}}}}},
			"MCP 'deleted-connection' attached to agent 'Agent' could not be exported: it is not an MCP connection of this workspace"},
		{ExportInput{Agents: []ExportAgent{{ID: "a", Name: "Agent", Skills: []ExportAgentSkill{{ID: "s", Name: "Gone"}}}}},
			"Skill 'Gone' attached to agent 'Agent' could not be exported"},
		{ExportInput{MCPs: []ExportMCP{{ID: "m", Name: "Odd", Spec: YAMLMap{{"type", "stdio"}}}}},
			"MCP instance 'Odd' uses unsupported transport 'stdio'"},
		{ExportInput{MCPs: []ExportMCP{{ID: "m", Name: "Odd", Spec: YAMLMap{}}}},
			"MCP instance 'Odd' uses unsupported transport 'None'"},
		{ExportInput{Skills: []ExportSkill{{ID: "s", Name: "Empty"}}},
			"skill 'skill_empty_s' is source_type=content but has no content"},
	}
	for _, c := range cases {
		_, err := ExportBundle(c.in, noop)
		var inv *api.ExportInvalidError
		if !errors.As(err, &inv) || inv.Msg != c.want {
			t.Errorf("err = %v, want %q", err, c.want)
		}
	}
}

func TestExportBundleBuiltinMCPIsSkipped(t *testing.T) {
	b, err := ExportBundle(ExportInput{
		MCPs:   []ExportMCP{{ID: "m", Name: "Platform Search", Builtin: true, EnvVars: []string{"AGENTAREA_PLATFORM_TOKEN"}}},
		Agents: []ExportAgent{{ID: "a", Name: "Agent", Tools: []ExportTool{{Type: "mcp", Name: "Platform Search", HasName: true}}}},
	}, func(string, ...any) {})
	if err != nil {
		t.Fatal(err)
	}
	if text := SafeDumpYAML(b); strings.Contains(text, "AGENTAREA_PLATFORM_TOKEN") || !strings.Contains(text, "mcps: []") {
		t.Fatalf("builtin MCP exported:\n%s", text)
	}
}

func TestExportBundleGolden(t *testing.T) {
	const agentID, skillID, triggerID = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"
	var warned []string
	warn := func(msg string, args ...any) { warned = append(warned, msg) }
	b, err := ExportBundle(ExportInput{
		WorkspaceID: "w", WorkspaceSlug: "ws", WorkspaceName: "Test Workspace",
		Skills: []ExportSkill{{ID: skillID, Name: "S", SourceType: "content", Content: "# S\nbody"}},
		Agents: []ExportAgent{{ID: agentID, Name: "Test Agent", Instruction: "Do it",
			Tools:  []ExportTool{{Type: "code", Name: "agentarea/math", HasName: true}, {Type: "code", Name: "agentarea/math", HasName: true}},
			Skills: []ExportAgentSkill{{ID: skillID, Name: "S"}}}},
		Triggers: []ExportTrigger{
			{ID: triggerID, Name: "Daily", Kind: "cron", AgentID: agentID, Text: "Report", Cron: "0 9 * * *", Timezone: "UTC", Enabled: true},
			{ID: "t2", Name: "Stream", Kind: "stream", AgentID: agentID, Text: "x"},
			{ID: "t3", Name: "Blank", Kind: "cron", AgentID: agentID, Text: "  "},
			{ID: "t4", Name: "Other", Kind: "cron", AgentID: "elsewhere", Text: "x"},
			{ID: "t5", Name: "Cond", Kind: "cron", AgentID: agentID, Text: "x", HasConditions: true},
		},
	}, warn)
	if err != nil {
		t.Fatal(err)
	}
	const a = "agent_test_agent_11111111111111111111111111111111"
	want := `schema_version: 0.1.0
name: ws
display_name: Test Workspace
description: ''
metadata:
  capabilities: []
setup:
- key: setup_model_` + a + `
  label: Model for Test Agent
  type: string
  required: true
  help: Choose a model available in the destination workspace.
mcps: []
skills:
- key: skill_s_22222222222222222222222222222222
  name: S
  source_type: content
  content: '# S

    body'
agents:
- key: ` + a + `
  name: Test Agent
  description: ''
  instruction: Do it
  model: ${setup.setup_model_` + a + `}
  mcps: []
  skills:
  - skill_s_22222222222222222222222222222222
  toolsets:
  - agentarea/math
channels: []
automations:
- key: automation_daily_33333333333333333333333333333333
  type: cron
  cron: 0 9 * * *
  timezone: UTC
  agent: ` + a + `
  prompt: Report
  enabled: true
policies: []
`
	if got := SafeDumpYAML(b); got != want {
		t.Fatalf("got:\n%s\nwant:\n%s", got, want)
	}
	if len(warned) != 4 {
		t.Errorf("warnings = %v", warned)
	}
}

func TestExportTemplateArgsHeaderAndFlags(t *testing.T) {
	ref := func(field, what string) string { return "${setup." + field + "}" }
	got := ExportTemplateArgs([]any{"X-Org: acme", "Cookie: a", "--password", "--x", "--flag=plain", YAMLInt("3"), "--secret", "v"}, "m", ref)
	want := []any{"X-Org: acme", "Cookie: ${setup.m_arg_1}", "--password", "--x", "--flag=plain", YAMLInt("3"), "--secret", "${setup.m_arg_7}"}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d] = %v, want %v", i, got[i], want[i])
		}
	}
}
