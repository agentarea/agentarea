package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// RunSettings are the deployment's run settings a RunConfig carries.
type RunSettings struct {
	OutageWait        api.OutageWait
	SkillsWindowShare float64
	// ToolSearchURL is the SearXNG-compatible service search_web asks
	// (AGENTAREA_TOOL_SEARCH_URL); empty, every search answers an error.
	ToolSearchURL string
}

// ResolveInput is what a run starts from (ResolveRunConfigRequest).
type ResolveInput struct {
	TaskID               string
	MCPInstanceIDs       []string
	SkillIDs             []string
	FileIDs              []string
	ModelOverride        string
	ProjectID            string
	TriggerEvent         map[string]any
	TriggerEventFileName string
	Policy               api.Policy
	Governance           api.GovernanceSnapshot
}

func definitionFailure(errType, msg string, err error) error {
	if errors.Is(err, ErrNotFound) || errors.Is(err, ErrRefused) {
		return nonRetryable(errType, msg+": "+err.Error(), err)
	}
	return err
}

// ResolveRunConfig is the run's first activity: every definition the run
// uses is read here, once, into one RunConfig (decision 3c).
func (s *Service) ResolveRunConfig(ctx context.Context, p Principal, in ResolveInput) (api.RunConfig, error) {
	ws, err := workspace(p)
	if err != nil {
		return api.RunConfig{}, err
	}
	if s.d.Definitions == nil || s.d.Agents == nil || s.d.Resolver == nil || s.d.Runtime == nil {
		return api.RunConfig{}, errors.New("resolving a run needs the agent, model, runtime and run definitions ports")
	}
	if s.d.Settings.OutageWait.RetryWindow <= 0 || s.d.Settings.SkillsWindowShare <= 0 {
		return api.RunConfig{}, errors.New("the run settings (outage wait, skills window share) are not configured")
	}
	defs := s.d.Definitions
	def, agent, err := s.runAgent(ctx, p, p.AgentID)
	if err != nil {
		return api.RunConfig{}, definitionFailure("AgentNotFoundError", "Agent "+p.AgentID+" not found", err)
	}
	if def.Archived {
		return api.RunConfig{}, nonRetryable("AgentArchived", fmt.Sprintf("agent %s is archived", p.AgentID), nil)
	}
	modelID := in.ModelOverride
	if modelID == "" {
		modelID = agent.ModelID
	}
	if modelID == "" {
		return api.RunConfig{}, nonRetryable("NoModelBoundError", fmt.Sprintf("Agent %s has no model bound. Assign a model instance to the agent, or pass override_model when starting the task.", p.AgentID), nil)
	}
	model, err := s.model(ctx, p, modelID)
	if err != nil {
		return api.RunConfig{}, definitionFailure("ModelInstanceNotFoundError", "Model instance "+modelID+" or its ModelSpec was not found", err)
	}
	if model.ContextWindow <= 0 {
		return api.RunConfig{}, nonRetryable("ValueError", fmt.Sprintf("ModelSpec for %s has no valid context_window", modelID), nil)
	}
	tools, err := defs.Tools(ctx, p, ToolsRequest{TaskID: in.TaskID, Agent: agent, MCPInstanceIDs: in.MCPInstanceIDs, Policy: in.Policy})
	if err != nil {
		return api.RunConfig{}, definitionFailure("ToolResolutionError", "the agent's tools could not be resolved", err)
	}
	skills, withheld, err := defs.Skills(ctx, p, agent, in.SkillIDs)
	if err != nil {
		return api.RunConfig{}, definitionFailure("SkillNotFound", "the run's skills could not be resolved", err)
	}
	projects, err := defs.ProjectInstructions(ctx, p, in.ProjectID)
	if err != nil {
		return api.RunConfig{}, definitionFailure("ProjectNotFound", "the run's project could not be resolved", err)
	}
	cfg := api.RunConfig{
		TaskID: in.TaskID, AgentID: p.AgentID, WorkspaceID: p.WorkspaceID, UserID: p.UserID, ResolvedAt: s.now(),
		Agent: agent, Model: model, Policy: in.Policy, Governance: in.Governance, ProjectInstructions: projects,
		ContextStrategy: model.DefaultContextStrategy, Tools: tools.Tools, SearchableTools: tools.SearchableTools,
		ToolProviders: tools.ToolProviders, Bindings: bindingsWithPolicyNames(tools.Bindings),
		OpenAPIOperationTools: tools.OpenAPIOperationTools, Skills: skills, WithheldSkills: withheld,
		SkillsWindowShare: s.d.Settings.SkillsWindowShare, OutageWait: s.d.Settings.OutageWait,
	}
	cfg.Agent.ModelID = modelID
	if err := reservedNames(cfg.Tools); err != nil {
		return api.RunConfig{}, err
	}
	if err := s.addDelegates(ctx, p, &cfg); err != nil {
		return api.RunConfig{}, err
	}
	manifest, err := s.d.Runtime.Manifest(ctx)
	if err != nil {
		cfg.RuntimeError = err.Error()
	}
	cfg.Runtime = runManifest(manifest)
	cfg.Inputs, err = defs.Inputs(ctx, p, InputsRequest{TaskID: in.TaskID, FileIDs: in.FileIDs, TriggerEvent: in.TriggerEvent, TriggerEventFileName: in.TriggerEventFileName})
	if err != nil {
		return api.RunConfig{}, definitionFailure("ValueError", "the run's files could not be prepared", err)
	}
	skillIDs := make([]string, 0, len(skills))
	for _, sk := range skills {
		skillIDs = append(skillIDs, sk.ID)
	}
	cfg.ConfigHash = domain.AgentConfigHash(agent.Instruction, modelID, toolConfigsJSON(agent.Tools), agent.Planning, agent.AgentType, skillIDs)
	if in.TaskID != "" {
		err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
			ok, err := s.store.MergeMetadata(ctx, tx, in.TaskID, map[string]any{"agent_config_hash": cfg.ConfigHash}, s.now())
			if err == nil && !ok {
				s.d.Log.WarnContext(ctx, "task vanished before its config hash could be recorded", "task_id", in.TaskID)
			}
			return err
		})
		if err != nil {
			s.d.Log.WarnContext(ctx, "failed to record the config hash", "task_id", in.TaskID, "error", err)
		}
	}
	return cfg, nil
}

