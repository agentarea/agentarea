// Package contract is the Python API's surface the Go backend must keep:
// every route of the live FastAPI app (mounts, the runner WebSocket, root and
// host-routed A2A routes) and each platform MCP server's tools/list.
// Regenerated with .omc/research/go-migration/routes/introspect.py.
package contract

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
)

//go:embed routes.json
var routesJSON []byte

//go:embed mcp-tools.json
var mcpToolsJSON []byte

// Streaming kinds of a route.
const (
	StreamingNone    = "none"
	StreamingSSE     = "SSE"
	StreamingWS      = "WS"
	StreamingMounted = "mounted"
	StreamingBody    = "stream-body"
)

// Route is one entry of routes.json. Method is "*" for a mount and "WS" for
// a WebSocket; Path keeps Starlette's converters ("{file_path:path}").
type Route struct {
	Method      string   `json:"method"`
	Path        string   `json:"path"`
	Name        *string  `json:"name"`
	OperationID *string  `json:"operation_id"`
	RouterFile  string   `json:"router_file"`
	InOpenAPI   bool     `json:"in_openapi"`
	Streaming   string   `json:"streaming"`
	Host        *string  `json:"host"`
	Tags        []string `json:"tags"`
	ASGIApp     string   `json:"asgi_app,omitempty"`
}

// Routes is routes.json.
type Routes struct {
	AppRoutes int     `json:"app_routes"`
	Routes    []Route `json:"routes"`
}

// Tool is one MCP tool as tools/list returns it.
type Tool struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"inputSchema"`
	Toolset     string          `json:"toolset"`
}

// MCPServer is one platform MCP mount and its tools; dynamic servers list
// their tools per request and carry none here.
type MCPServer struct {
	Mount string `json:"mount"`
	Kind  string `json:"kind"`
	Note  string `json:"note,omitempty"`
	Tools []Tool `json:"tools"`
}

// MCPTools is mcp-tools.json.
type MCPTools struct {
	PlatformSpanning MCPServer `json:"platform_spanning"`
	PlatformPinned   MCPServer `json:"platform_pinned"`
	ClientMCP        MCPServer `json:"client_mcp"`
	ConnectionMCP    MCPServer `json:"connection_mcp"`
}

// LoadRoutes decodes the embedded routes.json.
func LoadRoutes() (Routes, error) {
	var r Routes
	if err := decode(routesJSON, &r); err != nil {
		return Routes{}, fmt.Errorf("routes.json: %w", err)
	}
	return r, nil
}

// LoadMCPTools decodes the embedded mcp-tools.json.
func LoadMCPTools() (MCPTools, error) {
	var m MCPTools
	if err := decode(mcpToolsJSON, &m); err != nil {
		return MCPTools{}, fmt.Errorf("mcp-tools.json: %w", err)
	}
	return m, nil
}

// decode refuses fields the types do not know, so a regenerated file that
// changed shape fails here rather than losing data.
func decode(data []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	return dec.Decode(v)
}

// Pattern is the route in net/http pattern syntax, "METHOD /path", with
// Starlette's "{x:path}" written "{x...}" and other converters dropped.
func (r Route) Pattern() string {
	re := regexp.MustCompile(`\{(\w+):(\w+)\}`)
	return r.Method + " " + re.ReplaceAllStringFunc(r.Path, func(m string) string {
		sub := re.FindStringSubmatch(m)
		if sub[2] == "path" {
			return "{" + sub[1] + "...}"
		}
		return "{" + sub[1] + "}"
	})
}
