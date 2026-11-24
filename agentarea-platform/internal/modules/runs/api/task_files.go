package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ErrNoTaskFile: the task a turn works on holds nothing at the path.
var ErrNoTaskFile = errors.New("no such file in the task")

// TaskFileURL is a short-lived download URL of one file of a task.
type TaskFileURL struct {
	Path, URL, SHA256 string
	Size              int64
	ExpiresInSeconds  int
}

// TaskFileURLs signs downloads of the files a runner's turn of taskID works on: a subtask's
// parent's, else its own task's. Only committed files (inputs, uploads) are reachable.
type TaskFileURLs interface {
	TaskFileURLs(ctx context.Context, ws scope.Workspace, taskID, path string) ([]TaskFileURL, error)
}
