package store

import (
	"errors"

	"github.com/jackc/pgx/v5"
)

// IsNoRows reports a :one query that matched no row.
func IsNoRows(err error) bool { return errors.Is(err, pgx.ErrNoRows) }
