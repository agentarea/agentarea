package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func a2aOpenDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

// a2aLimiter refuses the identities in deny.
type a2aLimiter struct{ deny map[string]bool }

func (l a2aLimiter) Take(_ context.Context, scope, identity string, limit int) (bool, int, error) {
	if scope != httpx.A2ARPCScope || limit != httpx.A2ARPCLimit {
		return false, 0, nil
	}
	return !l.deny[identity], 7, nil
}

type a2aFixture struct {
	h        http.Handler
	agent    string
	archived string
	ws       string
}

func a2aSetup(t *testing.T, out http.RoundTripper) a2aFixture {
	t.Helper()
	d := a2aOpenDB(t)
	f := a2aFixture{agent: uuid.NewString(), archived: uuid.NewString(), ws: uuid.NewString()}
	ws, _ := scope.NewWorkspace(f.ws, "")
	if err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, `INSERT INTO agents (id, name, description, status, workspace_id, created_by, slug, tools, planning, a2ui_enabled) VALUES
			($1, 'Helper', NULL, 'active', $3, 'u', $4, '[{"tool_type":"mcp"}]', true, false),
			($2, 'Old', 'Retired', 'archived', $3, 'u', $5, NULL, NULL, NULL)`,
			f.agent, f.archived, f.ws, "h-"+f.agent[:8], "o-"+f.agent[:8])
		return err
	}); err != nil {
		t.Fatal(err)
	}
	principals := map[string]*authn.Principal{
		"member":   {UserID: "u1", AccessibleWorkspaces: []string{f.ws}, Credential: &authn.Credential{Kind: authn.KindSession}},
		"stranger": {UserID: "u2", AccessibleWorkspaces: []string{uuid.NewString()}},
		"agentkey": {UserID: "u3", BoundAgentID: f.agent, BoundWorkspaceID: f.ws, Credential: &authn.Credential{Kind: authn.KindAPIKey, KeyID: "k1"}},
		"otherkey": {UserID: "u3", BoundAgentID: uuid.NewString(), BoundWorkspaceID: f.ws, Credential: &authn.Credential{Kind: authn.KindAPIKey, KeyID: "k2"}},
		"limited":  {UserID: "slow", AccessibleWorkspaces: []string{f.ws}},
	}
	svc := service.New(service.Deps{DB: d})
	a2a := service.NewA2A(svc, service.A2APorts{
		APIURL: "http://api.test/", AgentURL: "https://{agent_id}.a2a.example.com",
		Principal: func(_ context.Context, token string) (*authn.Principal, error) {
			if p, ok := principals[token]; ok {
				cp := *p
				return &cp, nil
			}
			return nil, nil
		},
		RateLimiter: a2aLimiter{deny: map[string]bool{"user:slow": true}},
		Outbound:    out,
	})
	errs := httpx.NewErrors("http://api.test", slog.New(slog.DiscardHandler), MapError)
	cws, _ := scope.NewWorkspace(f.ws, "acme")
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: cws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}
	r := chi.NewRouter()
	Mount(r, errs, Edge{Workspace: admit}, New(svc, Extras{A2A: a2a, MaxBody: 4 << 10}))
	f.h = r
	return f
}

type a2aReq struct {
	method, path, body, token, host, version string
}

func a2aDo(t *testing.T, h http.Handler, q a2aReq) *httptest.ResponseRecorder {
	t.Helper()
	var req *http.Request
	if q.body != "" {
		req = httptest.NewRequest(q.method, q.path, strings.NewReader(q.body))
		req.Header.Set("Content-Type", "application/json")
	} else {
		req = httptest.NewRequest(q.method, q.path, nil)
	}
	if q.token != "" {
		req.Header.Set("Authorization", "Bearer "+q.token)
	}
	if q.host != "" {
		req.Host = q.host
	}
	if q.version != "" {
		req.Header.Set("A2A-Version", q.version)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func a2aExpect(t *testing.T, rec *httptest.ResponseRecorder, status int, contains ...string) {
	t.Helper()
	if rec.Code != status {
		t.Errorf("status %d, want %d: %s", rec.Code, status, rec.Body)
	}
	for _, c := range contains {
		if !strings.Contains(rec.Body.String(), c) {
			t.Errorf("body %s\nmissing %s", rec.Body, c)
		}
	}
}

func TestA2ADiscoveryIsPublicAcrossWorkspaces(t *testing.T) {
	f := a2aSetup(t, nil)
	base := "/v1/agents/" + f.agent
	rpc := "http://api.test/v1/agents/" + f.agent + "/a2a/rpc"
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: base + "/.well-known/agent-card.json"}), 200,
		`{"name":"Helper","description":"AI agent Helper","supportedInterfaces":[{"url":"`+rpc+`","protocolBinding":"JSONRPC","protocolVersion":"1.0"}],"provider":{"url":"http://api.test","organization":"AgentArea"}`)
	card := a2aDo(t, f.h, a2aReq{method: "GET", path: base + "/.well-known/agent-card.json"}).Body.String()
	if strings.Contains(card, "tool-execution") {
		t.Errorf("public card has extended skills: %s", card)
	}
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/v1/agents/" + f.archived + "/.well-known/a2a-info.json"}), 200,
		`{"protocol":"A2A","version":"1.0.0","server":"AgentArea","agent":{"id":"`+f.archived+`","name":"Old","description":"Retired","status":"archived"}`,
		`"a2a_url":"https://`+f.archived+`.a2a.example.com"`)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: base + "/.well-known/"}), 200,
		`"agent":{"id":"`+f.agent+`","name":"Helper","description":null}`, `"a2a-info.json":"http://api.test/v1/agents/`+f.agent+`/.well-known/a2a-info.json"`)
	missing := uuid.NewString()
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/v1/agents/" + missing + "/.well-known/agent-card.json"}), 404, "Agent "+missing+" not found")
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/v1/agents/nope/.well-known/a2a-info.json"}), 422, "uuid_parsing")
}

