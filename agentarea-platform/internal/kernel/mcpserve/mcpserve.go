// Package mcpserve serves the platform MCP server (apps/api platform_mcp):
// the spanning /mcp, the pinned /mcp/w/{workspace}, client bundles on
// /mcp/clients and the legacy /client-mcp, all mounted before /mcp. Each
// module contributes its tools from a mcp/ package beside handlers/ (D17);
// the tools/list of each mount is a checked-in contract.
package mcpserve

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// Mount paths, in the order they are matched.
const (
	MountPinned  = "/mcp/w/{workspace}"
	MountClients = "/mcp/clients"
	MountLegacy  = "/client-mcp"
	MountSpan    = "/mcp"
)

// Tool is one tool as tools/list shows it.
type Tool struct {
	Name         string          `json:"name"`
	Title        string          `json:"title,omitempty"`
	Description  string          `json:"description,omitempty"`
	InputSchema  json.RawMessage `json:"inputSchema"`
	OutputSchema json.RawMessage `json:"outputSchema,omitempty"`
	Annotations  map[string]any  `json:"annotations,omitempty"`
}

// Content is one block of a tool result.
type Content struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// Result is a tools/call result.
type Result struct {
	Content           []Content `json:"content"`
	StructuredContent any       `json:"structuredContent,omitempty"`
	IsError           bool      `json:"isError,omitempty"`
}

// Toolset is what a module contributes. On the spanning mount the caller has
// no workspace until a tool's workspace argument selects one.
type Toolset interface {
	Name() string
	Tools(ctx context.Context, p authn.Principal) ([]Tool, error)
	Call(ctx context.Context, p authn.Principal, tool string, args json.RawMessage) (Result, error)
}

// Server serves the registered toolsets on a mount.
type Server interface {
	Register(ts ...Toolset)
	Handler(mount string) http.Handler
}
