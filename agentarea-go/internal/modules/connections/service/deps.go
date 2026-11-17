package service

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// AuthStore is the mcp_auth_configs repository (store.Auth).
type AuthStore interface {
	List(ctx context.Context, s db.Session) ([]domain.AuthConfig, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.AuthConfig, bool, error)
	OwnedByConnection(ctx context.Context, s db.Session, connectionID uuid.UUID) ([]domain.AuthConfig, error)
	Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.AuthConfigNew, now time.Time) (domain.AuthConfig, error)
	SetSecretKey(ctx context.Context, s db.Session, id uuid.UUID, key string, now time.Time) error
	Update(ctx context.Context, s db.Session, id uuid.UUID, name, description *string, config map[string]any, now time.Time) error
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	LinkedInstances(ctx context.Context, s db.Session, id uuid.UUID) ([]string, error)
	LinkedConnections(ctx context.Context, s db.Session, id uuid.UUID) ([]string, error)
}

// LinkStore is the mcp_oauth_links repository (store.Links).
type LinkStore interface {
	Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, inst uuid.UUID, token, access string,
		provider map[string]any, expires *time.Time, now time.Time) (domain.OAuthLink, error)
	List(ctx context.Context, s db.Session, inst uuid.UUID) ([]domain.OAuthLink, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.OAuthLink, bool, error)
	Deactivate(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) (bool, error)
}

// ConnectionStore is the openapi_connections repository (store.OpenAPI).
type ConnectionStore interface {
	List(ctx context.Context, s db.Session, f ConnectionFilter, limit, offset int32) ([]domain.Connection, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// ConnectionFilter is the list's status and name/description search.
type ConnectionFilter = store.Filter

// Secrets is the secret store's backend for a session's workspace
// (profiles/cluster/secrets.Factory).
type Secrets interface {
	Manager(s db.Session, userID string) ksecrets.Manager
}

// Catalog is the workspace's secret catalog bound to an actor, used for the
// reference clearing that the catalog owns.
type Catalog func(ws scope.Workspace, actor ksecrets.Actor) ksecrets.Catalog

// Graph is the authorization graph the sharing and permission checks read.
type Graph interface {
	authz.Checker
	authz.Reader
}

// InstanceStore is the mcp_server_instances repository (store.Instances).
type InstanceStore interface {
	List(ctx context.Context, s db.Session) ([]domain.Instance, error)
	Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error)
	GetMany(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]domain.Instance, error)
	Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error)
	Insert(ctx context.Context, s db.Session, n store.InstanceNew) (domain.Instance, error)
	Update(ctx context.Context, s db.Session, id uuid.UUID, p store.InstancePatch) (bool, error)
	SetJSONSpec(ctx context.Context, s db.Session, id uuid.UUID, spec map[string]any, now time.Time) (bool, error)
	SetAuthConfig(ctx context.Context, s db.Session, id uuid.UUID, authConfig *uuid.UUID, now time.Time) (bool, error)
	SetVerification(ctx context.Context, s db.Session, id uuid.UUID, v domain.Verification) (bool, error)
	SetDiscovery(ctx context.Context, s db.Session, id uuid.UUID, v domain.Verification, tools []any, events map[string]any) (bool, error)
	SetLastDispatch(ctx context.Context, s db.Session, id uuid.UUID, dispatch map[string]any) (bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	InterruptStale(ctx context.Context, q db.Querier, v domain.Verification, before time.Time) (int64, error)
	NeverAttempted(ctx context.Context, q db.Querier, limit int32) ([]store.Pending, error)
	ConnectionOwners(ctx context.Context, q db.Querier, id uuid.UUID) ([]store.Owner, error)
	StampLastDispatch(ctx context.Context, q db.Querier, id uuid.UUID, stamp map[string]any) error
	PackageImportCandidates(ctx context.Context, q db.Querier, before time.Time, limit int32) ([]store.ImportRow, error)
	LockForImport(ctx context.Context, q db.Querier, id uuid.UUID) (store.ImportRow, bool, error)
	SetImportedSpec(ctx context.Context, q db.Querier, id uuid.UUID, spec map[string]any, transport string, now time.Time) error
}

// Specs is catalog's MCP server specs (catalog/api.MCPSpecs): mcp_servers is catalog's table.
type Specs = catalogapi.MCPSpecs

