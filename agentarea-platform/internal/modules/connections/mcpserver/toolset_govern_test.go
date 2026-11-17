package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	projectsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type fakePolicies struct {
	*recorder
	admin bool
}

func (f fakePolicies) refuse() error {
	if !f.admin {
		return authz.ErrNotWorkspaceAdmin
	}
	return nil
}

func (f fakePolicies) ListRules(_ context.Context, _ authn.Caller, p governanceapi.PolicyRuleFilter) ([]any, error) {
	f.saw("list %s %t", *p.SubjectType, *p.Enabled)
	if err := f.refuse(); err != nil {
		return nil, err
	}
	return []any{map[string]any{"id": "r1"}}, nil
}
func (f fakePolicies) GetRule(_ context.Context, _ authn.Caller, id string) (any, error) {
	f.saw("get %s", id)
	return nil, governanceapi.ErrPolicyRuleNotFound
}
func (f fakePolicies) CreateRule(_ context.Context, _ authn.Caller, doc json.RawMessage) (any, error) {
	f.saw("create %s", doc)
	return map[string]any{"id": "r2"}, nil
}
func (f fakePolicies) UpdateRule(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (any, error) {
	f.saw("update %s %s", id, doc)
	return map[string]any{"id": id}, nil
}
func (f fakePolicies) DeleteRule(_ context.Context, _ authn.Caller, id string) error {
	f.saw("delete %s", id)
	return nil
}
func (f fakePolicies) PreviewEffective(_ context.Context, _ authn.Caller, agentID string) (any, error) {
	f.saw("preview %q", agentID)
	return map[string]any{"budget": nil}, nil
}
func (f fakePolicies) RunPolicy(_ context.Context, _ authn.Caller, runID string) (any, error) {
	f.saw("run %s", runID)
	return nil, governanceapi.ErrRunPolicyNotFound
}

func TestPoliciesToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Policies: fakePolicies{rec, true}}, "policies")
	runToolCases(t, ts, rec, []toolCase{
		{"policies_list", `{"subject_type":"agent","enabled":true}`, "list agent true", `"r1"`, false},
		{"policies_get", `{"rule_id":"x"}`, "get x", "Policy rule not found", true},
		{"policies_create", `{"subject_type":"agent","subject_id":"a1","target":"tool:x","effect":"deny","params":null}`,
			`create {"condition":null,"effect":"deny","enabled":true,"params":{},"priority":0,"subject_id":"a1","subject_type":"agent","target":"tool:x"}`, `"r2"`, false},
		{"policies_update", `{"rule_id":"r1","enabled":false,"target":null}`, `update r1 {"enabled":false}`, `"r1"`, false},
		{"policies_delete", `{"rule_id":"r1"}`, "delete r1", `{"deleted":true}`, false},
		{"policies_preview_effective_policy", `{}`, `preview ""`, `"budget"`, false},
		{"policies_get_run_policy", `{"run_id":"t1"}`, "run t1", "Run policy snapshot not found", true},
	})
	member := toolsetNamed(t, Providers{Policies: fakePolicies{rec, false}}, "policies")
	runToolCases(t, member, rec, []toolCase{{"policies_list", `{"subject_type":"user","enabled":false}`, "list user false", authz.NotAdminDetail, true}})
}

type fakeSecrets struct{ *recorder }

func (f fakeSecrets) ListOwn(context.Context, authn.Caller) ([]governanceapi.PlatformSecret, error) {
	f.saw("list")
	return []governanceapi.PlatformSecret{{ID: "s1", Name: "token"}}, nil
}
func (f fakeSecrets) Create(_ context.Context, _ authn.Caller, name, value string, desc *string) (governanceapi.PlatformSecret, error) {
	f.saw("create %s %s %v", name, value, desc)
	return governanceapi.PlatformSecret{ID: "s2", Name: name}, nil
}
func (f fakeSecrets) DeleteByName(_ context.Context, _ authn.Caller, name string) error {
	f.saw("delete %s", name)
	if name == "gone" {
		return governanceapi.ErrNoSuchSecret
	}
	return nil
}

func TestSecretsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Secrets: fakeSecrets{rec}}, "secrets")
	runToolCases(t, ts, rec, []toolCase{
		{"secrets_list", `{}`, "list", `[{"description":null,"id":"s1","name":"token"}]`, false},
		{"secrets_create", `{"name":"api","value":"v"}`, "create api v <nil>", `{"created":true,"id":"s2","name":"api"}`, false},
		{"secrets_delete", `{"name":"gone"}`, "delete gone", "No such secret", true},
		{"secrets_delete", `{"name":"api"}`, "delete api", `{"deleted":true,"name":"api"}`, false},
	})
}

type fakeAudit struct{ *recorder }

