package mcpserver

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// recorder keeps what the last provider call was given.
type recorder struct{ last string }

func (r *recorder) saw(format string, a ...any) { r.last = fmt.Sprintf(format, a...) }

func ptr[T any](v T) *T { return &v }

type fakeAgents struct{ *recorder }

func (f fakeAgents) List(_ context.Context, c authn.Caller, limit, offset int) ([]agentsapi.AgentSummary, error) {
	f.saw("list %s %d %d", c.Workspace.ID(), limit, offset)
	return []agentsapi.AgentSummary{{ID: "a1", Name: "Ann"}}, nil
}
func (f fakeAgents) Get(_ context.Context, _ authn.Caller, id string) (agentsapi.AgentDetail, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return agentsapi.AgentDetail{}, agentsapi.ErrNotFound
	}
	return agentsapi.AgentDetail{ID: id, Name: "Ann", AgentType: "stateless", ReasoningMaxTokens: ptr(512)}, nil
}
func (f fakeAgents) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (agentsapi.AgentRef, error) {
	f.saw("create %s", doc)
	return agentsapi.AgentRef{ID: "a2", Name: "New"}, nil
}
func (f fakeAgents) Update(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (agentsapi.AgentRef, error) {
	f.saw("update %s %s", id, doc)
	return agentsapi.AgentRef{ID: id, Name: "Renamed"}, nil
}
func (f fakeAgents) Archive(_ context.Context, _ authn.Caller, id string) error {
	f.saw("archive %s", id)
	if id == "gone" {
		return agentsapi.ErrNotFound
	}
	return nil
}
func (f fakeAgents) Restore(_ context.Context, _ authn.Caller, id string) error {
	f.saw("restore %s", id)
	return nil
}

type fakeTaskDefs struct{ *recorder }

var defAt = time.Date(2026, 11, 1, 9, 0, 0, 0, time.UTC)

func (f fakeTaskDefs) List(_ context.Context, _ authn.Caller, agentID *string, limit int) ([]agentsapi.TaskDef, error) {
	f.saw("list %v %d", agentID, limit)
	return []agentsapi.TaskDef{{ID: "d1", AgentID: "a1", Parameters: json.RawMessage(`{"k":1}`), UpdatedAt: defAt}}, nil
}
func (f fakeTaskDefs) Get(_ context.Context, _ authn.Caller, id string) (agentsapi.TaskDef, error) {
	f.saw("get %s", id)
	return agentsapi.TaskDef{}, agentsapi.ErrNotFound
}
func (f fakeTaskDefs) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (agentsapi.TaskDef, error) {
	f.saw("create %s", doc)
	return agentsapi.TaskDef{ID: "d2", Name: "Daily", Parameters: json.RawMessage(`{}`), UpdatedAt: defAt}, nil
}
func (f fakeTaskDefs) Run(_ context.Context, _ authn.Caller, id string, params json.RawMessage) (any, error) {
	f.saw("run %s %s", id, params)
	return map[string]any{"id": "r1", "status": "pending", "scheduled_at": nil, "agent_id": "a1"}, nil
}

type fakeClients struct{ *recorder }

func (f fakeClients) List(_ context.Context, _ authn.Caller, limit, offset int) ([]agentsapi.ClientSummary, error) {
	f.saw("list %d %d", limit, offset)
	return []agentsapi.ClientSummary{{ID: "c1", Name: "Desk", Kind: "harness", MCPEndpointURL: "https://api.example/mcp/clients/c1"}}, nil
}
func (f fakeClients) Get(_ context.Context, _ authn.Caller, id string) (json.RawMessage, error) {
	f.saw("get %s", id)
	return json.RawMessage(`{"id":"c1","skills":[]}`), nil
}
func (f fakeClients) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (agentsapi.ClientSummary, error) {
	f.saw("create %s", doc)
	return agentsapi.ClientSummary{ID: "c2", Name: "New", Kind: "harness"}, nil
}
func (f fakeClients) Update(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (agentsapi.ClientSummary, error) {
	f.saw("update %s %s", id, doc)
	return agentsapi.ClientSummary{ID: id}, nil
}
func (f fakeClients) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return true, nil
}
func (f fakeClients) AddSkill(_ context.Context, _ authn.Caller, id, skill string) error {
	f.saw("add_skill %s %s", id, skill)
	return nil
}
func (f fakeClients) RemoveSkill(_ context.Context, _ authn.Caller, id, skill string) error {
	f.saw("remove_skill %s %s", id, skill)
	return nil
}
func (f fakeClients) AddMCPInstance(_ context.Context, _ authn.Caller, id, inst string, prefix *string, allowed []string) error {
	f.saw("add_mcp %s %s %v %v", id, inst, prefix, allowed)
	return nil
}
func (f fakeClients) RemoveMCPInstance(_ context.Context, _ authn.Caller, id, inst string) error {
	f.saw("remove_mcp %s %s", id, inst)
	return nil
}
func (f fakeClients) AddOpenAPIConnection(_ context.Context, _ authn.Caller, id, conn string, prefix *string, allowed []string) error {
	f.saw("add_openapi %s %s %s %v", id, conn, *prefix, allowed)
	return nil
}
func (f fakeClients) RemoveOpenAPIConnection(_ context.Context, _ authn.Caller, id, conn string) error {
	f.saw("remove_openapi %s %s", id, conn)
	return nil
}
func (f fakeClients) AddPlatformToolset(_ context.Context, _ authn.Caller, id, ts string, disabled []string) (string, error) {
	f.saw("add_toolset %s %s %v", id, ts, disabled)
	return "agentarea/" + ts, nil
}
func (f fakeClients) RemovePlatformToolset(_ context.Context, _ authn.Caller, id, ts string) error {
	f.saw("remove_toolset %s %s", id, ts)
	return nil
}

type fakeMembers struct{ *recorder }

func (f fakeMembers) ListMembers(_ context.Context, c authn.Caller) ([]identityapi.Member, error) {
	f.saw("members %s", c.Workspace.ID())
	return []identityapi.Member{{UserID: "u1", IsOwner: true, IsYou: true}}, nil
}
func (f fakeMembers) Invite(_ context.Context, _ authn.Caller, email *string, days *int) (identityapi.CreatedInvitation, error) {
	f.saw("invite %s %v", *email, days)
	return identityapi.CreatedInvitation{Invitation: identityapi.Invitation{ID: "i1", Email: email, Status: "pending"}, Token: "tok", EmailDelivery: "sent"}, nil
}
func (f fakeMembers) ListInvitations(context.Context, authn.Caller) ([]identityapi.Invitation, error) {
	f.saw("invitations")
	return []identityapi.Invitation{{ID: "i1"}}, nil
}
func (f fakeMembers) RevokeInvitation(_ context.Context, _ authn.Caller, id string) error {
	f.saw("revoke %s", id)
	return nil
}
func (f fakeMembers) RemoveMember(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("remove %s", id)
	return false, nil
}
func (f fakeMembers) ListWorkspaces(_ context.Context, p authn.Principal) ([]identityapi.Workspace, error) {
	f.saw("workspaces %s", p.UserID)
	return []identityapi.Workspace{{ID: wsID, Slug: "acme", Name: "Acme"}, {ID: "w2", Slug: "beta", Name: "Beta"}}, nil
}
func (f fakeMembers) CreateWorkspace(_ context.Context, p authn.Principal, name string) (identityapi.Workspace, error) {
	f.saw("create %s %q", p.UserID, name)
	return identityapi.Workspace{ID: "w3", Slug: "new", Name: name, CanAdminister: true}, nil
}
func (f fakeMembers) SetLogo(context.Context, authn.Caller, []byte) (identityapi.Workspace, error) {
	f.saw("set_logo")
	return identityapi.Workspace{}, nil
}
func (f fakeMembers) RemoveLogo(_ context.Context, c authn.Caller) (identityapi.Workspace, error) {
	f.saw("remove_logo %s %v", c.Workspace.ID(), c.AccessibleWorkspaces)
	return identityapi.Workspace{ID: wsID, Slug: "acme", Name: "Acme"}, nil
}

type fakeSkills struct {
	*recorder
	pkg  string
	repo []byte
}

func (f fakeSkills) List(context.Context, authn.Caller) ([]agentsapi.SkillSummary, error) {
	f.saw("list")
	return []agentsapi.SkillSummary{{ID: "s1", Name: "triage", SourceType: "content"}}, nil
}
func (f fakeSkills) Get(_ context.Context, _ authn.Caller, id string) (agentsapi.SkillDetail, error) {
	if id == "gone" {
		return agentsapi.SkillDetail{}, agentsapi.ErrSkillNotFound
	}
	return agentsapi.SkillDetail{SkillSummary: agentsapi.SkillSummary{ID: id, Name: "triage", SourceType: "zip", Package: f.pkg}, Content: "# T"}, nil
}
func (f fakeSkills) CreateFromFiles(_ context.Context, _ authn.Caller, files []agentsapi.SkillFileText, in agentsapi.SkillCreate) (agentsapi.SkillSummary, error) {
	f.saw("files %v %v %v", files, in.Name, *in.Description)
	return agentsapi.SkillSummary{ID: "s2", Name: "made", SourceType: "zip"}, nil
}
func (f fakeSkills) CreateFromArchive(_ context.Context, _ authn.Caller, z []byte, in agentsapi.SkillCreate) (agentsapi.SkillSummary, error) {
	zr, err := zip.NewReader(bytes.NewReader(z), int64(len(z)))
	if err != nil {
		return agentsapi.SkillSummary{}, err
	}
	var names []string
	for _, e := range zr.File {
		names = append(names, e.Name)
	}
	src := ""
	if in.SourceURL != nil {
		src = *in.SourceURL
	}
	f.last += fmt.Sprintf("archive %v %v src=%s;", names, in.Name, src)
	return agentsapi.SkillSummary{ID: "s3", Name: "imported", SourceType: "zip"}, nil
}
func (f fakeSkills) DownloadGitHubRepo(_ context.Context, _ authn.Caller, u string) ([]byte, error) {
	f.last = "download " + u + ";"
	return f.repo, nil
}
func (f fakeSkills) ExtractGitHubPackage(repoZip []byte, pkg string) ([]byte, error) {
	zr, err := zip.NewReader(bytes.NewReader(repoZip), int64(len(repoZip)))
	if err != nil {
		return nil, err
	}
	files := map[string]string{}
	for _, e := range zr.File {
		_, rel, _ := strings.Cut(e.Name, "/")
		if inner, ok := strings.CutPrefix(rel, pkg+"/"); ok || pkg == "" {
			if pkg == "" {
				inner = rel
			}
			files[inner] = "x"
		}
	}
	return zipOf(files), nil
}
func (f fakeSkills) EditMetadata(_ context.Context, _ authn.Caller, id string, name, desc *string) (agentsapi.SkillSummary, error) {
	f.saw("meta %s %v %v", id, *name, desc)
	return agentsapi.SkillSummary{ID: id, Name: *name}, nil
}
func (f fakeSkills) SetContent(_ context.Context, _ authn.Caller, id, content string) (agentsapi.SkillSummary, error) {
	f.saw("content %s %q", id, content)
	return agentsapi.SkillSummary{ID: id}, nil
}
func (f fakeSkills) ReplaceFiles(_ context.Context, _ authn.Caller, id string, files []agentsapi.SkillFileText) (agentsapi.SkillSummary, error) {
	f.saw("replace %s %d", id, len(files))
	return agentsapi.SkillSummary{ID: id}, nil
}
func (f fakeSkills) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return true, nil
}
func (f fakeSkills) ListFiles(_ context.Context, _ authn.Caller, id string, urls bool) ([]agentsapi.SkillFileEntry, error) {
	f.saw("files %s %v", id, urls)
	return []agentsapi.SkillFileEntry{{Path: "SKILL.md", Size: 3, URL: ptr("https://s3/x")}, {Path: "a.py", Size: 1}}, nil
}
func (f fakeSkills) FileURL(_ context.Context, _ authn.Caller, id, p string, exp int) (string, error) {
	f.saw("url %s %s %d", id, p, exp)
	return "https://s3/" + p, nil
}
func (f fakeSkills) FileContent(_ context.Context, _ authn.Caller, id, p string) ([]byte, error) {
	f.saw("read %s %s", id, p)
	if p == "bin" {
		return []byte{0xff, 0xfe}, nil
	}
	return []byte("hello"), nil
}

