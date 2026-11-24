package temporal

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"sync/atomic"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/interceptor"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
)

// Worker is durable.Worker on one task queue.
type Worker struct {
	client *Client
	queue  string
	limits durable.Limits
	kinds  map[string]durable.ActivityKind
	flows  map[string]bool
	errs   []error
	fatal  chan error
	sdk    worker.Worker
	poll   atomic.Bool
}

var _ durable.Worker = (*Worker)(nil)

// NewWorker builds a worker on queue with explicit pollers and slots
// (main.py:303-319): heartbeat throttling at the cancellation delivery
// interval, shutdown grace from config, activity errors mapped to the
// ApplicationError types the workflows match.
func (c *Client) NewWorker(queue string, limits durable.Limits) *Worker {
	w := &Worker{
		client: c,
		queue:  queue,
		limits: limits,
		kinds:  map[string]durable.ActivityKind{},
		flows:  map[string]bool{},
		fatal:  make(chan error, 1),
	}
	if queue == "" {
		w.errs = append(w.errs, errors.New("task queue is required"))
	}
	if err := limits.Validate(); err != nil {
		w.errs = append(w.errs, err)
	}
	if len(w.errs) > 0 {
		return w
	}
	w.sdk = worker.New(c.sdk, queue, worker.Options{
		MaxConcurrentActivityExecutionSize:     limits.MaxActivities,
		MaxConcurrentWorkflowTaskExecutionSize: limits.MaxWorkflows,
		ActivityTaskPollerBehavior:             worker.NewPollerBehaviorSimpleMaximum(worker.PollerBehaviorSimpleMaximumOptions{MaximumNumberOfPollers: limits.ActivityPollers}),
		WorkflowTaskPollerBehavior:             worker.NewPollerBehaviorSimpleMaximum(worker.PollerBehaviorSimpleMaximumOptions{MaximumNumberOfPollers: limits.WorkflowPollers}),
		WorkerStopTimeout:                      c.config.ShutdownGrace,
		MaxHeartbeatThrottleInterval:           c.config.HeartbeatThrottle,
		DefaultHeartbeatThrottleInterval:       c.config.HeartbeatThrottle,
		Interceptors:                           []interceptor.WorkerInterceptor{&errorMapping{}},
		OnFatalError: func(err error) {
			select {
			case w.fatal <- err:
			default:
			}
		},
	})
	return w
}

// Queue is the task queue the worker polls.
func (w *Worker) Queue() string { return w.queue }

func (w *Worker) RegisterWorkflow(f durable.Workflow) {
	switch {
	case f.Name == "":
		w.errs = append(w.errs, errors.New("workflow registered without a name"))
	case w.flows[f.Name]:
		w.errs = append(w.errs, fmt.Errorf("workflow %s registered twice", f.Name))
	default:
		w.flows[f.Name] = true
		w.register("workflow "+f.Name, func() { w.sdk.RegisterWorkflowWithOptions(f.Fn, workflow.RegisterOptions{Name: f.Name}) })
	}
}

func (w *Worker) RegisterActivity(a durable.Activity) {
	switch _, dup := w.kinds[a.Name]; {
	case a.Name == "":
		w.errs = append(w.errs, errors.New("activity registered without a name"))
	case !a.Kind.Valid():
		w.errs = append(w.errs, fmt.Errorf("activity %s: kind must be control or data, got %q", a.Name, a.Kind))
	case dup:
		w.errs = append(w.errs, fmt.Errorf("activity %s registered twice", a.Name))
	default:
		w.kinds[a.Name] = a.Kind
		w.register("activity "+a.Name, func() { w.sdk.RegisterActivityWithOptions(a.Fn, activity.RegisterOptions{Name: a.Name}) })
	}
}

// register records the SDK's registration panics (a function of the wrong
// shape) as errors Run returns.
func (w *Worker) register(what string, fn func()) {
	if w.sdk == nil {
		return
	}
	defer func() {
		if r := recover(); r != nil {
			w.errs = append(w.errs, fmt.Errorf("register %s: %v", what, r))
		}
	}()
	fn()
}

func (w *Worker) Kinds() map[string]durable.ActivityKind { return maps.Clone(w.kinds) }

func (w *Worker) Polling() bool { return w.poll.Load() }

// Run polls until ctx ends or the worker stops on its own; a worker that
// stopped polling is an error, as in main.py:521-550. Stopping waits for
// running activities up to the shutdown grace.
func (w *Worker) Run(ctx context.Context) error {
	if err := errors.Join(w.errs...); err != nil {
		return fmt.Errorf("worker on %s: %w", w.queue, err)
	}
	if err := w.sdk.Start(); err != nil {
		return fmt.Errorf("start worker on %s: %w", w.queue, err)
	}
	w.poll.Store(true)
	defer w.poll.Store(false)
	select {
	case <-ctx.Done():
		w.sdk.Stop()
		return nil
	case err := <-w.fatal:
		w.sdk.Stop()
		return fmt.Errorf("worker on %s stopped polling: %w", w.queue, err)
	}
}

// errorMapping turns a durable.ApplicationError from an activity into the
// Temporal ApplicationError the workflows' retry policies and handlers match.
type errorMapping struct {
	interceptor.WorkerInterceptorBase
}

func (*errorMapping) InterceptActivity(_ context.Context, next interceptor.ActivityInboundInterceptor) interceptor.ActivityInboundInterceptor {
	i := &mapActivityErrors{}
	i.Next = next
	return i
}

type mapActivityErrors struct {
	interceptor.ActivityInboundInterceptorBase
}

func (m *mapActivityErrors) ExecuteActivity(ctx context.Context, in *interceptor.ExecuteActivityInput) (any, error) {
	out, err := m.Next.ExecuteActivity(ctx, in)
	return out, toTemporalError(err)
}

func toTemporalError(err error) error {
	appErr, ok := errors.AsType[*durable.ApplicationError](err)
	if !ok {
		return err
	}
	return temporal.NewApplicationErrorWithOptions(appErr.Message, appErr.Type, temporal.ApplicationErrorOptions{
		NonRetryable: appErr.NonRetryable,
		Cause:        appErr.Cause,
		Details:      appErr.Details,
	})
}
