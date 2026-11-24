package main

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestTables(t *testing.T) {
	cases := []struct {
		name string
		sql  string
		want []string
	}{
		{"select", `-- name: GetAgent :one
SELECT * FROM agents WHERE id = @id AND workspace_id = @workspace_id;`, []string{"agents"}},
		{"joins and comma list", `SELECT a.id FROM agents a, clients AS c
JOIN client_skills cs ON cs.client_id = c.id LEFT JOIN "skills" s USING (skill_id)`,
			[]string{"agents", "client_skills", "clients", "skills"}},
		{"insert with columns and conflict", `INSERT INTO tasks (id, status) VALUES ($1, 'from x')
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status RETURNING *`, []string{"tasks"}},
		{"update and delete using", `UPDATE public.tasks SET x = 1 FROM cost_entries ce WHERE ce.task_id = tasks.id;
DELETE FROM task_events USING tasks WHERE task_events.task_id = tasks.id`,
			[]string{"cost_entries", "task_events", "tasks"}},
		{"cte, functions, extract, distinct from, locking", `WITH recent AS (SELECT * FROM task_events), ids AS (SELECT 1)
SELECT EXTRACT(EPOCH FROM created_at), x IS DISTINCT FROM y
FROM recent, unnest(@ids::uuid[]) u JOIN LATERAL (SELECT 1 FROM tasks) l ON true
FOR UPDATE OF recent SKIP LOCKED`, []string{"task_events", "tasks"}},
		{"schema qualified and system", `SELECT * FROM agentarea_enterprise.usage_hourly, pg_catalog.pg_class, information_schema.tables`,
			[]string{"agentarea_enterprise.usage_hourly"}},
		{"strings and comments ignored", `SELECT 'FROM fake' /* FROM fake2 */, $$ FROM fake3 $$ FROM agents`, []string{"agents"}},
	}
	for _, c := range cases {
		if got := Tables(c.sql); !slices.Equal(got, c.want) {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}

func TestCheckFindsForeignAndUnknownTables(t *testing.T) {
	dir := t.TempDir()
	owners := filepath.Join(dir, "owners.csv")
	write(t, owners, "table,owner\nagents,agents\nworkspaces,identity\nevent_outbox,kernel\n")
	write(t, filepath.Join(dir, "modules/agents/store/queries/agents.sql"),
		"SELECT * FROM agents JOIN workspaces w ON w.id = agents.workspace_id;\nINSERT INTO event_outbox (id) VALUES (1);\nSELECT * FROM nowhere;")
	write(t, filepath.Join(dir, "modules/identity/store/queries/workspaces.sql"), "SELECT * FROM workspaces")
	write(t, filepath.Join(dir, "modules/agents/runtime/store/queries/leases.sql"), "SELECT * FROM workspaces")
	problems, files, err := check(owners, filepath.Join(dir, "modules"))
	if err != nil {
		t.Fatal(err)
	}
	if files != 3 || len(problems) != 4 {
		t.Fatalf("files=%d problems=%v", files, problems)
	}
	joined := strings.Join(problems, "\n")
	for _, want := range []string{`runtime/store/queries/leases.sql: table "workspaces" is owned by identity, not agents`, `"workspaces" is owned by identity, not agents`, `"event_outbox" is owned by kernel`, `"nowhere" is not in`} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %s", want, joined)
		}
	}
}

func TestOwnersFileIsWellFormed(t *testing.T) {
	f, err := os.Open("owners.csv")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	owners, err := readOwners(f)
	if err != nil {
		t.Fatal(err)
	}
	modules := map[string]bool{"kernel": true, "enterprise": true}
	entries, err := os.ReadDir("../../internal/modules")
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		modules[e.Name()] = true
	}
	for table, owner := range owners {
		if !modules[owner] {
			t.Errorf("table %s: owner %q is not a module", table, owner)
		}
	}
}

func write(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
}
