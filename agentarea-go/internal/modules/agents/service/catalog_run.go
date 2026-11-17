package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// CatalogRun implements api.CatalogRuns over the catalog's agent items.
type CatalogRun struct {
	S      *Service
	Items  CatalogItems
	Policy SkillInstallPolicy
}

var _ api.CatalogRuns = CatalogRun{}

// CatalogDefinition is get_with_catalog(to_run=True) past the tenant lookup:
// the install policy, then the item projected (_project_catalog_item) with its
// MCP tools bound to the workspace's connections by name, unbound names kept.
func (x CatalogRun) CatalogDefinition(ctx context.Context, ws scope.Workspace, userID, agentID string) (api.Definition, error) {
	if x.Items == nil {
		return api.Definition{}, &UnwiredError{Feature: "the catalog's agent items"}
	}
	if x.Policy == nil {
		return api.Definition{}, &UnwiredError{Feature: "the catalog install policy"}
	}
	if _, err := uuid.Parse(agentID); err != nil {
		return api.Definition{}, api.ErrNotFound
	}
	item, ok, err := x.Items.AgentItem(ctx, ws, agentID)
	if err != nil {
		return api.Definition{}, err
	}
	if !ok {
		return api.Definition{}, api.ErrNotFound
	}
	c := authn.Caller{Principal: authn.Principal{UserID: userID}, Workspace: ws}
	if err := x.Policy.RequireAllowed(ctx, c, item.RegistryID, item.RegistryTrust); err != nil {
		var refused *govapi.InstallRefusedError
		if errors.As(err, &refused) {
			return api.Definition{}, &api.AgentRefusedError{Msg: err.Error()}
		}
		return api.Definition{}, err
	}
	sp, err := parseAgentSpec(item)
	if err != nil {
		return api.Definition{}, err
	}
	a := domain.Agent{ID: item.ID, Name: item.Name, Status: domain.StatusActive, Description: item.Description,
		Instruction: sp.str("instruction"), AgentType: "stateless", RegistryItemID: &item.ID}
	if a.Description == nil {
		a.Description = sp.str("description")
	}
	if p, ok := sp.raw["planning"].(bool); ok {
		a.Planning = &p
	}
	if _, ok := sp.raw["tools"].([]any); ok {
		var errs fieldErrs
		tools := sp.tools(&errs)
		if len(errs) > 0 {
			b, _ := json.Marshal(errs)
			return api.Definition{}, fmt.Errorf("catalog agent %s has malformed tools: %s", domain.SkillRepr(item.Name), b)
		}
		if err := x.S.bindMCP(ctx, c, tools, false); err != nil {
			return api.Definition{}, err
		}
		if a.Tools, err = StoredJSON(tools); err != nil {
			return api.Definition{}, err
		}
	}
	return definitionOf(a), nil
}
