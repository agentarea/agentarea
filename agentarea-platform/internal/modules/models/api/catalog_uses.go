package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// SpecUses is which provider and model specs any workspace's configs and
// instances are on, read in a catalog sync's transaction.
type SpecUses interface {
	UsedProviderSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
	UsedModelSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
}
