package service

import (
	"context"
	"io"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/store"
)

// Store is the identity repository (store.Store).
type Store interface {
	SlugTaken(ctx context.Context, q db.Querier, slug string) (bool, error)
	InsertWorkspace(ctx context.Context, q db.Querier, w domain.Workspace) (domain.Workspace, error)
	OwnedWorkspaceIDs(ctx context.Context, q db.Querier, userID string) ([]string, error)
	InsertInvitation(ctx context.Context, s db.Session, id uuid.UUID, email *string, tokenHash, invitedBy string, expiresAt, now time.Time) (domain.Invitation, error)
	InvitationByTokenHash(ctx context.Context, q db.Querier, tokenHash string) (domain.Invitation, bool, error)
	MarkAccepted(ctx context.Context, q db.Querier, id uuid.UUID, userID string, acceptedAt, now time.Time) error
	AddForInvitation(ctx context.Context, q db.Querier, invitationID uuid.UUID, workspaceID, userID string, grantedAt, now time.Time) (bool, error)
	MembershipExists(ctx context.Context, q db.Querier, workspaceID, userID string) (bool, error)
	InsertAPIKey(ctx context.Context, s db.Session, k store.NewAPIKey, now time.Time) (domain.APIKey, error)

	GetWorkspace(ctx context.Context, q db.Querier, id string) (domain.Workspace, bool, error)
	ListWorkspacesForUser(ctx context.Context, q db.Querier, userID string, memberIDs []string) ([]domain.Workspace, error)
	SetLogoKey(ctx context.Context, q db.Querier, id string, key *string, now time.Time) error
	ListPendingInvitations(ctx context.Context, s db.Session) ([]domain.Invitation, error)
	InvitationByID(ctx context.Context, q db.Querier, id uuid.UUID) (domain.Invitation, bool, error)
	RevokeInvitation(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) error
	ListMemberships(ctx context.Context, q db.Querier, workspaceID string) ([]domain.MembershipRow, error)
	MembershipUserIDs(ctx context.Context, q db.Querier, workspaceID string) ([]string, error)
	AddMembership(ctx context.Context, q db.Querier, workspaceID, userID string, now time.Time) error
	EndMembership(ctx context.Context, s db.Session, userID string, emails []string, address func(string) string, now time.Time) error
	APIKeyByID(ctx context.Context, s db.Session, id uuid.UUID) (domain.APIKey, bool, error)
	ListAPIKeys(ctx context.Context, s db.Session, createdBy *string, agentID *uuid.UUID) ([]domain.APIKey, error)
	ListClientAPIKeys(ctx context.Context, s db.Session, clientID uuid.UUID) ([]domain.APIKey, error)
	DeactivateAPIKey(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) error
	ListExternalIdentities(ctx context.Context, q db.Querier, userID string) ([]domain.ExternalIdentity, error)
	RevokeExternalIdentity(ctx context.Context, q db.Querier, userID string, id uuid.UUID, now time.Time) (bool, error)
	ExternalIdentityHolder(ctx context.Context, q db.Querier, provider, externalID string) (string, bool, error)
	LinkedExternalIDs(ctx context.Context, q db.Querier, userID, provider string) ([]string, error)
	InsertExternalIdentity(ctx context.Context, q db.Querier, userID string, a domain.MessengerAccount, method string, now time.Time) (domain.ExternalIdentity, error)
	RenameExternalIdentity(ctx context.Context, q db.Querier, userID string, a domain.MessengerAccount, now time.Time) (domain.ExternalIdentity, error)
}

// GraphReader is what identity reads from the authorization graph: member
// tuples, resource grants and the explorer's permission checks.
type GraphReader interface {
	authz.Reader
	authz.Checker
}

// Directory resolves user ids to identities (auth/identity_directory.py);
// nil when AGENTAREA_AUTH_KRATOS_ADMIN_URL is unset, as Python's None.
type Directory interface {
	// Resolve omits ids it has no entry for or could not ask about.
	Resolve(ctx context.Context, userIDs []string) (map[string]domain.Identity, error)
	// Lookup is nil for an unknown id; store.ErrDirectoryUnavailable when unreachable.
	Lookup(ctx context.Context, userID string) (*domain.Identity, error)
}

