package store

import (
	"context"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Installation reads and creates the single installation row. The table has
// no workspace, so its queries run through db.Global.
type Installation struct{}

// GetOrCreate inserts the row with a fresh id when none exists and returns the
// id of the one row. Concurrent callers all insert; the single-row index keeps
// one and the rest read it.
func (Installation) GetOrCreate(ctx context.Context, g db.Global, now time.Time) (string, error) {
	var id string
	err := g.Write(ctx, func(ctx context.Context, q db.Querier) error {
		fresh := strings.ReplaceAll(uuid.NewString(), "-", "")
		if err := New(q).InsertInstallation(ctx, InsertInstallationParams{ID: fresh, Now: utc(now)}); err != nil {
			return err
		}
		got, err := New(q).GetInstallation(ctx)
		id = got
		return err
	})
	return id, err
}

// utc is a timestamp without time zone holding t in UTC.
func utc(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}