func toolConfigsJSON(tools []api.ToolConfig) []any {
	if tools == nil {
		return nil
	}
	b, err := json.Marshal(tools)
	if err != nil {
		return nil
	}
	var out []any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	return out
}

// bindingsWithPolicyNames gives a connection's tool the id-qualified name that alone may allow it.
func bindingsWithPolicyNames(in map[string]api.ToolBinding) map[string]api.ToolBinding {
	out := maps.Clone(in)
	for name, b := range out {
		if len(b.PolicyNames) > 0 {
			continue
		}
		switch {
		case b.Source == "mcp" && b.MCP != nil:
			raw := b.MCP.RawName
			if raw == "" {
				raw = name
			}
			b.PolicyNames = []string{"mcp:" + b.MCP.InstanceID + ":" + raw}
		case b.Source == "openapi" && b.OpenAPI != nil:
			b.PolicyNames = []string{"openapi:" + b.OpenAPI.ConnectionID + ":" + name}
		case b.Source == "remote_agent" && b.RemoteAgent != nil && b.RemoteAgent.A2AURL != "":
			b.PolicyNames = []string{"a2a:" + b.RemoteAgent.A2AURL}
		}
		out[name] = b
	}
	return out
}

func reservedNames(tools []api.ToolDefinition) error {
	for _, t := range tools {
		if domain.ControlFlowTool(t.Name) {
			return nonRetryable("ReservedToolName", fmt.Sprintf("tool %q collides with a built-in tool of the run", t.Name), nil)
		}
	}
	return nil
}

