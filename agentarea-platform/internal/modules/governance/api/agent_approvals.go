package api

import (
	"context"
	"fmt"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// AgentApprovals is the agent editor's approval toggle as policy rules
// (approval_sync.py): agent-scoped approval rules, the ones the toggle wrote
// marked managed_by "agent_tools".
type AgentApprovals interface {
	ApprovalTargets
	// Sync is sync_agent_approval_rules in the agent write's transaction s.
	Sync(ctx context.Context, s db.Session, c authn.Caller, agentID string, targets []string) error
	// Release is release_unticked_approvals: the enabled approval rules of
	// unticked the toggle did not write are deleted for a workspace admin and
	// refused (*ApprovalEnforcedError) for anyone else.
	Release(ctx context.Context, s db.Session, c authn.Caller, agentID string, unticked []string) error
}

// ApprovalEnforcedError is ApprovalEnforcedByPolicyError.
type ApprovalEnforcedError struct{ Targets []string }

func (e *ApprovalEnforcedError) Error() string {
	names := make([]string, len(e.Targets))
	for i, t := range e.Targets {
		names[i] = strings.TrimPrefix(t, "tool:")
	}
	slices.Sort(names)
	return fmt.Sprintf("Approval for %s can only be changed by a workspace admin.", strings.Join(names, ", "))
}

// InstallPolicy is CatalogInstallGuard: whether a catalog item of a registry
// and trust may become a workspace's own, and may still run.
type InstallPolicy interface {
	// RequireAllowed is require_allowed: the workspace's and the caller's
	// rules; a refusal is *InstallRefusedError.
	RequireAllowed(ctx context.Context, c authn.Caller, registryID, trust string) error
	// RunRefusal is why the workspace's rules alone keep a run from an item of that source.
	RunRefusal(ctx context.Context, ws scope.Workspace, registryID, trust string) (reason string, refused bool, err error)
}

// InstallRefusedError is CatalogInstallRefusedError (a PermissionError, 403).
type InstallRefusedError struct{ Reason string }

func (e *InstallRefusedError) Error() string { return "Install refused by policy: " + e.Reason }
