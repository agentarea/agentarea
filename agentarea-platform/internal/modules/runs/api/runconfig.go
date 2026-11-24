package api

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// RunConfig is everything a run executes under, resolved once by its first
// activity (resolve_run_config_activity, decision 3c). Later activities get
// the part they need from the workflow and read no definition again: agent,
// model, provider, tools, connections, skills, delegates and projects are
// fixed here. What later activities may still read live is listed in
// workflows/ACTIVITIES.md ("Live reads"): credentials by reference, spend caps
// and ledger sums, billing, wallet, skill package bytes, the task log.
//
// It lives in api, not domain, because it carries money.Decimal (domain is
// standard library only, rule 3) and because other modules' api answers are
// its parts.
type RunConfig struct {
	TaskID      string    `json:"task_id"`
	AgentID     string    `json:"agent_id"`
	WorkspaceID string    `json:"workspace_id"`
	UserID      string    `json:"user_id"`
	ResolvedAt  time.Time `json:"resolved_at"`
	// ConfigHash is the agent's declared configuration as resolved, stamped on the task.
	ConfigHash string `json:"config_hash"`

	Agent  AgentSpec     `json:"agent"`
	Model  ResolvedModel `json:"model"`
	Policy Policy        `json:"policy"`
	// Governance is the task's governance snapshot when the run started; a
	// continuation replaces it (and Policy) through the continue_execution update.
	Governance GovernanceSnapshot `json:"governance"`

	// ProjectInstructions are the project's and its ancestors', root first.
	ProjectInstructions []string `json:"project_instructions"`
	// ContextStrategy is static, hybrid or dynamic.
	ContextStrategy string `json:"context_strategy"`

	// Tools are the model-facing definitions (static and hybrid strategies).
	Tools []ToolDefinition `json:"tools"`
	// SearchableTools are revealed by load_tools.
	SearchableTools []SearchableTool `json:"searchable_tools"`
	// ToolProviders are activated by activate_tool_source (dynamic strategy).
	ToolProviders []ToolProvider `json:"tool_providers"`
	// Bindings say how each model-facing tool name runs; the tool activity
	// gets only the binding of the tool it calls.
	Bindings map[string]ToolBinding `json:"bindings"`
	// OpenAPIOperationTools maps an OpenAPI attachment's name to its operation tools, for policy names.
	OpenAPIOperationTools map[string][]string `json:"openapi_operation_tools"`
	// Delegates are the local agents the run may delegate to, by tool name.
	Delegates map[string]Delegate `json:"delegates"`

	Skills         []Skill         `json:"skills"`
	WithheldSkills []WithheldSkill `json:"withheld_skills"`
	// SkillsWindowShare is the share of the model window all activated skills may take.
	SkillsWindowShare float64 `json:"skills_window_share"`

	// Runtime is the sandbox runtime manifest, nil with RuntimeError when it could not be read.
	Runtime      *RuntimeManifest `json:"runtime"`
	RuntimeError string           `json:"runtime_error"`
	// Inputs are the task's selected files and trigger event file, copied into the workspace.
	Inputs []InputFile `json:"inputs"`

	OutageWait OutageWait `json:"outage_wait"`
}

// AgentSpec is the agent row as the run uses it (catalog built-ins included).
type AgentSpec struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	Instruction string `json:"instruction"`
	AgentType   string `json:"agent_type"`
	ModelID     string `json:"model_id"`
	Planning    bool   `json:"planning"`
	A2UIEnabled bool   `json:"a2ui_enabled"`
	// ReasoningEffort is a level; ReasoningMaxTokens a budget; both empty keep the model's default.
	ReasoningEffort    string       `json:"reasoning_effort"`
	ReasoningMaxTokens *int         `json:"reasoning_max_tokens"`
	AnswerCheck        *AnswerCheck `json:"answer_check"`
	Tools              []ToolConfig `json:"tools"`
}

// ToolConfig is one entry of the agent's tools, as saved.
type ToolConfig struct {
	// Type is code, mcp, agent or openapi.
	Type     string             `json:"type"`
	Name     string             `json:"name"`
	Settings ToolConfigSettings `json:"settings"`
}

// ToolConfigSettings holds every type's settings; a type reads only its own.
type ToolConfigSettings struct {
	DisabledMethods []string `json:"disabled_methods"`
	ImageModelID    string   `json:"image_model_id"`
	VideoModelID    string   `json:"video_model_id"`
	// AllowedTools narrows an MCP server or OpenAPI connection; nil allows all.
	AllowedTools        []string `json:"allowed_tools"`
	OpenAPIConnectionID string   `json:"openapi_connection_id"`
	LoadMode            string   `json:"load_mode"`
	DescriptionOverride string   `json:"description_override"`
	DelegateAgentID     string   `json:"agent_id"`
	A2AURL              string   `json:"a2a_url"`
	AuthSecretName      string   `json:"auth_secret_name"`
}

// ResolvedModel, ModelPrices and ProviderProfile are owned by models.
type (
	ResolvedModel   = modelsapi.ResolvedModel
	ModelPrices     = modelsapi.ModelPrices
	ProviderProfile = modelsapi.ProviderProfile
)

