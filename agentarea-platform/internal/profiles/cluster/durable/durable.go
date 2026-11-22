// Package durable builds the Temporal adapter of a cluster deployment from
// the environment: one client per process and a worker per queue
// (main.py:303-357).
package durable

import (
	"context"
	"log/slog"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable/temporal"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
)

// Durable is the connected client and the config it was built from.
type Durable struct {
	Config kernel.Config
	client *temporal.Client
}

// Open loads kernel.Config from l and dials Temporal with TEMPORAL_* read
// from the process environment. Every configuration problem is reported at once.
func Open(ctx context.Context, l *config.Loader, logger *slog.Logger) (*Durable, error) {
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		return nil, err
	}
	c, err := temporal.Dial(ctx, cfg, nil, logger)
	if err != nil {
		return nil, err
	}
	return &Durable{Config: cfg, client: c}, nil
}

// LoadConfig reads kernel.Config from l and checks TEMPORAL_* in the process
// environment; l reports what is wrong.
func LoadConfig(l *config.Loader) kernel.Config {
	cfg := kernel.Load(l)
	if _, err := temporal.ConnectOptions(nil); err != nil {
		l.Fail("TEMPORAL_ADDRESS", err)
	}
	return cfg
}

// OpenLazy is Open over a checked cfg without the connection: the client
// dials on first use, so the serve role starts while Temporal is still coming up.
func OpenLazy(cfg kernel.Config, logger *slog.Logger) (*Durable, error) {
	c, err := temporal.DialLazy(cfg, nil, logger)
	if err != nil {
		return nil, err
	}
	return &Durable{Config: cfg, client: c}, nil
}

// Executor starts and drives workflows.
func (d *Durable) Executor() kernel.Executor { return d.client }

// Scheduler keeps Temporal Schedules.
func (d *Durable) Scheduler() kernel.Scheduler { return d.client }

// AgentWorker polls AGENTAREA_TEMPORAL_QUEUE with the configured limits.
func (d *Durable) AgentWorker() kernel.Worker {
	return d.client.NewWorker(d.Config.Queues.Agent, d.Config.Limits)
}

// TriggerWorker polls AGENTAREA_TRIGGER_QUEUE with Python's fixed limits.
func (d *Durable) TriggerWorker() kernel.Worker {
	return d.client.NewWorker(d.Config.Queues.Trigger, kernel.TriggerLimits())
}

// NewWorker polls queue with limits; the runner socket opens one per client.
func (d *Durable) NewWorker(queue string, limits kernel.Limits) kernel.Worker {
	return d.client.NewWorker(queue, limits)
}

// Component runs w in a lifecycle group: it fails the group when the worker
// stops polling.
func Component(name string, w kernel.Worker) lifecycle.Component {
	return lifecycle.Loop(name, w.Run)
}

// WaitNamespace returns once the Temporal namespace is registered; nil when ctx ends first.
func (d *Durable) WaitNamespace(ctx context.Context) error { return d.client.WaitNamespace(ctx) }

// Worker runs w in a lifecycle group once the namespace is registered: it fails the group when
// the worker stops polling, and is not ready until it polls.
func Worker(name string, d *Durable, w kernel.Worker) lifecycle.Component {
	return lifecycle.Loop(name, func(ctx context.Context) error {
		if err := d.WaitNamespace(ctx); err != nil || ctx.Err() != nil {
			return err
		}
		return w.Run(ctx)
	})
}

// Close closes the connection; workers must have stopped.
func (d *Durable) Close() { d.client.Close() }
