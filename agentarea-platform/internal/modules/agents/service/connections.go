package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

// AgentTools implements api.AgentTools over the read pool.
type AgentTools struct{ DB db.Database }

var _ api.AgentTools = AgentTools{}

func (t AgentTools) agents(ctx context.Context, ws scope.Workspace) ([]domain.Agent, error) {
	s, release, err := t.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.Agents{}.List(ctx, s)
}

// Naming is _agents_naming.
func (t AgentTools) Naming(ctx context.Context, ws scope.Workspace, id string) ([]string, error) {
	all, err := t.agents(ctx, ws)
	if err != nil {
		return nil, err
	}
	return naming(all, id), nil
}

func naming(all []domain.Agent, id string) []string {
	var out []string
	for _, a := range all {
		if bytes.Contains(a.Tools, []byte(id)) {
			out = append(out, a.ID)
		}
	}
	return out
}

// MCPConsumers is the agent scan of GET /mcp-server-instances/{id}/consumers.
func (t AgentTools) MCPConsumers(ctx context.Context, ws scope.Workspace, id, name string) ([]api.AgentConnectionUse, error) {
	all, err := t.agents(ctx, ws)
	if err != nil {
		return nil, err
	}
	return mcpUses(all, id, name), nil
}

func mcpUses(all []domain.Agent, id, name string) []api.AgentConnectionUse {
	var out []api.AgentConnectionUse
	for _, a := range all {
		if a.Status == domain.StatusArchived || a.HarnessClientID != nil {
			continue
		}
		var tools []any
		if json.Unmarshal(a.Tools, &tools) != nil {
			continue
		}
		for _, raw := range tools {
			tc, ok := raw.(map[string]any)
			if !ok || tc["type"] != "mcp" {
				continue
			}
			ref := pyStr(tc["name"])
			if ref == "" || (ref != id && ref != name) {
				continue
			}
			use := api.AgentConnectionUse{AgentID: a.ID, AgentName: a.Name, AgentSlug: a.Slug, ServerRef: ref}
			settings, _ := tc["settings"].(map[string]any)
			if allowed, ok := settings["allowed_tools"].([]any); ok {
				use.EnabledTools = []string{}
				for _, perm := range allowed {
					switch p := perm.(type) {
					case map[string]any:
						if n := pyStr(p["tool_name"]); n != "" {
							use.EnabledTools = append(use.EnabledTools, n)
						}
					case string:
						use.EnabledTools = append(use.EnabledTools, p)
					}
				}
			}
			out = append(out, use)
			break
		}
	}
	return out
}

// pyStr is str(v) for the scalars a tools JSON holds; "" for null.
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	default:
		return fmt.Sprint(x)
	}
}

// ClientBundles implements api.ClientBundles.
type ClientBundles struct{ Skills *Skills }

var _ api.ClientBundles = ClientBundles{}

// Locate is ClientRepository.locate_workspace.
func (b ClientBundles) Locate(ctx context.Context, clientID string, workspaces []string) (string, bool, error) {
	id, err := uuid.Parse(clientID)
	if err != nil || len(workspaces) == 0 {
		return "", false, nil
	}
	q, release, err := b.Skills.s.d.DB.Global().Read(ctx)
	if err != nil {
		return "", false, err
	}
	defer release()
	return store.LocateClient(ctx, q, id, workspaces)
}

func stringList(raw []byte) []string {
	var l []any
	if json.Unmarshal(raw, &l) != nil || l == nil {
		return nil
	}
	out := make([]string, 0, len(l))
	for _, v := range l {
		out = append(out, pyStr(v))
	}
	return out
}

func attachments(links []store.ClientLink) []api.ClientAttachment {
	out := make([]api.ClientAttachment, 0, len(links))
	for _, l := range links {
		out = append(out, api.ClientAttachment{ID: l.TargetID.String(), NamespacePrefix: l.NamespacePrefix, AllowedTools: stringList(l.AllowedTools)})
	}
	return out
}

// Bundle is the client half of _resolve_client_scope.
func (b ClientBundles) Bundle(ctx context.Context, ws scope.Workspace, userID, clientID string) (api.ClientBundle, bool, error) {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return api.ClientBundle{}, false, nil
	}
	s, release, err := b.Skills.s.d.DB.Read(ctx, ws)
	if err != nil {
		return api.ClientBundle{}, false, err
	}
	defer release()
	var c store.Clients
	row, ok, err := c.Get(ctx, s, id)
	if err != nil || !ok {
		return api.ClientBundle{}, false, err
	}
	out := api.ClientBundle{ID: row.ID.String(), Name: row.Name}
	if row.Description != nil {
		out.Description = *row.Description
	}
	ids := []uuid.UUID{id}
	mcp, err := c.MCPInstances(ctx, s, ids)
	if err != nil {
		return api.ClientBundle{}, false, err
	}
	out.MCPInstances = attachments(mcp)
	oa, err := c.OpenAPIConnections(ctx, s, ids)
	if err != nil {
		return api.ClientBundle{}, false, err
	}
	out.OpenAPI = attachments(oa)
	sets, err := c.Toolsets(ctx, s, ids)
	if err != nil {
		return api.ClientBundle{}, false, err
	}
	for _, t := range sets {
		disabled := stringList(t.DisabledMethods)
		if disabled == nil {
			disabled = []string{}
		}
		out.Toolsets = append(out.Toolsets, api.ClientToolset{Toolset: t.Toolset, DisabledMethods: disabled})
	}
	links, err := c.Skills(ctx, s, ids)
	if err != nil {
		return api.ClientBundle{}, false, err
	}
	for _, l := range links {
		sk, ok, err := store.Skills{}.Get(ctx, s, l.SkillID)
		if err != nil {
			return api.ClientBundle{}, false, err
		}
		if !ok {
			continue
		}
		content, err := b.Skills.readSkillMD(ctx, s, userID, &sk, false)
		if err != nil {
			return api.ClientBundle{}, false, err
		}
		cs := api.ClientSkill{ID: sk.ID, Name: sk.Name, Content: content}
		if sk.Description != nil {
			cs.Description = *sk.Description
		}
		out.Skills = append(out.Skills, cs)
	}
	return out, true, nil
}
