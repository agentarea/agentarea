package store

import (
	"context"
	"slices"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

func boundInstance(t *testing.T, pool *pgxpool.Pool, ws db.Session, transport, jsonSpec string) string {
	t.Helper()
	id := uuid.NewString()
	if _, err := pool.Exec(context.Background(), `INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id,
		created_by, transport, json_spec) VALUES ($1, 's', $2, $3, 'member', $4, $5::jsonb)`,
		id, "egress-proof-"+id[:8], ws.Workspace().ID(), transport, jsonSpec); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestTheInstancesBoundToAnExitAreTheWorkspacesOwn(t *testing.T) {
	pool := openPool(t)
	tenant, other := workspace(t, pool), workspace(t, pool)
	exit := uuid.NewString()
	bound := boundInstance(t, pool, tenant, "docker", `{"egress_exit": "`+exit+`"}`)
	boundURL := boundInstance(t, pool, tenant, "url", `{"egress_exit": "`+exit+`"}`)
	boundInstance(t, pool, tenant, "docker", `{}`)
	boundInstance(t, pool, tenant, "docker", `{"egress_exit": "`+uuid.NewString()+`"}`)
	boundInstance(t, pool, other, "docker", `{"egress_exit": "`+exit+`"}`)

	got, err := EgressBound(context.Background(), tenant, exit)
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, i := range got {
		ids = append(ids, i.ID)
		if i.Name == "" || (i.ID == bound && i.Transport != "docker") || (i.ID == boundURL && i.Transport != "url") {
			t.Fatalf("instance %+v", i)
		}
	}
	slices.Sort(ids)
	want := []string{bound, boundURL}
	slices.Sort(want)
	if !slices.Equal(ids, want) {
		t.Fatalf("bound %v, want %v", ids, want)
	}
}
