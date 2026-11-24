package store

import (
	"errors"

	"github.com/jackc/pgx/v5/pgconn"
)

// UniqueViolation is SQLSTATE unique_violation.
const UniqueViolation = "23505"

// ConstraintError is a write a table constraint refused, by SQLSTATE.
type ConstraintError struct{ Code string }

func (e *ConstraintError) Error() string { return "constraint violation " + e.Code }

// Constraint is the SQLSTATE of the integrity constraint (class 23) err broke.
func Constraint(err error) (string, bool) {
	var ce *ConstraintError
	if errors.As(err, &ce) {
		return ce.Code, true
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) && len(pg.Code) == 5 && pg.Code[:2] == "23" {
		return pg.Code, true
	}
	return "", false
}