// Policy is the run's effective governance policy (governance EffectivePolicy).
type Policy struct {
	Budget          *BudgetPolicy        `json:"budget"`
	Tokens          *TokenPolicy         `json:"tokens"`
	Execution       *ExecutionPolicy     `json:"execution"`
	Tools           *ToolsPolicy         `json:"tools"`
	Approval        *ApprovalPolicy      `json:"approval"`
	ContentSafety   *ContentSafetyPolicy `json:"content_safety"`
	SourcePolicyIDs []string             `json:"source_policy_ids"`
	ResolverVersion string               `json:"resolver_version"`
}

type BudgetPolicy struct {
	MonthlySpendCap      *money.Decimal `json:"monthly_spend_cap_usd"`
	AgentMonthlySpendCap *money.Decimal `json:"agent_monthly_spend_cap_usd"`
	RunBudget            *money.Decimal `json:"run_budget_usd"`
	ServiceBudget        *money.Decimal `json:"service_budget_usd"`
	SpendCaps            []SpendCap     `json:"spend_caps"`
}

// SpendCap caps part of the spend; empty fields do not narrow it.
type SpendCap struct {
	Amount       money.Decimal `json:"amount_usd"`
	OwnAgent     bool          `json:"own_agent"`
	ClientID     string        `json:"client_id"`
	ConnectionID string        `json:"connection_id"`
	Tool         string        `json:"tool"`
	Currency     string        `json:"currency"`
	// Category is llm, tools or empty; Period is run or empty (calendar month).
	Category string `json:"category"`
	Period   string `json:"period"`
}

type TokenPolicy struct {
	MaxTokens        *int `json:"max_tokens"`
	MaxTokensPerCall *int `json:"max_tokens_per_call"`
}

type ExecutionPolicy struct {
	MaxModelTurns       *int `json:"max_model_turns"`
	MaxToolCallsPerTurn *int `json:"max_tool_calls_per_turn"`
	MaxToolCallsTotal   *int `json:"max_tool_calls_total"`
}

type ToolsPolicy struct {
	// Allowed nil allows every tool; empty allows none.
	Allowed []string `json:"allowed"`
	Denied  []string `json:"denied"`
}

type ApprovalPolicy struct {
	RequiresHumanApproval *bool               `json:"requires_human_approval"`
	EscalationRules       []string            `json:"escalation_rules"`
	Approvers             []string            `json:"approvers"`
	ApproversByTool       map[string][]string `json:"approvers_by_tool"`
}

type ContentSafetyPolicy struct {
	PromptInjectionDetection *bool        `json:"prompt_injection_detection_enabled"`
	AnswerCheck              *AnswerCheck `json:"answer_check"`
}

type AnswerCheck struct {
	Enabled            bool   `json:"enabled"`
	Language           string `json:"language"`
	RewriteInstruction string `json:"rewrite_instruction"`
}

// GovernanceSnapshot is the task's governance_snapshot metadata.
type GovernanceSnapshot struct {
	Revision int `json:"revision"`
	// LimitCeilings is keyed by the failure reason a limit stops a run with
	// (iteration_limit, tool_call_limit, token_limit, budget_exceeded).
	LimitCeilings   map[string]string `json:"limit_ceilings"`
	RequestedPolicy Policy            `json:"requested_policy"`
	EffectivePolicy Policy            `json:"effective_policy"`
	ResolvedAt      time.Time         `json:"resolved_at"`
}

// ToolDefinition is a model-facing tool (OpenAI function form).
type ToolDefinition struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// SearchableTool is held back until load_tools reveals it.
type SearchableTool struct {
	Name         string         `json:"name"`
	Description  string         `json:"description"`
	ConnectionID string         `json:"connection_id"`
	Schema       map[string]any `json:"schema"`
	SourceType   string         `json:"source_type"`
}

// ToolProvider is one source activate_tool_source opens.
type ToolProvider struct {
	Name         string           `json:"name"`
	ProviderType string           `json:"provider_type"`
	Description  string           `json:"description"`
	Tools        []ToolDefinition `json:"tools"`
}

// ToolBinding is how one model-facing tool runs. Exactly one of the pointers
// is set, matching Source (mcp, openapi, code, remote_agent).
type ToolBinding struct {
	Source      string              `json:"source"`
	MCP         *MCPBinding         `json:"mcp"`
	OpenAPI     *OpenAPIBinding     `json:"openapi"`
	Code        *CodeBinding        `json:"code"`
	RemoteAgent *RemoteAgentBinding `json:"remote_agent"`
	// PolicyNames are the other names a policy rule may use for the tool;
	// RestrictingNames may only deny it or hold it for approval.
	PolicyNames      []string `json:"policy_names"`
	RestrictingNames []string `json:"restricting_names"`
	// Cost is the connector's declared price; nil when it declares none.
	Cost *ToolCost `json:"cost"`
}

