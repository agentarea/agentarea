package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ErrNotFound: no such agent in the workspace.
var ErrNotFound = errors.New("agent not found")

// AnswerCheck is the agent's final-answer check as saved.
type AnswerCheck struct {
	Enabled            bool
	Language           string
	RewriteInstruction string
}

// ToolModel is a model a code toolset may call and its default reasoning and output budget.
type ToolModel struct {
	ModelID            string
	ReasoningEffort    string
	ReasoningMaxTokens *int
	MaxTokens          *int
}

// ToolSettings holds every tool type's settings; a type reads only its own.
// AllowedTools is the MCP tool names or the OpenAPI operation names.
type ToolSettings struct {
	DisabledMethods     []string
	ImageModelID        string
	VideoModelID        string
	Models              []ToolModel
	AllowedTools        []string
	OpenAPIConnectionID string
	LoadMode            string
	DescriptionOverride string
	AgentID             string
	A2AURL              string
	AuthSecretName      string
}

// Tool is one entry of the agent's tools as saved (Type: code, mcp, agent, openapi).
type Tool struct {
	Type     string
	Name     string
	Settings ToolSettings
}

// Skill is a skill attached to an agent, with its package pointer as saved
// (s3_path), the source type and the catalog item it was installed from.
type Skill struct {
	ID             string
	Name           string
	Description    string
	SourceType     string
	Package        string
	RegistryItemID string
}

// Definition is the agent row as build_agent_config_activity reads it
// (AgentRepository.get_with_skills): workspace-filtered, archived included.
type Definition struct {
	ID                 string
	Name               string
	Description        string
	Instruction        string
	AgentType          string
	ModelID            string
	Planning           bool
	A2UIEnabled        bool
	ReasoningEffort    string
	ReasoningMaxTokens *int
	AnswerCheck        *AnswerCheck
	Tools              []Tool
	Archived           bool
	ClientID           string
	RegistryItemID     string
	Skills             []Skill
}

// Definitions is what runs reads to resolve a run's agent: a tenant agent only.
type Definitions interface {
	// Definition returns ErrNotFound when the workspace has no such agent.
	Definition(ctx context.Context, ws scope.Workspace, agentID string) (Definition, error)
}

// AgentRefusedError: the install policy keeps the run from a catalog agent.
type AgentRefusedError struct{ Msg string }

func (e *AgentRefusedError) Error() string { return e.Msg }

// CatalogRuns is a catalog agent the workspace has not installed, run from
// its definition (get_with_catalog with to_run).
type CatalogRuns interface {
	// CatalogDefinition projects the catalog agent item agentID once the install
	// policy allowed it for userID; ErrNotFound when no such item, *AgentRefusedError when refused.
	CatalogDefinition(ctx context.Context, ws scope.Workspace, userID, agentID string) (Definition, error)
}
