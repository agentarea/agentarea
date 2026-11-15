package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	projectsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
)

func projectNotFound(err error) error {
	if errors.Is(err, projectsapi.ErrProjectNotFound) {
		return &toolError{err.Error()}
	}
	return err
}

// parentProjectArg is the parent_project_id a tool was given: a UUID or nothing.
func parentProjectArg(v *string) error {
	if v == nil {
		return nil
	}
	if _, err := uuid.Parse(*v); err != nil {
		raw, _ := json.Marshal(*v)
		return &toolError{"parent_project_id must be a UUID, got '" + string(raw[1:len(raw)-1]) + "'"}
	}
	return nil
}

type projectIDArgs struct {
	ProjectID string `json:"project_id"`
}

func projectRef(p projectsapi.PlatformProject) map[string]any {
	return map[string]any{"id": p.ID, "name": p.Name}
}

func projectLink(p projectsapi.PlatformProjects, title, kind, childKey string, add bool) toolDef {
	return toolDef{title: title, effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
		in, err := decodeArgs[map[string]any](args)
		if err != nil {
			return nil, err
		}
		project, _ := in["project_id"].(string)
		child, _ := in[childKey].(string)
		if add {
			if err := p.Link(ctx, c, kind, project, child); err != nil {
				return nil, projectNotFound(err)
			}
			return map[string]any{"added": true}, nil
		}
		if err := p.Unlink(ctx, c, kind, project, child); err != nil {
			return nil, projectNotFound(err)
		}
		return map[string]any{"removed": true}, nil
	}}
}

// projectTools is tools/projects_toolset.py.
func projectTools(p projectsapi.PlatformProjects) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List projects", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Limit  *int `json:"limit"`
				Offset int  `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxListed))
			ps, err := p.List(ctx, c, limit, in.Offset)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(ps))
			for i, pr := range ps {
				out[i] = map[string]any{"id": pr.ID, "name": pr.Name, "description": pr.Description}
			}
			return out, nil
		}},
		"get": {title: "Get project", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[projectIDArgs](args)
			if err != nil {
				return nil, err
			}
			pr, err := p.Get(ctx, c, in.ProjectID)
			if err != nil {
				return nil, projectNotFound(err)
			}
			return map[string]any{"id": pr.ID, "name": pr.Name, "description": pr.Description,
				"instructions": pr.Instructions, "parent_project_id": pr.ParentProjectID}, nil
		}},
		"create": {title: "Create project", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name            *string `json:"name"`
				Description     *string `json:"description"`
				Instructions    *string `json:"instructions"`
				ParentProjectID *string `json:"parent_project_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			if err := parentProjectArg(in.ParentProjectID); err != nil {
				return nil, err
			}
			doc, err := json.Marshal(map[string]any{"name": in.Name, "description": in.Description,
				"instructions": in.Instructions, "parent_project_id": in.ParentProjectID})
			if err != nil {
				return nil, err
			}
			pr, err := p.Create(ctx, c, doc)
			if err != nil {
				return nil, projectNotFound(err)
			}
			return projectRef(pr), nil
		}},
		"update": {title: "Update project", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ProjectID       string  `json:"project_id"`
				ParentProjectID *string `json:"parent_project_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			if err := parentProjectArg(in.ParentProjectID); err != nil {
				return nil, err
			}
			doc, err := patchArgs(args, []string{"project_id"}, []string{"name", "description", "instructions", "parent_project_id"})
			if err != nil {
				return nil, err
			}
			pr, err := p.Update(ctx, c, in.ProjectID, doc)
			if err != nil {
				return nil, projectNotFound(err)
			}
			return projectRef(pr), nil
		}},
		"delete": {title: "Delete project", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[projectIDArgs](args)
			if err != nil {
				return nil, err
			}
			deleted, err := p.Delete(ctx, c, in.ProjectID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}},
		"add_skill":           projectLink(p, "Attach skill to project", projectsapi.LinkSkill, "skill_id", true),
		"remove_skill":        projectLink(p, "Detach skill from project", projectsapi.LinkSkill, "skill_id", false),
		"add_agent":           projectLink(p, "Attach agent to project", projectsapi.LinkAgent, "agent_id", true),
		"remove_agent":        projectLink(p, "Detach agent from project", projectsapi.LinkAgent, "agent_id", false),
		"add_mcp_instance":    projectLink(p, "Attach MCP instance to project", projectsapi.LinkMCPInstance, "mcp_instance_id", true),
		"remove_mcp_instance": projectLink(p, "Detach MCP instance from project", projectsapi.LinkMCPInstance, "mcp_instance_id", false),
	}
}
