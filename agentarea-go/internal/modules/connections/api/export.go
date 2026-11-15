package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// ExportInstance is an MCP server instance as the workspace config export reads it.
type ExportInstance struct {
	ID, Name string
	// Platform is a connection the deployment supplies: never exported.
	Platform bool
	// Spec is get_transport_spec_for_instance.
	Spec wirejson.Object
	// EnvVars is get_configured_env_vars.
	EnvVars        []string
	ContextSigning bool
}

// MCPExports lists the MCP server instances for the workspace config export.
type MCPExports interface {
	// ExportInstances is MCPServerInstanceService.list() in its order, each
	// with its transport spec. A spec that is gone is an error naming it.
	ExportInstances(ctx context.Context, c authn.Caller) ([]ExportInstance, error)
}