func zipOf(files map[string]string) []byte {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, name := range slices.Sorted(maps.Keys(files)) {
		w, _ := zw.Create(name)
		_, _ = w.Write([]byte(files[name]))
	}
	_ = zw.Close()
	return buf.Bytes()
}

type toolCase struct {
	tool, args string
	// want is what the provider saw ("" skips the check).
	want string
	// out is a substring of the JSON result text; isError marks a refusal.
	out     string
	isError bool
}

func runToolCases(t *testing.T, ts mcpserve.Toolset, rec *recorder, cases []toolCase) {
	t.Helper()
	c, err := gate().EnterWorkspace(context.Background(), authn.Principal{UserID: "u1"}, "acme")
	if err != nil {
		t.Fatal(err)
	}
	ctx := authn.WithCaller(context.Background(), c)
	served := map[string]bool{}
	tools, _ := ts.Tools(ctx, c.Principal)
	for _, tool := range tools {
		served[tool.Name] = true
	}
	for _, tc := range cases {
		rec.last = ""
		if !served[tc.tool] {
			t.Fatalf("%s is not served", tc.tool)
		}
		res, err := ts.Call(ctx, c.Principal, tc.tool, json.RawMessage(tc.args))
		text := ""
		if err != nil {
			text = err.Error()
		} else {
			text = res.Content[0].Text
		}
		if (err != nil) != tc.isError {
			t.Fatalf("%s: err=%v text=%s", tc.tool, err, text)
		}
		if tc.want != "" && rec.last != tc.want {
			t.Fatalf("%s: provider saw %q, want %q", tc.tool, rec.last, tc.want)
		}
		if !strings.Contains(text, tc.out) {
			t.Fatalf("%s: result %s lacks %s", tc.tool, text, tc.out)
		}
		if err == nil {
			if _, ok := res.StructuredContent.(map[string]any); !ok {
				t.Fatalf("%s: structured content %T", tc.tool, res.StructuredContent)
			}
		}
	}
}