func (f fakeAudit) List(_ context.Context, _ authn.Caller, q governanceapi.PlatformAuditQuery) ([]governanceapi.PlatformAuditEvent, error) {
	since := ""
	if q.Since != nil {
		since = q.Since.Format(time.RFC3339)
	}
	f.saw("list %s %s %d %s", q.Action, since, q.Limit, q.Cursor)
	out := make([]governanceapi.PlatformAuditEvent, q.Limit)
	for i := range out {
		out[i] = governanceapi.PlatformAuditEvent{ID: fmt.Sprintf("e%d", i), Action: q.Action, CreatedAt: time.Date(2026, 11, 1, 9, 0, 0, 0, time.UTC)}
	}
	return out, nil
}

func TestAuditToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Audit: fakeAudit{rec}}, "audit")
	runToolCases(t, ts, rec, []toolCase{
		{"audit_list", `{"action":"agent.create","since":"2026-11-01T10:00:00+01:00","limit":2}`, "list agent.create 2026-11-01T09:00:00Z 2 ",
			`"next_cursor":"e1"`, false},
		{"audit_list", `{"limit":500}`, "list   100 ", `"created_at":"2026-11-01T09:00:00"`, false},
		{"audit_list", `{"since":"yesterday"}`, "", "Invalid isoformat string: 'yesterday'", true},
	})
}

type fakeProjects struct{ *recorder }

func (f fakeProjects) List(_ context.Context, _ authn.Caller, limit, offset int) ([]projectsapi.PlatformProject, error) {
	f.saw("list %d %d", limit, offset)
	return []projectsapi.PlatformProject{{ID: "p1", Name: "Ops"}}, nil
}
func (f fakeProjects) Get(_ context.Context, _ authn.Caller, id string) (projectsapi.PlatformProject, error) {
	f.saw("get %s", id)
	return projectsapi.PlatformProject{}, projectsapi.ErrProjectNotFound
}
func (f fakeProjects) Create(_ context.Context, _ authn.Caller, doc json.RawMessage) (projectsapi.PlatformProject, error) {
	f.saw("create %s", doc)
	return projectsapi.PlatformProject{ID: "p2", Name: "New"}, nil
}
func (f fakeProjects) Update(_ context.Context, _ authn.Caller, id string, doc json.RawMessage) (projectsapi.PlatformProject, error) {
	f.saw("update %s %s", id, doc)
	return projectsapi.PlatformProject{ID: id, Name: "Renamed"}, nil
}
func (f fakeProjects) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return false, nil
}
func (f fakeProjects) Link(_ context.Context, _ authn.Caller, kind, p, child string) error {
	f.saw("link %s %s %s", kind, p, child)
	return nil
}
func (f fakeProjects) Unlink(_ context.Context, _ authn.Caller, kind, p, child string) error {
	f.saw("unlink %s %s %s", kind, p, child)
	return nil
}

func TestProjectsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Projects: fakeProjects{rec}}, "projects")
	runToolCases(t, ts, rec, []toolCase{
		{"projects_list", `{}`, "list 50 0", `[{"description":null,"id":"p1","name":"Ops"}]`, false},
		{"projects_list", `{"limit":4294967346,"offset":3}`, "list 1000 3", `"p1"`, false},
		{"projects_get", `{"project_id":"p9"}`, "get p9", "Project not found", true},
		{"projects_create", `{"name":"New","parent_project_id":"nope"}`, "", "parent_project_id must be a UUID, got 'nope'", true},
		{"projects_create", `{"name":"New"}`, `create {"description":null,"instructions":null,"name":"New","parent_project_id":null}`, `{"id":"p2","name":"New"}`, false},
		{"projects_update", `{"project_id":"p1","name":"Renamed","description":null}`, `update p1 {"name":"Renamed"}`, `"Renamed"`, false},
		{"projects_delete", `{"project_id":"p1"}`, "delete p1", `{"deleted":false}`, false},
		{"projects_add_skill", `{"project_id":"p1","skill_id":"s1"}`, "link skill p1 s1", `{"added":true}`, false},
		{"projects_remove_agent", `{"project_id":"p1","agent_id":"a1"}`, "unlink agent p1 a1", `{"removed":true}`, false},
		{"projects_add_mcp_instance", `{"project_id":"p1","mcp_instance_id":"m1"}`, "link mcp_instance p1 m1", `{"added":true}`, false},
	})
}

type fakeWorkspaceFiles struct{ *recorder }

