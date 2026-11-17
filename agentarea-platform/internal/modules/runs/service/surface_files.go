package service

import (
	"context"
	"errors"
	"net/http"
	"regexp"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// FilesMounted is whether a task's artifacts and live files can be read.
func (s *Surface) FilesMounted() bool { return s.d.TaskFiles != nil }

var artifactID = regexp.MustCompile(`^art_[0-9a-f]{32}$`)

func (s *Surface) fileErr(ctx context.Context, msg string, err error) error {
	var fe *sandboxapi.TaskFileError
	if errors.As(err, &fe) {
		return httpx.HTTPError(fe.Status, fe.Detail).Wrap(err)
	}
	return s.internal(ctx, msg, err)
}

func (s *Surface) artifactItems(ctx context.Context, ws scope.Workspace, agentID, taskID string) ([]any, error) {
	items, err := s.d.TaskFiles.Artifacts(ctx, ws.ID(), taskID)
	if err != nil {
		return nil, s.fileErr(ctx, "Failed to list artifacts", err)
	}
	out := make([]any, 0, len(items))
	for _, a := range items {
		var created any
		if a.CreatedAt != nil {
			created = PyISO(*a.CreatedAt, false)
		}
		out = append(out, wirejson.Object{
			{Key: "id", Value: a.ID}, {Key: "path", Value: a.Path}, {Key: "name", Value: a.Name},
			{Key: "size", Value: a.Size}, {Key: "content_type", Value: nullable(a.ContentType)},
			{Key: "sha256", Value: nullable(a.SHA256)}, {Key: "created_at", Value: created},
			{Key: "download_url", Value: "/v1/workspaces/" + ws.Slug() + "/agents/" + agentID + "/tasks/" + taskID + "/artifacts/files/" + a.ID},
		})
	}
	return out, nil
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// Artifacts is list_task_artifacts.
func (s *Surface) Artifacts(ctx context.Context, agentID, taskID string) ([]any, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID); err != nil {
		return nil, err
	}
	return s.artifactItems(ctx, c.Workspace, agentID, taskID)
}

// Artifact is download_task_artifact.
func (s *Surface) Artifact(ctx context.Context, agentID, taskID, id string) (sandboxapi.Download, error) {
	c, err := caller(ctx)
	if err != nil {
		return sandboxapi.Download{}, err
	}
	if _, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID); err != nil {
		return sandboxapi.Download{}, err
	}
	if !artifactID.MatchString(id) {
		return sandboxapi.Download{}, notFound("Artifact not found")
	}
	d, err := s.d.TaskFiles.Artifact(ctx, c.Workspace.ID(), taskID, id)
	if err != nil {
		return sandboxapi.Download{}, s.fileErr(ctx, "Failed to download the artifact", err)
	}
	return d, nil
}

// liveSandboxPath is _normalize_live_sandbox_path.
func liveSandboxPath(v string, allowEmpty bool) (string, error) {
	if allowEmpty && v == "" {
		return "", nil
	}
	relative := httpx.HTTPError(http.StatusUnprocessableEntity, "Sandbox path must be relative")
	if v == "" || strings.HasPrefix(v, "/") || strings.ContainsAny(v, "\\\x00") {
		return "", relative
	}
	var parts []string
	for _, p := range strings.Split(v, "/") {
		switch p {
		case "":
			continue
		case ".", "..":
			return "", relative
		}
		parts = append(parts, p)
	}
	if len(parts) == 0 {
		return "", relative
	}
	return strings.Join(parts, "/"), nil
}

func harnessTask(t Task) bool {
	_, ok := t.Metadata.Get(runnerKey)
	return ok
}

// SandboxFiles is list_task_sandbox_files.
func (s *Surface) SandboxFiles(ctx context.Context, agentID, taskID, prefix string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	prefix, err = liveSandboxPath(prefix, true)
	if err != nil {
		return nil, err
	}
	paths, err := s.d.TaskFiles.ListFiles(ctx, c.Workspace.ID(), taskID, prefix, harnessTask(t))
	if err != nil {
		return nil, s.fileErr(ctx, "Failed to list sandbox files", err)
	}
	items := make([]any, 0, len(paths))
	for _, p := range paths {
		items = append(items, wirejson.Object{{Key: "path", Value: p}})
	}
	return wirejson.Object{{Key: "items", Value: items}, {Key: "total", Value: len(items)}}, nil
}

// SandboxFile is read_task_sandbox_file.
func (s *Surface) SandboxFile(ctx context.Context, agentID, taskID, filePath string) (sandboxapi.Download, error) {
	c, err := caller(ctx)
	if err != nil {
		return sandboxapi.Download{}, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return sandboxapi.Download{}, err
	}
	p, err := liveSandboxPath(filePath, false)
	if err != nil {
		return sandboxapi.Download{}, err
	}
	d, err := s.d.TaskFiles.ReadFile(ctx, c.Workspace.ID(), taskID, p, harnessTask(t))
	if err != nil {
		return sandboxapi.Download{}, s.fileErr(ctx, "Failed to read the sandbox file", err)
	}
	return d, nil
}

// TaskStatus is get_agent_task_status.
func (s *Surface) TaskStatus(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get task status", err)
	}
	if !ok || t.AgentID != agentID {
		return nil, notFound("Task not found")
	}
	t = s.enrich(ctx, t)
	execID := t.executionID()
	st := s.workflowStatus(ctx, execID)
	artifacts := []any{}
	if s.d.TaskFiles != nil {
		if artifacts, err = s.artifactItems(ctx, c.Workspace, agentID, taskID); err != nil {
			return nil, err
		}
	}
	exec := st.ExecutionStatus
	if exec == "" {
		exec = st.Status
	}
	paused := false
	if exec == "running" {
		if live := s.liveState(ctx, execID); live != nil {
			paused = truthy(live["paused"])
		}
	}
	result := t.Result
	if t.Result == nil && st.Result != nil {
		result = st.Result
	}
	var start, end, elapsed any
	if st.StartTime != nil {
		start = PyISO(*st.StartTime, false)
	}
	if st.EndTime != nil {
		end = PyISO(*st.EndTime, false)
		if st.StartTime != nil {
			elapsed = st.EndTime.Sub(*st.StartTime).Seconds()
		}
	}
	var errText any
	if t.Error != nil {
		errText = *t.Error
	}
	return wirejson.Object{
		{Key: "task_id", Value: taskID}, {Key: "agent_id", Value: agentID}, {Key: "execution_id", Value: execID},
		{Key: "status", Value: t.Status}, {Key: "execution_status", Value: exec}, {Key: "paused", Value: paused},
		{Key: "success", Value: st.Success}, {Key: "failure_reason", Value: st.FailureReason},
		{Key: "start_time", Value: start}, {Key: "end_time", Value: end}, {Key: "execution_time", Value: elapsed},
		{Key: "error", Value: errText}, {Key: "result", Value: result}, {Key: "artifacts", Value: artifacts},
	}, nil
}
