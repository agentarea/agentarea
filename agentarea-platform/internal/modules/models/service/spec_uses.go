package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

// SpecUses implements api.SpecUses.
type SpecUses struct{}

var _ api.SpecUses = SpecUses{}

func set(ids []uuid.UUID, err error) (map[uuid.UUID]bool, error) {
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]bool, len(ids))
	for _, id := range ids {
		out[id] = true
	}
	return out, nil
}

func (SpecUses) UsedProviderSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	if len(ids) == 0 {
		return map[uuid.UUID]bool{}, nil
	}
	return set(store.New(tx.Q()).UsedProviderSpecs(ctx, ids))
}

func (SpecUses) UsedModelSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	if len(ids) == 0 {
		return map[uuid.UUID]bool{}, nil
	}
	return set(store.New(tx.Q()).UsedModelSpecs(ctx, ids))
}