func TestA2AAuthorizationAtTheEdge(t *testing.T) {
	f := a2aSetup(t, nil)
	rpc := "/v1/agents/" + f.agent + "/a2a/rpc"
	body := `{"jsonrpc":"2.0","id":1,"method":"GetExtendedAgentCard"}`
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/agents/nope/a2a/rpc", body: body}), 404, "Agent not found")
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/agents/" + uuid.NewString() + "/a2a/rpc", body: body, token: "member"}), 404, "Agent not found")
	anon := a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body})
	a2aExpect(t, anon, 401, "Authentication required")
	if anon.Header().Get("WWW-Authenticate") != "Bearer" {
		t.Errorf("challenge %q", anon.Header().Get("WWW-Authenticate"))
	}
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body, token: "unknown"}), 401, "Authentication required")
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body, token: "stranger"}), 403, "Insufficient permissions. Required: agent:read")
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body, token: "otherkey"}), 403, "Insufficient permissions. Required: agent:read")
	limited := a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body, token: "limited"})
	a2aExpect(t, limited, 429, "Rate limit exceeded")
	if limited.Header().Get("Retry-After") != "7" {
		t.Errorf("Retry-After %q", limited.Header().Get("Retry-After"))
	}
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/v1/agents/" + f.agent + "/a2a/well-known"}), 401)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/v1/agents/" + f.agent + "/a2a/well-known", token: "agentkey"}), 200,
		`"url":"http://api.test/v1/agents/`+f.agent+`/a2a/rpc"`)
}

func TestA2AJSONRPC(t *testing.T) {
	f := a2aSetup(t, nil)
	rpc := "/v1/agents/" + f.agent + "/a2a/rpc"
	call := func(token, version, body string) *httptest.ResponseRecorder {
		return a2aDo(t, f.h, a2aReq{method: "POST", path: rpc, body: body, token: token, version: version})
	}
	ext := call("agentkey", "1.0", `{"jsonrpc":"2.0","id":"r1","method":"GetExtendedAgentCard","params":{}}`)
	a2aExpect(t, ext, 200, `{"result":{"name":"Helper"`, `{"id":"tool-execution"`, `{"id":"task-planning"`, `}]},"id":"r1","jsonrpc":"2.0"}`)
	a2aExpect(t, call("member", "", `{"jsonrpc":"2.0","id":2,"method":"GetExtendedAgentCard"}`), 200,
		`{"error":{"code":-32009,"message":"A2A version '0.3' is not supported by this handler. Expected version '1.0'.","data":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"VERSION_NOT_SUPPORTED","domain":"a2a-protocol.org","metadata":{}}]},"id":2,"jsonrpc":"2.0"}`)
	a2aExpect(t, call("member", "1.0", `{"jsonrpc":"2.0","id":3,"method":"Nope"}`), 200,
		`{"error":{"code":-32601,"message":"Method not found"},"id":3,"jsonrpc":"2.0"}`)
	a2aExpect(t, call("member", "1.0", `{"jsonrpc":"2.0","id":4,"method":"SendMessage","params":{"message":{}}}`), 200,
		`{"error":{"code":-32004,"message":"SendMessage is not available yet","data":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"UNSUPPORTED_OPERATION"`)
	a2aExpect(t, call("member", "1.0", `{"jsonrpc":"2.0","id":5,"method":"GetTask","params":{"bogus":1}}`), 200,
		`{"error":{"code":-32602,"message":"Invalid params","data":"Message type \"lf.a2a.v1.GetTaskRequest\" has no field named \"bogus\"`)
	a2aExpect(t, call("member", "1.0", `{"jsonrpc":"2.0",`), 200,
		`{"error":{"code":-32700,"message":"Expecting property name enclosed in double quotes: line 1 column 18 (char 17)"},"id":null,"jsonrpc":"2.0"}`)
	a2aExpect(t, call("member", "1.0", "\xff"), 200, `{"error":{"code":-32700,"message":"The request body is not UTF-8"},"id":null,"jsonrpc":"2.0"}`)
	a2aExpect(t, call("member", "1.0", `[{"jsonrpc":"2.0","method":"GetTask"}]`), 200, `"message":"Batch requests are not supported"`)
}