func toolsetNamed(t *testing.T, p Providers, name string) mcpserve.Toolset {
	t.Helper()
	all, err := p.Toolsets("https://api.example/")
	if err != nil {
		t.Fatal(err)
	}
	for _, ts := range all {
		if ts.Name() == name {
			return ts
		}
	}
	t.Fatalf("no toolset %s", name)
	return nil
}

func TestAgentsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Agents: fakeAgents{rec}}, "agents")
	runToolCases(t, ts, rec, []toolCase{
		{"agents_list", `{}`, "list " + wsID + " 50 0", `[{"description":null,"id":"a1","name":"Ann"}]`, false},
		{"agents_list", `{"limit":5,"offset":10}`, "list " + wsID + " 5 10", `"a1"`, false},
		{"agents_list", `{"limit":5000}`, "list " + wsID + " 1000 0", `"a1"`, false},
		{"agents_list", `{"limit":-1}`, "list " + wsID + " 1 0", `"a1"`, false},
		{"agents_get", `{"agent_id":"a1"}`, "get a1", `"reasoning_max_tokens":512`, false},
		{"agents_get", `{"agent_id":"gone"}`, "", "Agent not found", true},
		{"agents_create", `{"name":"New","model_id":null,"tools":[],"reasoning_effort":null}`, `create {"model_id":null,"name":"New","tools":[]}`, `{"id":"a2","name":"New"}`, false},
		{"agents_update", `{"agent_id":"a1","name":"Renamed","model_id":null,"client_id":null}`, `update a1 {"client_id":null,"name":"Renamed"}`, `"Renamed"`, false},
		{"agents_archive", `{"agent_id":"gone"}`, "archive gone", `{"archived":false}`, false},
		{"agents_restore", `{"agent_id":"a1"}`, "restore a1", `{"restored":true}`, false},
	})
}

func TestTaskDefinitionsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{TaskDefs: fakeTaskDefs{rec}}, "task_definitions")
	runToolCases(t, ts, rec, []toolCase{
		{"task_definitions_list", `{}`, "list <nil> 100", `"parameters":{"k":1}`, false},
		{"task_definitions_list", `{"limit":0}`, "", "limit must be between 1 and 1000", true},
		{"task_definitions_get", `{"definition_id":"d9"}`, "get d9", "Task definition d9 not found", true},
		{"task_definitions_create", `{"name":"Daily","agent_id":"a1","description":"do it"}`, `create {"agent_id":"a1","description":"do it","name":"Daily","parameters":{}}`, `"updated_at":"2026-11-01T09:00:00Z"`, false},
		{"task_definitions_run", `{"definition_id":"d1","parameters":{"x":2}}`, `run d1 {"x":2}`, `{"run_id":"r1","scheduled_at":null,"status":"pending"}`, false},
	})
}

func TestClientsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Clients: fakeClients{rec}}, "clients")
	runToolCases(t, ts, rec, []toolCase{
		{"clients_list", `{}`, "list 100 0", `"mcp_endpoint_url":"https://api.example/mcp/clients/c1"`, false},
		{"clients_list", `{"limit":5000}`, "list 1000 0", `"c1"`, false},
		{"clients_get", `{"client_id":"c1"}`, "get c1", `{"id":"c1","skills":[]}`, false},
		{"clients_create", `{"name":"New"}`, `create {"description":null,"kind":"harness","name":"New"}`, `"id":"c2"`, false},
		{"clients_update", `{"client_id":"c1","name":null,"default_model":null,"sandbox":true}`, `update c1 {"default_model":null,"sandbox":true}`, `"id":"c1"`, false},
		{"clients_delete", `{"client_id":"c1"}`, "delete c1", `{"deleted":true}`, false},
		{"clients_add_skill", `{"client_id":"c1","skill_id":"s1"}`, "add_skill c1 s1", `{"added":true}`, false},
		{"clients_remove_skill", `{"client_id":"c1","skill_id":"s1"}`, "remove_skill c1 s1", `{"removed":true}`, false},
		{"clients_add_mcp_instance", `{"client_id":"c1","mcp_instance_id":"m1"}`, "add_mcp c1 m1 <nil> []", `{"added":true}`, false},
		{"clients_remove_mcp_instance", `{"client_id":"c1","mcp_instance_id":"m1"}`, "remove_mcp c1 m1", `{"removed":true}`, false},
		{"clients_add_openapi_connection", `{"client_id":"c1","openapi_connection_id":"o1","namespace_prefix":"crm","allowed_tools":["a"]}`, "add_openapi c1 o1 crm [a]", `{"added":true}`, false},
		{"clients_remove_openapi_connection", `{"client_id":"c1","openapi_connection_id":"o1"}`, "remove_openapi c1 o1", `{"removed":true}`, false},
		{"clients_add_platform_toolset", `{"client_id":"c1","toolset":"runs","disabled_methods":["cancel"]}`, "add_toolset c1 runs [cancel]", `{"added":"agentarea/runs"}`, false},
		{"clients_remove_platform_toolset", `{"client_id":"c1","toolset":"agentarea/runs"}`, "remove_toolset c1 agentarea/runs", `{"removed":true}`, false},
	})
}

func TestMembersToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Members: fakeMembers{rec}}, "members")
	runToolCases(t, ts, rec, []toolCase{
		{"members_list", `{}`, "members " + wsID, `"is_owner":true,"is_you":true`, false},
		{"members_invite", `{"email":"a@b.c"}`, "invite a@b.c <nil>", `"email_delivery":"sent"`, false},
		{"members_list_invitations", `{}`, "invitations", `"id":"i1"`, false},
		{"members_revoke_invitation", `{"invitation_id":"i1"}`, "revoke i1", `{"revoked":true}`, false},
		{"members_remove", `{"user_id":"u2"}`, "remove u2", `"status":"revocation_pending"`, false},
	})
}

func TestWorkspacesToolsetActsOnNoWorkspace(t *testing.T) {
	rec := &recorder{}
	p := Providers{Members: fakeMembers{rec}}
	ts := toolsetNamed(t, p, "workspaces")
	if u, ok := ts.(Unscoped); !ok || !u.Unscoped() {
		t.Fatal("workspaces is workspace-scoped")
	}
	all, _ := p.Toolsets("https://api.example/")
	pinned := NewPlatform(false, Info{}, Auth{}, nil)
	pinned.Register(all...)
	if got := strings.Join(pinned.Toolsets(), ","); got != "members" {
		t.Fatalf("pinned serves %s", got)
	}

	prin := authn.Principal{UserID: "u1", AccessibleWorkspaces: []string{"w2"}}
	call := func(tool, args string) (mcpserve.Result, error) {
		return ts.Call(context.Background(), prin, tool, json.RawMessage(args))
	}
	res, err := call("workspaces_list", `{"query":" BET"}`)
	if err != nil || !strings.Contains(res.Content[0].Text, `"mcp_url":"https://api.example/mcp/w/beta"`) || strings.Contains(res.Content[0].Text, "acme") {
		t.Fatalf("list: %v %v", res, err)
	}
	if _, err := call("workspaces_create", `{"name":"  Team "}`); err != nil || rec.last != `create u1 "Team"` {
		t.Fatalf("create: %v %q", err, rec.last)
	}
	if _, err := call("workspaces_create", `{"name":"  "}`); err == nil || err.Error() != "Workspace name must not be empty" {
		t.Fatalf("empty name: %v", err)
	}
	if _, err := call("workspaces_update", `{"workspace":"acme","clear_logo":true}`); err != nil || rec.last != "remove_logo "+wsID+" [w2 "+wsID+"]" {
		t.Fatalf("clear logo: %v %q", err, rec.last)
	}
	for args, want := range map[string]string{
		`{"workspace":"acme"}`: "Nothing to update: pass logo_path or clear_logo",
		`{"workspace":"acme","logo_path":"a.png","clear_logo":true}`: "Pass either logo_path or clear_logo, not both",
		`{"workspace":"zed","clear_logo":true}`:                      "No accessible workspace 'zed'",
	} {
		if _, err := call("workspaces_update", args); err == nil || err.Error() != want {
			t.Fatalf("%s: %v", args, err)
		}
	}
}

func TestSkillsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Skills: fakeSkills{recorder: rec}}, "skills")
	runToolCases(t, ts, rec, []toolCase{
		{"skills_list", `{}`, "list", `"source_type":"content"`, false},
		{"skills_get", `{"skill_id":"gone"}`, "", "Skill not found", true},
		{"skills_get", `{"skill_id":"s1"}`, "", `"content":"# T"`, false},
		{"skills_create", `{"files":{"/SKILL.md":"# A","b/c.py":"x"},"description":"d"}`, "files [{SKILL.md # A} {b/c.py x}] <nil> d", `"file_count":2`, false},
		{"skills_create", `{"files":{"a.py":"x"}}`, "", "files must include a SKILL.md at the root", true},
		{"skills_create", `{"files":{}}`, "", "files must be a non-empty {path: text} map", true},
		{"skills_create_from_archive", `{"zip_base64":"!!"}`, "", "Invalid base64", true},
		{"skills_edit_metadata", `{"skill_id":"s1","name":"n"}`, "meta s1 n <nil>", `{"description":null,"id":"s1","name":"n"}`, false},
		{"skills_edit_content", `{"skill_id":"s1","files":{"SKILL.md":"# new"}}`, `content s1 "# new"`, `"mode":"content"`, false},
		{"skills_edit_content", `{"skill_id":"s1","files":{"SKILL.md":"#","x.py":""}}`, "", "Skill is content-mode", true},
		{"skills_delete", `{"skill_id":"s1"}`, "delete s1", `{"deleted":true}`, false},
		{"skills_list_files", `{"skill_id":"s1","include_urls":true}`, "files s1 true", `[{"path":"SKILL.md","size":3,"url":"https://s3/x"},{"path":"a.py","size":1}]`, false},
		{"skills_get_file", `{"skill_id":"s1","path":"a.py","as_url":true}`, "url s1 a.py 3600", `"expires_in":3600`, false},
		{"skills_get_file", `{"skill_id":"s1","path":"a.py","as_url":true,"expires_in":999999999}`, "url s1 a.py 86400", `"expires_in":86400`, false},
		{"skills_get_file", `{"skill_id":"s1","path":"a.py","as_url":true,"expires_in":1}`, "url s1 a.py 60", `"expires_in":60`, false},
		{"skills_get_file", `{"skill_id":"s1","path":"a.py"}`, "read s1 a.py", `{"content":"hello","path":"a.py"}`, false},
		{"skills_get_file", `{"skill_id":"s1","path":"bin"}`, "", `binary file; retry with as_url=true`, true},
	})

	pkgRec := &recorder{}
	pkg := toolsetNamed(t, Providers{Skills: fakeSkills{recorder: pkgRec, pkg: "skills/s1"}}, "skills")
	runToolCases(t, pkg, pkgRec, []toolCase{
		{"skills_edit_content", `{"skill_id":"s1","files":{"z.py":"","SKILL.md":"#"}}`, "replace s1 2", `"files_written":["SKILL.md","z.py"]`, false},
	})
}

