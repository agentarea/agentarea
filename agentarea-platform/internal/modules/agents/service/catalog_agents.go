package service

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// CatalogAgents implements AgentCatalog over the catalog's agent items.
type CatalogAgents struct {
	S      *Service
	Items  CatalogItems
	Policy SkillInstallPolicy
}

var _ AgentCatalog = CatalogAgents{}

// agentSpec is a catalog agent item's spec as the presets and the fork read it.
type agentSpec struct {
	raw  map[string]any
	item catalogapi.CatalogItem
}

func parseAgentSpec(item catalogapi.CatalogItem) (agentSpec, error) {
	sp := agentSpec{raw: map[string]any{}, item: item}
	if len(item.Spec) == 0 || string(item.Spec) == "null" {
		return sp, nil
	}
	v, err := wirejson.Unmarshal(item.Spec)
	if err != nil {
		return sp, fmt.Errorf("catalog agent %s: spec does not parse: %w", item.ID, err)
	}
	if o, ok := v.(wirejson.Object); ok {
		for _, kv := range o {
			sp.raw[kv.Key] = kv.Value
		}
	}
	return sp, nil
}

// truthyList is spec.get(key) or []: nil when it is not a list.
func (sp agentSpec) truthyList(key string) ([]any, bool) {
	v := sp.raw[key]
	if !toolsTruthy(v) {
		return []any{}, true
	}
	l, ok := v.([]any)
	return l, ok
}

func (sp agentSpec) str(key string) *string {
	s, ok := sp.raw[key].(string)
	if !ok {
		return nil
	}
	return &s
}

// tools are spec.tools as ToolConfig validates them; errs collects what does not.
func (sp agentSpec) tools(errs *fieldErrs) []domain.Tool {
	l, ok := sp.truthyList("tools")
	if !ok {
		*errs = append(*errs, httpx.FieldError{Loc: []any{"tools"}, Msg: "Input should be a valid list", Type: "list_type"})
		return nil
	}
	out := []domain.Tool{}
	for i, t := range l {
		if tool, ok := ParseTool(t, []any{"tools", i}, errs); ok {
			out = append(out, tool)
		}
	}
	return out
}

// PresetMalformedError is a preset the response model refuses: the route answers 500.
type PresetMalformedError struct {
	Name string
	Errs fieldErrs
}

func (e *PresetMalformedError) Error() string {
	b, _ := json.Marshal(e.Errs)
	return fmt.Sprintf("Catalog preset %s is malformed: %s", domain.SkillRepr(e.Name), b)
}

// PresetsJSON is list_agent_presets: each preset with its tools validated
// and its skill keys resolved, the keys nothing matches listed apart.
func (x CatalogAgents) PresetsJSON(ctx context.Context, c authn.Caller) (any, error) {
	items, err := x.Items.AgentPresets(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(items))
	for _, item := range items {
		sp, err := parseAgentSpec(item)
		if err != nil {
			return nil, err
		}
		var errs fieldErrs
		tools := sp.tools(&errs)
		models, okModels := sp.truthyList("preferred_models")
		keys, okSkills := sp.truthyList("skills")
		triggers, okTriggers := sp.truthyList("triggers")
		for key, ok := range map[string]bool{"preferred_models": okModels, "skills": okSkills, "triggers": okTriggers} {
			if !ok {
				errs = append(errs, httpx.FieldError{Loc: []any{key}, Msg: "Input should be a valid list", Type: "list_type"})
			}
		}
		for i, m := range models {
			if _, ok := m.(string); !ok {
				errs = append(errs, httpx.FieldError{Loc: []any{"preferred_models", i}, Msg: "Input should be a valid string", Type: "string_type"})
			}
		}
		for i, t := range triggers {
			if _, ok := t.(wirejson.Object); !ok {
				errs = append(errs, httpx.FieldError{Loc: []any{"triggers", i}, Msg: "Input should be a valid dictionary or instance of TriggerSpec", Type: "model_type"})
			}
		}
		if len(errs) > 0 {
			return nil, &PresetMalformedError{Name: item.Name, Errs: errs}
		}
		skills := []any{}
		unavailable := []any{}
		for _, k := range keys {
			key := pyStr(k)
			found, ok, err := x.Items.SkillByKey(ctx, c.Workspace, key)
			if err != nil {
				return nil, err
			}
			if !ok {
				unavailable = append(unavailable, key)
				continue
			}
			skills = append(skills, wirejson.Object{{Key: "id", Value: found.ID}, {Key: "name", Value: found.Name},
				{Key: "description", Value: strOrNil(found.Description)}})
		}
		toolsJSON := make([]any, len(tools))
		for i, t := range tools {
			toolsJSON[i] = ToolResponse(t)
		}
		instruction := ""
		if s := sp.str("instruction"); s != nil {
			instruction = *s
		}
		out = append(out, wirejson.Object{
			{Key: "id", Value: item.ID}, {Key: "name", Value: item.Name}, {Key: "description", Value: strOrNil(item.Description)},
			{Key: "instruction", Value: instruction}, {Key: "preferred_models", Value: models}, {Key: "tools", Value: toolsJSON},
			{Key: "skills", Value: skills}, {Key: "unavailable_skills", Value: unavailable}, {Key: "triggers", Value: triggers},
		})
	}
	return out, nil
}

