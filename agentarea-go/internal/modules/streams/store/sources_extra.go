package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// SourceByID finds a source by id in any workspace; false when none.
func (Streams) SourceByID(ctx context.Context, q db.Querier, id uuid.UUID) (domain.Source, bool, error) {
	r, err := New(q).SourceByID(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Source{}, false, nil
	}
	if err != nil {
		return domain.Source{}, false, err
	}
	return ToSource(r), true, nil
}
