package runs

import (
	"log/slog"
	"reflect"
	"strings"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/runner"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// RunnerDeps are what a harness client's runner routes need; app passes them in.
type RunnerDeps struct {
	DB      db.Database
	Gate    runner.Gate
	Clients agentsapi.RunnerClients
	Slugs   identityapi.WorkspaceSlugs
	Broker  events.Broker
	// Redis keeps the runners' presence.
	Redis redis.Cmdable
	// Files is the default bucket, where a runner's task files go.
	Files   blob.Store
	Workers runner.Workers
	// Tokens and Live are nil without AGENTAREA_MCP_GATEWAY_SECRET; the routes are then unmounted.
	Tokens authn.TurnTokens
	Live   authn.LiveTurns
	Log    *slog.Logger
}

// NewRunnerPresence is which clients' runners are connected, read from the keys their sockets keep in rdb.
func NewRunnerPresence(rdb redis.Cmdable) api.RunnerPresence { return runner.RedisPresence{RDB: rdb} }

// RunnerSurface is GET /v1/runner/whoami, PUT /v1/runner/tasks/{id}/files/*
// and the runner socket /v1/runner/connect.
type RunnerSurface struct{ d RunnerDeps }

// NewRunnerSurface constructs the runner routes.
func NewRunnerSurface(d RunnerDeps) *RunnerSurface { return &RunnerSurface{d: d} }

func absent(v any) bool {
	if v == nil {
		return true
	}
	rv := reflect.ValueOf(v)
	return rv.Kind() == reflect.Pointer && rv.IsNil()
}

// Missing names the ports the runner routes lack.
func (m *RunnerSurface) Missing() []string {
	d := m.d
	var out []string
	for _, p := range []struct {
		name string
		v    any
	}{
		{"database", d.DB}, {"gate", d.Gate}, {"runner clients (agents)", d.Clients}, {"workspace slugs (identity)", d.Slugs},
		{"broker", d.Broker}, {"redis", d.Redis}, {"harness files bucket", d.Files}, {"temporal workers", d.Workers},
		{"turn tokens (AGENTAREA_MCP_GATEWAY_SECRET)", d.Tokens}, {"live turns", d.Live},
	} {
		if absent(p.v) {
			out = append(out, p.name)
		}
	}
	return out
}

// Serve mounts the runner routes when every port is present.
func (m *RunnerSurface) Serve() serve.Module {
	return serve.Module{
		Name:   "runs runner",
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			log := m.d.Log
			if log == nil {
				log = slog.Default()
			}
			if missing := m.Missing(); len(missing) > 0 {
				log.Warn("Runner routes are not mounted", "missing", strings.Join(missing, ", "))
				return nil
			}
			d := m.d
			runner.Mount(rt.Mux.Chi(), rt.Errors, runner.Deps{
				Tasks: runner.StoreTasks{DB: d.DB}, Gate: d.Gate, Clients: d.Clients, Slugs: d.Slugs, Broker: d.Broker,
				Presence: runner.RedisPresence{RDB: d.Redis}, Files: d.Files, Workers: d.Workers,
				Tokens: d.Tokens, Live: d.Live, Log: log.With("component", "runner"),
			})
			return nil
		},
	}
}