func (f fakeWorkspaceFiles) ListFiles(_ context.Context, _ scope.Workspace, prefix string, max int) ([]sandboxapi.PlatformFile, error) {
	f.saw("list %q %d", prefix, max)
	return []sandboxapi.PlatformFile{{Path: "a.txt", Size: 3, ContentType: "text/plain"}, {Path: "b"}}, nil
}
func (f fakeWorkspaceFiles) FileExists(_ context.Context, _ scope.Workspace, p string) (bool, error) {
	f.saw("exists %s", p)
	return p != "gone", nil
}
func (f fakeWorkspaceFiles) ReadFile(_ context.Context, _ scope.Workspace, p string) ([]byte, error) {
	f.saw("read %s", p)
	switch p {
	case "gone":
		return nil, sandboxapi.ErrFileNotFound
	case "bin":
		return []byte{0xff}, nil
	case "big":
		return make([]byte, fileReadMaxBytes+1), nil
	}
	return []byte("héllo"), nil
}
func (f fakeWorkspaceFiles) PlanUploads(_ context.Context, _ scope.Workspace, actor string, entries []sandboxapi.UploadEntry) ([]sandboxapi.PlannedUpload, error) {
	f.saw("plan %s %d %s", actor, len(entries), entries[0].SHA256)
	return []sandboxapi.PlannedUpload{{Path: entries[0].Path, Status: "unchanged"}}, nil
}
func (f fakeWorkspaceFiles) DeleteFile(_ context.Context, _ scope.Workspace, p string) error {
	f.saw("delete %s", p)
	if p == "apps/x" {
		return &sandboxapi.ReadOnlyError{Msg: "'apps/x' belongs to an MCP app and is read-only; only the app itself can change it"}
	}
	return nil
}
func (f fakeWorkspaceFiles) DownloadURL(ws scope.Workspace, p string) string {
	return "https://api.example/v1/workspaces/" + ws.Slug() + "/files/download/" + p
}

type fakeSlugs struct{}

func (fakeSlugs) Slug(context.Context, string) (string, error) { return "acme", nil }

func TestWorkspaceFilesToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{WorkspaceFiles: fakeWorkspaceFiles{rec}, Slugs: fakeSlugs{}}, "workspace_files")
	runToolCases(t, ts, rec, []toolCase{
		{"workspace_files_list", `{"prefix":"r/"}`, `list "r/" 200`, `{"content_type":null,"last_modified":null,"path":"b","size":0}`, false},
		{"workspace_files_list", `{"max_items":99999999}`, `list "" 10000`, `"b"`, false},
		{"workspace_files_get_url", `{"path":"a.txt"}`, "exists a.txt", `"url":"https://api.example/v1/workspaces/acme/files/download/a.txt"`, false},
		{"workspace_files_get_url", `{"path":"gone"}`, "exists gone", "File not found", true},
		{"workspace_files_read", `{"path":"a.txt"}`, "read a.txt", `"content":"héllo"`, false},
		{"workspace_files_read", `{"path":"bin"}`, "read bin", "File is not UTF-8 text; use get_url", true},
		{"workspace_files_read", `{"path":"big"}`, "read big", "File is larger than 524288 bytes; use get_url", true},
		{"workspace_files_read", `{"path":"gone"}`, "read gone", "File not found", true},
		{"workspace_files_upload_urls", `{"files":[]}`, "", "files must not be empty", true},
		{"workspace_files_upload_urls", `{"files":[{"path":"a.txt","sha256":"ab"}]}`, "plan u1 1 ab", `"status":"unchanged"`, false},
		{"workspace_files_delete", `{"path":"apps/x"}`, "delete apps/x", "belongs to an MCP app", true},
		{"workspace_files_delete", `{"path":"a.txt"}`, "delete a.txt", `{"deleted":true,"path":"a.txt"}`, false},
	})
}

type fakeNetwork struct{ *recorder }

func (f fakeNetwork) Topology(_ context.Context, c authn.Caller) (any, error) {
	f.saw("topology %s", c.Workspace.ID())
	return map[string]any{"nodes": []any{}, "edges": []any{}}, nil
}

func TestNetworkToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Network: fakeNetwork{rec}}, "network")
	runToolCases(t, ts, rec, []toolCase{{"network_get_topology", `{}`, "topology " + wsID, `"nodes":[]`, false}})
}

// TestRunPathCallsTheRegistry is a run's code tool call through the pinned
// registry: it acts as the run's agent in its workspace.
func TestRunPathCallsTheRegistry(t *testing.T) {
	rec := &recorder{}
	toolsets, err := Providers{Network: fakeNetwork{rec}, Policies: fakePolicies{rec, true}}.Toolsets("https://api.example")
	if err != nil {
		t.Fatal(err)
	}
	p := NewPlatform(false, Info{}, Auth{}, nil)
	p.Register(toolsets...)
	if !p.Serves("network", "get_topology") || p.Serves("network", "nope") || p.Serves("runs", "start") {
		t.Fatal("Serves")
	}
	ws, _ := scope.NewWorkspace(wsID, "acme")
	c := authn.Caller{Principal: authn.Principal{UserID: "u1", Subject: &authn.Subject{Kind: authn.SubjectAgent, ID: "a1"}}, Workspace: ws}
	res, err := p.Run(context.Background(), c, "network_get_topology", json.RawMessage(`{}`))
	if err != nil || res.IsError || rec.last != "topology "+wsID {
		t.Fatalf("run: %+v %v %q", res, err, rec.last)
	}
	res, err = p.Run(context.Background(), c, "policies_get", json.RawMessage(`{"rule_id":"r"}`))
	if err != nil || !res.IsError || !strings.Contains(res.Content[0].Text, "Policy rule not found") {
		t.Fatalf("refusal: %+v %v", res, err)
	}
}