// Install is _resolve_agent_id then install_catalog_agent: the workspace's
// agent the identifier names, its earlier fork of the catalog item, or a new one;
// an existing one needs read, and delete when it is archived and so restored.
func (x CatalogAgents) Install(ctx context.Context, c authn.Caller, identifier string) (string, error) {
	s := x.S
	ws := c.Workspace
	var existing domain.Agent
	var has bool
	var item catalogapi.CatalogItem
	var isItem bool
	id, err := uuid.Parse(identifier)
	if err == nil {
		if existing, has, err = s.load(ctx, ws, id, false); err != nil {
			return "", err
		}
		if !has {
			if item, isItem, err = x.Items.AgentItem(ctx, ws, id.String()); err != nil {
				return "", err
			}
		}
	} else {
		if err := s.read(ctx, ws, func(sess db.Session) error {
			existing, has, err = s.store.BySlug(ctx, sess, identifier)
			return err
		}); err != nil {
			return "", err
		}
		if !has {
			all, err := x.Items.AgentItems(ctx, ws)
			if err != nil {
				return "", err
			}
			for _, it := range all {
				if domain.Slug(it.Name) == identifier {
					item, isItem = it, true
					break
				}
			}
		}
	}
	if !has {
		if !isItem {
			return "", domain.ErrAgentNotFound
		}
		if err := s.read(ctx, ws, func(sess db.Session) error {
			existing, has, err = s.store.ByRegistryItem(ctx, sess, item.ID)
			return err
		}); err != nil {
			return "", err
		}
		if !has {
			return x.fork(ctx, c, item)
		}
	}
	id = uuid.MustParse(existing.ID)
	if err := s.Require(ctx, c, "read", id); err != nil {
		return "", err
	}
	if existing.Status == domain.StatusArchived {
		if err := s.Require(ctx, c, "delete", id); err != nil {
			return "", err
		}
		if err := s.setStatus(ctx, c, id, domain.StatusArchived, domain.StatusActive, "agent.restore"); err != nil {
			return "", err
		}
	}
	return existing.ID, nil
}

// fork is _fork_catalog_agent: the install policy, the item's tools bound to
// the caller's connections, then the agent with no model.
func (x CatalogAgents) fork(ctx context.Context, c authn.Caller, item catalogapi.CatalogItem) (string, error) {
	s := x.S
	if x.Policy == nil {
		return "", &UnwiredError{Feature: "the catalog install policy"}
	}
	if err := x.Policy.RequireAllowed(ctx, c, item.RegistryID, item.RegistryTrust); err != nil {
		return "", err
	}
	sp, err := parseAgentSpec(item)
	if err != nil {
		return "", err
	}
	if _, ok := sp.raw["tools"].([]any); !ok {
		return "", fmt.Errorf("catalog agent %s has no tools list in its spec", domain.SkillRepr(item.Name))
	}
	var errs fieldErrs
	tools := sp.tools(&errs)
	if len(errs) > 0 {
		b, _ := json.Marshal(errs)
		return "", fmt.Errorf("catalog agent %s has malformed tools: %s", domain.SkillRepr(item.Name), b)
	}
	if err := s.bindMCP(ctx, c, tools, false); err != nil {
		return "", err
	}
	if err := s.requireUsable(ctx, c, tools, nil); err != nil {
		return "", err
	}
	targets, tools := liftApprovals(tools)
	raw, err := StoredJSON(tools)
	if err != nil {
		return "", err
	}
	description := item.Description
	if description == nil {
		description = sp.str("description")
	}
	var planning *bool
	if p, ok := sp.raw["planning"].(bool); ok {
		planning = &p
	}
	a := domain.Agent{
		ID: uuid.NewString(), Name: item.Name, Status: domain.StatusActive, Description: description,
		Instruction: sp.str("instruction"), Tools: raw, Planning: planning, AgentType: "stateless", RegistryItemID: &item.ID,
	}
	err = retrySlug(func() error {
		return s.write(ctx, c.Workspace, func(sess db.Session) error {
			if err := s.insertAgent(ctx, sess, c, &a, nil, s.d.Now()); err != nil {
				return err
			}
			if err := s.syncLoans(ctx, a.ID, tools, nil); err != nil {
				return err
			}
			if err := x.Items.MarkInstalled(ctx, sess, item.ID, a.ID, item.Version); err != nil {
				return err
			}
			return s.syncApprovals(ctx, sess, c, a.ID, targets, false)
		})
	})
	if err != nil {
		return "", err
	}
	return a.ID, nil
}
