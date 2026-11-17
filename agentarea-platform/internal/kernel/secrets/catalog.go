package secrets

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// Secret is one row of the workspace catalog (encrypted_secrets) without its
// value: the value is reached only through a Manager.
type Secret struct {
	ID          string
	WorkspaceID string
	Name        string
	Description *string
	// OwnerType and OwnerID are nil for a secret a user created; set, the
	// platform minted it for that entity and the secrets API will not edit it.
	OwnerType   *string
	OwnerID     *string
	ExternalRef *string
	CreatedBy   string
	UpdatedBy   *string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// UserOwned reports whether a user created the secret directly.
func (s Secret) UserOwned() bool { return s.OwnerType == nil }

// ConsumerRef is a consumer that resolves a secret and keeps the reference
// inside a JSON document (secret_references).
type ConsumerRef struct {
	ConsumerType string
	ConsumerID   string
	Field        string
}

// Reference is one slot of a consumer that points at a secret.
type Reference struct {
	SecretID string
	Field    string
}

// SurfacedOwnerTypes are the owner types whose secrets a user expects to find
// when looking for "my credentials", listed read-only beside their own.
// task-input/* and a2a_push_token:* scale with usage, not setup, and stay out.
func SurfacedOwnerTypes() []string {
	return []string{"provider_config", "mcp_instance", "mcp_auth_config", "openapi_connection", "trigger", "agent"}
}

var (
	// ErrManaged: the secret belongs to a connection, so it is not the user's to change.
	ErrManaged = errors.New("secret is managed by a connection")
	// ErrAccessDenied: the caller holds no can_use_secret on the secret.
	ErrAccessDenied = errors.New("secret use denied")
	// ErrDuplicateName: the name is taken in this workspace.
	ErrDuplicateName = errors.New("secret name taken")
)

// ManagedError is ErrManaged with Python's message.
type ManagedError struct{ Message string }

func (e *ManagedError) Error() string        { return e.Message }
func (e *ManagedError) Is(target error) bool { return target == ErrManaged }

// AccessDeniedError is ErrAccessDenied with Python's message.
type AccessDeniedError struct{ Message string }

func (e *AccessDeniedError) Error() string        { return e.Message }
func (e *AccessDeniedError) Is(target error) bool { return target == ErrAccessDenied }

// NotFoundError is ErrNotFound with Python's message.
type NotFoundError struct{ Message string }

func (e *NotFoundError) Error() string        { return e.Message }
func (e *NotFoundError) Is(target error) bool { return target == ErrNotFound }

// DuplicateNameError is ErrDuplicateName with Python's message.
type DuplicateNameError struct{ Name string }

func (e *DuplicateNameError) Error() string {
	return fmt.Sprintf("A secret named '%s' already exists", e.Name)
}
func (e *DuplicateNameError) Is(target error) bool { return target == ErrDuplicateName }

// InUseError: something still resolves the secret. Consumers may be empty
// when the guard was a foreign key from a column, not a registered reference.
type InUseError struct{ Consumers []ConsumerRef }

func (e *InUseError) Error() string {
	parts := make([]string, len(e.Consumers))
	for i, c := range e.Consumers {
		parts[i] = c.ConsumerType + ":" + c.ConsumerID
	}
	listed := strings.Join(parts, ", ")
	if listed == "" {
		listed = "unknown"
	}
	return "Secret is still used by " + listed
}

// UseSecret is the verb the graph is asked about (permission use_secret on secret:<id>).
const UseSecret = "use_secret" // #nosec G101 -- a permission verb, not a credential

// Actor is the caller a catalog call acts for.
type Actor struct {
	UserID string
	// GraphSubject is the authorization-graph subject, "User:<id>" or "Agent:<id>".
	GraphSubject string
}

// Guard answers can_use_secret: held by the creator, whoever administers the
// workspace, and anyone granted secret_user (PermissionService.check).
type Guard interface {
	CanUseSecret(ctx context.Context, subject, secretID string) (bool, error)
}

// Ownership writes and removes the graph tuples of a secret
// (rebac.ownership grant_resource_owner / revoke_resource). GrantOwner makes
// the creator the secret's manager under the workspace's root project; its
// failure undoes the secret.
type Ownership interface {
	GrantOwner(ctx context.Context, secretID, workspaceID, owner string) error
	Revoke(ctx context.Context, secretID string) error
}

// Change is one field of an audit diff; secret values are always "***".
type Change struct {
	Field  string
	Before any
	After  any
}

// AuditEntry is one audit row about a secret, by name only.
type AuditEntry struct {
	Action       string // secret.create, secret.rotate, secret.update, secret.delete
	SecretID     string
	ResourceName string
	Changes      []Change
}

// Auditor records an audit row in the caller's transaction (AuditService.record).
type Auditor interface {
	Record(ctx context.Context, s db.Session, e AuditEntry) error
}

// Catalog is workspace-scoped operations on the secret catalog
// (catalog_service.py), bound to one workspace and one actor. It is the only
// thing allowed to act on a user's behalf and refuses every row the platform
// manages: those are named after the connection that resolves them, so
// "creating" one would overwrite a live credential.
type Catalog interface {
	ListUser(ctx context.Context) ([]Secret, error)
	// ListVisible is the user's own secrets first, then the surfaced managed
	// ones, each group by name.
	ListVisible(ctx context.Context) ([]Secret, error)
	Get(ctx context.Context, id string) (Secret, error)
	GetByName(ctx context.Context, name string) (Secret, error)
	// GetForUse is a user-owned secret the caller may wire into a connection.
	GetForUse(ctx context.Context, id string) (Secret, error)
	GetNamedForUse(ctx context.Context, name string) (Secret, error)
	// Consumers is the display index; the delete guard is the foreign key.
	Consumers(ctx context.Context, id string) ([]ConsumerRef, error)
	CreateUser(ctx context.Context, name, value string, description *string) (Secret, error)
	RotateUser(ctx context.Context, id, value string) (Secret, error)
	UpdateDescription(ctx context.Context, id string, description *string) (Secret, error)
	// DeleteUser returns *InUseError while a reference or foreign key points at it.
	DeleteUser(ctx context.Context, id string) error
	AddReference(ctx context.Context, secretID, consumerType, consumerID, field string) error
	ClearReferences(ctx context.Context, consumerType, consumerID string) error
	// StageReferences replaces a consumer's references in the caller's
	// transaction, which commits them with the consumer's own row.
	StageReferences(ctx context.Context, s db.Session, consumerType, consumerID string, refs []Reference) error
	CountUser(ctx context.Context) (int, error)
}
