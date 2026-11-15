package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

func TestOAuthConnectWrites(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	conn := insertConnection(t, pool, s, "pending", nil, "[]")
	if _, err := pool.Exec(ctx, `UPDATE openapi_connections SET status = 'pending' WHERE id = $1`, conn); err != nil {
		t.Fatal(err)
	}
	o := OAuthConnect{}
	now := time.Now()
	id := uuid.New()
	a, err := o.InsertOwnedAuth(ctx, s, id, "u1", domain.AuthConfigNew{Name: "openapi-oauth-x", AuthType: "oauth2",
		Config: map[string]any{"token_url": "https://t"}}, "openapi_connection", conn, now)
	if err != nil {
		t.Fatal(err)
	}
	if a.OpenAPIConnID == nil || *a.OpenAPIConnID != conn.String() || a.MCPInstanceID != nil {
		t.Fatalf("owned auth = %+v", a)
	}
	if ok, err := o.AttachConnectionAuth(ctx, other, conn, id, now); err != nil || ok {
		t.Fatalf("another workspace attached: ok=%v err=%v", ok, err)
	}
	if ok, err := o.AttachConnectionAuth(ctx, s, conn, id, now); err != nil || !ok {
		t.Fatalf("attach ok=%v err=%v", ok, err)
	}
	var status string
	var auth uuid.UUID
	if err := pool.QueryRow(ctx, `SELECT status, auth_config_id FROM openapi_connections WHERE id = $1`, conn).Scan(&status, &auth); err != nil {
		t.Fatal(err)
	}
	if status != "active" || auth != id {
		t.Fatalf("connection status=%s auth=%s", status, auth)
	}
}
