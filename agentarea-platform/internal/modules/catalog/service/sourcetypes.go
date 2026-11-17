package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// SourceTypes is the global catalog's source types (api.SourceTypes).
type SourceTypes struct{ DB db.Database }

var _ api.SourceTypes = SourceTypes{}

// SourceTypeRows implements api.SourceTypes.
func (s SourceTypes) SourceTypeRows(ctx context.Context) ([]api.SourceTypeRow, error) {
	q, release, err := s.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.SourceTypes{}.Rows(ctx, q)
}

// SourceTypeRowsBySlug implements api.SourceTypes.
func (s SourceTypes) SourceTypeRowsBySlug(ctx context.Context, slug string) ([]api.SourceTypeRow, error) {
	q, release, err := s.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.SourceTypes{}.RowsBySlug(ctx, q, slug)
}