func TestSkillsImportFromGitHub(t *testing.T) {
	repo := zipOf(map[string]string{
		"acme-kit-abc123/README.md":         "x",
		"acme-kit-abc123/skills/a/SKILL.md": "---\nname: alpha\ndescription: \"First\"\n---\nbody",
		"acme-kit-abc123/skills/a/run.py":   "x",
		"acme-kit-abc123/skills/b/SKILL.md": "no frontmatter",
		"acme-kit-abc123/other/SKILL.md":    "---\nname: other\n---\n",
	})
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Skills: fakeSkills{recorder: rec, repo: repo}}, "skills")
	c, _ := gate().EnterWorkspace(context.Background(), authn.Principal{UserID: "u1"}, "acme")
	ctx := authn.WithCaller(context.Background(), c)
	call := func(args string) (string, error) {
		res, err := ts.Call(ctx, c.Principal, "skills_import_from_github", json.RawMessage(args))
		if err != nil {
			return "", err
		}
		return res.Content[0].Text, nil
	}

	_, err := call(`{"github_url":"https://github.com/acme/kit/tree/main/skills"}`)
	var payload map[string]any
	if err == nil || json.Unmarshal([]byte(err.Error()), &payload) != nil || payload["code"] != "multiple_skills_found" {
		t.Fatalf("multiple: %v", err)
	}
	if cands := payload["candidates"].([]any); len(cands) != 2 || cands[0].(map[string]any)["raw_url"] != "https://raw.githubusercontent.com/acme/kit/main/skills/a/SKILL.md" {
		t.Fatalf("candidates: %v", payload["candidates"])
	}

	out, err := call(`{"github_url":"https://github.com/acme/kit/tree/main/skills","skill_name":"alpha","name":"Renamed"}`)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(rec.last, "archive [SKILL.md run.py]") || !strings.Contains(rec.last, "src=https://github.com/acme/kit/tree/main/skills") {
		t.Fatalf("provider saw %q", rec.last)
	}
	if !strings.Contains(out, `"package_path":"skills/a"`) || !strings.Contains(out, `"resolved_source_url":"https://raw.githubusercontent.com/acme/kit/main/skills/a/SKILL.md"`) {
		t.Fatalf("single import: %s", out)
	}

	out, err = call(`{"github_url":"https://github.com/acme/kit","import_all":true}`)
	if err != nil || !strings.Contains(out, `"count":3`) || !strings.Contains(out, "/acme/kit/abc123/other/SKILL.md") {
		t.Fatalf("import all: %s %v", out, err)
	}

	if _, err := call(`{"github_url":"https://gitlab.com/acme/kit"}`); err == nil || err.Error() != "Not a GitHub URL: https://gitlab.com/acme/kit" {
		t.Fatalf("not github: %v", err)
	}
}

