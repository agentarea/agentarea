package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// CatalogUses implements api.CatalogUses.
type CatalogUses struct{}

var _ api.CatalogUses = CatalogUses{}

func (CatalogUses) MoveItem(ctx context.Context, tx db.Session, oldID, newID uuid.UUID, oldCopy, newCopy *uuid.UUID) (int, error) {
	q := store.New(tx.Q())
	n, err := q.MoveOpenAPIConnectionItems(ctx, store.MoveOpenAPIConnectionItemsParams{OldID: oldID, NewID: newID})
	if err != nil {
		return 0, err
	}
	if oldCopy != nil && newCopy != nil {
		m, err := q.MoveMCPInstanceSpecs(ctx, store.MoveMCPInstanceSpecsParams{OldSpec: oldCopy.String(), NewSpec: newCopy.String()})
		if err != nil {
			return 0, err
		}
		n += m
	}
	return int(n), nil
}

func (CatalogUses) ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error) {
	out := map[uuid.UUID]bool{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := store.New(tx.Q()).OpenAPIReferencedItems(ctx, ids)
	if err != nil {
		return nil, err
	}
	for _, id := range rows {
		out[id] = true
	}
	return out, nil
}
