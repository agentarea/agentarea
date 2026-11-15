package service

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

func networkExec(t *testing.T, d db.Database, ws scope.Workspace, sql string, args ...any) {
	t.Helper()
	err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, sql, args...)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestNetworkReadsAgentsSkillsAndMembers(t *testing.T) {
	d := clientOpenDB(t)
	id := uuid.NewString()
	ws, err := scope.NewWorkspace(id, "")
	if err != nil {
		t.Fatal(err)
	}
	networkExec(t, d, ws, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, "ws-"+id[:8])
	live, archived := uuid.NewString(), uuid.NewString()
	agent := `INSERT INTO agents (id, name, status, workspace_id, created_by, slug, model_id, tools, created_at)
		VALUES ($1, $2, $3, $4, 'u', $5, $6, $7::json, now() + $8 * interval '1 second')`
	networkExec(t, d, ws, agent, live, "Scout", "active", id, "scout-"+live[:6], "m-1", `[{"type":"mcp","server_id":"x"}]`, 0)
	networkExec(t, d, ws, agent, archived, "Old", "archived", id, "old-"+archived[:6], nil, nil, 1)
	parent, child := uuid.NewString(), uuid.NewString()
	skill := `INSERT INTO skills (id, name, workspace_id, created_by, slug, source_type, network_scope, created_at)
		VALUES ($1, $2, $3, 'u', $4, 'inline', $5, now() + $6 * interval '1 second')`
	networkExec(t, d, ws, skill, parent, "Web", id, "web-"+parent[:6], "egress", 0)
	networkExec(t, d, ws, skill, child, "Fetch", id, "fetch-"+child[:6], "egress", 1)
	networkExec(t, d, ws, `INSERT INTO agent_skills (agent_id, skill_id) VALUES ($1, $2)`, live, parent)
	networkExec(t, d, ws, `INSERT INTO skill_members (parent_skill_id, child_skill_id) VALUES ($1, $2)`, parent, child)

	n := Network{DB: d}
	ctx := context.Background()
	agents, err := n.NetworkAgents(ctx, ws)
	if err != nil || len(agents) != 1 || agents[0].ID != live || *agents[0].ModelID != "m-1" || len(agents[0].Skills) != 1 || agents[0].Skills[0].ID != parent {
		t.Fatalf("agents: %+v %v", agents, err)
	}
	if string(agents[0].Tools) == "" {
		t.Fatal("tools not read")
	}
	skills, members, err := n.NetworkSkills(ctx, ws)
	if err != nil || len(skills) != 2 || skills[0].ID != parent || skills[0].NetworkScope != "egress" || len(members) != 1 || members[0].ChildID != child {
		t.Fatalf("skills: %+v %+v %v", skills, members, err)
	}
	all, err := n.AllAgents(ctx, ws)
	if err != nil || len(all) != 2 {
		t.Fatalf("all agents: %+v %v", all, err)
	}
}
