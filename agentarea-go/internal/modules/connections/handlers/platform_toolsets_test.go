package handlers

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// TestToolWritesCheckTheRoutesRelation: each @requires tool refuses a
// malformed id and a caller the graph denies before touching anything.
func TestToolWritesCheckTheRoutesRelation(t *testing.T) {
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "member"}, Workspace: ws}
	w := &world{allow: false}
	svc := service.New(service.Deps{DB: memDB{}, Graph: worldGraph{w}})
	ctx := context.Background()
	id := uuid.NewString()
	openapi := OpenAPIToolset{Svc: svc}
	mcp := MCPServersToolset{Svc: svc}
	for name, call := range map[string]func(string) error{
		"openapi update":   func(id string) error { _, err := openapi.Update(ctx, c, id, []byte(`{"name":"x"}`)); return err },
		"openapi discover": func(id string) error { _, err := openapi.DiscoverTools(ctx, c, id); return err },
		"openapi delete":   func(id string) error { _, err := openapi.Delete(ctx, c, id); return err },
		"mcp update":       func(id string) error { _, err := mcp.Update(ctx, c, id, []byte(`{"name":"x"}`)); return err },
		"mcp delete":       func(id string) error { _, err := mcp.Delete(ctx, c, id); return err },
		"mcp verify":       func(id string) error { _, _, err := mcp.Verify(ctx, c, id); return err },
	} {
		if err := call(id); err == nil || err.Error() != "Permission denied" {
			t.Fatalf("%s: %v", name, err)
		}
		param := "instance_id"
		if name[:7] == "openapi" {
			param = "connection_id"
		}
		if err := call("jira"); err == nil || err.Error() != param+" must be a UUID" {
			t.Fatalf("%s malformed: %v", name, err)
		}
	}
}
