package authz

import (
	"context"
	"errors"
	"log/slog"
	"slices"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// WorkspaceAuthority resolves workspace reach (auth/authorization.py
// AuthorizationService); the "authorization" extension replaces it.
type WorkspaceAuthority interface {
	// AccessibleWorkspaces returns workspace ids the principal may act in
	// beyond ownership and membership.
	AccessibleWorkspaces(ctx context.Context, p authn.Principal) ([]string, error)
	// CanWrite reports whether the caller may mutate entities in workspaceID.
	CanWrite(ctx context.Context, c authn.Caller, workspaceID string) (bool, error)
	// CanAdminister reports whether the caller may change the workspace itself
	// (policy, spend limits, access grants). Membership does not confer it.
	CanAdminister(ctx context.Context, c authn.Caller, workspaceID string) (bool, error)
}

// AdministersByOwnership is the default CanAdminister: the personal workspace
// (id equal to the user id) or one listed in AdminWorkspaces. A nil list
// denies. An implementation with its own roles overrides it; one that has not
// considered the question inherits ownership-only rather than a hole.
func AdministersByOwnership(c authn.Caller, workspaceID string) bool {
	return workspaceID == c.UserID || slices.Contains(c.AdminWorkspaces, workspaceID)
}

// WorkspaceScoped is the open-core WorkspaceAuthority: owned and joined
// workspaces only, both resolved by the request; it grants nothing on top.
type WorkspaceScoped struct{}

func (WorkspaceScoped) AccessibleWorkspaces(context.Context, authn.Principal) ([]string, error) {
	return []string{}, nil
}

func (WorkspaceScoped) CanWrite(_ context.Context, c authn.Caller, workspaceID string) (bool, error) {
	return workspaceID == c.Workspace.ID(), nil
}

func (WorkspaceScoped) CanAdminister(_ context.Context, c authn.Caller, workspaceID string) (bool, error) {
	return AdministersByOwnership(c, workspaceID), nil
}

// OwnedWorkspaces lists the workspaces a user owns (workspaces.owner_user_id),
// which is what confers administration; the graph's Workspace#admin tuple
// feeds resource checks only.
type OwnedWorkspaces interface {
	OwnedWorkspaceIDs(ctx context.Context, userID string) ([]string, error)
}

// NotAdminDetail is the 403 detail of a refused admin action.
const NotAdminDetail = "Only a workspace admin may perform this action"

// WorkspaceRequiredDetail is the 422 detail of an admin check naming no workspace.
const WorkspaceRequiredDetail = "workspace_id is required"

// ErrNotWorkspaceAdmin refuses an admin action (403, NotAdminDetail).
var ErrNotWorkspaceAdmin = errors.New("workspace admin required")

// ErrWorkspaceRequired refuses an admin check with no target (422, WorkspaceRequiredDetail).
var ErrWorkspaceRequired = errors.New("workspace id required")

// Admins answers "may this caller administer that workspace" for every door,
// HTTP or not (auth/authorization.py is_workspace_admin and friends).
type Admins struct {
	authority WorkspaceAuthority
	owned     OwnedWorkspaces
	log       *slog.Logger
}

// NewAdmins builds Admins; log may be nil for slog.Default.
func NewAdmins(authority WorkspaceAuthority, owned OwnedWorkspaces, log *slog.Logger) Admins {
	if log == nil {
		log = slog.Default()
	}
	return Admins{authority: authority, owned: owned, log: log}
}

// resolve fills AdminWorkspaces for a caller minted outside the HTTP edge.
// nil means not asked yet, empty means asked and administers nothing. A
// failed lookup resolves to empty: denying is recoverable, granting is not.
func (a Admins) resolve(ctx context.Context, c *authn.Caller) {
	if c.AdminWorkspaces != nil {
		return
	}
	ids, err := a.owned.OwnedWorkspaceIDs(ctx, c.UserID)
	if err != nil {
		a.log.WarnContext(ctx, "could not resolve owned workspaces; denying admin", "user_id", c.UserID, "error", err)
		ids = nil
	}
	if ids == nil {
		ids = []string{}
	}
	c.AdminWorkspaces = ids
}

// IsAdmin reports whether the caller administers the workspace it acts in.
// A run never does: it acts as its agent, whoever it is attributed to.
func (a Admins) IsAdmin(ctx context.Context, c *authn.Caller) (bool, error) {
	if c.ActsAsAgent() {
		return false, nil
	}
	a.resolve(ctx, c)
	return a.authority.CanAdminister(ctx, *c, c.Workspace.ID())
}

// Require returns ErrNotWorkspaceAdmin unless IsAdmin. Endpoints that write
// policy, money or the graph gate on it; membership is not enough.
func (a Admins) Require(ctx context.Context, c *authn.Caller) error {
	ok, err := a.IsAdmin(ctx, c)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotWorkspaceAdmin
	}
	return nil
}

// RequireOf is Require for a workspace named in the path, which need not be
// the one the caller acts in. An empty target is refused, not defaulted.
func (a Admins) RequireOf(ctx context.Context, c *authn.Caller, workspaceID string) error {
	if workspaceID == "" {
		return ErrWorkspaceRequired
	}
	if c.ActsAsAgent() {
		return ErrNotWorkspaceAdmin
	}
	a.resolve(ctx, c)
	ok, err := a.authority.CanAdminister(ctx, *c, workspaceID)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotWorkspaceAdmin
	}
	return nil
}

// Edge actions on an agent (auth/access.py).
const (
	AgentRead    = "agent:read"
	AgentWrite   = "agent:write"
	AgentExecute = "agent:execute"
	AgentStream  = "agent:stream"
)

// EdgeDecision is the answer of AuthorizeAgentAction.
type EdgeDecision struct {
	Allowed bool
	Reason  string
}

// AuthorizeAgentAction is the one edge admission decision every protocol
// (REST, A2A, MCP, triggers) asks: may p perform action on the agent. A nil p
// is anonymous; there are no public grants, so it is refused. An agent's key
// reaches that agent only. Otherwise the agent's workspace must be accessible.
func AuthorizeAgentAction(p *authn.Principal, action, agentWorkspaceID, agentID string) EdgeDecision {
	if p == nil {
		return EdgeDecision{Reason: "anonymous subject and no public grant"}
	}
	if p.BoundAgentID != "" {
		if p.BoundAgentID == agentID && p.BoundWorkspaceID == agentWorkspaceID {
			return EdgeDecision{Allowed: true, Reason: "agent key"}
		}
		return EdgeDecision{Reason: "key bound to agent " + p.BoundAgentID}
	}
	if slices.Contains(p.AccessibleWorkspaces, agentWorkspaceID) {
		return EdgeDecision{Allowed: true, Reason: "workspace scope"}
	}
	return EdgeDecision{Reason: "subject " + p.UserID + " not in agent workspace " + agentWorkspaceID}
}
