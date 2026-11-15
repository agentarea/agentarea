package authz

import (
	"context"
	"log/slog"
)

// RelationForPermission maps a route's verb onto the resource bit it needs
// (auth/openfga_permission.py _BIT_BY_PERMISSION). The bits do not imply one
// another; execute is can_invoke, which nothing but an explicit grant gives.
func RelationForPermission(permission string) (string, bool) {
	switch permission {
	case "view", "use", "read", "operate", "connect":
		return CanRead, true
	case "execute":
		return CanInvoke, true
	case "use_secret":
		return CanUseSecret, true
	case "use_connection":
		return CanUseConnection, true
	case "edit", "write", "update", "configure":
		return CanWrite, true
	case "manage", "own", "delete":
		return CanManage, true
	}
	return "", false
}

// Ungoverned reports resource types the graph does not govern: the database
// scopes them, so a graph check would refuse their owner.
func Ungoverned(resourceType string) bool {
	return resourceType == "model_instance" || resourceType == "model"
}

// Permissions is PermissionService over the graph: every governed type is a
// resource:<id> object whose kind lives in the database.
type Permissions struct {
	checker Checker
	log     *slog.Logger
}

// NewPermissions builds Permissions; log may be nil for slog.Default.
func NewPermissions(checker Checker, log *slog.Logger) Permissions {
	if log == nil {
		log = slog.Default()
	}
	return Permissions{checker: checker, log: log}
}

// Check reports whether subject may perform permission on the resource. An
// unmapped verb denies; a graph failure is returned, never coerced.
func (p Permissions) Check(ctx context.Context, subject, permission, resourceType, resourceID string) (bool, error) {
	if Ungoverned(resourceType) {
		return true, nil
	}
	relation, ok := RelationForPermission(permission)
	if !ok {
		p.log.WarnContext(ctx, "no resource permission mapping; denying", "resource_type", resourceType, "permission", permission)
		return false, nil
	}
	return p.checker.Check(ctx, subject, relation, TypeResource, resourceID)
}

// Require returns ErrDenied unless the caller may perform permission on the
// resource (auth/permission.py require_permission).
func (p Permissions) Require(ctx context.Context, caller interface{ GraphSubject() string }, permission, resourceType, resourceID string) error {
	subject := caller.GraphSubject()
	ok, err := p.Check(ctx, subject, permission, resourceType, resourceID)
	if err != nil {
		return err
	}
	if !ok {
		p.log.WarnContext(ctx, "permission denied", "subject", subject, "permission", permission, "resource_type", resourceType, "resource_id", resourceID)
		return ErrDenied
	}
	return nil
}
