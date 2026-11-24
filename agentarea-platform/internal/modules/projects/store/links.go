package store

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
)

// Links are the child ids linked to each of ids, keyed by project id.
func (Projects) Links(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]*domain.Links, error) {
	out := make(map[string]*domain.Links, len(ids))
	for _, id := range ids {
		out[id.String()] = &domain.Links{}
	}
	if len(ids) == 0 {
		return out, nil
	}
	q, ws := New(s.Q()), s.Workspace().ID()
	skills, err := q.SkillLinks(ctx, SkillLinksParams{WorkspaceID: ws, ProjectIds: ids})
	if err != nil {
		return nil, err
	}
	for _, r := range skills {
		l := out[r.ProjectID.String()]
		l.Skills = append(l.Skills, r.ChildID.String())
	}
	mcps, err := q.MCPInstanceLinks(ctx, MCPInstanceLinksParams{WorkspaceID: ws, ProjectIds: ids})
	if err != nil {
		return nil, err
	}
	for _, r := range mcps {
		l := out[r.ProjectID.String()]
		l.MCPInstances = append(l.MCPInstances, r.ChildID.String())
	}
	agents, err := q.AgentLinks(ctx, AgentLinksParams{WorkspaceID: ws, ProjectIds: ids})
	if err != nil {
		return nil, err
	}
	for _, r := range agents {
		l := out[r.ProjectID.String()]
		l.Agents = append(l.Agents, r.ChildID.String())
	}
	return out, nil
}

// Link adds child to the project; linking twice is a no-op.
func (Projects) Link(ctx context.Context, s db.Session, k domain.LinkKind, project, child uuid.UUID) error {
	q, ws := New(s.Q()), s.Workspace().ID()
	switch k {
	case domain.LinkSkill:
		return q.AddSkill(ctx, AddSkillParams{ChildID: child, WorkspaceID: ws, ProjectID: project})
	case domain.LinkMCPInstance:
		return q.AddMCPInstance(ctx, AddMCPInstanceParams{ChildID: child, WorkspaceID: ws, ProjectID: project})
	case domain.LinkAgent:
	}
	return q.AddAgent(ctx, AddAgentParams{ChildID: child, WorkspaceID: ws, ProjectID: project})
}

// Unlink removes child from the project; an absent link is a no-op.
func (Projects) Unlink(ctx context.Context, s db.Session, k domain.LinkKind, project, child uuid.UUID) error {
	q, ws := New(s.Q()), s.Workspace().ID()
	switch k {
	case domain.LinkSkill:
		return q.RemoveSkill(ctx, RemoveSkillParams{WorkspaceID: ws, ProjectID: project, ChildID: child})
	case domain.LinkMCPInstance:
		return q.RemoveMCPInstance(ctx, RemoveMCPInstanceParams{WorkspaceID: ws, ProjectID: project, ChildID: child})
	case domain.LinkAgent:
	}
	return q.RemoveAgent(ctx, RemoveAgentParams{WorkspaceID: ws, ProjectID: project, ChildID: child})
}

// AgentProjects are the workspace's projects the agent belongs to.
func (Projects) AgentProjects(ctx context.Context, s db.Session, agentID uuid.UUID) ([]uuid.UUID, error) {
	return New(s.Q()).AgentProjectIDs(ctx, AgentProjectIDsParams{WorkspaceID: s.Workspace().ID(), AgentID: agentID})
}
