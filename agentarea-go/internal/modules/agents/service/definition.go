package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// Definitions implements api.Definitions: get_with_skills as the run's
// config activity reads it, over the read pool.
type Definitions struct{ Service *Service }

var _ api.Definitions = Definitions{}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// Definition is the tenant agent with its skills; archived agents included.
func (d Definitions) Definition(ctx context.Context, ws scope.Workspace, agentID string) (api.Definition, error) {
	id, err := uuid.Parse(agentID)
	if err != nil {
		return api.Definition{}, api.ErrNotFound
	}
	a, ok, err := d.Service.load(ctx, ws, id, true)
	if err != nil {
		return api.Definition{}, err
	}
	if !ok {
		return api.Definition{}, api.ErrNotFound
	}
	return definitionOf(a), nil
}

func definitionOf(a domain.Agent) api.Definition {
	out := api.Definition{
		ID: a.ID, Name: a.Name, Description: str(a.Description), Instruction: str(a.Instruction), AgentType: a.AgentType,
		ModelID: str(a.ModelID), Planning: a.Planning != nil && *a.Planning, A2UIEnabled: a.A2UIEnabled != nil && *a.A2UIEnabled,
		ReasoningEffort: str(a.ReasoningEffort), Archived: a.Status == domain.StatusArchived, ClientID: str(a.ClientID),
		RegistryItemID: str(a.RegistryItemID),
	}
	if a.ReasoningMaxTokens != nil {
		v := int(*a.ReasoningMaxTokens)
		out.ReasoningMaxTokens = &v
	}
	out.AnswerCheck = answerCheck(a.AnswerCheck)
	for _, t := range toolsFromColumn(a.Tools) {
		out.Tools = append(out.Tools, apiTool(t))
	}
	for _, sk := range a.Skills {
		out.Skills = append(out.Skills, api.Skill{ID: sk.ID, Name: sk.Name, Description: str(sk.Description),
			SourceType: sk.SourceType, Package: str(sk.Package), RegistryItemID: str(sk.RegistryItemID)})
	}
	return out
}

func apiTool(t domain.Tool) api.Tool {
	out := api.Tool{Type: t.Type, Name: t.Name}
	if t.Settings == nil {
		return out
	}
	s := t.Settings
	if s.DisabledMethods != nil {
		out.Settings.DisabledMethods = *s.DisabledMethods
	}
	out.Settings.ImageModelID, out.Settings.VideoModelID = str(s.ImageModelID), str(s.VideoModelID)
	out.Settings.DescriptionOverride, out.Settings.AgentID = str(s.DescriptionOverride), str(s.AgentID)
	out.Settings.A2AURL, out.Settings.AuthSecretName = str(s.A2AURL), str(s.AuthSecretName)
	out.Settings.OpenAPIConnectionID, out.Settings.LoadMode = str(s.OpenAPIConnectionID), str(s.LoadMode)
	switch {
	case s.MCPAllowed != nil:
		out.Settings.AllowedTools = []string{}
		for _, p := range *s.MCPAllowed {
			out.Settings.AllowedTools = append(out.Settings.AllowedTools, p.ToolName)
		}
	case s.OpenAPIAllowed != nil:
		out.Settings.AllowedTools = append([]string{}, *s.OpenAPIAllowed...)
	}
	return out
}