// MCPBinding names the server behind an MCP tool and how to reach it.
type MCPBinding struct {
	InstanceID    string `json:"instance_id"`
	InstanceName  string `json:"instance_name"`
	AttachmentRef string `json:"attachment_ref"`
	RawName       string `json:"raw_name"`
	ServerName    string `json:"server_name"`
	ServerIcon    string `json:"server_icon"`
	// Transport is streamable_http, sse or gateway; URL is where.
	Transport string `json:"transport"`
	URL       string `json:"url"`
	// AuthConfigID and EnvSecretNames are resolved to headers and values at call time.
	AuthConfigID   string   `json:"auth_config_id"`
	EnvSecretNames []string `json:"env_secret_names"`
	// SignsContext sends the signed X-AgentArea-Context header.
	SignsContext bool `json:"signs_context"`
	// OpensApp names the MCP App the tool's result opens; empty for none.
	OpensApp string `json:"opens_app"`
}

// OpenAPIBinding is one operation of an OpenAPI connection.
type OpenAPIBinding struct {
	ConnectionID   string         `json:"connection_id"`
	ConnectionName string         `json:"connection_name"`
	OperationID    string         `json:"operation_id"`
	Method         string         `json:"method"`
	BaseURL        string         `json:"base_url"`
	Path           string         `json:"path"`
	Parameters     map[string]any `json:"parameters"`
	AuthConfigID   string         `json:"auth_config_id"`
	// Paid is set for connections that answer 402 and are paid from the agent's wallet.
	Paid bool `json:"paid"`
}

// CodeBinding is a method of a built-in toolset (agentarea/<namespace>).
type CodeBinding struct {
	Namespace       string   `json:"namespace"`
	Method          string   `json:"method"`
	DisabledMethods []string `json:"disabled_methods"`
	ImageModelID    string   `json:"image_model_id"`
	VideoModelID    string   `json:"video_model_id"`
}

// RemoteAgentBinding is a delegate reached over A2A; AgentName is its label.
type RemoteAgentBinding struct {
	AgentName      string `json:"agent_name"`
	A2AURL         string `json:"a2a_url"`
	AuthSecretName string `json:"auth_secret_name"`
}

// RemoteAgentTask is a task a remote delegate is still working on: the run waits
// for it and asks Endpoint about TaskID until it ends.
type RemoteAgentTask struct {
	TaskID   string `json:"task_id"`
	Endpoint string `json:"endpoint"`
	// Legacy is an A2A 0.3 agent (tasks/get).
	Legacy bool `json:"legacy"`
}

// ToolCost is what a connector declares a call costs and who pays.
type ToolCost struct {
	// Payer is platform or workspace.
	Payer          string        `json:"payer"`
	Connector      string        `json:"connector"`
	VendorCost     money.Decimal `json:"vendor_cost"`
	VendorCurrency string        `json:"vendor_currency"`
	Unit           string        `json:"unit"`
	// Declaration is the connector's cost declaration as written (ADR-0038):
	// a rate on an argument or the response, a reported or settled cost. Nil
	// charges VendorCost per call.
	Declaration map[string]any `json:"declaration,omitempty"`
}

// Delegate is a local agent a delegation tool hands its task to.
type Delegate struct {
	AgentID     string `json:"agent_id"`
	AgentName   string `json:"agent_name"`
	Description string `json:"description"`
}

// Skill is what the prompt lists of a skill; its body is read at activation.
type Skill struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	// Package is the package pointer as configured: a catalog digest or the workspace copy's key.
	Package string   `json:"package"`
	Files   []string `json:"files"`
}

type WithheldSkill struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Reason string `json:"reason"`
}

// RuntimeManifest is the sandbox image's manifest (schema version 2).
type RuntimeManifest struct {
	SchemaVersion      int               `json:"schema_version"`
	ImageVersion       string            `json:"image_version"`
	ManagedEnvironment string            `json:"managed_environment"`
	PythonVersion      string            `json:"python_version"`
	PythonExecutable   string            `json:"python_executable"`
	NodeVersion        string            `json:"node_version"`
	NPMVersion         string            `json:"npm_version"`
	Tools              map[string]string `json:"tools"`
	Packages           map[string]string `json:"packages"`
	Browser            string            `json:"browser"`
	EnvironmentMutable bool              `json:"environment_mutable"`
	ArbitraryCode      bool              `json:"arbitrary_code"`
	Supervisor         Supervisor        `json:"supervisor"`
}

type Supervisor struct {
	Path            string `json:"path"`
	SHA256          string `json:"sha256"`
	ProtocolVersion int    `json:"protocol_version"`
	CommandUID      int    `json:"command_uid"`
	CommandGID      int    `json:"command_gid"`
}

// InputFile is a file the run was given, as copied into the task's workspace.
type InputFile struct {
	Path string `json:"path"`
	// Kind is attachment or trigger_event.
	Kind   string `json:"kind"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// OutageWait is how a run rides out a dependency it cannot reach.
type OutageWait struct {
	RetryWindow time.Duration   `json:"retry_window"`
	Backoff     []time.Duration `json:"backoff"`
	Deadline    time.Duration   `json:"deadline"`
}
