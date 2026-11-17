package store

import (
	"bytes"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// IsNoRows is a :one query that found nothing.
func IsNoRows(err error) bool { return errors.Is(err, pgx.ErrNoRows) }

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

func fromNullUUID(u uuid.NullUUID) *string {
	if !u.Valid {
		return nil
	}
	s := u.UUID.String()
	return &s
}

// naive is a timestamp without time zone holding t's UTC wall clock, as the
// Python writes (datetime.utcnow()).
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func fromTimestamp(t pgtype.Timestamp) time.Time { return t.Time }

func fromTimestampPtr(t pgtype.Timestamp) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time
	return &v
}

// jsonMap decodes a stored JSON object, keeping numbers as written.
func jsonMap(b []byte) (map[string]any, error) {
	if len(b) == 0 {
		return nil, nil
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	return m, nil
}

func jsonObject(m map[string]any) []byte {
	if m == nil {
		m = map[string]any{}
	}
	raw, err := json.Marshal(m)
	if err != nil {
		panic(err) // a map of decoded JSON values always marshals
	}
	return raw
}

func tstz(t time.Time) pgtype.Timestamptz { return pgtype.Timestamptz{Time: t, Valid: true} }