func TestA2AExtendedCardRefusesAnUnavailableAgent(t *testing.T) {
	f := a2aSetup(t, nil)
	rec := a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/agents/" + f.archived + "/a2a/rpc", token: "member", version: "1.0",
		body: `{"jsonrpc":"2.0","id":1,"method":"GetExtendedAgentCard"}`})
	a2aExpect(t, rec, 200, `{"error":{"code":-32602,"message":"Agent Old (ID: `+f.archived+`) is not available (status: archived)","data":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"INVALID_PARAMS"`)
}

func TestA2AAgentHost(t *testing.T) {
	f := a2aSetup(t, nil)
	host := f.agent + ".a2a.example.com"
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/.well-known/agent-card.json", host: host}), 200,
		`"supportedInterfaces":[{"url":"https://`+host+`/","protocolBinding":"JSONRPC"`, `"provider":{"url":"https://`+host+`"`)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/", host: host + ":443", token: "member", version: "1.0",
		body: `{"jsonrpc":"2.0","id":1,"method":"GetExtendedAgentCard"}`}), 200, `"url":"https://`+host+`/"`)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/", host: host, body: `{}`}), 401)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/.well-known/agent-card.json", host: "api.test"}), 404)
	off := a2aDo(t, f.h, a2aReq{method: "POST", path: "/", host: "api.test", body: `{}`})
	a2aExpect(t, off, 405)
	if off.Header().Get("Allow") != "GET" {
		t.Errorf("Allow %q", off.Header().Get("Allow"))
	}
	unknown := uuid.NewString()
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "GET", path: "/.well-known/agent-card.json", host: unknown + ".a2a.example.com"}), 404, "Agent "+unknown+" not found")
}

func TestA2AReadAgentCard(t *testing.T) {
	peer := http.NewServeMux()
	peer.HandleFunc("GET /good/.well-known/agent-card.json", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"name":"Peer","description":"Helps","skills":[{"id":"s","name":"Search","description":"Finds"}],"url":"x","capabilities":{}}`))
	})
	peer.HandleFunc("GET /list/.well-known/agent-card.json", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte(`[1]`)) })
	peer.HandleFunc("GET /bad/.well-known/agent-card.json", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte(`{"name":`)) })
	peer.HandleFunc("GET /typed/.well-known/agent-card.json", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte(`{"name":5}`)) })
	srv := httptest.NewServer(peer)
	t.Cleanup(srv.Close)
	f := a2aSetup(t, http.DefaultTransport)
	read := func(body string) *httptest.ResponseRecorder {
		return a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/workspaces/acme/a2a/agent-cards", body: body})
	}
	a2aExpect(t, read(`{"url":" `+srv.URL+`/good/.well-known/agent-card.json "}`), 200,
		`{"address":"`+srv.URL+`/good","name":"Peer","description":"Helps","skills":[{"name":"Search","description":"Finds"}]}`)
	a2aExpect(t, read(`{"url":"`+srv.URL+`/missing"}`), 400,
		"No agent card at "+srv.URL+"/missing: Failed to fetch agent card from "+srv.URL+"/missing/.well-known/agent-card.json (HTTP 404): Client error '404 Not Found' for url")
	a2aExpect(t, read(`{"url":"`+srv.URL+`/bad"}`), 400, "Failed to parse JSON for agent card from "+srv.URL+"/bad/.well-known/agent-card.json: Expecting value: line 1 column 9 (char 8)")
	a2aExpect(t, read(`{"url":"`+srv.URL+`/list"}`), 400, "the card is not a JSON object")
	a2aExpect(t, read(`{"url":"`+srv.URL+`/typed"}`), 400, "Failed to validate agent card structure", "Failed to parse name field: expected string or bytes-like object, got 'int'.")
	a2aExpect(t, read(`{"url":"http://127.0.0.1:1"}`), 400, "Network communication error fetching agent card from http://127.0.0.1:1/.well-known/agent-card.json")
	a2aExpect(t, read(`{}`), 422, `"loc":["body","url"]`)
	a2aExpect(t, read(`{"url":1}`), 422, "string_type")
}

func TestA2AReadAgentCardUnwired(t *testing.T) {
	f := a2aSetup(t, nil)
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/workspaces/acme/a2a/agent-cards", body: `{"url":"http://peer"}`}), 501, "Reading an agent card is not available yet")
}

func TestA2ARPCBodyIsBoundedByTheEdgeLimit(t *testing.T) {
	f := a2aSetup(t, nil)
	body := `{"jsonrpc":"2.0","id":1,"method":"GetExtendedAgentCard","params":{"pad":"` + strings.Repeat("x", 8<<10) + `"}}`
	a2aExpect(t, a2aDo(t, f.h, a2aReq{method: "POST", path: "/v1/agents/" + f.agent + "/a2a/rpc", body: body, token: "member", version: "1.0"}),
		http.StatusRequestEntityTooLarge, "Request body too large")
}
