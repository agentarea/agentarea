package service

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

func TestConnectionBoardReadsStateAndScope(t *testing.T) {
	f := newInstFixture(t)
	ws := f.c.Workspace
	insert := `INSERT INTO mcp_server_instances (id, workspace_id, created_by, name, server_spec_id, transport, network_scope, verification, last_dispatch, managed_by)
		VALUES ($1, $2, 'owner', $3, 's', 'url', $4, $5::jsonb, $6::jsonb, $7)`
	broken, calls, fine, plat := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	globalExec(t, f.pools, insert, broken, ws.ID(), "b-verify", "private", `{"status":"failed","error":"401"}`, nil, nil)
	globalExec(t, f.pools, insert, calls, ws.ID(), "a-calls", "private", `{"status":"ok"}`, `{"status":"failed","error":"boom"}`, nil)
	globalExec(t, f.pools, insert, fine, ws.ID(), "c-fine", "egress", `{"status":"ok"}`, nil, nil)
	globalExec(t, f.pools, insert, plat, "platform-ws", "p-down", "egress", `{"status":"failed"}`, nil, "platform")

	b := ConnectionBoard{DB: f.pools}
	ctx := context.Background()
	failing, err := b.FailingMCPInstances(ctx, ws, 20)
	if err != nil || len(failing) != 2 || failing[0].ID != calls || failing[1].ID != broken {
		t.Fatalf("failing: %+v %v", failing, err)
	}
	if one, _ := b.FailingMCPInstances(ctx, ws, 1); len(one) != 1 {
		t.Fatalf("limit: %+v", one)
	}
	all, err := b.MCPInstances(ctx, ws)
	if err != nil {
		t.Fatal(err)
	}
	scopes := map[string]string{}
	for _, i := range all {
		scopes[i.ID] = i.NetworkScope
	}
	if scopes[fine] != "egress" || scopes[broken] != "private" {
		t.Fatalf("scopes: %v", scopes)
	}
	conns, err := b.OpenAPIConnections(ctx, ws)
	if err != nil || len(conns) != 0 {
		t.Fatalf("openapi: %+v %v", conns, err)
	}
}
