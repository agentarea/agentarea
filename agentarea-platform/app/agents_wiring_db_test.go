package app

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	agentsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/secrets"
)

// wiringGraph allows every check and lists every resource written to it.
type wiringGraph struct {
	mu      sync.Mutex
	objects map[string]bool
}

func (g *wiringGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return true, nil
}

func (g *wiringGraph) BatchCheck(_ context.Context, items []authz.CheckItem) ([]bool, error) {
	out := make([]bool, len(items))
	for i := range out {
		out[i] = true
	}
	return out, nil
}

func (g *wiringGraph) ListObjects(context.Context, string, string, string) ([]string, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var out []string
	for o := range g.objects {
		out = append(out, o)
	}
	return out, nil
}

func (g *wiringGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }

func (g *wiringGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, w := range writes {
		if id, ok := strings.CutPrefix(w.Object, authz.TypeResource+":"); ok {
			g.objects[id] = true
		}
	}
	return nil
}

type wired struct {
	m       *moduleSet
	d       db.Database
	redis   *miniredis.Miniredis
	secrets *secrets.Factory
	c       authn.Caller
}

// wiredModules builds every module as the API process does, over a fresh
// database, an in-memory Redis and a graph that allows everything.
func wiredModules(t *testing.T) wired {
	t.Helper()
	d := pulseDB(t)
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	f, err := secrets.NewFactory(ksecrets.Config{Backend: ksecrets.BackendDatabase, EncryptionKey: "48pCGWLB98XVpxnYbIedmj9j43n2SXLAu8oCQePXx1g="}, http.DefaultClient)
	if err != nil {
		t.Fatal(err)
	}
	m := buildModules(newEdge(nil, authz.Admins{}), coreDeps{DB: d, Graph: &wiringGraph{objects: map[string]bool{}}, Redis: rdb, Secrets: f, Outbound: testOutbound(t),
		APIURL: "https://api.test", Lookup: mapLookup(nil), Connections: connections.LoadConfig(config.New(mapLookup(nil)))})
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	if err := d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'Acme', 'u1', 'acme')`, ws.ID())
		return err
	}); err != nil {
		t.Fatal(err)
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "u1", AdminWorkspaces: []string{ws.ID()}, AccessibleWorkspaces: []string{ws.ID()}}, Workspace: ws}
	return wired{m: m, d: d, redis: mr, secrets: f, c: c}
}

func (w wired) exec(t *testing.T, sql string, args ...any) {
	t.Helper()
	if err := w.d.Write(context.Background(), w.c.Workspace, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, sql, args...)
		return err
	}); err != nil {
		t.Fatal(err)
	}
}

func TestTheWiredWorkspaceConfigToolsetExports(t *testing.T) {
	w := wiredModules(t)
	out, err := w.m.toolsets.WorkspaceConfig.Export(context.Background(), w.c)
	var unwired *agentsservice.UnwiredError
	if errors.As(err, &unwired) {
		t.Fatalf("workspace_config_export is unwired: %v", err)
	}
	if err != nil || !strings.Contains(out, "Acme") {
		t.Fatalf("export %q %v", out, err)
	}
}

func TestTheWiredClientsToolsetAttachesConnectionsAndShowsPresence(t *testing.T) {
	w := wiredModules(t)
	ctx := context.Background()
	clients := w.m.toolsets.Clients
	created, err := clients.Create(ctx, w.c, json.RawMessage(`{"name": "Codex", "kind": "codex"}`))
	if err != nil {
		t.Fatal(err)
	}
	instance, conn := uuid.NewString(), uuid.NewString()
	w.exec(t, `INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id, created_by, transport) VALUES ($1, 's', 'github', $2, 'u1', 'url')`, instance, w.c.Workspace.ID())
	w.exec(t, `INSERT INTO openapi_connections (id, workspace_id, created_by, name, base_url) VALUES ($1, $2, 'u1', 'Petstore', 'https://pets.test')`, conn, w.c.Workspace.ID())
	if err := clients.AddMCPInstance(ctx, w.c, created.ID, instance, nil, nil); err != nil {
		t.Fatalf("attach MCP instance: %v", err)
	}
	if err := clients.AddOpenAPIConnection(ctx, w.c, created.ID, conn, nil, []string{"listPets"}); err != nil {
		t.Fatalf("attach OpenAPI connection: %v", err)
	}
	if list, err := clients.List(ctx, w.c, 100, 0); err != nil || len(list) != 1 {
		t.Fatalf("list with an OpenAPI link %+v %v", list, err)
	}
	read := func() map[string]any {
		t.Helper()
		raw, err := clients.Get(ctx, w.c, created.ID)
		if err != nil {
			t.Fatal(err)
		}
		var body map[string]any
		if err := json.Unmarshal(raw, &body); err != nil {
			t.Fatal(err)
		}
		return body
	}
	body := read()
	links, _ := body["openapi_connections"].([]any)
	if len(links) != 1 || links[0].(map[string]any)["name"] != "Petstore" || body["online"] != false {
		t.Fatalf("client %v", body)
	}
	if mcps, _ := body["mcp_instances"].([]any); len(mcps) != 1 || mcps[0].(map[string]any)["name"] != "github" {
		t.Fatalf("mcp instances %v", body["mcp_instances"])
	}
	if err := w.redis.Set("runners:online:"+created.ID, "1"); err != nil {
		t.Fatal(err)
	}
	if body := read(); body["online"] != true {
		t.Fatalf("runner connected but %v", body["online"])
	}
}

func TestDeletingAnAgentDeletesItsWalletCredentials(t *testing.T) {
	w := wiredModules(t)
	ctx := context.Background()
	agent, kept := uuid.New(), uuid.New()
	for _, id := range []uuid.UUID{agent, kept} {
		w.exec(t, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', 'active', $2, 'u1', $3)`, id, w.c.Workspace.ID(), id.String())
		w.exec(t, `INSERT INTO agent_wallets (id, workspace_id, created_by, agent_id, wallet_type, credentials_secret_id) VALUES ($1, $2, 'u1', $3, 'x402', $4)`,
			uuid.New(), w.c.Workspace.ID(), id, "wallet_creds_"+id.String())
	}
	if err := w.d.Write(ctx, w.c.Workspace, func(ctx context.Context, s db.Session) error {
		for _, id := range []uuid.UUID{agent, kept} {
			if err := w.secrets.Manager(s, "u1").Set(ctx, "wallet_creds_"+id.String(), `{"x402_private_key": "0xabc"}`); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := w.m.agents.Bundles().DeleteAgent(ctx, w.c, agent.String()); err != nil {
		t.Fatal(err)
	}
	has := func(id uuid.UUID) bool {
		t.Helper()
		var ok bool
		if err := w.d.Write(ctx, w.c.Workspace, func(ctx context.Context, s db.Session) (err error) {
			ok, err = w.secrets.Manager(s, "u1").Has(ctx, "wallet_creds_"+id.String())
			return err
		}); err != nil {
			t.Fatal(err)
		}
		return ok
	}
	if has(agent) {
		t.Error("the deleted agent's wallet credentials are left behind")
	}
	if !has(kept) {
		t.Error("another agent's wallet credentials went too")
	}
}
