package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// CodeToolset is one code toolset's catalogue entry (get_code_tools_metadata()[name]).
// DisplayName is the raw display_name, empty when unset.
type CodeToolset struct {
	Name                     string
	Description              string
	DisplayName              string
	Category                 string
	Plane                    *string
	Group                    *string
	RequiresUserConfirmation bool
	Methods                  []CodeToolMethod
}

// CodeToolMethod is one entry of a toolset's available_methods.
type CodeToolMethod struct {
	Name                     string
	DisplayName              string
	Description              string
	Effect                   *string
	RequiresUserConfirmation bool
}

// ToolsMCPInstance is an MCP server instance with get_available_tools()
// (decoded JSON entries, as persisted).
type ToolsMCPInstance struct {
	ID    string
	Name  string
	Tools []any
}

// ToolsMCP lists the MCP tools of the caller's workspace (connections module).
type ToolsMCP interface {
	// InstanceTools is MCPServerInstanceService.list() in its order; with
	// instanceID set it is that one instance (mcp_service.get), or none.
	InstanceTools(ctx context.Context, c authn.Caller, instanceID string) ([]ToolsMCPInstance, error)
}

// AgentCatalog is the catalog's agent registry (catalog module).
type AgentCatalog interface {
	// PresetsJSON is GET /agents/presets' body (list_presets rendered as AgentPresetResponse).
	PresetsJSON(ctx context.Context, c authn.Caller) (any, error)
	// Install is _resolve_agent_id then install_catalog_agent: the id of the
	// workspace copy (created, existing or restored from archived);
	// domain.ErrAgentNotFound when nothing resolves.
	Install(ctx context.Context, c authn.Caller, identifier string) (agentID string, err error)
}

// ExportSkills is the skill store the export reads (skills route group).
type ExportSkills interface {
	// ExportSkills is SkillService.list() (the workspace's own skills, repository
	// order) with Content set to read_skill_md(skill) for every skill that is not
	// source_type github with a source_url. A ValueError is *api.ExportInvalidError.
	ExportSkills(ctx context.Context, c authn.Caller) ([]domain.ExportSkill, error)
}

// ExportMCPInstance is an MCP server instance as the export reads it.
type ExportMCPInstance struct {
	ID        string
	Name      string
	ManagedBy string
	IsCatalog bool
	// Spec is get_transport_spec_for_instance(instance), key order kept.
	Spec wirejson.Object
	// EnvVars is get_configured_env_vars().
	EnvVars []string
	// ContextSigning is bool(json_spec.get("context_signing")).
	ContextSigning bool
}

// ExportMCPs lists the MCP server instances (connections module).
type ExportMCPs interface {
	// ExportInstances is MCPServerInstanceService.list() in its order with each
	// transport spec; a spec it cannot build is *api.ExportInvalidError (ValueError).
	ExportInstances(ctx context.Context, c authn.Caller) ([]ExportMCPInstance, error)
}

// ExportTriggerRow is a trigger row as the export reads it.
type ExportTriggerRow struct {
	ID             string
	Name           string
	TriggerType    string
	AgentID        string
	Conditions     any
	TaskParameters wirejson.Object
	CronExpression string
	Timezone       string
	IsActive       bool
}

// ExportTriggers lists the workspace's triggers (streams module).
type ExportTriggers interface {
	// ExportTriggers is TriggerRepository.list_all() in its order.
	ExportTriggers(ctx context.Context, c authn.Caller) ([]ExportTriggerRow, error)
}

// ExportWorkspaces names the caller's workspace (identity module).
type ExportWorkspaces interface {
	// WorkspaceName is the workspaces row's name (load_workspace); a missing row is an error.
	WorkspaceName(ctx context.Context, c authn.Caller) (string, error)
}

// MiscDeps are the ports of GET /agents/tools, the presets, install and the export.
type MiscDeps struct {
	ToolsMCP         ToolsMCP
	AgentCatalog     AgentCatalog
	ExportSkills     ExportSkills
	ExportMCPs       ExportMCPs
	ExportTriggers   ExportTriggers
	ExportWorkspaces ExportWorkspaces
}
