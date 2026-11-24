package api

import (
	"context"
	"io"
	"net/http"
	"time"
)

// TaskFiles reads a task's artifacts and live sandbox files through the
// sandbox manager, or a runner task's harness files (agents_tasks.py
// download_task_artifact, list_task_sandbox_files, read_task_sandbox_file;
// agentarea_tasks/harness.py HarnessFiles). Every failure the caller answers
// is a *TaskFileError.
type TaskFiles interface {
	Artifacts(ctx context.Context, workspaceID, taskID string) ([]TaskArtifact, error)
	// Artifact streams one artifact; artifactID already matched art_[0-9a-f]{32}.
	Artifact(ctx context.Context, workspaceID, taskID, artifactID string) (Download, error)
	// ListFiles lists the live sandbox, or the harness files when harness;
	// prefix is already normalized.
	ListFiles(ctx context.Context, workspaceID, taskID, prefix string, harness bool) ([]string, error)
	// ReadFile streams one file; path is already normalized.
	ReadFile(ctx context.Context, workspaceID, taskID, path string, harness bool) (Download, error)
	// PublishArtifact publishes a file made outside the sandbox, a runner's,
	// as the task's artifact at path, as a file published from the sandbox is.
	PublishArtifact(ctx context.Context, workspaceID, taskID, path, contentType string, body []byte) (TaskArtifact, error)
}

// TaskArtifact is a published artifact; ContentType and SHA256 are "" when absent.
type TaskArtifact struct {
	ID, Path, Name string
	Size           int64
	ContentType    string
	SHA256         string
	CreatedAt      *time.Time
}

// Download is a body to stream and the headers to answer with: Content-Type
// (with Starlette's charset for text/*), Content-Disposition,
// X-Content-Type-Options and Content-Length when known. The caller closes Body.
type Download struct {
	Body   io.ReadCloser
	Header http.Header
}

// TaskFileError is the HTTP answer Python gives: Status and Detail as is.
type TaskFileError struct {
	Status int
	Detail string
}

func (e *TaskFileError) Error() string { return e.Detail }

// Is matches any *TaskFileError with the same status and detail.
func (e *TaskFileError) Is(target error) bool {
	t, ok := target.(*TaskFileError)
	return ok && t.Status == e.Status && t.Detail == e.Detail
}

var (
	ErrTaskFilesNotConfigured = &TaskFileError{Status: http.StatusServiceUnavailable, Detail: "Sandbox file access is not configured"}
	ErrTaskFilesUnavailable   = &TaskFileError{Status: http.StatusServiceUnavailable, Detail: "Sandbox file access is temporarily unavailable"}
	ErrSandboxExpired         = &TaskFileError{Status: http.StatusGone, Detail: "Sandbox workspace has expired"}
	ErrArtifactListInvalid    = &TaskFileError{Status: http.StatusBadGateway, Detail: "Artifact list response is invalid"}
	ErrSandboxFileListInvalid = &TaskFileError{Status: http.StatusBadGateway, Detail: "Sandbox file list is invalid"}
)
