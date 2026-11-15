package api

import (
	"context"
	"errors"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Files is the workspace file store other modules read and write through
// (agentarea_common/artifacts ArtifactService). Paths are workspace-relative.
// sandbox implements it; until it does, no route that needs it is mounted.
type Files interface {
	// PlanUploads diffs a {path, sha256} manifest against the store
	// (workspace_writes.py plan_uploads): per entry unchanged, a presigned
	// upload, or an error; one entry's failure never fails the call.
	PlanUploads(ctx context.Context, ws scope.Workspace, actorUserID string, entries []UploadEntry) ([]PlannedUpload, error)
	// List is every object under prefix, directory markers included.
	List(ctx context.Context, ws scope.Workspace, prefix string) ([]FileInfo, error)
	// Get reads a whole object: ErrFileNotFound or ErrInvalidPath when it cannot.
	Get(ctx context.Context, ws scope.Workspace, path string) (File, error)
	// Exists reports whether the object is stored; ErrInvalidPath for a path
	// the store refuses.
	Exists(ctx context.Context, ws scope.Workspace, path string) (bool, error)
	// Delete removes the object, recording the artifact event as the actor;
	// ErrInvalidPath for a path the store refuses.
	Delete(ctx context.Context, ws scope.Workspace, actorUserID, path string) error
	// Head is an object's stored digest, size and content type; false when
	// absent, ErrInvalidPath for a path the store refuses.
	Head(ctx context.Context, ws scope.Workspace, path string) (ObjectHead, bool, error)
	// DownloadHeaders are secure_download_headers: nosniff, and attachment
	// for content a browser would render.
	DownloadHeaders(contentType, filename string) http.Header
}

// ObjectHead is ArtifactService.head; SHA256 is "" when the object carries no digest.
type ObjectHead struct {
	SHA256      string
	Size        int64
	ContentType string
}

// ErrFileNotFound is FileNotFoundError.
var ErrFileNotFound = errors.New("file not found")

// ErrInvalidPath is InvalidArtifactPathError.
var ErrInvalidPath = errors.New("invalid artifact path")

// UploadEntry is one manifest entry; ContentType may be empty.
type UploadEntry struct {
	Path        string
	SHA256      string
	ContentType *string
}

// PlannedUpload is plan_uploads' answer for one entry. Status is
// "unchanged", "upload" or "error".
type PlannedUpload struct {
	Path      string
	Status    string
	UploadURL *string
	Method    *string
	Headers   map[string]string
	ExpiresIn *int
	Error     *string
}

// FileInfo is one listed object; LastModified is the store's ISO string.
type FileInfo struct {
	Path         string
	Size         int64
	LastModified *string
}

// File is an object's bytes and content type.
type File struct {
	Data        []byte
	ContentType string
}
