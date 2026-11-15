// Package lifecycle starts a role's components in order, keeps them running,
// and stops them in reverse order with a deadline.
//
// It replaces the Python API lifespan (main.py: start order, then shutdown
// with 2 s timeouts per step in reverse) and mcp-manager's managerapp Run and
// Close hooks: a background loop that returns before it is asked to stop is a
// failure that stops the whole group.
package lifecycle

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"
)

// Component is one long-lived part of a role: a pool, an HTTP listener, a
// consumer, a worker. Start returns once the component is ready; Stop returns
// once it released what it holds or ctx expired.
type Component interface {
	Name() string
	Start(ctx context.Context) error
	Stop(ctx context.Context) error
}

// Failer is implemented by components that can fail after Start, such as a
// background loop. A value on the channel stops the group.
type Failer interface {
	Failed() <-chan error
}

// Checker reports whether a dependency is healthy, for readiness endpoints.
type Checker interface {
	Name() string
	Check(ctx context.Context) error
}

// Options bound the group's start and stop.
type Options struct {
	// StartupTimeout bounds starting every component (AGENTAREA_STARTUP_TIMEOUT).
	StartupTimeout time.Duration
	// ShutdownTimeout bounds stopping every component (AGENTAREA_SHUTDOWN_TIMEOUT).
	ShutdownTimeout time.Duration
}

// Group is an ordered set of components.
type Group struct {
	opts  Options
	comps []Component
}

// NewGroup returns an empty group.
func NewGroup(opts Options) *Group { return &Group{opts: opts} }

// Add appends components; they start in the order added.
func (g *Group) Add(cs ...Component) { g.comps = append(g.comps, cs...) }

// StartError is a component that failed to start.
type StartError struct {
	Component string
	Err       error
}

func (e *StartError) Error() string { return fmt.Sprintf("start %s: %v", e.Component, e.Err) }

func (e *StartError) Unwrap() error { return e.Err }

// FailedError is a component that failed while running.
type FailedError struct {
	Component string
	Err       error
}

func (e *FailedError) Error() string { return fmt.Sprintf("%s failed: %v", e.Component, e.Err) }

func (e *FailedError) Unwrap() error { return e.Err }

// StopError is a component that failed to stop cleanly.
type StopError struct {
	Component string
	Err       error
}

func (e *StopError) Error() string { return fmt.Sprintf("stop %s: %v", e.Component, e.Err) }

func (e *StopError) Unwrap() error { return e.Err }

// Run starts every component, waits until ctx is done or one fails, then
// stops the started ones in reverse order. It returns nil after a clean stop
// requested through ctx, and otherwise every error joined.
func (g *Group) Run(ctx context.Context) error {
	started, err := g.start(ctx)
	var runErr error
	if err == nil {
		runErr = g.wait(ctx, started)
	}
	stopErr := g.stop(started)
	return errors.Join(err, runErr, stopErr)
}

func (g *Group) start(ctx context.Context) ([]Component, error) {
	startCtx, cancel := withTimeout(ctx, g.opts.StartupTimeout)
	defer cancel()
	started := make([]Component, 0, len(g.comps))
	for _, c := range g.comps {
		if err := c.Start(startCtx); err != nil {
			return started, &StartError{Component: c.Name(), Err: err}
		}
		started = append(started, c)
	}
	return started, nil
}

func (g *Group) wait(ctx context.Context, started []Component) error {
	failed := make(chan error, len(started))
	done := make(chan struct{})
	defer close(done)
	for _, c := range started {
		f, ok := c.(Failer)
		if !ok {
			continue
		}
		go func(name string, ch <-chan error) {
			select {
			case err := <-ch:
				if err == nil {
					err = errors.New("stopped before it was asked to")
				}
				failed <- &FailedError{Component: name, Err: err}
			case <-done:
			}
		}(c.Name(), f.Failed())
	}
	select {
	case <-ctx.Done():
		return nil
	case err := <-failed:
		return err
	}
}

func (g *Group) stop(started []Component) error {
	stopCtx, cancel := withTimeout(context.Background(), g.opts.ShutdownTimeout)
	defer cancel()
	var errs []error
	for i := len(started) - 1; i >= 0; i-- {
		if err := started[i].Stop(stopCtx); err != nil {
			errs = append(errs, &StopError{Component: started[i].Name(), Err: err})
		}
	}
	return errors.Join(errs...)
}

func withTimeout(ctx context.Context, d time.Duration) (context.Context, context.CancelFunc) {
	if d <= 0 {
		return context.WithCancel(ctx)
	}
	return context.WithTimeout(ctx, d)
}

// Func is a Component from two functions; either may be nil.
func Func(name string, start, stop func(ctx context.Context) error) Component {
	return &funcComponent{name: name, start: start, stop: stop}
}

type funcComponent struct {
	name        string
	start, stop func(ctx context.Context) error
}

func (f *funcComponent) Name() string { return f.name }

func (f *funcComponent) Start(ctx context.Context) error {
	if f.start == nil {
		return nil
	}
	return f.start(ctx)
}

func (f *funcComponent) Stop(ctx context.Context) error {
	if f.stop == nil {
		return nil
	}
	return f.stop(ctx)
}

// Loop is a Component that runs fn in the background from Start until Stop
// cancels its context. fn must return when its context ends; returning
// earlier, with or without an error, fails the group.
func Loop(name string, fn func(ctx context.Context) error) Component {
	return &loop{name: name, fn: fn}
}

type loop struct {
	name   string
	fn     func(ctx context.Context) error
	cancel context.CancelFunc
	done   chan struct{}
	failed chan error
	mu     sync.Mutex
	err    error
}

func (l *loop) Name() string { return l.name }

func (l *loop) Failed() <-chan error { return l.failed }

func (l *loop) Start(context.Context) error {
	ctx, cancel := context.WithCancel(context.Background())
	l.cancel = cancel
	l.done = make(chan struct{})
	l.failed = make(chan error, 1)
	go func() {
		defer close(l.done)
		err := l.fn(ctx)
		if ctx.Err() == nil {
			l.failed <- err
			return
		}
		l.mu.Lock()
		l.err = err
		l.mu.Unlock()
	}()
	return nil
}

func (l *loop) Stop(ctx context.Context) error {
	if l.cancel == nil {
		return nil
	}
	l.cancel()
	select {
	case <-l.done:
	case <-ctx.Done():
		return fmt.Errorf("did not stop in time: %w", ctx.Err())
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.err != nil && !errors.Is(l.err, context.Canceled) {
		return l.err
	}
	return nil
}
