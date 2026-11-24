package domain

// Tool types of ToolConfig's discriminated union.
const (
	ToolCode    = "code"
	ToolMCP     = "mcp"
	ToolAgent   = "agent"
	ToolOpenAPI = "openapi"
)

// MCPPermission is one MCP tool an agent may call.
type MCPPermission struct {
	ToolName                 string
	RequiresUserConfirmation *bool
}

// Settings is every tool type's settings; a type reads and renders only its own.
type Settings struct {
	RequiresUserConfirmation *bool
	DisabledMethods          *[]string
	ImageModelID             *string
	VideoModelID             *string
	MCPAllowed               *[]MCPPermission
	DescriptionOverride      *string
	AgentID                  *string
	A2AURL                   *string
	AuthSecretName           *string
	OpenAPIConnectionID      *string
	OpenAPIAllowed           *[]string
	LoadMode                 *string
}

// Tool is one ToolConfig. Settings is nil when the config carries none.
type Tool struct {
	Type     string
	Name     string
	Settings *Settings
}

// ToolTypes lists the union's tags in declaration order.
func ToolTypes() []string { return []string{ToolCode, ToolMCP, ToolAgent, ToolOpenAPI} }