// Logos is the object store bucket that holds workspace logos (the
// artifacts bucket, WorkspaceLogoStore).
type Logos interface {
	Put(ctx context.Context, key string, body io.Reader, size int64, opts blob.PutOptions) error
	Delete(ctx context.Context, key string) error
	PresignGet(ctx context.Context, key string, ttl time.Duration) (blob.Presigned, error)
}

// LinkCodes issues messenger link codes (identity/linking.py LinkCodes).
type LinkCodes interface {
	Issue(ctx context.Context, userID string) (string, error)
	// Redeem spends code from the messenger account and returns the user awaiting its
	// confirmation; false when the code is unknown, used or expired.
	Redeem(ctx context.Context, code, provider, externalID string) (string, bool, error)
	// Confirm consumes what the account redeemed; false when nothing waits.
	Confirm(ctx context.Context, provider, externalID string) (string, bool, error)
	// Offer issues a code, good for ttl, that names the account a bot offered it to; issued is
	// false, and no code returned, while one offered to the account through the source is unspent.
	Offer(ctx context.Context, o domain.LinkOffer, ttl time.Duration) (code string, issued bool, err error)
	// PeekOffer is what code was offered for, the code left in place; false when it is gone.
	PeekOffer(ctx context.Context, code string) (domain.LinkOffer, bool, error)
	// TakeOffer spends code; false when it is gone.
	TakeOffer(ctx context.Context, code string) (domain.LinkOffer, bool, error)
}

// Named is a workspace row the access explorer shows by name.
type Named struct {
	ID   string
	Name string
}

// Resources are the explorer's reads of other modules' tables: agents and
// skills (agents), skill collections (agents), MCP servers (connections).
// Every read is limited to ws.
type Resources interface {
	// Exists is the namespace repository's get_by_id(id) is not None for
	// Agent, MCPServer, Skill and SkillCollection.
	Exists(ctx context.Context, ws scope.Workspace, namespace string, id uuid.UUID) (bool, error)
	// Agents is AgentRepository.list_all(include_archived=...), in its order.
	Agents(ctx context.Context, ws scope.Workspace, includeArchived bool) ([]Named, error)
	// Collections is SkillCollectionRepository.list_all, in its order.
	Collections(ctx context.Context, ws scope.Workspace) ([]Named, error)
	// SkillCounts is SkillCollectionRepository.skill_counts: collection id to skills in it.
	SkillCounts(ctx context.Context, ws scope.Workspace) (map[string]int, error)
	// MCPServers is MCPServerRepository.list_all, in its order.
	MCPServers(ctx context.Context, ws scope.Workspace) ([]Named, error)
	// Skills are the workspace's skills.
	Skills(ctx context.Context, ws scope.Workspace) ([]Named, error)
}

// WorkspaceCreated runs in the transaction that inserts a workspace and
// fails it when it fails (get_workspace_service on_workspace_created:
// governance's provision_default_policies).
type WorkspaceCreated func(ctx context.Context, q db.Querier, ws scope.Workspace, creatorUserID string) error

// Deps are the service's ports.
type Deps struct {
	DB     db.Database
	Store  Store
	Graph  authz.Writer
	Agents agentsapi.Lookup
	// OnWorkspaceCreated is nil until governance is ported.
	OnWorkspaceCreated WorkspaceCreated
	// Reader is nil only where Graph is.
	Reader    GraphReader
	Directory Directory
	// Logos is nil until the object store is wired; a workspace with a logo
	// then cannot be described.
	Logos Logos
	// LinkCodes is nil without the Redis broker (503, as Python).
	LinkCodes LinkCodes
	// Audit is governance's trail; nil until wired, and nothing is recorded.
	Audit governanceapi.AuditWriter
	// Resources is nil until agents and connections expose these reads; the
	// explorer routes that need them are not mounted.
	Resources Resources
	// Mailer is nil when the deployment has no transactional mail.
	Mailer Mailer
	// AppURL is the webapp's base, where an invitation link points.
	AppURL string
	// Outbox queues an event in the caller's transaction; events.Publish when nil.
	Outbox func(ctx context.Context, tx db.Session, createdBy string, e events.Envelope) error
	// Now is the process clock; rows Python stamps with datetime.now() get
	// its local wall clock, those stamped with utcnow its UTC one.
	Now func() time.Time
}
