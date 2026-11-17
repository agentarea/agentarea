package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestClientRowsLinksAndWorkspace(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	var c Clients
	id := uuid.New()
	desc := "d"
	now := time.Date(2026, 1, 2, 3, 4, 5, 6789, time.UTC)
	if err := c.Insert(ctx, s, id, "u1", "Codex", &desc, "codex", now); err != nil {
		t.Fatal(err)
	}
	row, ok, err := c.Get(ctx, s, id)
	if err != nil || !ok || row.Name != "Codex" || row.Kind != "codex" || !row.Sandbox || string(row.AllowDomains) != "[]" || row.Models != nil {
		t.Fatalf("%+v %v %v", row, ok, err)
	}
	if _, ok, _ := c.Get(ctx, other, id); ok {
		t.Fatal("another workspace reads the client")
	}
	newer := uuid.New()
	if err := c.Insert(ctx, s, newer, "u1", "Claude", nil, "claude", now.Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if rows, _ := c.List(ctx, s, []uuid.UUID{id, newer, uuid.New()}, 0, 10); len(rows) != 2 || rows[0].ID != newer {
		t.Fatalf("newest first %v", rows)
	}
	if rows, _ := c.List(ctx, s, []uuid.UUID{id, newer}, 1, 10); len(rows) != 1 || rows[0].ID != id {
		t.Fatalf("offset %v", rows)
	}
	model := "gpt"
	row.DefaultModel, row.AllowDomains, row.Sandbox = &model, []byte(`["pypi.org"]`), false
	if err := c.Update(ctx, s, row, now); err != nil {
		t.Fatal(err)
	}
	if row, _, _ = c.Get(ctx, s, id); *row.DefaultModel != "gpt" || row.Sandbox || string(row.AllowDomains) != `["pypi.org"]` {
		t.Fatalf("update %+v", row)
	}

	mine, foreign := uuid.New(), uuid.New()
	for sk, ws := range map[uuid.UUID]string{mine: s.Workspace().ID(), foreign: other.Workspace().ID()} {
		if _, err := pool.Exec(ctx, `INSERT INTO skills (id, name, workspace_id, created_by, slug) VALUES ($1, 'S', $2, 'u', $3)`, sk, ws, sk.String()); err != nil {
			t.Fatal(err)
		}
		if err := c.AddSkill(ctx, s, id, sk); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddSkill(ctx, s, id, mine); err != nil {
		t.Fatal("linking twice is a no-op:", err)
	}
	skills, err := c.Skills(ctx, s, []uuid.UUID{id})
	if err != nil || len(skills) != 1 || skills[0].SkillID != mine {
		t.Fatalf("skills of the workspace only: %v %v", skills, err)
	}

	inst, prefix := uuid.New(), "gh"
	if _, err := pool.Exec(ctx, `INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id, created_by, transport) VALUES ($1, 's', 'GitHub', $2, 'u', 'url')`, inst, s.Workspace().ID()); err != nil {
		t.Fatal(err)
	}
	if err := c.SetMCPInstance(ctx, s, id, inst, nil, nil); err != nil {
		t.Fatal(err)
	}
	if err := c.SetMCPInstance(ctx, s, id, inst, &prefix, []byte(`["a"]`)); err != nil {
		t.Fatal(err)
	}
	links, _ := c.MCPInstances(ctx, s, []uuid.UUID{id})
	if len(links) != 1 || *links[0].NamespacePrefix != "gh" || string(links[0].AllowedTools) != `["a"]` {
		t.Fatalf("upsert replaces %+v", links)
	}
	if links, _ := c.MCPInstances(ctx, other, []uuid.UUID{id}); len(links) != 0 {
		t.Fatal("links read across workspaces")
	}
	for _, ts := range []string{"agentarea/runs", "agentarea/agents"} {
		if err := c.SetToolset(ctx, s, id, ts, nil); err != nil {
			t.Fatal(err)
		}
	}
	ts, _ := c.Toolsets(ctx, s, []uuid.UUID{id})
	if len(ts) != 2 || ts[0].Toolset != "agentarea/agents" || ts[0].DisabledMethods != nil {
		t.Fatalf("toolsets by name %+v", ts)
	}
	if err := c.RemoveToolset(ctx, s, id, "agentarea/agents"); err != nil {
		t.Fatal(err)
	}

	if _, err := pool.Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug, client_id) VALUES ($1, 'A', 'active', $2, 'u', $3, $4)`,
		uuid.New(), s.Workspace().ID(), uuid.NewString(), id); err != nil {
		t.Fatal(err)
	}
	if n, err := c.AgentCount(ctx, s, id); err != nil || n != 1 {
		t.Fatalf("agent count %d %v", n, err)
	}
	if ok, _ := c.Delete(ctx, other, id); ok {
		t.Fatal("deleted across workspaces")
	}
	if _, err := pool.Exec(ctx, `DELETE FROM agents WHERE client_id = $1`, id); err != nil {
		t.Fatal(err)
	}
	if ok, err := c.Delete(ctx, s, id); err != nil || !ok {
		t.Fatalf("delete %v %v", ok, err)
	}
}

func TestTaskDefRows(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	var d TaskDefs
	agent, archived := uuid.New(), uuid.New()
	for a, st := range map[uuid.UUID]string{agent: "active", archived: "archived"} {
		if _, err := pool.Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', $2, $3, 'u', $4)`, a, st, s.Workspace().ID(), a.String()); err != nil {
			t.Fatal(err)
		}
	}
	if st, ok, err := d.AgentStatus(ctx, s, archived); err != nil || !ok || st != "archived" {
		t.Fatalf("%q %v %v", st, ok, err)
	}
	if _, ok, _ := d.AgentStatus(ctx, other, agent); ok {
		t.Fatal("agent read across workspaces")
	}
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	first, second := uuid.New(), uuid.New()
	for i, id := range []uuid.UUID{first, second} {
		a := agent
		if i == 1 {
			a = archived
		}
		if err := d.Insert(ctx, s, "u1", TaskDefRow{ID: id, Name: "n", Description: "d", AgentID: a, Parameters: []byte(`{"k": 1}`)}, base.Add(time.Duration(i)*time.Hour)); err != nil {
			t.Fatal(err)
		}
	}
	rows, err := d.List(ctx, s, nil, 10)
	if err != nil || len(rows) != 2 || rows[0].ID != second {
		t.Fatalf("newest first %v %v", rows, err)
	}
	if rows, _ := d.List(ctx, s, &agent, 10); len(rows) != 1 || rows[0].ID != first {
		t.Fatalf("agent filter %v", rows)
	}
	if rows, _ := d.List(ctx, s, nil, 1); len(rows) != 1 {
		t.Fatalf("limit %v", rows)
	}
	row, ok, _ := d.Get(ctx, s, first)
	if !ok || string(row.Parameters) != `{"k": 1}` || !row.CreatedAt.Equal(base) {
		t.Fatalf("%+v", row)
	}
	row.Name = "m"
	if err := d.Update(ctx, s, row, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if row, _, _ = d.Get(ctx, s, first); row.Name != "m" || !row.UpdatedAt.Equal(base.Add(time.Minute)) {
		t.Fatalf("update %+v", row)
	}
	if ok, _ := d.Delete(ctx, other, first); ok {
		t.Fatal("deleted across workspaces")
	}
	if ok, _ := d.Delete(ctx, s, first); !ok {
		t.Fatal("not deleted")
	}
}
