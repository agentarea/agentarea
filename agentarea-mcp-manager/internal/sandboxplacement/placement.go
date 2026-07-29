// Package sandboxplacement is the control-plane seam that decides WHERE a
// sandbox execution runs. The runner (control plane) depends on the Placer
// abstraction; concrete data planes — Kubernetes warm pods, the docker
// sandbox-executor, a future host pool or microVM provider — are registered as
// Targets and selected per execution by placement rules, never wired in
// directly. This keeps "which sandbox" a domain decision and every data plane an
// interchangeable adapter.
package sandboxplacement

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// ErrNoEligibleTarget is returned when no registered target satisfies the
// placement constraints. It is a sentinel so callers can distinguish a
// placement DENY (a 4xx: the task asked for a region we do not serve) from a
// data-plane/backend failure. Never fall back to a non-matching target.
var ErrNoEligibleTarget = errors.New("no sandbox target satisfies placement constraints")

// Executor runs one command on a concrete data plane. It is the port every
// sandbox backend implements: it knows how to execute, not where it sits.
type Executor interface {
	ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error)
}

// Capabilities describe an operator-declared data plane: a stable name and the
// region it runs in. Placement matches task Constraints against these; the data
// plane itself stays unaware of them. Kept intentionally minimal — isolation
// tier / runtime class will be added when a second provider actually reads them
// (see the host-pool/gVisor provider), rather than sitting here as dead data.
type Capabilities struct {
	Name   string // stable target id, e.g. "kubernetes-eu", "hostpool-us"
	Region string // deployment region, e.g. "eu-central"; empty means undeclared
}

// Target binds a data-plane Executor to its declared Capabilities. Registering a
// Target is the only step needed to make a new sandbox available for placement.
type Target struct {
	Executor     Executor
	Capabilities Capabilities
}

// Constraints express where a task MAY run. They are derived from the execution
// record's runtime selector (not chosen ad hoc by the caller) so residency is
// enforced by the control plane. An empty Region means "unconstrained".
type Constraints struct {
	Region string
}

// Placer selects a Target that satisfies the given Constraints.
type Placer interface {
	Select(ctx context.Context, c Constraints) (*Target, error)
}

// Registry is a static Placer over a fixed, declaration-ordered set of Targets.
// It is the default placement policy: filter by constraints and FAIL HARD when
// nothing is eligible, otherwise pick the first eligible target in declaration
// order. Because there is no per-task pin yet, region determinism is what keeps
// a task on the same sandbox across calls — so NewRegistry enforces that no two
// targets share a region (a duplicate would let "first eligible" re-route a task
// mid-session and silently drop its workspace). A store-backed task->target pin
// replaces that invariant later without changing this seam.
type Registry struct {
	targets []Target
}

// NewRegistry builds a Registry, validating that every target is usable, is
// uniquely named, and occupies a unique region. It fails fast on
// misconfiguration rather than deferring the error to the first execution.
func NewRegistry(targets ...Target) (*Registry, error) {
	if len(targets) == 0 {
		return nil, fmt.Errorf("sandbox placement registry requires at least one target")
	}
	seenName := make(map[string]struct{}, len(targets))
	seenRegion := make(map[string]struct{}, len(targets))
	for _, t := range targets {
		if t.Capabilities.Name == "" {
			return nil, fmt.Errorf("sandbox placement target must have a name")
		}
		if t.Executor == nil {
			return nil, fmt.Errorf("sandbox placement target %q has no executor", t.Capabilities.Name)
		}
		if _, dup := seenName[t.Capabilities.Name]; dup {
			return nil, fmt.Errorf("duplicate sandbox placement target name %q", t.Capabilities.Name)
		}
		if _, dup := seenRegion[t.Capabilities.Region]; dup {
			return nil, fmt.Errorf(
				"duplicate sandbox placement target region %q: without a task->target pin, two targets in one region would re-route tasks mid-session",
				t.Capabilities.Region,
			)
		}
		seenName[t.Capabilities.Name] = struct{}{}
		seenRegion[t.Capabilities.Region] = struct{}{}
	}
	return &Registry{targets: append([]Target(nil), targets...)}, nil
}

// Select returns the first target satisfying the constraints, or
// ErrNoEligibleTarget when none is eligible. Region matching is asymmetric: an
// empty constraint matches any target, but a non-empty constraint requires an
// exact region match — a task pinned to "eu" must never run on a target that
// declares no region. Refusing to run is the correct outcome for residency.
func (r *Registry) Select(_ context.Context, c Constraints) (*Target, error) {
	for i := range r.targets {
		t := &r.targets[i]
		if c.Region != "" && t.Capabilities.Region != c.Region {
			continue
		}
		return t, nil
	}
	return nil, fmt.Errorf("%w (region=%q): refusing to run elsewhere", ErrNoEligibleTarget, c.Region)
}

// Targets returns the registered targets' capabilities in declaration order. It
// backs control-plane observability ("what sandboxes can we place on") without
// exposing executors.
func (r *Registry) Targets() []Capabilities {
	caps := make([]Capabilities, 0, len(r.targets))
	for i := range r.targets {
		caps = append(caps, r.targets[i].Capabilities)
	}
	return caps
}
