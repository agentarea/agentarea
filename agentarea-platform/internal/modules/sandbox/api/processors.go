package api

import (
	"context"
	"errors"
	"time"
)

// ErrProcessorUnavailable: the sandbox could not run a processor's code at all.
var ErrProcessorUnavailable = errors.New("the sandbox could not run the processor")

// CodeRun is what the sandbox reports of one processor run; Stderr is read only when it failed.
type CodeRun struct {
	ExitCode        int
	Stdout          string
	StdoutTruncated bool
	Stderr          string
}

// Processors runs a stream processor's bash command in its own sandbox
// session (processor_sandbox.py SandboxCodeRunner). Every failure to run
// wraps ErrProcessorUnavailable.
type Processors interface {
	Run(ctx context.Context, workspaceID, session, command string, timeout time.Duration, maxOutputBytes int) (CodeRun, error)
}
