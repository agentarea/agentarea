package api

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// ErrProjectNotFound: the workspace has no such project.
var ErrProjectNotFound = errors.New("Project not found") //nolint:staticcheck // Python's message

// PlatformProject is a project as the projects toolset shows it.
type PlatformProject struct {
	ID, Name                                   string
	Description, Instructions, ParentProjectID *string
}

// Link kinds of PlatformProjects.Link and Unlink.
const (
	LinkSkill       = "skill"
	LinkAgent       = "agent"
	LinkMCPInstance = "mcp_instance"
)

// PlatformProjects is what the platform projects toolset calls
// (tools/projects_toolset.py); every project route is member-level. Errors
// other than ErrProjectNotFound carry the tool's answer as their text.
type PlatformProjects interface {
	List(ctx context.Context, c authn.Caller, limit, offset int) ([]PlatformProject, error)
	Get(ctx context.Context, c authn.Caller, projectID string) (PlatformProject, error)
	// Create takes a ProjectCreate document.
	Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (PlatformProject, error)
	// Update takes a ProjectUpdate document of the fields to write.
	Update(ctx context.Context, c authn.Caller, projectID string, doc json.RawMessage) (PlatformProject, error)
	// Delete reports whether there was such a project.
	Delete(ctx context.Context, c authn.Caller, projectID string) (bool, error)
	Link(ctx context.Context, c authn.Caller, kind, projectID, childID string) error
	Unlink(ctx context.Context, c authn.Caller, kind, projectID, childID string) error
}
