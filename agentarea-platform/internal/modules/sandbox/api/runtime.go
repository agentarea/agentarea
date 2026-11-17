package api

import (
	"context"
	"errors"
)

// Runtime is the platform's side of the sandbox runtime contract: the shell
// and file tools, the completion barrier and the image manifest, all over the
// sandbox manager (AGENTAREA_MCP_MANAGER_URL). Python neither creates nor
// deletes a sandbox; the manager provisions one per task on demand.
type Runtime interface {
	// Bash is shell_toolset.bash: project inputs copied in, the command
	// executed in place, stdout/stderr read back by reference. Every failure
	// is a tool outcome; error is only the context ending.
	Bash(ctx context.Context, call BashCall) (ToolOutcome, error)
	// PutFile writes into the live sandbox /workspace (SandboxFileStore.put).
	PutFile(ctx context.Context, workspaceID, taskID, path string, data []byte) (StoredFile, error)
	// ReadFile is SandboxFileStore.get; ErrFileNotFound on 404.
	ReadFile(ctx context.Context, workspaceID, taskID, path string) ([]byte, string, error)
	// ListFiles is SandboxFileStore.list: paths under prefix, .agentarea/ hidden.
	ListFiles(ctx context.Context, workspaceID, taskID, prefix string) ([]string, error)
	// FileExists is SandboxFileStore.exists: list(prefix=path) then equality.
	FileExists(ctx context.Context, workspaceID, taskID, path string) (bool, error)
	// ValidateArtifacts is validate_published_artifacts, the completion barrier.
	ValidateArtifacts(ctx context.Context, workspaceID, taskID string, declared []string) (ArtifactValidation, error)
	// Manifest is fetch_runtime_manifest; ErrRuntimeUnavailable wraps why not.
	Manifest(ctx context.Context) (*RuntimeManifest, error)
}

// ErrRuntimeUnavailable is a manifest that could not be fetched or validated;
// its message is RuntimeDiscoveryResult.error.
var ErrRuntimeUnavailable = errors.New("runtime manifest unavailable")

// BashCall is one bash(command, timeout_seconds) call of a run.
type BashCall struct {
	WorkspaceID, TaskID, WorkflowID string
	Command                         string
	TimeoutSeconds                  *int
	// ProjectID is the run metadata's project_id: its files are copied to
	// inputs/project before the command runs.
	ProjectID string
}

// ToolOutcome is _tool_error or _shell_outcome. Outcome is "error" or "exit".
type ToolOutcome struct {
	Success  bool
	Result   string
	Error    string
	ExitCode *int
	Outcome  string
}

// StoredFile is what the sandbox reports for a put.
type StoredFile struct {
	Path string
	Size int64
}

// ArtifactValidation is ArtifactValidationResult. State is passed, failed
// or unavailable; Capability is set with unavailable.
type ArtifactValidation struct {
	State      string
	Generation int
	Evidence   []ArtifactEvidence
	Issues     []ArtifactIssue
	Capability string
}

type ArtifactEvidence struct {
	Path, Validator, SHA256 string
	Size                    int64
}

type ArtifactIssue struct{ Path, Validator, Code, Message string }

// RuntimeManifest is the sandbox image's manifest, schema version 2.
type RuntimeManifest struct {
	SchemaVersion       int               `json:"schema_version"`
	ImageVersion        string            `json:"image_version"`
	ManagedEnvironment  string            `json:"managed_environment"`
	Python              RuntimePython     `json:"python"`
	Node                RuntimeNode       `json:"node"`
	Tools               map[string]string `json:"tools"`
	Packages            map[string]string `json:"packages"`
	Features            RuntimeFeatures   `json:"features"`
	ExecutionSupervisor RuntimeSupervisor `json:"execution_supervisor"`
}

type RuntimePython struct {
	Version    string `json:"version"`
	Executable string `json:"executable"`
}

type RuntimeNode struct {
	Version    string  `json:"version"`
	NPMVersion *string `json:"npm_version"`
}

type RuntimeFeatures struct {
	Browser                    string `json:"browser"`
	ManagedEnvironmentMutation bool   `json:"managed_environment_mutation"`
	ArbitraryWorkspaceCode     bool   `json:"arbitrary_workspace_code"`
}

type RuntimeSupervisor struct {
	Path            string `json:"path"`
	SHA256          string `json:"sha256"`
	ProtocolVersion int    `json:"protocol_version"`
	CommandUID      int    `json:"command_uid"`
	CommandGID      int    `json:"command_gid"`
}

// Inventory is the workspace's live sandboxes (GET /sandboxes).
type Inventory interface {
	Sandboxes(ctx context.Context, workspaceID string) (SandboxList, error)
}

type SandboxList struct {
	Items []SandboxSummary
	Total int
}

type SandboxSummary struct {
	ID, Provider, WorkspaceID, TaskID, State string
	CreatedAt                                string
	ExpiresAt                                *string
	CPU, Memory                              string
	Isolation                                string
}
