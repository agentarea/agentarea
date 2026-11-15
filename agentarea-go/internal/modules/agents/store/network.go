package store

import "github.com/jackc/pgx/v5/pgtype"

// OptText reads a nullable text column.
func OptText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	v := t.String
	return &v
}
