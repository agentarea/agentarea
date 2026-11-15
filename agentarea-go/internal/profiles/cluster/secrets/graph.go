package secrets

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

// secretResourceType is what the permission check names; a secret is a
// governed resource:<id> like any other.
const secretResourceType = "secret"

// Guard is kernel.Guard over the graph: use_secret on resource:<id>.
type Guard struct {
	perms authz.Permissions
}

var _ kernel.Guard = (*Guard)(nil)

// NewGuard checks through perms.
func NewGuard(perms authz.Permissions) *Guard { return &Guard{perms: perms} }

// CanUseSecret returns a graph failure as an error, never as an answer.
func (g *Guard) CanUseSecret(ctx context.Context, subject, secretID string) (bool, error) {
	return g.perms.Check(ctx, subject, kernel.UseSecret, secretResourceType, secretID)
}

// Ownership is kernel.Ownership over the graph (rebac.ownership).
type Ownership struct {
	graph authz.ReadWriter
}

var _ kernel.Ownership = (*Ownership)(nil)

// NewOwnership writes through graph.
func NewOwnership(graph authz.ReadWriter) *Ownership { return &Ownership{graph: graph} }

// GrantOwner puts the secret under the workspace's root project and makes
// owner its reader, writer and manager.
func (o *Ownership) GrantOwner(ctx context.Context, secretID, workspaceID, owner string) error {
	return authz.GrantResourceOwner(ctx, o.graph, secretID, workspaceID, owner, authz.OwnerRelations())
}

// Revoke deletes every tuple on the secret once its row is gone.
func (o *Ownership) Revoke(ctx context.Context, secretID string) error {
	return authz.RevokeResource(ctx, o.graph, secretID)
}
