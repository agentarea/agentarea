package store

import (
	"errors"
	"strings"

	"github.com/jackc/pgx/v5/pgconn"
)

// SlugTaken is a unique violation on a workspace slug constraint: another
// request took the slug between the scan and the insert.
func SlugTaken(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && pg.Code == "23505" && strings.HasSuffix(pg.ConstraintName, "_workspace_slug")
}
