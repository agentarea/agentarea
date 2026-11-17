package docker

import (
	"bytes"
	"context"
	"os/exec"
)

// Runner runs one container runtime command and returns its two streams.
type Runner interface {
	Run(ctx context.Context, args ...string) (stdout, stderr []byte, err error)
}

type execRunner struct{ binary string }

func (r execRunner) Run(ctx context.Context, args ...string) ([]byte, []byte, error) {
	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, r.binary, args...) //nolint:gosec // the binary is the configured runtime; args are built here
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	return stdout.Bytes(), stderr.Bytes(), err
}
