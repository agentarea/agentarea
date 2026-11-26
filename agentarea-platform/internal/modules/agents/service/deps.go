package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// Graph is the authorization graph agents checks, lists and writes through.
type Graph interface {
	authz.Checker
	authz.Lister
	authz.Writer
}

// Models reads model instances (models module).
type Models interface {
	// ModelKind is the kind of the workspace's model instance, false when it has none.
	ModelKind(ctx context.Context, ws scope.Workspace, id string) (kind string, found bool, err error)
	// InstanceName is the instance's names, kind and reasoning levels, false when the workspace has none.
	InstanceName(ctx context.Context, ws scope.Workspace, id string) (name modelsapi.InstanceName, found bool, err error)
}

// Approvals reads and writes an agent's approval policy rules (governance module).
type Approvals interface {
	// Targets are the approval targets of each agent that has rules.
	Targets(ctx context.Context, ws scope.Workspace, agentIDs []string) (map[string][]string, error)
	// Sync makes the agent's toggle-owned rules exactly targets, in the agent write's transaction.
	Sync(ctx context.Context, s db.Session, c authn.Caller, agentID string, targets []string) error
	// Release deletes for a workspace admin the enabled approval rules of unticked
	// that the toggle did not write; for anyone else such a rule is *govapi.ApprovalEnforcedError.
	Release(ctx context.Context, s db.Session, c authn.Caller, agentID string, unticked []string) error
}

// Connections is what attaching MCP and OpenAPI connections to an agent needs (connections module).
type Connections interface {
	// BindMCPName is the id of the one connection named name that is the caller's or the platform's;
	// "" keeps the name; ambiguous or foreign is an error.
	BindMCPName(ctx context.Context, c authn.Caller, name string, refuseUnbound bool) (string, error)
	// Lend and Withdraw move a connection's loan to an agent.
	Lend(ctx context.Context, connectionID, agentID string) error
	Withdraw(ctx context.Context, connectionID, agentID string) error
}

// CodeTools is the registry of the built-in code toolsets (get_code_tools_metadata).
type CodeTools interface {
	Names() []string
	// Metadata is every toolset in registry order.
	Metadata() []CodeToolset
}

// Presence tells which runner clients are connected (Redis presence keys).
type Presence interface {
	Online(ctx context.Context, clientIDs []string) (map[string]bool, error)
}

// WalletCredentials deletes the secret holding an agent's wallet keys (wallet module).
type WalletCredentials interface {
	DeleteCredentials(ctx context.Context, s db.Session, userID, agentID string) error
}

// DelegateSecrets finds a workspace secret by name (find_secret); false when there is none.
type DelegateSecrets interface {
	SecretNamed(ctx context.Context, ws scope.Workspace, name string) (ksecrets.Secret, bool, error)
}

// UnwiredError is a feature whose owner module is not ported yet.
type UnwiredError struct{ Feature string }

func (e *UnwiredError) Error() string { return e.Feature + " is not available yet" }

// Deps are the service's ports.
type Deps struct {
	DB          db.Database
	Graph       Graph
	Models      Models
	Approvals   Approvals
	Connections Connections
	// Attachable tells the connections the platform manages, which every
	// workspace may attach; nil treats none as the platform's.
	Attachable ClientConnections
	Presence   Presence
	CodeTools  CodeTools
	Triggers   AgentTriggers
	// Wallets deletes a deleted agent's wallet keys; nil leaves them.
	Wallets WalletCredentials
	// Secrets finds the secret a remote delegate is bound to; nil answers 501 for binding one.
	Secrets DelegateSecrets
	// A2AAgentURL is AGENTAREA_A2A_AGENT_URL with its {agent_id} placeholder; empty leaves a2a_url null.
	A2AAgentURL string
	// Audit writes audit rows in the request's transaction; nil leaves them unwritten.
	Audit govapi.AuditWriter
	// Admin refuses a caller in ctx who is not an admin of its workspace
	// (can_administer_workspace); nil refuses everyone.
	Admin func(ctx context.Context) error
	Now   func() time.Time
	Log   interface {
		WarnContext(ctx context.Context, msg string, args ...any)
	}
}

type agentStore interface {
	Insert(ctx context.Context, s db.Session, createdBy string, a domain.Agent, now time.Time) error
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Agent, bool, error)
	BySlug(ctx context.Context, s db.Session, slug string) (domain.Agent, bool, error)
	ByRegistryItem(ctx context.Context, s db.Session, item string) (domain.Agent, bool, error)
	List(ctx context.Context, s db.Session) ([]domain.Agent, error)
	Update(ctx context.Context, s db.Session, a domain.Agent, now time.Time) error
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	Skills(ctx context.Context, s db.Session, id uuid.UUID) ([]domain.SkillRef, error)
	SetSkills(ctx context.Context, s db.Session, id uuid.UUID, skills []uuid.UUID, now time.Time) error
	Clients(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]store.ClientSummary, error)
	ByHarnessClient(ctx context.Context, s db.Session, client uuid.UUID) ([]domain.Agent, error)
}

type storeClient = store.ClientSummary

func (s *Service) clients(ctx context.Context, sess db.Session, ids []uuid.UUID) (map[string]storeClient, error) {
	return s.store.Clients(ctx, sess, ids)
}
