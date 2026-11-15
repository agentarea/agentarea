package authz

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	kauthz "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
)

// testdata/python_wire.json is what the Python graph code sent for each
// scenario (testdata/python_wire.py). The OpenFGA store keeps the tuples it
// wrote, so the Go adapter must send the same requests and reach the same
// result.

type answer struct {
	Status int             `json:"status"`
	JSON   json.RawMessage `json:"json"`
}

type recorded struct {
	Method        string            `json:"method"`
	Path          string            `json:"path"`
	Query         map[string]string `json:"query"`
	Authorization string            `json:"authorization"`
	Body          any               `json:"body"`
}

type scenario struct {
	Name      string              `json:"name"`
	Responses map[string][]answer `json:"responses"`
	Token     string              `json:"token"`
	ModelID   string              `json:"model_id"`
	Requests  []recorded          `json:"requests"`
	Result    any                 `json:"result"`
	Error     string              `json:"error"`
}

const pyStore = "01JSTORE0000000000000000AA"

type fakeServer struct {
	mu        sync.Mutex
	responses map[string][]answer
	requests  []recorded
}

func (f *fakeServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	raw, _ := io.ReadAll(r.Body)
	var body any
	if len(raw) > 0 {
		_ = json.Unmarshal(raw, &body)
	}
	q := map[string]string{}
	for k, v := range r.URL.Query() {
		q[k] = v[0]
	}
	f.requests = append(f.requests, recorded{Method: r.Method, Path: r.URL.Path, Query: q, Authorization: r.Header.Get("Authorization"), Body: body})
	key := r.Method + " " + r.URL.Path[strings.LastIndex(r.URL.Path, "/")+1:]
	answers := f.responses[key]
	a := answer{JSON: json.RawMessage(`{}`)}
	switch {
	case len(answers) > 1:
		a, f.responses[key] = answers[0], answers[1:]
	case len(answers) == 1:
		a = answers[0]
	}
	if a.Status == 0 {
		a.Status = http.StatusOK
	}
	if len(a.JSON) == 0 {
		a.JSON = json.RawMessage(`{}`)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(a.Status)
	_, _ = w.Write(a.JSON)
}

func sortedKeys(m map[string]struct{}) []string { return slices.Sorted(maps.Keys(m)) }

// goScenarios is each Python scenario done the Go way.
func goScenarios(c *Client, base string) map[string]func(ctx context.Context) (any, error) {
	none := func(err error) (any, error) { return nil, err }
	perm := kauthz.NewPermissions(c, nil)
	out := map[string]func(ctx context.Context) (any, error){
		"grant_resource_owner": func(ctx context.Context) (any, error) {
			return none(kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:u1", kauthz.OwnerRelations()))
		},
		"grant_agent_owner": func(ctx context.Context) (any, error) {
			return none(kauthz.GrantResourceOwner(ctx, c, "a1", "w1", "User:u1", kauthz.AgentOwnerRelations()))
		},
		"grant_resource_owner_existing": func(ctx context.Context) (any, error) {
			return none(kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:u1", kauthz.OwnerRelations()))
		},
		"grant_resource_owner_refused": func(ctx context.Context) (any, error) {
			return none(kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:u1", kauthz.OwnerRelations()))
		},
		"write_idempotent_existing": func(ctx context.Context) (any, error) {
			return kauthz.WriteIdempotent(ctx, c, kauthz.Tuple{User: "User:u1", Relation: "reader", Object: "resource:r1"})
		},
		"delete_idempotent_missing": func(ctx context.Context) (any, error) {
			return kauthz.DeleteIdempotent(ctx, c, kauthz.Tuple{User: "User:u1", Relation: "members", Object: "Workspace:w1"})
		},
		"enroll_agent":   func(ctx context.Context) (any, error) { return none(kauthz.EnrollAgent(ctx, c, "a1", "w1")) },
		"withdraw_agent": func(ctx context.Context) (any, error) { return none(kauthz.WithdrawAgent(ctx, c, "a1", "w1")) },
		"revoke_resource": func(ctx context.Context) (any, error) {
			return none(kauthz.RevokeResource(ctx, c, "r1"))
		},
		"seed_workspace": func(ctx context.Context) (any, error) { return none(kauthz.SeedWorkspace(ctx, c, "w1", "u1")) },
		"grant_workspace_membership": func(ctx context.Context) (any, error) {
			return none(kauthz.GrantWorkspaceMembership(ctx, c, "w1", "u2"))
		},
		"revoke_workspace_membership": func(ctx context.Context) (any, error) {
			return none(kauthz.RevokeWorkspaceMembership(ctx, c, "w1", "u2"))
		},
		"revoke_workspace_membership_missing": func(ctx context.Context) (any, error) {
			return none(kauthz.RevokeWorkspaceMembership(ctx, c, "w1", "u2"))
		},
		"check_workspace_membership": func(ctx context.Context) (any, error) {
			return kauthz.IsWorkspaceMember(ctx, c, "w1", "u2")
		},
		"list_workspace_member_ids": func(ctx context.Context) (any, error) { return kauthz.WorkspaceMemberIDs(ctx, c, "w1") },
		"list_workspace_ids_for_member": func(ctx context.Context) (any, error) {
			return kauthz.MemberWorkspaceIDs(ctx, c, "u1")
		},
		"readable_resource_ids": func(ctx context.Context) (any, error) {
			ids, err := kauthz.ReadableResourceIDs(ctx, c, "User:u1")
			return sortedKeys(ids), err
		},
		"make_personal":        func(ctx context.Context) (any, error) { return none(kauthz.MakePersonal(ctx, c, "c1")) },
		"share_with_workspace": func(ctx context.Context) (any, error) { return none(kauthz.ShareWithWorkspace(ctx, c, "c1")) },
		"lend_connection":      func(ctx context.Context) (any, error) { return none(kauthz.LendConnection(ctx, c, "c1", "a1")) },
		"withdraw_connection": func(ctx context.Context) (any, error) {
			return none(kauthz.WithdrawConnection(ctx, c, "c1", "a1"))
		},
		"is_connection_owner": func(ctx context.Context) (any, error) {
			return kauthz.IsConnectionOwner(ctx, c, "User:u1", "c1")
		},
		"personal_connection_ids": func(ctx context.Context) (any, error) {
			ids, err := kauthz.PersonalConnectionIDs(ctx, c, []string{"c1"})
			return sortedKeys(ids), err
		},
		"permission_ungoverned": func(ctx context.Context) (any, error) {
			return perm.Check(ctx, "User:u1", "delete", "model", "m1")
		},
		"permission_check_error": func(ctx context.Context) (any, error) {
			return perm.Check(ctx, "User:u1", "view", "agent", "r1")
		},
		"bootstrap": func(ctx context.Context) (any, error) {
			cfg, err := Bootstrap(ctx, kauthz.Config{URL: base, StoreName: "agentarea", Timeout: 10 * time.Second, Bootstrap: true, ApplyModel: true, APIToken: "tok"}, nil)
			return map[string]string{"store_id": cfg.StoreID, "model_id": cfg.ModelID}, err
		},
	}
	for _, verb := range []string{"view", "execute", "use_secret", "use_connection", "configure", "delete", "bogus"} {
		out["permission_"+verb] = func(ctx context.Context) (any, error) { return perm.Check(ctx, "Agent:a1", verb, "agent", "r1") }
	}
	return out
}

func pythonErrorName(err error) string {
	var oe *kauthz.OwnershipError
	var re *kauthz.ResponseError
	var ue *kauthz.UnavailableError
	switch {
	case err == nil:
		return ""
	case errors.As(err, &oe):
		return "ResourceOwnershipError"
	case errors.As(err, &ue):
		return "OpenFGAUnavailableError"
	case errors.As(err, &re):
		return "OpenFGAError"
	}
	return err.Error()
}

func jsonValue(t *testing.T, v any) any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestWireMatchesCapture(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("testdata", "python_wire.json"))
	if err != nil {
		t.Fatal(err)
	}
	var scenarios []scenario
	if err := json.Unmarshal(raw, &scenarios); err != nil {
		t.Fatal(err)
	}
	if len(scenarios) < 30 {
		t.Fatalf("only %d scenarios", len(scenarios))
	}
	for _, sc := range scenarios {
		t.Run(sc.Name, func(t *testing.T) {
			fake := &fakeServer{responses: sc.Responses, requests: []recorded{}}
			srv := httptest.NewServer(fake)
			defer srv.Close()
			c, err := NewClient(srv.URL+"/", pyStore, sc.ModelID, sc.Token, 5*time.Second, nil)
			if err != nil {
				t.Fatal(err)
			}
			run, ok := goScenarios(c, srv.URL)[sc.Name]
			if !ok {
				t.Fatalf("no Go scenario %q", sc.Name)
			}
			result, err := run(context.Background())
			if got := pythonErrorName(err); got != sc.Error {
				t.Fatalf("error = %q (%v), Python raised %q", got, err, sc.Error)
			}
			if err == nil && !reflect.DeepEqual(jsonValue(t, result), sc.Result) {
				t.Errorf("result = %v, Python returned %v", jsonValue(t, result), sc.Result)
			}
			got := jsonValue(t, fake.requests)
			want := jsonValue(t, sc.Requests)
			if !reflect.DeepEqual(got, want) {
				g, _ := json.MarshalIndent(got, "", " ")
				w, _ := json.MarshalIndent(want, "", " ")
				t.Errorf("requests differ\nGo:\n%s\nPython:\n%s", g, w)
			}
		})
	}
}

func TestRequireExtends(t *testing.T) {
	base, err := PackagedModel()
	if err != nil {
		t.Fatal(err)
	}
	if err := RequireExtends(base, base); err != nil {
		t.Fatalf("model does not extend itself: %v", err)
	}
	custom := jsonValue(t, base).(map[string]any)
	defs := custom["type_definitions"].([]any)
	for i, d := range defs {
		td := d.(map[string]any)
		switch td["type"] {
		case "resource":
			rel := td["relations"].(map[string]any)
			delete(rel, "invoker")
			rel["can_invoke"] = map[string]any{"this": map[string]any{}}
			md := td["metadata"].(map[string]any)
			md["module"] = "custom"
		case "role":
			defs = append(defs[:i], defs[i+1:]...)
		}
	}
	custom["type_definitions"] = append(defs, map[string]any{"type": "team"})
	err = RequireExtends(custom, base)
	if err == nil {
		t.Fatal("a model dropping relations was accepted")
	}
	for _, want := range []string{"type role is missing", "resource#invoker is missing", "resource#can_invoke is redefined"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("%q not in %v", want, err)
		}
	}
	if strings.Contains(err.Error(), "can_read") {
		t.Errorf("provenance counted as a change: %v", err)
	}
}

func TestLoadModelReadsYAML(t *testing.T) {
	path := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(path, []byte("schema_version: '1.2'\ntype_definitions:\n  - type: User\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := LoadModel(path)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(m, map[string]any{"schema_version": "1.2", "type_definitions": []any{map[string]any{"type": "User"}}}) {
		t.Fatalf("%v", m)
	}
}
