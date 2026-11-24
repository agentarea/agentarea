package service

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// taskFileURLTTL is how long a signed download of a task file stays valid.
const taskFileURLTTL = 5 * time.Minute

var _ api.TaskFileURLs = (*Surface)(nil)

// TaskFileURLs signs downloads of the files the turn of taskID works on.
func (s *Surface) TaskFileURLs(ctx context.Context, ws scope.Workspace, taskID, path string) ([]api.TaskFileURL, error) {
	if s.d.Workspaces == nil {
		return nil, errors.New("task files cannot be signed: this deployment has no task workspace")
	}
	t, ok, err := s.loadTask(ctx, ws, taskID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, notFound("Task not found")
	}
	filesTask, _ := liveFilesOf(t, taskID)
	signed, err := s.d.Workspaces.DownloadURLs(ctx, ws.ID(), filesTask, path, taskFileURLTTL)
	if errors.Is(err, sandboxapi.ErrFileNotFound) || errors.Is(err, sandboxapi.ErrWorkspaceInvalid) {
		return nil, api.ErrNoTaskFile
	}
	if err != nil {
		return nil, err
	}
	out := make([]api.TaskFileURL, 0, len(signed))
	for _, f := range signed {
		out = append(out, api.TaskFileURL{Path: f.Path, URL: f.URL, SHA256: f.SHA256, Size: f.Size, ExpiresInSeconds: int(taskFileURLTTL.Seconds())})
	}
	return out, nil
}
