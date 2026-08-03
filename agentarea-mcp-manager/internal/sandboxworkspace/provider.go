// Package sandboxworkspace owns the durable-to-live workspace boundary for
// agent sandboxes. Sandbox runtimes provide compute; a Provider decides what
// task workspace exists and which immutable inputs must be materialized into it.
package sandboxworkspace

import (
	"context"
	"errors"

	"github.com/agentarea/mcp-manager/internal/workspace"
)

var ErrLifecycleUnsupported = errors.New("workspace lifecycle operation is unsupported")

// Mount is a provider-neutral description of a task workspace. Root is the
// path visible inside the sandbox. Hydration contains short-lived transfer
// descriptors and is never persisted in Redis or Temporal payloads.
type Mount struct {
	WorkspaceID    string
	TaskID         string
	Root           string
	Generation     int64
	ManifestSHA256 string
	RevisionSHA256 string
	Hydration      workspace.Hydration
}

// Ensurer is the minimum workspace data-plane capability required by the
// on-demand runtime path. Lifecycle capabilities stay separate so providers do
// not have to implement operations the control plane never calls.
type Ensurer interface {
	Ensure(context.Context, string, string) (*Mount, error)
}

type Archiver interface {
	Archive(context.Context, string, string) error
}

type Restorer interface {
	Restore(context.Context, string, string) error
}

type Deleter interface {
	Delete(context.Context, string, string) error
}

// Provider is retained as the composed full lifecycle contract for providers
// that support every operation. Runtime hydration intentionally depends only
// on Ensurer.
type Provider interface {
	Ensurer
	Archiver
	Restorer
	Deleter
}
