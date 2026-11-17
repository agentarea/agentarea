package api

import (
	"context"
	"errors"
)

// TaskWorkspace is the immutable, generation-based task workspace under
// workspaces/{ws}/tasks/{task}/ (artifacts/workspace.py
// S3WorkspaceRepository): content-addressed objects, one manifest per
// generation, a current pointer advanced by compare-and-swap under a fenced
// lease. The sandbox manager hydrates a sandbox from it.
type TaskWorkspace interface {
	// PutFiles commits the files as one generation; identical content
	// commits nothing and returns the current ref.
	PutFiles(ctx context.Context, workspaceID, taskID string, files []WorkspaceFile, opts WriteOptions) (ManifestRef, error)
	// AttachObject copies a workspace object (a staging upload) into the
	// task by server-side copy, verified against src's sha256 and size.
	AttachObject(ctx context.Context, workspaceID, taskID, path string, src AttachSource, opts WriteOptions) (ManifestRef, error)
	// ImportPrefix copies every object under workspaces/{ws}/{sourcePrefix}/
	// to targetPrefix/ in one generation (import_workspace_prefix).
	ImportPrefix(ctx context.Context, workspaceID, taskID, sourcePrefix, targetPrefix string, opts WriteOptions) (ManifestRef, error)
	// Get reads a committed file, verified; ErrFileNotFound when absent.
	Get(ctx context.Context, workspaceID, taskID, path string) ([]byte, string, error)
	// Exists reports a live entry of the current manifest.
	Exists(ctx context.Context, workspaceID, taskID, path string) (bool, error)
}

// ErrWorkspaceInvalid is WorkspaceValidationError, ErrWorkspaceConflict
// WorkspaceConflictError and ErrWorkspaceQuota WorkspaceQuotaError; errors
// returned wrap one of them and carry Python's message.
var (
	ErrWorkspaceInvalid  = errors.New("invalid_workspace_reference")
	ErrWorkspaceConflict = errors.New("workspace_conflict")
	ErrWorkspaceQuota    = errors.New("workspace_quota_exceeded")
)

// WorkspaceFile is one file to commit; ContentType "" is guessed from the path.
type WorkspaceFile struct {
	Path        string
	Data        []byte
	ContentType string
}

// AttachSource is a workspace-relative object key and its declared identity.
type AttachSource struct {
	Key         string
	SHA256      string
	Size        int64
	ContentType string
}

// WriteOptions: Owner names the lease (generated when empty); Actor, when
// set, records artifact events for the changed paths.
type WriteOptions struct {
	Owner string
	Actor *Actor
}

// Actor is ArtifactActor: a user, or an agent writing for its task's owner.
type Actor struct {
	UserID    string
	ActorType string
	AgentID   *string
	TaskID    *string
}

// ManifestRef is WorkspaceManifestRef.
type ManifestRef struct {
	SchemaVersion  int    `json:"schema_version"`
	WorkspaceID    string `json:"workspace_id"`
	TaskID         string `json:"task_id"`
	Generation     int64  `json:"generation"`
	ManifestURI    string `json:"manifest_uri"`
	ManifestSHA256 string `json:"manifest_sha256"`
	BaseGeneration int64  `json:"base_generation"`
	FencingToken   int64  `json:"fencing_token"`
}