func TestContractToolsCarryTitlesAndHints(t *testing.T) {
	ts := toolsetNamed(t, Providers{Clients: fakeClients{&recorder{}}}, "clients")
	tools, _ := ts.Tools(context.Background(), authn.Principal{})
	if len(tools) != 13 {
		t.Fatalf("clients tools = %d", len(tools))
	}
	byName := map[string]mcpserve.Tool{}
	for _, tool := range tools {
		byName[tool.Name] = tool
	}
	del := byName["clients_delete"]
	if del.Title != "Delete client" || del.Annotations["destructiveHint"] != true || del.Annotations["idempotentHint"] != true || del.Annotations["openWorldHint"] != false {
		t.Fatalf("clients_delete = %+v", del)
	}
	list := byName["clients_list"]
	if list.Annotations["readOnlyHint"] != true {
		t.Fatalf("clients_list = %+v", list)
	}
	if _, has := list.Annotations["destructiveHint"]; has {
		t.Fatalf("read tool carries destructiveHint")
	}
	if strings.Contains(string(list.InputSchema), `"workspace"`) {
		t.Fatalf("pinned contract schema has the workspace argument: %s", list.InputSchema)
	}
}

type fakeFiles struct {
	sandboxapi.Files
	sizes map[string]int64
}

func (f fakeFiles) Head(_ context.Context, ws scope.Workspace, p string) (sandboxapi.ObjectHead, bool, error) {
	if ws.ID() != wsID {
		return sandboxapi.ObjectHead{}, false, fmt.Errorf("wrong workspace %s", ws.ID())
	}
	size, ok := f.sizes[p]
	return sandboxapi.ObjectHead{Size: size}, ok, nil
}

func (f fakeFiles) Get(_ context.Context, _ scope.Workspace, p string) (sandboxapi.File, error) {
	return sandboxapi.File{Data: []byte("png:" + p)}, nil
}

func TestWorkspacesUpdateSetsLogoFromAFile(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Members: logoMembers{fakeMembers{rec}}, Files: fakeFiles{sizes: map[string]int64{"logo.png": 10, "big.png": 2 << 20}}}, "workspaces")
	prin := authn.Principal{UserID: "u1"}
	call := func(args string) error {
		_, err := ts.Call(context.Background(), prin, "workspaces_update", json.RawMessage(args))
		return err
	}
	if err := call(`{"workspace":"acme","logo_path":"logo.png"}`); err != nil || rec.last != "set_logo "+wsID+" png:logo.png" {
		t.Fatalf("set: %v %q", err, rec.last)
	}
	for args, want := range map[string]string{
		`{"workspace":"acme","logo_path":"none.png"}`: "File not found",
		`{"workspace":"acme","logo_path":"big.png"}`:  "Logo exceeds the 1048576-byte limit",
	} {
		if err := call(args); err == nil || err.Error() != want {
			t.Fatalf("%s: %v", args, err)
		}
	}
	noFiles := toolsetNamed(t, Providers{Members: fakeMembers{rec}}, "workspaces")
	if _, err := noFiles.Call(context.Background(), prin, "workspaces_update", json.RawMessage(`{"workspace":"acme","logo_path":"logo.png"}`)); err == nil {
		t.Fatal("logo_path served without a file store")
	}
}

type logoMembers struct{ fakeMembers }

func (m logoMembers) SetLogo(_ context.Context, c authn.Caller, data []byte) (identityapi.Workspace, error) {
	m.saw("set_logo %s %s", c.Workspace.ID(), data)
	return identityapi.Workspace{ID: wsID, Slug: "acme"}, nil
}
