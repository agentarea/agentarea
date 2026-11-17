package app

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	kdurable "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
)

type pollingWorker struct {
	kdurable.Worker
	polling bool
}

func (w *pollingWorker) Polling() bool { return w.polling }

func probe(t *testing.T, h *processHealth, path string) (int, string) {
	t.Helper()
	rec := httptest.NewRecorder()
	h.handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec.Code, rec.Body.String()
}

func TestWorkerReadyOnlyOnceStartedAndPolling(t *testing.T) {
	agent, trigger := &pollingWorker{}, &pollingWorker{}
	h := &processHealth{pollers: map[string]kdurable.Worker{"agents": agent, "triggers": trigger}}
	if code, _ := probe(t, h, "/livez"); code != http.StatusOK {
		t.Fatalf("livez %d", code)
	}
	if code, body := probe(t, h, "/readyz"); code != http.StatusServiceUnavailable || body != "starting" {
		t.Fatalf("before start: %d %q", code, body)
	}
	if err := h.ready().Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	agent.polling = true
	if code, body := probe(t, h, "/readyz"); code != http.StatusServiceUnavailable || body != "not polling: triggers" {
		t.Fatalf("one idle: %d %q", code, body)
	}
	trigger.polling = true
	if code, body := probe(t, h, "/readyz"); code != http.StatusOK || body != "ready" {
		t.Fatalf("ready: %d %q", code, body)
	}
	if err := h.ready().Stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	if code, _ := probe(t, h, "/readyz"); code != http.StatusServiceUnavailable {
		t.Fatalf("after stop: %d", code)
	}
	if code, _ := probe(t, h, "/other"); code != http.StatusNotFound {
		t.Fatalf("unknown path: %d", code)
	}
}

func TestProcessWithoutTemporalWorkersReadyOnceStarted(t *testing.T) {
	h := &processHealth{}
	if code, body := probe(t, h, "/readyz"); code != http.StatusServiceUnavailable || body != "starting" {
		t.Fatalf("before start: %d %q", code, body)
	}
	if err := h.ready().Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if code, body := probe(t, h, "/readyz"); code != http.StatusOK || body != "ready" {
		t.Fatalf("started: %d %q", code, body)
	}
}
