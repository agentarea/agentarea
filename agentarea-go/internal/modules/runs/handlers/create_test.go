package handlers

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

type nopPolicies struct{ governanceapi.RunPolicies }

type nopLauncher struct{}

func (nopLauncher) Launch(context.Context, string, store.StoredTask) (service.Launched, error) {
	return service.Launched{}, nil
}

func createRouter(t *testing.T, execute error) http.Handler {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	workspace := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "user-1"}, Workspace: ws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}
	s := service.NewSurface(service.SurfaceDeps{DB: fakeDB{}, Log: quiet(), Policies: nopPolicies{}, Launcher: nopLauncher{},
		Permissions: func(context.Context, authn.Caller, string, string, string) error { return execute }})
	r := chi.NewRouter()
	srv := New(s, nil)
	srv.authority = func(context.Context, string) error { return nil }
	Mount(r, httpx.NewErrors("http://api", quiet(), MapError, edgeAdmin), workspace, srv)
	return r
}

func TestCreateBodyRefusesTriggerParametersAtTheField(t *testing.T) {
	h := createRouter(t, nil)
	path := "/v1/workspaces/acme/agents/" + uuid.NewString() + "/tasks/sync"
	code, body := call(t, h, "POST", path, `{"description":"x","parameters":{"session":{},"trigger_event":1},"webhook":{"url":"https://x","extra":1}}`)
	if code != http.StatusUnprocessableEntity ||
		!strings.Contains(body, `"loc":["body","parameters"]`) ||
		!strings.Contains(body, "session, trigger_event is set by the trigger") ||
		!strings.Contains(body, `"loc":["body","webhook","extra"]`) {
		t.Fatalf("%d %s", code, body)
	}
}

func TestScheduleNeedsAnOffsetAndTheFuture(t *testing.T) {
	h := createRouter(t, nil)
	path := "/v1/workspaces/acme/agents/" + uuid.NewString() + "/tasks/schedule"
	code, body := call(t, h, "POST", path, `{"description":"x","scheduled_at":"2030-01-01T10:00:00"}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, "scheduled_at must include a UTC offset") {
		t.Fatalf("%d %s", code, body)
	}
	code, body = call(t, h, "POST", path, `{"description":"x","scheduled_at":"2001-01-01T10:00:00Z"}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, "scheduled_at must be in the future") {
		t.Fatalf("%d %s", code, body)
	}
}

func TestExecuteIsCheckedBeforeTheBody(t *testing.T) {
	h := createRouter(t, authz.ErrDenied)
	path := "/v1/workspaces/acme/agents/" + uuid.NewString() + "/tasks/sync"
	if code, body := call(t, h, "POST", path, `[]`); code != http.StatusForbidden {
		t.Fatalf("%d %s", code, body)
	}
}

func TestContinueBoundsEachGrant(t *testing.T) {
	h := createRouter(t, nil)
	path := "/v1/workspaces/acme/tasks/" + uuid.NewString() + "/continue"
	code, body := call(t, h, "POST", path, `{"additional_iterations":1001,"additional_budget_usd":0,"other":1}`)
	if code != http.StatusUnprocessableEntity ||
		!strings.Contains(body, `"loc":["body","additional_iterations"]`) ||
		!strings.Contains(body, `"loc":["body","additional_budget_usd"]`) ||
		!strings.Contains(body, `"loc":["body","other"]`) {
		t.Fatalf("%d %s", code, body)
	}
}
