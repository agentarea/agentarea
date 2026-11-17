package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// OAuthConnect is the OAuth connect flow's writes.
type OAuthConnect struct{}

// InsertOwnedAuth writes an auth config minted for one connection, deleted
// with it: ownerKind is mcp_instance or openapi_connection.
func (OAuthConnect) InsertOwnedAuth(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.AuthConfigNew, ownerKind string, owner uuid.UUID, now time.Time) (domain.AuthConfig, error) {
	p := InsertAuthConfigParams{
		ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, AuthType: n.AuthType,
		Config: jsonObject(n.Config), Name: n.Name, Description: text(n.Description), Now: naive(now),
	}
	o := uuid.NullUUID{UUID: owner, Valid: true}
	if ownerKind == "mcp_instance" {
		p.McpInstanceID = o
	} else {
		p.OpenapiConnectionID = o
	}
	r, err := New(s.Q()).InsertAuthConfig(ctx, p)
	if err != nil {
		return domain.AuthConfig{}, err
	}
	return authFrom(r)
}

// AttachConnectionAuth signs an API connection in with the auth config and
// marks it active; false when the workspace has no such connection.
func (OAuthConnect) AttachConnectionAuth(ctx context.Context, s db.Session, connectionID, authConfigID uuid.UUID, now time.Time) (bool, error) {
	n, err := New(s.Q()).AttachConnectionAuth(ctx, AttachConnectionAuthParams{
		ID: connectionID, WorkspaceID: s.Workspace().ID(),
		AuthConfigID: uuid.NullUUID{UUID: authConfigID, Valid: true}, Now: naive(now),
	})
	return n > 0, err
}
