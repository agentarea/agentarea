package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/domain"
)

// Signups stores sign-up attributions; the table has no workspace.
type Signups struct{}

// Insert stores the identity's attribution once; true when this call inserted it.
func (Signups) Insert(ctx context.Context, g db.Global, identityID string, createdAt time.Time, method *string, a domain.Attribution, now time.Time) (bool, error) {
	inserted := false
	err := g.Write(ctx, func(ctx context.Context, q db.Querier) error {
		_, err := New(q).InsertSignupAttribution(ctx, InsertSignupAttributionParams{
			IdentityID: identityID, CreatedAt: utc(createdAt), UpdatedAt: utc(now), Method: text(method), Channel: a.Channel,
			ReferrerHost: text(a.ReferrerHost), LandingHost: text(a.LandingHost), LandingPath: text(a.LandingPath),
			UtmSource: text(a.UTMSource), UtmMedium: text(a.UTMMedium), UtmCampaign: text(a.UTMCampaign),
		})
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return nil
		case err != nil:
			return err
		}
		inserted = true
		return nil
	})
	return inserted, err
}

func text(s *string) pgtype.Text {
	if s == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *s, Valid: true}
}

// LockForPulse takes the pulse's advisory lock and the installation row in one transaction and
// calls fn with the row; fn's true stamps the pulse sent at now and is returned. Another replica
// holding the lock is false.
func (Installation) LockForPulse(ctx context.Context, d db.Database, key db.LockKey, now time.Time, fn func(ctx context.Context, row domain.Installation) (bool, error)) (bool, error) {
	if _, err := (Installation{}).GetOrCreate(ctx, d.Global(), now); err != nil {
		return false, err
	}
	sent := false
	_, err := d.TryLock(ctx, key, func(ctx context.Context, q db.Querier) error {
		row, err := New(q).LockInstallationForPulse(ctx)
		if err != nil {
			return err
		}
		due := domain.Installation{ID: row.ID, CreatedAt: row.CreatedAt.Time}
		if row.LastPulseAt.Valid {
			t := row.LastPulseAt.Time
			due.LastPulse = &t
		}
		ok, err := fn(ctx, due)
		if err != nil || !ok {
			return err
		}
		if err := New(q).SetLastPulse(ctx, SetLastPulseParams{ID: row.ID, At: utc(now)}); err != nil {
			return err
		}
		sent = true
		return nil
	})
	return sent && err == nil, err
}
