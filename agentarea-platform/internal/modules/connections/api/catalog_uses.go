package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// CatalogUses is what a catalog sync does to the OpenAPI connections and MCP
// instances made from its items; every method runs in the sync's transaction
// across workspaces.
type CatalogUses interface {
	// MoveItem points the OpenAPI connections made from oldID at newID and,
	// both set, the MCP instances running from oldCopy at newCopy; how many moved.
	MoveItem(ctx context.Context, tx db.Session, oldID, newID uuid.UUID, oldCopy, newCopy *uuid.UUID) (int, error)
	// ReferencedItems are those of ids an OpenAPI connection names.
	ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
}