// Runtime is the MCP runtime (connections/runtime and connections/gateway,
// the merged mcp-manager), called in process. See PORTING-NOTES "Runtime port".
type Runtime interface {
	// Gateway serves ANY /mcp/{instance_id}/mcp as the manager's demand
	// gateway did: cold start on demand, a request lease per call, 503 with
	// X-AgentArea-MCP-Starting while another request starts the workload,
	// X-AgentArea-MCP-Start-Failure for a classified startup failure. Calls
	// come from this process, so they carry no manager authorization header.
	Gateway() http.Handler
	// Retire stops the instance's workload so the next call starts it from
	// the current spec (DELETE /mcp/{id}); nil when nothing runs. A
	// *RuntimeRetirementError means the desired state is unchanged.
	Retire(ctx context.Context, instanceID string) error
	// Health is GET /instances/{id}/health; ErrRuntimeNotRunning when the
	// workload never started or was reaped.
	Health(ctx context.Context, instanceID string) (RuntimeHealth, error)
	// Validate is POST /containers/validate with dry_run: Valid false
	// carries the refusal text.
	Validate(ctx context.Context, name string, jsonSpec map[string]any) (RuntimeValidation, error)
	// ImportPackage is POST /packages/import: the image an npx/uvx package
	// became. *PackageRejectedError is final (422); any other error is retried later.
	ImportPackage(ctx context.Context, instanceID string) (ImportedPackage, error)
}

// RuntimeHealth is one workload's health report.
type RuntimeHealth struct {
	Healthy bool
	Status  string
}

// ErrRuntimeNotRunning is a workload the runtime does not run.
var ErrRuntimeNotRunning = errors.New("mcp runtime: not running")

// RuntimeRetirementError is a retirement that did not finish: Conflict is
// the manager's 409 (a request still holds the workload), otherwise 503.
type RuntimeRetirementError struct {
	Conflict bool
	Msg      string
}

func (e *RuntimeRetirementError) Error() string { return e.Msg }

// RuntimeValidation is the validate answer; Details is the manager's body.
type RuntimeValidation struct {
	Valid   bool
	Details map[string]any
	Message string
}

// ImportedPackage is a package import's result.
type ImportedPackage struct {
	Image   string
	Command []string
	Port    int
	Package map[string]any
}

// PackageRejectedError is a package the runtime cannot convert.
type PackageRejectedError struct{ Msg string }

func (e *PackageRejectedError) Error() string { return e.Msg }

// AgentConnectionUse is one mcp tool config of an agent naming a connection (agents/api).
type AgentConnectionUse = agentsapi.AgentConnectionUse

// AgentTools is agents' read of their saved tools JSON (agents/api).
type AgentTools = agentsapi.AgentTools

// ClientBundles is agents' read of a client's attachments for its MCP endpoint (agents/api).
type ClientBundles = agentsapi.ClientBundles

// AuditWriter is governance's audit trail, written in the caller's transaction (governance/api).
type AuditWriter = governanceapi.AuditWriter

// WorkspaceRule is one enabled workspace-subject policy rule (governance/api).
type WorkspaceRule = governanceapi.WorkspaceRule

// ToolPolicies is governance's read of the policy layers (workspace_tool_policy
// and the workspace+user effective policy).
type ToolPolicies = governanceapi.ToolPolicies

// EgressExitBinding is governance's require_bindable (governance/api).
type EgressExitBinding = governanceapi.EgressExitBinding

// AgentApprovals is governance's read of agents' enabled approval rule
// targets (approval_targets_for_agents), for /consumers' confirm_tools.
type AgentApprovals = governanceapi.ApprovalTargets

// Outbound is the outbound HTTP the module makes: member-supplied URLs
// through the pinned, SSRF-vetted transport, and the address policy.
type Outbound interface {
	Transport(dest netguard.Destination) http.RoundTripper
	Guard() *netguard.Guard
}

// KV is the short-lived state the OAuth flow keeps (Redis): SetEx and GetDel.
type KV interface {
	SetEx(ctx context.Context, key, value string, ttl time.Duration) error
	// GetDel returns ok false when the key is absent or expired.
	GetDel(ctx context.Context, key string) (string, bool, error)
}

// OAuthStore is the OAuth connect flow's writes (store.OAuthConnect): an auth
// config minted for one connection (ownerKind mcp_instance or
// openapi_connection), and an API connection's credential attached (status active).
type OAuthStore interface {
	InsertOwnedAuth(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.AuthConfigNew, ownerKind string, owner uuid.UUID, now time.Time) (domain.AuthConfig, error)
	AttachConnectionAuth(ctx context.Context, s db.Session, connectionID, authConfigID uuid.UUID, now time.Time) (bool, error)
}

// CatalogAPIItem is a one-click API catalog item (CatalogApiItem).
type CatalogAPIItem struct {
	ID          uuid.UUID
	ExternalID  string
	Name        string
	Description *string
	Spec        map[string]any
}

// CatalogItems is catalog's load_catalog_api_item: *domain.NotFound "Catalog
// connection not found", *domain.Invalid "Catalog item is not a one-click API connection".
type CatalogItems interface {
	CatalogAPIItem(ctx context.Context, ws scope.Workspace, id uuid.UUID) (CatalogAPIItem, error)
}
