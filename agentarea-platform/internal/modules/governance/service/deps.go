// Package service of governance: use cases; one file per Python service file. deps.go declares what it needs from other modules (rule 2).
package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

// PolicyStore is the policies repository (store.Policies).
type PolicyStore interface {
	List(ctx context.Context, s db.Session, f store.Filter) ([]domain.Rule, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Rule, bool, error)
	Create(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, r domain.Rule, now time.Time) (domain.Rule, error)
	Update(ctx context.Context, s db.Session, id uuid.UUID, p store.Patch, now time.Time) (domain.Rule, bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// AuditStore is the audit_events repository (store.Audit).
type AuditStore interface {
	Insert(ctx context.Context, q db.Querier, e domain.AuditEvent, now time.Time) error
	InsertOnce(ctx context.Context, q db.Querier, e domain.AuditEvent) (bool, error)
	Query(ctx context.Context, s db.Session, f domain.AuditQuery) ([]domain.AuditEvent, error)
	ResourcePage(ctx context.Context, s db.Session, resourceType string, actions []string, limit, offset int) ([]domain.AuditEvent, int64, error)
}

// SecretCatalogs builds the secret catalog bound to a workspace and actor,
// recording its audit rows through audit (secrets profile NewCatalog).
type SecretCatalogs func(ws scope.Workspace, actor secrets.Actor, audit secrets.Auditor) secrets.Catalog

// OwnerRef is the entity a managed secret names.
type OwnerRef struct{ Type, ID string }

// OwnerNames maps owners to display names, leaving out the ones that are
// gone (secrets profile ResolveOwnerNames).
type OwnerNames func(ctx context.Context, s db.Session, owners []OwnerRef) (map[OwnerRef]string, error)

// TaskMetadata reads a task's metadata JSON in the workspace, false when the
// workspace has no such task (runs owns tasks).
type TaskMetadata interface {
	TaskMetadata(ctx context.Context, ws scope.Workspace, taskID string) ([]byte, bool, error)
}

// AuditSink forwards every recorded audit row (ext.AuditSink).
type AuditSink interface {
	Emit(ctx context.Context, event map[string]any) error
}

// EgressExitStore is the egress_exits repository (store.EgressExits).
type EgressExitStore interface {
	List(ctx context.Context, s db.Session) ([]domain.EgressExit, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.EgressExit, bool, error)
	Create(ctx context.Context, s db.Session, e domain.EgressExit, now time.Time) (domain.EgressExit, error)
	Update(ctx context.Context, s db.Session, id uuid.UUID, changes store.EgressExitChanges, now time.Time) (domain.EgressExit, bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// EgressBindings is connections' read and retirement of the instances bound
// to an exit (connections/api).
type EgressBindings = connectionsapi.EgressBindings

// EgressExitPorts is what the egress exit use cases need where the edition
// enforces them. Upstream is the outbound address policy's URL check.
type EgressExitPorts struct {
	Store     EgressExitStore
	Graph     authz.Graph
	Instances EgressBindings
	Upstream  func(ctx context.Context, rawURL string) error
}

// Deps are the service's ports.
type Deps struct {
	DB       db.Database
	Policies PolicyStore
	Audit    AuditStore
	// Secrets and Owners are nil until app passes the secrets profile; the
	// secret routes are not mounted without them.
	Secrets SecretCatalogs
	Owners  OwnerNames
	// Tasks is nil until runs implements it; the snapshot route is not
	// mounted without it.
	Tasks TaskMetadata
	// Sink is nil when no edition registers one.
	Sink AuditSink
	// EgressExits is nil where no edition enforces egress exits: every
	// egress exit use case answers api.ErrEgressExitsUnsupported.
	EgressExits *EgressExitPorts
	// DefaultPoliciesPath replaces the packaged baseline when set
	// (GOVERNANCE_DEFAULT_POLICIES_PATH).
	DefaultPoliciesPath string
	// Now is the process clock; nil is time.Now.
	Now func() time.Time
	Log *slog.Logger
}
