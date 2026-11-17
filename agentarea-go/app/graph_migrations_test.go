package app

import (
	"context"
	"net/url"
	"os"
	"strings"
	"testing"

	"github.com/google/uuid"

	kauthz "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func TestGraphMigrationsAreInOrder(t *testing.T) {
	if err := kauthz.CheckMigrations(graphMigrations(nil)); err != nil {
		t.Fatal(err)
	}
}

// TestGraphMigrationStepFailsUnrecorded needs AGENTAREA_DB_TEST_URL.
func TestGraphMigrationStepFailsUnrecorded(t *testing.T) {
	raw := os.Getenv("AGENTAREA_DB_TEST_URL")
	if raw == "" {
		t.Skip("AGENTAREA_DB_TEST_URL not set")
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	admin, err := schema.Open(raw)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = admin.Close() }()
	name := "aa_go_graph_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.ExecContext(ctx, "DROP DATABASE "+name+" WITH (FORCE)") })
	pw, _ := u.User.Password()
	vars := map[string]string{
		"AGENTAREA_DB_HOST": u.Hostname(), "AGENTAREA_DB_PORT": u.Port(), "AGENTAREA_DB_NAME": name,
		"AGENTAREA_DB_USER": u.User.Username(), "AGENTAREA_DB_PASSWORD": pw, "AGENTAREA_DB_SSLMODE": "disable",
	}
	b, _ := quiet()
	b.lookup = mapLookup(vars)
	if err := b.Run(ctx, []string{"migrate"}); err != nil {
		t.Fatal(err)
	}
	dbc := db.LoadConfig(config.New(b.lookup))
	log := newLogger(b.stderr, config.Common{})
	failing := kauthz.GraphMigration{ID: "20991231_2359_needs_graph", Apply: func(ctx context.Context, _ db.Querier, graph kauthz.GraphProvider) error {
		_, err := graph(ctx)
		return err
	}}
	steps := append(graphMigrations(log), failing)
	err = b.applyGraphMigrations(ctx, dbc, steps, log)
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_AUTHZ_FGA_STORE_ID") {
		t.Fatalf("a step needing an unconfigured graph: %v", err)
	}
	ran := 0
	conn, err := schema.Open(strings.Replace(raw, u.Path, "/"+name, 1))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if err := conn.QueryRowContext(ctx, "SELECT count(*) FROM graph_migrations WHERE id = $1", failing.ID).Scan(&ran); err != nil || ran != 0 {
		t.Fatalf("a failed step was recorded: %d %v", ran, err)
	}
}
