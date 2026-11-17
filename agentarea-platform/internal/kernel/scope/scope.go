// Package scope holds the workspace a call acts in, the errors that refuse a
// call outside it, and the slug rules for workspaces and workspace-scoped
// entities.
//
// Every store method takes a Workspace (layout D16): the guarantee the Python
// ORM gave at runtime (base/tenant_scope.py) is carried by the signature.
package scope

import (
	"errors"
	"fmt"
	"strings"
)

// Workspace is the workspace a call acts in. The zero value names no
// workspace and is refused wherever one is required.
type Workspace struct {
	id   string
	slug string
}

// ErrNoWorkspace is returned when a workspace is built without an id.
var ErrNoWorkspace = errors.New("workspace id is required; refusing to act without a workspace")

// NewWorkspace names the workspace by id and, when a request named it by its
// URL handle, by slug. A context minted outside HTTP passes an empty slug.
func NewWorkspace(id, slug string) (Workspace, error) {
	if id == "" {
		return Workspace{}, ErrNoWorkspace
	}
	return Workspace{id: id, slug: slug}, nil
}

// ID is the workspace id (String(255) in the workspaces table, not a UUID).
func (w Workspace) ID() string { return w.id }

// Slug is the handle the request named the workspace by; empty outside HTTP.
func (w Workspace) Slug() string { return w.slug }

// IsZero reports whether w names no workspace.
func (w Workspace) IsZero() bool { return w.id == "" }

func (w Workspace) String() string {
	if w.slug == "" {
		return w.id
	}
	return fmt.Sprintf("%s (%s)", w.slug, w.id)
}

// UnreachableError: the principal may not act in the workspace it named.
// Raised alike for a workspace that does not exist and one the principal
// cannot reach, so the refusal does not reveal which workspaces exist
// (auth/context.py WorkspaceUnreachableError).
type UnreachableError struct {
	Reference string
}

func (e *UnreachableError) Error() string {
	return fmt.Sprintf("No accessible workspace '%s'", e.Reference)
}

// AccessDeniedSafeDetail is the only detail a client sees for AccessDeniedError.
const AccessDeniedSafeDetail = "The requested resource does not exist or you don't have access to it"

// AccessDeniedError: a resource of another workspace was addressed. It is
// rendered as 404 not_found with AccessDeniedSafeDetail, never 403, so the
// existence of resources in other workspaces is not leaked
// (exceptions/workspace.py WorkspaceAccessDenied). Error() is the verbose
// form, for logs only.
type AccessDeniedError struct {
	ResourceType      string
	ResourceID        string
	CurrentWorkspace  string
	ResourceWorkspace string
	UserID            string
}

func (e *AccessDeniedError) Error() string {
	var msg string
	if e.ResourceWorkspace != "" {
		msg = fmt.Sprintf("Access denied to %s '%s'. Resource belongs to workspace '%s' but user is in workspace '%s'",
			e.ResourceType, e.ResourceID, e.ResourceWorkspace, e.CurrentWorkspace)
	} else {
		msg = fmt.Sprintf("Access denied to %s '%s'. Resource not found in workspace '%s'",
			e.ResourceType, e.ResourceID, e.CurrentWorkspace)
	}
	return msg + logContext(e.CurrentWorkspace, e.UserID, e.ResourceID)
}

// MissingContextError: the request carries no workspace context; rendered as
// 400 missing_context with SafeDetail (exceptions/workspace.py MissingWorkspaceContext).
type MissingContextError struct {
	Field  string
	UserID string
}

func (e *MissingContextError) Error() string {
	return "Missing required context field: " + e.Field + logContext("", e.UserID, "")
}

// SafeDetail is what the client sees.
func (e *MissingContextError) SafeDetail() string {
	return "Request must include valid " + e.Field + " information"
}

func logContext(workspaceID, userID, resourceID string) string {
	var parts []string
	if workspaceID != "" {
		parts = append(parts, "workspace_id="+workspaceID)
	}
	if userID != "" {
		parts = append(parts, "user_id="+userID)
	}
	if resourceID != "" {
		parts = append(parts, "resource_id="+resourceID)
	}
	if len(parts) == 0 {
		return ""
	}
	return " (" + strings.Join(parts, ", ") + ")"
}
