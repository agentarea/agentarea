package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

type streamTasks struct {
	events []domain.A2AJSON
	err    error
}

func (s streamTasks) Handle(context.Context, service.A2ACall) (domain.A2AJSON, error) { return nil, nil }

func (s streamTasks) Stream(_ context.Context, _ service.A2ACall, emit func(domain.A2AJSON) error) error {
	for _, e := range s.events {
		if err := emit(e); err != nil {
			return err
		}
	}
	return s.err
}

func streamServe(t *testing.T, tasks streamTasks) *httptest.ResponseRecorder {
	t.Helper()
	agent := uuid.NewString()
	a := service.NewA2A(&service.Service{}, service.A2APorts{Tasks: tasks})
	h := a2aHandlers{a: a, errs: httpx.NewErrors("http://api.test", slog.New(slog.DiscardHandler), MapError)}
	adm := service.A2AAdmission{
		Agent: domain.Agent{ID: agent, WorkspaceID: "w1"}, Principal: &authn.Principal{UserID: "u", AccessibleWorkspaces: []string{"w1"}},
		Auth: domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1"},
	}
	req := domain.A2ARPCRequest{ID: "7", Method: "SendStreamingMessage"}
	rec := httptest.NewRecorder()
	h.stream(rec, httptest.NewRequest(http.MethodPost, "/", nil), adm, "rpc", req, "1.0")
	return rec
}

func TestA2AStreamWritesEventFrames(t *testing.T) {
	rec := streamServe(t, streamTasks{events: []domain.A2AJSON{
		{{Key: "task", Value: domain.A2AJSON{{Key: "id", Value: "t1"}}}},
		{{Key: "statusUpdate", Value: domain.A2AJSON{{Key: "taskId", Value: "t1"}}}},
	}})
	if rec.Code != http.StatusOK || !strings.HasPrefix(rec.Header().Get("Content-Type"), "text/event-stream") {
		t.Fatalf("%d %v", rec.Code, rec.Header())
	}
	want := `data: {"result": {"task": {"id": "t1"}}, "id": "7", "jsonrpc": "2.0"}` + "\r\n\r\n" +
		`data: {"result": {"statusUpdate": {"taskId": "t1"}}, "id": "7", "jsonrpc": "2.0"}` + "\r\n\r\n"
	if rec.Body.String() != want {
		t.Errorf("%q", rec.Body.String())
	}
}

func TestA2AStreamErrorAfterAnEventIsAnErrorFrame(t *testing.T) {
	rec := streamServe(t, streamTasks{
		events: []domain.A2AJSON{{{Key: "task", Value: domain.A2AJSON{{Key: "id", Value: "t1"}}}}},
		err:    domain.A2ATaskNotFound("gone"),
	})
	body := rec.Body.String()
	if rec.Code != http.StatusOK || !strings.Contains(body, "event: error\r\ndata: {\"error\"") || !strings.Contains(body, `"code": -32001`) {
		t.Errorf("%d %q", rec.Code, body)
	}
}

func TestA2AStreamErrorBeforeTheFirstEventIsJSON(t *testing.T) {
	rec := streamServe(t, streamTasks{err: domain.A2ATaskNotFound("gone")})
	if rec.Code != http.StatusOK || !strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") || !strings.Contains(rec.Body.String(), `"code":-32001`) {
		t.Errorf("%d %v %s", rec.Code, rec.Header(), rec.Body)
	}
}

func TestA2AStreamPermissionRefusedBeforeTheFirstEventIs403(t *testing.T) {
	rec := streamServe(t, streamTasks{err: httpx.HTTPError(http.StatusForbidden, "Permission denied")})
	if rec.Code != http.StatusForbidden || !strings.Contains(rec.Body.String(), "Permission denied") {
		t.Errorf("%d %s", rec.Code, rec.Body)
	}
}
