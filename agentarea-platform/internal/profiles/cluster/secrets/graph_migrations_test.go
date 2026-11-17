package secrets

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/google/uuid"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
)

func TestSecretOwnersMigrationGrantsCreators(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	ws, agent := uuid.NewString(), uuid.NewString()
	byUser, byAgent, byPlatform, owned := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	for _, s := range []struct {
		sql  string
		args []any
	}{
		{`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, []any{ws, "ws-" + ws[:8]}},
		{`INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'a', 'active', $2, 'u1', 'a')`, []any{agent, ws}},
		{`INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, created_by) VALUES ($1, $2, 'one', 'x', 'u1')`, []any{byUser, ws}},
		{`INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, created_by) VALUES ($1, $2, 'two', 'x', $3)`, []any{byAgent, ws, agent}},
		{`INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, created_by) VALUES ($1, $2, 'three', 'x', 'platform')`, []any{byPlatform, ws}},
		{`INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, created_by, owner_type, owner_id) VALUES ($1, $2, 'four', 'x', 'u1', 'trigger', $3)`, []any{owned, ws, owned}},
	} {
		if _, err := d.pool.Exec(ctx, s.sql, s.args...); err != nil {
			t.Fatal(err)
		}
	}
	g := &memGraph{}
	step := SecretOwners(quietLogger())
	if err := kauthz.CheckMigrations([]kauthz.GraphMigration{step}); err != nil {
		t.Fatal(err)
	}
	if err := step.Apply(ctx, d.pool, func(context.Context) (kauthz.Graph, error) { return graphOf{g}, nil }); err != nil {
		t.Fatal(err)
	}
	has := func(user, rel, id string) bool {
		return slices.Contains(g.tuples, kauthz.Tuple{User: user, Relation: rel, Object: "resource:" + id})
	}
	project := kauthz.RootProject(ws)
	for _, id := range []string{byUser, byAgent, byPlatform} {
		if !has(project, kauthz.RelProject, id) {
			t.Errorf("%s not under the root project", id)
		}
	}
	for _, rel := range kauthz.OwnerRelations() {
		if !has("User:u1", rel, byUser) || !has("Agent:"+agent, rel, byAgent) {
			t.Errorf("owner %s missing", rel)
		}
	}
	for _, tp := range g.tuples {
		if tp.Object == "resource:"+owned || (tp.Object == "resource:"+byPlatform && tp.Relation != kauthz.RelProject) {
			t.Errorf("unexpected tuple %v", tp)
		}
	}
}

func TestSecretOwnersMigrationNeedsNoGraphWithNothingToDo(t *testing.T) {
	d := openTestDB(t)
	ctx := context.Background()
	tx, err := d.pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `UPDATE encrypted_secrets SET owner_type = 'trigger' WHERE owner_type IS NULL`); err != nil {
		t.Fatal(err)
	}
	unreachable := func(context.Context) (kauthz.Graph, error) { return nil, errors.New("graph not reachable") }
	if err := SecretOwners(quietLogger()).Apply(ctx, tx, unreachable); err != nil {
		t.Fatal(err)
	}
}

// graphOf is memGraph as the whole graph port.
type graphOf struct{ *memGraph }

func (graphOf) BatchCheck(context.Context, []kauthz.CheckItem) ([]bool, error) { return nil, nil }
func (graphOf) ListObjects(context.Context, string, string, string) ([]string, error) {
	return nil, nil
}
