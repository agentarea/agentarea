// Package sandboxcontract defines the provider-neutral command and inline-file
// messages shared by the sandbox control plane and its data-plane adapters.
package sandboxcontract

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/agentarea/mcp-manager/internal/workspace"
)

const MaxCommandBodyBytes = 256 * 1024

var ErrFileNotFound = errors.New("sandbox file not found")

type ExecuteRequest struct {
	ExecutorIncarnation  string                 `json:"executor_incarnation,omitempty"`
	CommandBody          string                 `json:"command_body,omitempty"`
	CommandPath          string                 `json:"command_path,omitempty"`
	ArtifactPaths        []string               `json:"artifact_paths,omitempty"`
	TimeoutSeconds       int                    `json:"timeout_seconds,omitempty"`
	StdoutMaxBytes       int64                  `json:"stdout_max_bytes,omitempty"`
	StderrMaxBytes       int64                  `json:"stderr_max_bytes,omitempty"`
	WorkflowID           string                 `json:"workflow_id,omitempty"`
	TaskID               string                 `json:"task_id,omitempty"`
	WorkspaceID          string                 `json:"workspace_id,omitempty"`
	WorkspaceManifestRef *workspace.ManifestRef `json:"workspace_manifest_ref,omitempty"`
	WorkspaceHydration   *workspace.Hydration   `json:"workspace_hydration,omitempty"`
}

func (r *ExecuteRequest) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, field := range []string{"args", "env", "script", "input_files", "content_base64", "script_content", "script_name"} {
		if _, exists := fields[field]; exists {
			return fmt.Errorf("unsupported_contract_version: legacy inline execution fields are forbidden; use command_body and manager-owned task inputs")
		}
	}
	type requestAlias ExecuteRequest
	var decoded requestAlias
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*r = ExecuteRequest(decoded)
	return nil
}

type SandboxArtifact struct {
	Path        string `json:"path"`
	Name        string `json:"name,omitempty"`
	ContentType string `json:"content_type,omitempty"`
	Size        int64  `json:"size,omitempty"`
	SHA256      string `json:"sha256,omitempty"`
	Error       string `json:"error,omitempty"`
}

type ExecuteResponse struct {
	Stdout           string                       `json:"stdout,omitempty"`
	Stderr           string                       `json:"stderr,omitempty"`
	StdoutRef        *workspace.Entry             `json:"stdout_ref,omitempty"`
	StderrRef        *workspace.Entry             `json:"stderr_ref,omitempty"`
	StdoutTruncated  bool                         `json:"stdout_truncated,omitempty"`
	StderrTruncated  bool                         `json:"stderr_truncated,omitempty"`
	ExitCode         int                          `json:"exit_code"`
	ExecutionTimeMs  int64                        `json:"execution_time_ms"`
	Artifacts        []SandboxArtifact            `json:"artifacts,omitempty"`
	WorkspaceChanges []workspace.ChangeDescriptor `json:"workspace_changes,omitempty"`
}

type FilePutRequest struct {
	WorkspaceID         string `json:"workspace_id"`
	TaskID              string `json:"task_id"`
	ExecutorIncarnation string `json:"executor_incarnation,omitempty"`
	Path                string `json:"path"`
	ContentBase64       string `json:"content_base64"`
}

type FilePutResponse struct {
	Path string `json:"path"`
	Size int64  `json:"size"`
}

type FileGetResponse struct {
	ContentBase64 string `json:"content_base64"`
	Size          int64  `json:"size"`
}

type FileListResponse struct {
	Paths []string `json:"paths"`
}
