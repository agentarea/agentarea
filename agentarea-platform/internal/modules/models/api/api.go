// Package api is what other modules may import from models: identifiers and the
// interfaces models implements for them. Nothing else of models is importable
// (rule 1).
package api

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ManagedByPlatform marks a provider configuration whose credentials the deployment supplies.
const ManagedByPlatform = "platform"

// ErrNotFound: the model instance does not exist or is not visible to the workspace.
var ErrNotFound = errors.New("model instance not found")

// ErrRefused: the instance exists but may not be used (a part from another workspace, no valid context window).
var ErrRefused = errors.New("model instance refused")

// Principal is who a call acts as.
type Principal struct {
	WorkspaceID string
	UserID      string
	AgentID     string
}

// ResolvedModel is the model instance, its spec and its provider as one call
// needs them (ResolvedModelInfo). Field names and JSON tags are runs/api's,
// so a run's stored configuration reads back unchanged.
type ResolvedModel struct {
	ModelID             string `json:"model_id"`
	ModelName           string `json:"model_name"`
	DisplayName         string `json:"display_name"`
	ProviderType        string `json:"provider_type"`
	ProviderDisplayName string `json:"provider_display_name"`
	// APIKeySecret names the credential, never its value.
	APIKeySecret string `json:"api_key_secret"`
	// ManagedBy is "platform" when the deployment's credentials pay, else empty.
	ManagedBy              string          `json:"managed_by"`
	EndpointURL            string          `json:"endpoint_url"`
	ContextWindow          int             `json:"context_window"`
	MaxOutputTokens        *int            `json:"max_output_tokens"`
	Prices                 ModelPrices     `json:"prices"`
	SupportsVision         bool            `json:"supports_vision"`
	ReasoningLevels        []string        `json:"reasoning_levels"`
	Provider               ProviderProfile `json:"provider"`
	DefaultContextStrategy string          `json:"default_context_strategy"`
}

// ModelPrices are the spec's USD prices per token; nil is unpriced.
type ModelPrices struct {
	Input         *money.Decimal `json:"input"`
	Output        *money.Decimal `json:"output"`
	CachedInput   *money.Decimal `json:"cached_input"`
	CacheCreation *money.Decimal `json:"cache_creation"`
	Image         *money.Decimal `json:"image,omitempty"`
	VideoSecond   *money.Decimal `json:"video_second,omitempty"`
}

// ProviderProfile is the provider spec's HTTP contract as a chat call needs it.
type ProviderProfile struct {
	BaseURL          string   `json:"base_url"`
	Transport        string   `json:"transport"`
	Auth             string   `json:"auth"`
	ReasoningParam   string   `json:"reasoning_param"`
	ReasoningLevels  []string `json:"reasoning_levels"`
	CacheBreakpoints bool     `json:"cache_breakpoints"`
}

// ToolDefinition is a function tool the model may call.
type ToolDefinition struct {
	Name        string
	Description string
	Parameters  map[string]any
}

// ContentPart is a part of a multi-part message: text, or an image by URL.
type ContentPart struct {
	Type     string
	Text     string
	ImageURL string
}

// ToolCall is a call the model asked for; Arguments is its JSON text.
type ToolCall struct {
	ID        string
	Name      string
	Arguments string
}

// Message is a message as the provider receives it; Parts replaces Content when set.
type Message struct {
	Role       string
	Content    string
	Parts      []ContentPart
	ToolCalls  []ToolCall
	ToolCallID string
	Name       string
}

// Chunk is one streamed delta: text, or reasoning when Thinking; Final marks the closing callback.
type Chunk struct {
	Delta    string
	Thinking bool
	Final    bool
	Index    int
}

// Call is one call to a resolved model.
type Call struct {
	Model              ResolvedModel
	Messages           []Message
	Tools              []ToolDefinition
	Temperature        *float64
	MaxTokens          int
	ReasoningEffort    string
	ReasoningMaxTokens *int
	// Funded: billing holds the call, so a platform credential may be used.
	Funded  bool
	OnChunk func(Chunk)
}

// Usage counts a call's tokens; Prompt includes CachedPrompt.
type Usage struct {
	Prompt, Completion, Total, CachedPrompt, CacheCreation int64
}

// Reply is a model's answer. A failed call is a *durable.ApplicationError
// typed as Python's exception, its details carrying {"llm_failure": {cause,
// message, error_type, retryable}} when the failure is classified.
type Reply struct {
	Content, Thinking string
	ToolCalls         []ToolCall
	Usage             Usage
	FinishReason      string
	// ProviderCostUSD is what the provider charged (reported, else the spec's prices).
	ProviderCostUSD money.Decimal
	// Interrupted: ctx ended after the provider reported usage.
	Interrupted bool
	// ChunkCount is how many deltas OnChunk received.
	ChunkCount int
}

// Caller makes model calls (LLMModel over llm_execution_service's resolution).
type Caller interface {
	Call(ctx context.Context, p Principal, call Call) (Reply, error)
}

// Resolver resolves a model instance once for a run (resolve_model_activity).
// ErrNotFound and ErrRefused are final.
type Resolver interface {
	Model(ctx context.Context, p Principal, modelID string) (ResolvedModel, error)
}

// SpecUse is which catalog specs the workspace's configurations and instances use.
type SpecUse interface {
	ProviderSpecIDsWithVisibleConfigs(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error)
	ModelSpecIDsWithVisibleInstances(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error)
}
