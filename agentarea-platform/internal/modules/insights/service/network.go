package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// ErrMembershipGraphDown is a membership graph read that failed (503).
var ErrMembershipGraphDown = errors.New("Workspace membership graph unavailable") //nolint:staticcheck // Python's detail

// Topology is GET /network/topology: every live agent, egress skill,
// connection and trigger of the workspace with their relations. Every
// member sees the whole workspace.
func (s *Service) Topology(ctx context.Context, c authn.Caller) (Topology, error) {
	r, ws := s.d.Reads, c.Workspace
	in := GraphInput{Enterprise: s.d.Edition == "enterprise"}
	agents, err := r.Agents.NetworkAgents(ctx, ws)
	if err != nil {
		return Topology{}, fmt.Errorf("agents: %w", err)
	}
	for _, a := range agents {
		ga := GraphAgent{ID: a.ID, Name: a.Name, Status: a.Status, Description: a.Description, ModelID: a.ModelID, Tools: a.Tools}
		for _, sk := range a.Skills {
			ga.Skills = append(ga.Skills, GraphRef{ID: sk.ID, Name: sk.Name})
		}
		in.Agents = append(in.Agents, ga)
	}
	skills, members, err := r.Agents.NetworkSkills(ctx, ws)
	if err != nil {
		return Topology{}, fmt.Errorf("skills: %w", err)
	}
	for _, sk := range skills {
		in.Skills = append(in.Skills, GraphSkill{ID: sk.ID, Name: sk.Name, SourceType: sk.SourceType, NetworkScope: sk.NetworkScope, Description: sk.Description})
	}
	for _, m := range members {
		in.Members = append(in.Members, GraphMember{ParentID: m.ParentID, ChildID: m.ChildID})
	}
	instances, err := r.Connections.MCPInstances(ctx, ws)
	if err != nil {
		return Topology{}, fmt.Errorf("mcp instances: %w", err)
	}
	specs := map[string]map[string]any{}
	for _, i := range instances {
		gi := GraphInstance{ID: i.ID, Name: i.Name, NetworkScope: i.NetworkScope, ToolCount: i.ToolCount, JSONSpec: i.JSONSpec}
		if FirstIconSrc(i.JSONSpec) == nil && i.ServerSpecID != "" {
			spec, seen := specs[i.ServerSpecID]
			if !seen {
				if spec, err = s.specJSON(ctx, ws, i.ServerSpecID, i.Platform); err != nil {
					return Topology{}, err
				}
				specs[i.ServerSpecID] = spec
			}
			gi.SpecJSON = spec
		}
		in.Instances = append(in.Instances, gi)
	}
	conns, err := r.Connections.OpenAPIConnections(ctx, ws)
	if err != nil {
		return Topology{}, fmt.Errorf("openapi connections: %w", err)
	}
	for _, c := range conns {
		in.OpenAPI = append(in.OpenAPI, GraphOpenAPI{ID: c.ID, Name: c.Name, Status: c.Status, Description: c.Description, BaseURL: c.BaseURL, ToolCount: c.ToolCount})
	}
	triggers, err := r.AllTriggers.ListTriggers(ctx, ws, nil)
	if err != nil {
		return Topology{}, fmt.Errorf("triggers: %w", err)
	}
	for _, t := range triggers {
		in.Triggers = append(in.Triggers, GraphTrigger{ID: t.ID, Name: t.Name, AgentID: t.AgentID, Type: t.TriggerType, Active: t.IsActive})
	}
	return BuildTopology(in), nil
}

func (s *Service) specJSON(ctx context.Context, ws scope.Workspace, id string, platform bool) (map[string]any, error) {
	spec, ok, err := s.d.Reads.Specs.Get(ctx, ws, id, catalogapi.MCPSpecGet{PlatformBacked: platform})
	if err != nil {
		return nil, fmt.Errorf("mcp spec %s: %w", id, err)
	}
	if !ok {
		return nil, nil
	}
	return spec.JSONSpec, nil
}

// PeopleAccess is GET /network/people-access for a workspace admin: who of
// the workspace's people may run which agent (agent:execute admission), at
// most MaxPeople by MaxAgents. The admin check comes before any read.
func (s *Service) PeopleAccess(ctx context.Context, c authn.Caller) (PeopleAccess, error) {
	if err := s.d.Admin(ctx); err != nil {
		return PeopleAccess{}, err
	}
	r, ws := s.d.Reads, c.Workspace
	members, err := authz.WorkspaceMemberIDs(ctx, r.Members, ws.ID())
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to inspect network workspace memberships", "error", err)
		return PeopleAccess{}, fmt.Errorf("%w: %w", ErrMembershipGraphDown, err)
	}
	owner, _, err := r.Owners.Owner(ctx, ws.ID())
	if err != nil {
		return PeopleAccess{}, fmt.Errorf("workspace owner: %w", err)
	}
	selected, total := SelectPeople(members, owner)
	agents, err := r.Agents.AllAgents(ctx, ws)
	if err != nil {
		return PeopleAccess{}, fmt.Errorf("agents: %w", err)
	}
	chosen := agents[:min(len(agents), MaxAgents)]
	out := PeopleAccess{WorkspaceID: ws.ID(), People: []Person{}, Access: []Access{},
		TotalPeople: total, TotalAgents: len(agents),
		Complete: len(selected) == total && len(chosen) == len(agents)}
	for _, id := range selected {
		p := Person{UserID: id}
		if id == c.UserID && c.Email != "" {
			email := c.Email
			p.Email = &email
		}
		out.People = append(out.People, p)
		subject := &authn.Principal{UserID: id, AccessibleWorkspaces: []string{ws.ID()}}
		for _, a := range chosen {
			d := authz.AuthorizeAgentAction(subject, authz.AgentExecute, ws.ID(), a.ID)
			out.Access = append(out.Access, Access{UserID: id, AgentID: a.ID, Allowed: d.Allowed, Reason: d.Reason})
		}
	}
	return out, nil
}
