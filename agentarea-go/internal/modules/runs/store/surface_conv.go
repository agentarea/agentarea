package store

import (
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// NoRows reports a :one query that found nothing.
func NoRows(err error) bool { return errors.Is(err, pgx.ErrNoRows) }

// Text is a nullable text parameter: nil is NULL.
func Text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

// TextPtr reads a nullable text column.
func TextPtr(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

// Timestamp is a timestamp-without-zone parameter, in UTC.
func Timestamp(t time.Time) pgtype.Timestamp { return pgtype.Timestamp{Time: t.UTC(), Valid: true} }

// Timestamptz is a timestamptz parameter; the zero time is NULL.
func Timestamptz(t time.Time) pgtype.Timestamptz {
	if t.IsZero() {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: t, Valid: true}
}

// TimestampPtr reads a nullable timestamp column as UTC.
func TimestampPtr(t pgtype.Timestamp) *time.Time {
	if !t.Valid {
		return nil
	}
	u := t.Time.UTC()
	return &u
}

// TimestamptzPtr reads a nullable timestamptz column as UTC.
func TimestamptzPtr(t pgtype.Timestamptz) *time.Time {
	if !t.Valid {
		return nil
	}
	u := t.Time.UTC()
	return &u
}
