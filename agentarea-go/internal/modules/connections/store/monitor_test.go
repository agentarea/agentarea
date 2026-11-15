package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestMonitorQueries(t *testing.T) {
	pool := openPool(t)
	ws := workspace(t, pool)
	ctx := context.Background()
	insert := func(spec string) uuid.UUID {
		id := uuid.New()
		if _, err := pool.Exec(ctx, `INSERT INTO mcp_server_instances (id, workspace_id, created_by, name, server_spec_id, transport, json_spec, verification)
			VALUES ($1, $2, 'u1', 'n', $3, 'command', $4::json, '{"schema_version":1,"status":"succeeded"}')`,
			id, ws.Workspace().ID(), uuid.NewString(), spec); err != nil {
			t.Fatal(err)
		}
		return id
	}
	fresh := insert(`{}`)
	recent := insert(`{"package_import":{"status":"unavailable","at":"` + time.Now().UTC().Format(time.RFC3339) + `"}}`)
	old := insert(`{"package_import":{"status":"unavailable","at":"2020-01-01T00:00:00+00:00"}}`)
	done := insert(`{"package_import":{"status":"imported"}}`)

	rows, err := Instances{}.PackageImportCandidates(ctx, pool, time.Now().Add(-time.Hour), 100000)
	if err != nil {
		t.Fatal(err)
	}
	got := map[uuid.UUID]bool{}
	for _, r := range rows {
		got[r.ID] = true
	}
	if !got[fresh] || !got[old] || got[recent] || got[done] {
		t.Fatalf("candidates fresh=%v old=%v recent=%v done=%v", got[fresh], got[old], got[recent], got[done])
	}

	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	row, ok, err := Instances{}.LockForImport(ctx, tx, fresh)
	if err != nil || !ok || row.Transport != "command" {
		t.Fatalf("lock %+v %v %v", row, ok, err)
	}
	if err := (Instances{}).SetImportedSpec(ctx, tx, fresh, map[string]any{"image": "pkg:1"}, "docker", time.Now()); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err := (Instances{}).StampLastDispatch(ctx, pool, fresh, map[string]any{"status": "failed", "error": "x"}); err != nil {
		t.Fatal(err)
	}
	var transport, image, dispatch string
	if err := pool.QueryRow(ctx, `SELECT transport, json_spec->>'image', last_dispatch->>'status' FROM mcp_server_instances WHERE id = $1`, fresh).
		Scan(&transport, &image, &dispatch); err != nil {
		t.Fatal(err)
	}
	if transport != "docker" || image != "pkg:1" || dispatch != "failed" {
		t.Fatalf("row %s %s %s", transport, image, dispatch)
	}
	if _, ok, err := (Instances{}).LockForImport(ctx, pool, uuid.New()); ok || err != nil {
		t.Fatalf("missing row: %v %v", ok, err)
	}
}
