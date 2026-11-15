package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// AgentConnectionUse is one mcp tool config of an agent that names a
// connection (the /consumers scan).
type AgentConnectionUse struct {
	AgentID   string
	AgentName string
	AgentSlug string
	// ServerRef is the tool config's name: the instance id or its name.
	ServerRef string
	// EnabledTools is settings.allowed_tools as tool names; nil when the
	// setting is not a list (every tool).
	EnabledTools []string
}

// AgentTools is what connections reads of agents' saved tools JSON.
type AgentTools interface {
	// Naming is every agent, archived and harness ones included, whose tools
	// JSON mentions id anywhere (_agents_naming).
	Naming(ctx context.Context, ws scope.Workspace, id string) ([]string, error)
	// MCPConsumers is, per agent the workspace lists (not archived, no
	// harness agents), the first mcp tool config whose name is id or name.
	MCPConsumers(ctx context.Context, ws scope.Workspace, id, name string) ([]AgentConnectionUse, error)
}

// ClientAttachment is one connection attached to a client.
type ClientAttachment struct {
	ID              string
	NamespacePrefix *string
	// AllowedTools nil serves every tool.
	AllowedTools []string
}

// ClientToolset is one platform toolset attached to a client.
type ClientToolset struct {
	Toolset         string
	DisabledMethods []string
}

// ClientSkill is one skill attached to a client, with its SKILL.md.
type ClientSkill struct {
	ID          string
	Name        string
	Description string
	Content     string
}

// ClientBundle is everything a client's MCP endpoint serves.
type ClientBundle struct {
	ID           string
	Name         string
	Description  string
	MCPInstances []ClientAttachment
	OpenAPI      []ClientAttachment
	Toolsets     []ClientToolset
	Skills       []ClientSkill
}

// ClientBundles is what connections reads of clients for /mcp/clients/{id}.
type ClientBundles interface {
	// Locate is ClientRepository.locate_workspace: the workspace of the
	// client, if it is one of workspaces.
	Locate(ctx context.Context, clientID string, workspaces []string) (string, bool, error)
	// Bundle is the client's attachments in ws, read as userID; false when ws
	// has no such client.
	Bundle(ctx context.Context, ws scope.Workspace, userID, clientID string) (ClientBundle, bool, error)
}
