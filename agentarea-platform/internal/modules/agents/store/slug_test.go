package store

import (
	"errors"
	"fmt"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"
)

func TestSlugTakenOnlyForSlugConstraints(t *testing.T) {
	for err, want := range map[error]bool{
		fmt.Errorf("insert: %w", &pgconn.PgError{Code: "23505", ConstraintName: "uq_agents_workspace_slug"}): true,
		&pgconn.PgError{Code: "23505", ConstraintName: "uq_skill_collections_workspace_slug"}:                true,
		&pgconn.PgError{Code: "23505", ConstraintName: "uq_skills_registry_item"}:                            false,
		&pgconn.PgError{Code: "23503", ConstraintName: "uq_agents_workspace_slug"}:                           false,
		errors.New("other"): false,
	} {
		if SlugTaken(err) != want {
			t.Errorf("%v: want %v", err, want)
		}
	}
}
