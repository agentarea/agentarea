package service

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// Network implements api.Network over the read pool.
type Network struct {
	DB db.Database
}

var _ api.Network = Network{}

func (n Network) read(ctx context.Context, ws scope.Workspace, fn func(q *store.Queries) error) error {
	s, release, err := n.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(store.New(s.Q()))
}

// NetworkAgents implements api.Network.
func (n Network) NetworkAgents(ctx context.Context, ws scope.Workspace) ([]api.NetworkAgent, error) {
	var out []api.NetworkAgent
	err := n.read(ctx, ws, func(q *store.Queries) error {
		rows, err := q.NetworkAgents(ctx, ws.ID())
		if err != nil {
			return err
		}
		links, err := q.NetworkAgentSkills(ctx, ws.ID())
		if err != nil {
			return err
		}
		skills := map[string][]api.SkillRef{}
		for _, l := range links {
			skills[l.AgentID.String()] = append(skills[l.AgentID.String()], api.SkillRef{ID: l.ID.String(), Name: l.Name})
		}
		for _, r := range rows {
			a := api.NetworkAgent{ID: r.ID.String(), Name: r.Name, Status: r.Status, Description: store.OptText(r.Description),
				ModelID: store.OptText(r.ModelID), Skills: skills[r.ID.String()]}
			if len(r.Tools) > 0 {
				a.Tools = json.RawMessage(r.Tools)
			}
			out = append(out, a)
		}
		return nil
	})
	return out, err
}

// NetworkSkills implements api.Network.
func (n Network) NetworkSkills(ctx context.Context, ws scope.Workspace) ([]api.NetworkSkill, []api.SkillMember, error) {
	var skills []api.NetworkSkill
	var members []api.SkillMember
	err := n.read(ctx, ws, func(q *store.Queries) error {
		rows, err := q.NetworkSkills(ctx, ws.ID())
		if err != nil {
			return err
		}
		for _, r := range rows {
			skills = append(skills, api.NetworkSkill{ID: r.ID.String(), Name: r.Name, Description: store.OptText(r.Description),
				SourceType: r.SourceType, NetworkScope: r.NetworkScope})
		}
		ms, err := q.NetworkSkillMembers(ctx, ws.ID())
		for _, m := range ms {
			members = append(members, api.SkillMember{ParentID: m.ParentSkillID.String(), ChildID: m.ChildSkillID.String()})
		}
		return err
	})
	return skills, members, err
}

// AllAgents implements api.Network.
func (n Network) AllAgents(ctx context.Context, ws scope.Workspace) ([]api.AgentName, error) {
	var out []api.AgentName
	err := n.read(ctx, ws, func(q *store.Queries) error {
		rows, err := q.NetworkAgentNames(ctx, ws.ID())
		for _, r := range rows {
			out = append(out, api.AgentName{ID: r.ID.String(), Name: r.Name})
		}
		return err
	})
	return out, err
}
