package app

import (
	"context"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"sync/atomic"

	kdurable "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
)

// processHealth is health.py: a process that serves no traffic (worker,
// events) tells the orchestrator a working process from a dead one. /livez
// answers while the process answers; /readyz once every component started and
// each Temporal worker, if it runs any, polls its queue.
type processHealth struct {
	started atomic.Bool
	pollers map[string]kdurable.Worker
}

func (h *processHealth) readiness() (bool, string) {
	if !h.started.Load() {
		return false, "starting"
	}
	var idle []string
	for queue, w := range h.pollers {
		if !w.Polling() {
			idle = append(idle, queue)
		}
	}
	if len(idle) > 0 {
		slices.Sort(idle)
		return false, "not polling: " + strings.Join(idle, ", ")
	}
	return true, "ready"
}

func (h *processHealth) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /livez", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("alive")) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, _ *http.Request) {
		ready, reason := h.readiness()
		if !ready {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_, _ = w.Write([]byte(reason))
	})
	return mux
}

// listener serves the endpoints on addr; it must name every interface, the
// kubelet probes the pod IP, not loopback.
func (h *processHealth) listener(addr string, log *slog.Logger) lifecycle.Component {
	return newHTTPComponent("health", addr, h.handler(), log)
}

// ready is the group's last component: readiness waits for every start.
func (h *processHealth) ready() lifecycle.Component {
	return lifecycle.Func("ready",
		func(context.Context) error { h.started.Store(true); return nil },
		func(context.Context) error { h.started.Store(false); return nil })
}
