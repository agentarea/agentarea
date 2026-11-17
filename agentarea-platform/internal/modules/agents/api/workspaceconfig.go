package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ExportInvalidError is a resource the bundle cannot carry (the export's
// ValueError); REST answers it 422 with Msg as the detail.
type ExportInvalidError struct{ Msg string }

func (e *ExportInvalidError) Error() string { return e.Msg }

// WorkspaceConfig is what the workspace_config toolset (workspace_config_export) calls.
type WorkspaceConfig interface {
	// Export is export_workspace for c: the workspace bundle as YAML. It
	// refuses a caller who is not an admin of c's workspace, as the REST route
	// and @requires_workspace_admin do.
	Export(ctx context.Context, c authn.Caller) (string, error)
}
