// Package governance is the governance module: policy rules and their
// resolution, the tool decision point and gates (api), the audit trail, and
// the secrets HTTP surface over the secrets kernel.
package governance

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// Deps are what governance needs from other modules and the kernel, as
// interfaces declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Workspace admits the caller into /v1/workspaces/{workspace} and puts
	// it in the request context (authn.CallerFrom).
	Workspace func(http.Handler) http.Handler
	// Admin refuses a caller who does not administer the workspace.
	Admin func(ctx context.Context) error
	// Secrets and Owners: nil leaves the six secret routes unmounted.
	Secrets service.SecretCatalogs
	Owners  service.OwnerNames
	// Tasks: nil leaves the task-policy-snapshot route unmounted.
	Tasks service.TaskMetadata
	Sink  service.AuditSink
	// EgressExits is set where the edition enforces egress exits (its Store
	// is governance's own); nil answers every /egress-exits route 404.
	EgressExits *service.EgressExitPorts
	// DefaultPoliciesPath replaces the packaged baseline when set.
	DefaultPoliciesPath string
	Now                 func() time.Time
	Log                 *slog.Logger
}

// Module is governance, constructed once per process; a role picks which of
// its parts run.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	if d.Log == nil {
		d.Log = slog.Default()
	}
	var egress *service.EgressExitPorts
	if d.EgressExits != nil {
		p := *d.EgressExits
		p.Store = store.EgressExits{}
		egress = &p
	}
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Policies: store.Policies{}, Audit: store.Audit{},
		Secrets: d.Secrets, Owners: d.Owners, Tasks: d.Tasks, Sink: d.Sink, EgressExits: egress,
		DefaultPoliciesPath: d.DefaultPoliciesPath, Now: d.Now, Log: d.Log.With("module", "governance"),
	})}
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "governance" }

// Audit writes audit rows in a caller's transaction (runs' event trail).
func (m *Module) Audit() api.AuditWriter { return m.svc }

// AuditReader reads audit rows (the inbox's approval decisions).
func (m *Module) AuditReader() api.AuditReader { return m.svc }

// Budgets reads the spend caps set now.
func (m *Module) Budgets() api.Budgets { return m.svc }

// RunPolicies resolves the policy a run starts with.
func (m *Module) RunPolicies() api.RunPolicies { return m.svc }

// ToolPolicies is what connections reads of the policy layers.
func (m *Module) ToolPolicies() api.ToolPolicies { return m.svc }

// ApprovalTargets reads agents' approval rules.
func (m *Module) ApprovalTargets() api.ApprovalTargets { return m.svc }

// ProvisionDefaults seeds a new workspace's baseline policies in the
// transaction that creates it (identity's OnWorkspaceCreated).
func (m *Module) ProvisionDefaults(ctx context.Context, q db.Querier, ws scope.Workspace, creatorUserID string) error {
	return m.svc.ProvisionDefaults(ctx, q, ws, creatorUserID)
}

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, m.d.Admin, handlers.New(m.svc, m.d.Admin),
				handlers.Routes{Secrets: m.svc.SecretsMounted(), Snapshots: m.d.Tasks != nil, EgressExits: m.svc.EgressExitsEnforced()})
			return nil
		},
	}
}

// EgressExitPorts is what egress exits need where the edition enforces them.
type EgressExitPorts = service.EgressExitPorts

// OwnerRef is the entity a managed secret names.
type OwnerRef = service.OwnerRef

// OwnersFrom adapts an owner-name resolver keyed by any {Type, ID} struct.
func OwnersFrom[K ~struct{ Type, ID string }](resolve func(context.Context, db.Session, []K) (map[K]string, error)) service.OwnerNames {
	return func(ctx context.Context, s db.Session, refs []OwnerRef) (map[OwnerRef]string, error) {
		keys := make([]K, len(refs))
		for i, r := range refs {
			keys[i] = K(r)
		}
		names, err := resolve(ctx, s, keys)
		if err != nil {
			return nil, err
		}
		out := make(map[OwnerRef]string, len(names))
		for k, v := range names {
			out[OwnerRef(k)] = v
		}
		return out, nil
	}
}

// EgressExits is the operator's writes of platform egress exits.
func (m *Module) EgressExits() api.EgressExitDeclarations { return m.svc }

// EgressExitBinding is what connections asks before an instance binds an
// exit; nil where the edition does not enforce egress exits.
func (m *Module) EgressExitBinding() api.EgressExitBinding {
	if !m.svc.EgressExitsEnforced() {
		return nil
	}
	return m.svc
}
