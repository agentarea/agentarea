package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

func (s *Service) agent(ctx context.Context, p Principal, agentID string) (agentsapi.Definition, api.AgentSpec, error) {
	ws, err := workspace(p)
	if err != nil {
		return agentsapi.Definition{}, api.AgentSpec{}, err
	}
	d, err := s.d.Agents.Definition(ctx, ws, agentID)
	if errors.Is(err, agentsapi.ErrNotFound) {
		err = fmt.Errorf("%w: %w", ErrNotFound, err)
	}
	if err != nil {
		return agentsapi.Definition{}, api.AgentSpec{}, err
	}
	return d, agentSpec(d), nil
}

// runAgent is the run's own agent: the workspace's, else the catalog agent
// with that id, run from its definition once the install policy allowed it.
func (s *Service) runAgent(ctx context.Context, p Principal, agentID string) (agentsapi.Definition, api.AgentSpec, error) {
	d, spec, err := s.agent(ctx, p, agentID)
	if !errors.Is(err, ErrNotFound) || s.d.CatalogAgents == nil {
		return d, spec, err
	}
	ws, err := workspace(p)
	if err != nil {
		return agentsapi.Definition{}, api.AgentSpec{}, err
	}
	d, err = s.d.CatalogAgents.CatalogDefinition(ctx, ws, p.UserID, agentID)
	var refused *agentsapi.AgentRefusedError
	switch {
	case errors.Is(err, agentsapi.ErrNotFound):
		return agentsapi.Definition{}, api.AgentSpec{}, fmt.Errorf("%w: %w", ErrNotFound, err)
	case errors.As(err, &refused):
		return agentsapi.Definition{}, api.AgentSpec{}, nonRetryable("CatalogInstallRefusedError", refused.Msg, err)
	case err != nil:
		return agentsapi.Definition{}, api.AgentSpec{}, err
	}
	return d, agentSpec(d), nil
}

func agentSpec(d agentsapi.Definition) api.AgentSpec {
	spec := api.AgentSpec{
		ID: d.ID, Name: d.Name, Description: d.Description, Instruction: d.Instruction, AgentType: d.AgentType,
		ModelID: d.ModelID, Planning: d.Planning, A2UIEnabled: d.A2UIEnabled, ReasoningEffort: d.ReasoningEffort,
		ReasoningMaxTokens: d.ReasoningMaxTokens,
	}
	if d.AnswerCheck != nil {
		spec.AnswerCheck = &api.AnswerCheck{Enabled: d.AnswerCheck.Enabled, Language: d.AnswerCheck.Language, RewriteInstruction: d.AnswerCheck.RewriteInstruction}
	}
	if d.Tools != nil {
		spec.Tools = make([]api.ToolConfig, len(d.Tools))
		for i, t := range d.Tools {
			st := t.Settings
			spec.Tools[i] = api.ToolConfig{Type: t.Type, Name: t.Name, Settings: api.ToolConfigSettings{
				DisabledMethods: st.DisabledMethods, ImageModelID: st.ImageModelID, VideoModelID: st.VideoModelID,
				AllowedTools: st.AllowedTools, OpenAPIConnectionID: st.OpenAPIConnectionID, LoadMode: st.LoadMode,
				DescriptionOverride: st.DescriptionOverride, DelegateAgentID: st.AgentID, A2AURL: st.A2AURL, AuthSecretName: st.AuthSecretName,
			}}
		}
	}
	return spec
}

func (s *Service) model(ctx context.Context, p Principal, modelID string) (api.ResolvedModel, error) {
	m, err := s.d.Resolver.Model(ctx, modelsapi.Principal(p), modelID)
	switch {
	case errors.Is(err, modelsapi.ErrNotFound):
		err = fmt.Errorf("%w: %w", ErrNotFound, err)
	case errors.Is(err, modelsapi.ErrRefused):
		err = fmt.Errorf("%w: %w", ErrRefused, err)
	}
	return m, err
}

func (s *Service) budget(ctx context.Context, p Principal) (*api.BudgetPolicy, error) {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return nil, err
	}
	b, err := s.d.Caps.CurrentBudget(ctx, governanceapi.RunPrincipal{Workspace: ws, UserID: p.UserID, AgentID: p.AgentID})
	if err != nil {
		return nil, err
	}
	return toRunBudget(b), nil
}

// runManifest is the sandbox image's manifest as a run's configuration keeps it.
func runManifest(m *sandboxapi.RuntimeManifest) *api.RuntimeManifest {
	if m == nil {
		return nil
	}
	return &api.RuntimeManifest{
		SchemaVersion: m.SchemaVersion, ImageVersion: m.ImageVersion, ManagedEnvironment: m.ManagedEnvironment,
		PythonVersion: m.Python.Version, PythonExecutable: m.Python.Executable,
		NodeVersion: m.Node.Version, NPMVersion: deref(m.Node.NPMVersion),
		Tools: m.Tools, Packages: m.Packages, Browser: m.Features.Browser,
		EnvironmentMutable: m.Features.ManagedEnvironmentMutation, ArbitraryCode: m.Features.ArbitraryWorkspaceCode,
		Supervisor: api.Supervisor(m.ExecutionSupervisor),
	}
}

// auditRecord is a task log audit line as governance stores it: the task is the resource.
func auditRecord(l domain.AuditLine) governanceapi.AuditRecord {
	return governanceapi.AuditRecord{EventID: l.EventID, Action: l.Action, ResourceType: "task", ResourceID: l.TaskID, ActorType: l.ActorType, ActorID: l.ActorID, Metadata: l.Metadata}
}

func modelMessages(in []domain.ModelMessage) []modelsapi.Message {
	out := make([]modelsapi.Message, len(in))
	for i, m := range in {
		msg := modelsapi.Message{Role: m.Role, Content: m.Content, ToolCallID: m.ToolCallID, Name: m.Name}
		for _, part := range m.Parts {
			msg.Parts = append(msg.Parts, modelsapi.ContentPart(part))
		}
		for _, c := range m.ToolCalls {
			msg.ToolCalls = append(msg.ToolCalls, modelsapi.ToolCall(c))
		}
		out[i] = msg
	}
	return out
}

func modelTools(in []api.ToolDefinition) []modelsapi.ToolDefinition {
	if in == nil {
		return nil
	}
	out := make([]modelsapi.ToolDefinition, len(in))
	for i, t := range in {
		out[i] = modelsapi.ToolDefinition{Name: t.Name, Description: t.Description, Parameters: t.Parameters}
	}
	return out
}
