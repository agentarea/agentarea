package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// PlatformFile is one stored object as workspace_files_list shows it;
// ContentType is "" when unknown.
type PlatformFile struct {
	Path         string
	Size         int64
	ContentType  string
	LastModified *string
}

// ReadOnlyError is WorkspaceReadOnlyError: the path belongs to an MCP app.
type ReadOnlyError struct{ Msg string }

func (e *ReadOnlyError) Error() string { return e.Msg }

// PlatformFiles is what the platform workspace_files toolset calls
// (tools/files_toolset.py) over the workspace artifact store.
type PlatformFiles interface {
	// ListFiles is ArtifactService.list: at most maxItems objects under prefix.
	ListFiles(ctx context.Context, ws scope.Workspace, prefix string, maxItems int) ([]PlatformFile, error)
	// FileExists is false for a path the store refuses.
	FileExists(ctx context.Context, ws scope.Workspace, path string) (bool, error)
	// ReadFile is the object's bytes: ErrFileNotFound or ErrInvalidPath when it cannot.
	ReadFile(ctx context.Context, ws scope.Workspace, path string) ([]byte, error)
	PlanUploads(ctx context.Context, ws scope.Workspace, actorUserID string, entries []UploadEntry) ([]PlannedUpload, error)
	// DeleteFile removes the object for good: *ReadOnlyError for an app's
	// path, ErrFileNotFound when it is not stored.
	DeleteFile(ctx context.Context, ws scope.Workspace, path string) error
	// DownloadURL is the API URL that downloads path in ws, which carries its slug.
	DownloadURL(ws scope.Workspace, path string) string
}
