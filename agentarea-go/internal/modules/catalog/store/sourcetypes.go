package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// SourceTypes reads the global catalog's source-type rows.
type SourceTypes struct{}

// Rows is every active source-type row, by registry priority, rank and name.
func (SourceTypes) Rows(ctx context.Context, q db.Querier) ([]api.SourceTypeRow, error) {
	rows, err := New(q).SourceTypeRows(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]api.SourceTypeRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, api.SourceTypeRow{Slug: r.ExternalID, Spec: r.Spec})
	}
	return out, nil
}

// RowsBySlug is the active rows of one slug, by registry priority.
func (SourceTypes) RowsBySlug(ctx context.Context, q db.Querier, slug string) ([]api.SourceTypeRow, error) {
	rows, err := New(q).SourceTypeRowsBySlug(ctx, slug)
	if err != nil {
		return nil, err
	}
	out := make([]api.SourceTypeRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, api.SourceTypeRow{Slug: r.ExternalID, Spec: r.Spec})
	}
	return out, nil
}