// addDelegates offers the model a tool per delegate (AgentToolBuilder,
// resolve_agent_tools_activity): a local one the agent it was saved with, unless archived
// or gone; a remote one reached at its a2a_url.
func (s *Service) addDelegates(ctx context.Context, p Principal, cfg *api.RunConfig) error {
	cfg.Delegates = map[string]api.Delegate{}
	for _, t := range cfg.Agent.Tools {
		if t.Type != "agent" {
			continue
		}
		if t.Settings.A2AURL != "" {
			if err := addRemoteDelegate(cfg, t); err != nil {
				return err
			}
			continue
		}
		if t.Settings.DelegateAgentID == "" {
			continue
		}
		def, d, err := s.agent(ctx, p, t.Settings.DelegateAgentID)
		if errors.Is(err, ErrNotFound) || errors.Is(err, ErrRefused) {
			s.d.Log.WarnContext(ctx, "delegate agent is not available", "agent_id", t.Settings.DelegateAgentID, "error", err)
			continue
		}
		if err != nil {
			return err
		}
		if def.Archived {
			s.d.Log.WarnContext(ctx, "delegate agent is archived", "agent_id", t.Settings.DelegateAgentID, "delegate", t.Name)
			continue
		}
		name := domain.DelegateToolName(t.Name)
		if _, taken := cfg.Bindings[name]; taken {
			return nonRetryable("ToolResolutionError", fmt.Sprintf("delegate %q and another tool of the agent are both offered to the model as %q; rename one", t.Name, name), nil)
		}
		desc := firstOf(t.Settings.DescriptionOverride, d.Description, "Agent: "+t.Name)
		cfg.Delegates[name] = api.Delegate{AgentID: t.Settings.DelegateAgentID, AgentName: t.Name, Description: desc}
		tool := delegateTool(name, t.Name, desc)
		cfg.Tools = append(cfg.Tools, tool)
		cfg.ToolProviders = append(cfg.ToolProviders, api.ToolProvider{Name: t.Name, ProviderType: "agent", Description: "Agent: " + t.Name, Tools: []api.ToolDefinition{tool}})
	}
	return nil
}

// addRemoteDelegate is the A2A binding of a delegate (A2AAgentTool): its tool runs on the
// remote_agent caller.
func addRemoteDelegate(cfg *api.RunConfig, t api.ToolConfig) error {
	name := domain.DelegateToolName(t.Name)
	if _, taken := cfg.Bindings[name]; taken {
		return nonRetryable("ToolResolutionError", fmt.Sprintf("delegate %q and another tool of the agent are both offered to the model as %q; rename one", t.Name, name), nil)
	}
	tool := delegateTool(name, t.Name, firstOf(t.Settings.DescriptionOverride, "Remote agent: "+t.Name))
	if cfg.Bindings == nil {
		cfg.Bindings = map[string]api.ToolBinding{}
	}
	cfg.Bindings[name] = api.ToolBinding{Source: "remote_agent", PolicyNames: []string{"a2a:" + t.Settings.A2AURL},
		RemoteAgent: &api.RemoteAgentBinding{AgentName: t.Name, A2AURL: t.Settings.A2AURL, AuthSecretName: t.Settings.AuthSecretName}}
	cfg.Tools = append(cfg.Tools, tool)
	cfg.ToolProviders = append(cfg.ToolProviders, api.ToolProvider{Name: t.Name, ProviderType: "agent", Description: "Agent: " + t.Name, Tools: []api.ToolDefinition{tool}})
	return nil
}

// delegateTool is AgentDelegationTool's function definition.
func delegateTool(name, agentName, desc string) api.ToolDefinition {
	return api.ToolDefinition{
		Name:        name,
		Description: fmt.Sprintf("Delegate a task to the '%s' agent. %s", agentName, desc),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"message": map[string]any{
					"type":        "string",
					"description": fmt.Sprintf("The task or question to send to the '%s' agent. Be specific and provide all necessary context.", agentName),
				},
			},
			"required": []any{"message"},
		},
	}
}

func firstOf(xs ...string) string {
	for _, x := range xs {
		if x != "" {
			return x
		}
	}
	return ""
}
