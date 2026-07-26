package sandboxcontrol

import (
	"fmt"
	"net/url"
	"strings"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

const (
	maxPersistedPathBytes       = 1024
	maxPersistedURIBytes        = 2048
	maxPersistedErrorBytes      = 1024
	maxPersistedContentType     = 255
	maxPersistedObjectVersion   = 512
	maxArtifactPaths            = 256
	maxArtifactPathBytesTotal   = 16 * 1024
	maxInputRefs                = 200
	maxOutputRefs               = 10002
	maxWorkspaceChanges         = 10000
	maxTimeoutSeconds           = 3600
	maxPersistedOutputByteLimit = 16 * 1024 * 1024
)

var allowedRunnerPhases = map[string]struct{}{
	"finalize_pending":         {},
	"finalized_after_recovery": {},
	"recovery_failed":          {},
	"workspace_commit_pending": {},
}

func validateCreateRequest(req *ExecutionCreateRequest) error {
	if req == nil {
		return fmt.Errorf("execution request is required")
	}
	if err := validateOptionalIdentifier("session_id", req.SessionID); err != nil {
		return err
	}
	if err := validateOptionalIdentifier("workflow_id", req.WorkflowID); err != nil {
		return err
	}
	if err := validateOptionalIdentifier("task_id", req.TaskID); err != nil {
		return err
	}
	if err := validateOptionalIdentifier("workspace_id", req.WorkspaceID); err != nil {
		return err
	}
	if err := validateRuntimeSelector(req.Runtime); err != nil {
		return err
	}
	if err := validatePersistedCommand(req.Command); err != nil {
		return err
	}
	if req.Command.PackageInstall != "" || req.Command.TaskID != "" || req.Command.WorkspaceID != "" || req.Command.WorkspaceManifestRef != nil || req.Command.WorkspaceHydration != nil {
		return fmt.Errorf("command workspace identity and hydration are activation-only")
	}
	if req.WorkflowID != "" && req.Command.WorkflowID != "" && req.WorkflowID != req.Command.WorkflowID {
		return fmt.Errorf("command workflow_id does not match execution workflow_id")
	}
	if req.WorkspaceManifestRef != nil {
		return validateManifestRef(req.WorkspaceManifestRef)
	}
	return nil
}

func validateExecutionRecord(record *ExecutionRecord) error {
	if record == nil {
		return fmt.Errorf("execution record is required")
	}
	if err := validateExecutionID(record.ID); err != nil {
		return err
	}
	for name, value := range map[string]string{
		"session_id": record.SessionID, "workflow_id": record.WorkflowID,
		"task_id": record.TaskID, "workspace_id": record.WorkspaceID,
	} {
		if err := validateOptionalIdentifier(name, value); err != nil {
			return err
		}
	}
	if record.TaskID == "" || record.WorkspaceID == "" {
		return fmt.Errorf("task_id and workspace_id are required")
	}
	if err := validateRuntimeSelector(record.Runtime); err != nil {
		return err
	}
	if err := validateStatus(record.Status); err != nil {
		return err
	}
	if err := validatePersistedCommand(record.Command); err != nil {
		return err
	}
	if record.Command.PackageInstall != "" || record.Command.TaskID != "" || record.Command.WorkspaceID != "" || record.Command.WorkspaceManifestRef != nil || record.Command.WorkspaceHydration != nil {
		return fmt.Errorf("activation-only command workspace data cannot be persisted")
	}
	if record.Command.WorkflowID != "" && record.WorkflowID != "" && record.Command.WorkflowID != record.WorkflowID {
		return fmt.Errorf("command workflow_id does not match execution workflow_id")
	}
	if err := validateInternalMetadata(record.Metadata); err != nil {
		return err
	}
	if record.WorkspaceManifestRef != nil {
		if err := validateManifestRef(record.WorkspaceManifestRef); err != nil {
			return err
		}
		if record.WorkspaceManifestRef.WorkspaceID != record.WorkspaceID || record.WorkspaceManifestRef.TaskID != record.TaskID {
			return fmt.Errorf("workspace_manifest_ref identity does not match execution")
		}
	}
	if len(record.OutputRefs) > maxOutputRefs {
		return fmt.Errorf("output_refs exceeds %d entries", maxOutputRefs)
	}
	for _, output := range record.OutputRefs {
		if err := validateEntry(output); err != nil {
			return fmt.Errorf("invalid output_ref: %w", err)
		}
	}
	if err := validateExecutionResult(record.Result); err != nil {
		return err
	}
	if err := validateBoundedString("error", record.Error, maxPersistedErrorBytes); err != nil {
		return err
	}
	return nil
}

func validateExecutionEvent(event ExecutionEventRequest) error {
	if event.EventType != "" {
		switch event.EventType {
		case EventTypeExecutionClaimed, EventTypeExecutionStarted, EventTypeExecutionProgress,
			EventTypeExecutionCompleted, EventTypeExecutionFailed, EventTypeExecutionCancelled:
		default:
			return fmt.Errorf("invalid execution event_type")
		}
	}
	if event.Status != "" {
		if err := validateStatus(event.Status); err != nil {
			return err
		}
	}
	if err := validateBoundedString("error", event.Error, maxPersistedErrorBytes); err != nil {
		return err
	}
	if err := validateInternalMetadata(event.Metadata); err != nil {
		return err
	}
	if len(event.OutputRefs) > maxOutputRefs {
		return fmt.Errorf("output_refs exceeds %d entries", maxOutputRefs)
	}
	for _, output := range event.OutputRefs {
		if err := validateEntry(output); err != nil {
			return fmt.Errorf("invalid output_ref: %w", err)
		}
	}
	if event.WorkspaceManifestRef != nil {
		if err := validateManifestRef(event.WorkspaceManifestRef); err != nil {
			return err
		}
	}
	return validateExecutionResult(event.Result)
}

func validateRuntimeSelector(selector RuntimeSelector) error {
	if selector.Region != "" {
		if err := workspace.ValidateIdentifier("runtime region", selector.Region); err != nil {
			return err
		}
	}
	return runtimeinfo.ValidatePackageInstall(selector.PackageInstall)
}

func validatePersistedCommand(command warmpool.ExecuteRequest) error {
	if command.CommandBody == "" {
		return fmt.Errorf("command_body is required")
	}
	if len(command.CommandBody) > warmpool.MaxCommandBodyBytes || strings.ContainsRune(command.CommandBody, 0) {
		return fmt.Errorf("command_body exceeds %d bytes or contains NUL", warmpool.MaxCommandBodyBytes)
	}
	if command.CommandPath != "" {
		commandPath, err := workspace.NormalizeRelativePath(command.CommandPath)
		if err != nil || len(commandPath) > maxPersistedPathBytes {
			return fmt.Errorf("command_path, when set, must be a valid bounded relative path")
		}
	}
	if err := validateOptionalIdentifier("command workflow_id", command.WorkflowID); err != nil {
		return err
	}
	if command.TimeoutSeconds < 0 || command.TimeoutSeconds > maxTimeoutSeconds {
		return fmt.Errorf("timeout_seconds must be between 0 and %d", maxTimeoutSeconds)
	}
	if command.StdoutMaxBytes < 0 || command.StdoutMaxBytes > maxPersistedOutputByteLimit ||
		command.StderrMaxBytes < 0 || command.StderrMaxBytes > maxPersistedOutputByteLimit {
		return fmt.Errorf("output capture limits must be between 0 and %d", maxPersistedOutputByteLimit)
	}
	if len(command.ArtifactPaths) > maxArtifactPaths {
		return fmt.Errorf("artifact_paths exceeds %d entries", maxArtifactPaths)
	}
	total := 0
	seen := make(map[string]struct{}, len(command.ArtifactPaths))
	for _, artifactPath := range command.ArtifactPaths {
		clean, err := workspace.NormalizeRelativePath(artifactPath)
		if err != nil || len(clean) > maxPersistedPathBytes {
			return fmt.Errorf("invalid bounded artifact_path")
		}
		total += len(clean)
		if total > maxArtifactPathBytesTotal {
			return fmt.Errorf("artifact_paths exceed total byte limit")
		}
		if _, exists := seen[clean]; exists {
			return fmt.Errorf("duplicate artifact_path %q", clean)
		}
		seen[clean] = struct{}{}
	}
	return validateInputRefs(command.InputRefs)
}

// validateInputRefs bounds and structurally checks the copy-in refs carried in
// a command. It stays structural: the executor holds the authoritative host and
// bucket allowlist for the transfer, so this only rejects malformed refs before
// they are persisted.
func validateInputRefs(refs []warmpool.InputRef) error {
	if len(refs) > maxInputRefs {
		return fmt.Errorf("input_refs exceeds %d entries", maxInputRefs)
	}
	seen := make(map[string]struct{}, len(refs))
	for _, ref := range refs {
		clean, err := workspace.NormalizeRelativePath(ref.RelativePath)
		if err != nil || len(clean) > maxPersistedPathBytes {
			return fmt.Errorf("invalid bounded input_ref relative_path")
		}
		if _, exists := seen[clean]; exists {
			return fmt.Errorf("duplicate input_ref %q", clean)
		}
		seen[clean] = struct{}{}
		if ref.URL == "" || len(ref.URL) > maxPersistedURIBytes {
			return fmt.Errorf("input_ref %q must carry a bounded transfer URL", clean)
		}
		if len(ref.ObjectURI) > maxPersistedURIBytes {
			return fmt.Errorf("input_ref %q object_uri exceeds persistence limit", clean)
		}
		parsed, parseErr := url.Parse(ref.ObjectURI)
		if parseErr != nil || parsed.Scheme != "s3" || parsed.Host == "" || parsed.Path == "" {
			return fmt.Errorf("input_ref %q object_uri must be an s3 URI", clean)
		}
		if ref.SHA256 != "" && (len(ref.SHA256) != 64 || !isLowerHex(ref.SHA256)) {
			return fmt.Errorf("input_ref %q sha256 must be a lowercase digest", clean)
		}
		if ref.Size < 0 {
			return fmt.Errorf("input_ref %q size is negative", clean)
		}
	}
	return nil
}

func validateInternalMetadata(values map[string]string) error {
	if len(values) > 2 {
		return fmt.Errorf("execution metadata contains too many keys")
	}
	for key, value := range values {
		switch key {
		case "runner_consumer":
			if err := workspace.ValidateIdentifier("runner_consumer", value); err != nil {
				return fmt.Errorf("invalid internal metadata: %w", err)
			}
		case "runner_phase":
			if _, allowed := allowedRunnerPhases[value]; !allowed {
				return fmt.Errorf("invalid internal metadata runner_phase")
			}
		default:
			return fmt.Errorf("execution metadata key %q is not internal", key)
		}
	}
	return nil
}

// field/invariant); splitting it would scatter the checks without reducing
// real complexity. Matches this branch's documented "complexity debt out of
// scope" stance in .golangci.yml.
//
//nolint:gocyclo // A result validator is inherently branchy (one guard per
func validateExecutionResult(result *warmpool.ExecuteResponse) error {
	if result == nil {
		return nil
	}
	if result.Stdout != "" || result.Stderr != "" {
		return fmt.Errorf("execution result bodies must be stored as immutable output refs")
	}
	if result.ExecutionTimeMs < 0 {
		return fmt.Errorf("execution_time_ms cannot be negative")
	}
	for name, ref := range map[string]*workspace.Entry{"stdout_ref": result.StdoutRef, "stderr_ref": result.StderrRef} {
		if ref != nil {
			if err := validateEntry(*ref); err != nil {
				return fmt.Errorf("invalid %s: %w", name, err)
			}
		}
	}
	if len(result.Artifacts) > maxArtifactPaths {
		return fmt.Errorf("artifacts exceeds %d entries", maxArtifactPaths)
	}
	for _, artifact := range result.Artifacts {
		if artifact.Path != "" {
			if clean, err := workspace.NormalizeRelativePath(artifact.Path); err != nil || len(clean) > maxPersistedPathBytes {
				return fmt.Errorf("invalid artifact path")
			}
		}
		if err := validateBoundedString("artifact name", artifact.Name, maxPersistedPathBytes); err != nil {
			return err
		}
		if err := validateBoundedString("artifact content_type", artifact.ContentType, maxPersistedContentType); err != nil {
			return err
		}
		if err := validateBoundedString("artifact error", artifact.Error, maxPersistedErrorBytes); err != nil {
			return err
		}
		if artifact.Size < 0 || (artifact.SHA256 != "" && (len(artifact.SHA256) != 64 || !isLowerHex(artifact.SHA256))) {
			return fmt.Errorf("invalid artifact immutable identity")
		}
	}
	if len(result.WorkspaceChanges) > maxWorkspaceChanges {
		return fmt.Errorf("workspace_changes exceeds %d entries", maxWorkspaceChanges)
	}
	for _, change := range result.WorkspaceChanges {
		if clean, err := workspace.NormalizeRelativePath(change.RelativePath); err != nil || len(clean) > maxPersistedPathBytes {
			return fmt.Errorf("invalid workspace change path")
		}
		if change.Size < 0 || (!change.Deleted && (len(change.SHA256) != 64 || !isLowerHex(change.SHA256))) ||
			(change.Deleted && (change.SHA256 != "" || change.Size != 0 || change.ContentType != "" || change.Mode != 0)) {
			return fmt.Errorf("invalid workspace change immutable identity")
		}
		if err := validateBoundedString("workspace change content_type", change.ContentType, maxPersistedContentType); err != nil {
			return err
		}
	}
	return nil
}

func validateEntry(entry workspace.Entry) error {
	if err := entry.Validate(); err != nil {
		return err
	}
	if len(entry.RelativePath) > maxPersistedPathBytes || len(entry.ObjectURI) > maxPersistedURIBytes ||
		len(entry.ObjectVersionOrETag) > maxPersistedObjectVersion {
		return fmt.Errorf("workspace entry string exceeds persistence limit")
	}
	return validateBoundedString("workspace entry content_type", entry.ContentType, maxPersistedContentType)
}

func validateManifestRef(ref *workspace.ManifestRef) error {
	if ref == nil {
		return fmt.Errorf("workspace_manifest_ref is required")
	}
	if err := ref.Validate(); err != nil {
		return fmt.Errorf("invalid workspace_manifest_ref: %w", err)
	}
	if len(ref.ManifestURI) > maxPersistedURIBytes {
		return fmt.Errorf("workspace manifest URI exceeds persistence limit")
	}
	return nil
}

func validateExecutionID(id string) error {
	return workspace.ValidateIdentifier("execution id", id)
}

func validateOptionalIdentifier(name, value string) error {
	if value == "" {
		return nil
	}
	return workspace.ValidateIdentifier(name, value)
}

func validateStatus(status string) error {
	switch status {
	case ExecutionStatusQueued, ExecutionStatusClaimed, ExecutionStatusRunning,
		ExecutionStatusCompleted, ExecutionStatusFailed, ExecutionStatusCancelled:
		return nil
	default:
		return fmt.Errorf("invalid execution status")
	}
}

func validateBoundedString(name, value string, maxBytes int) error {
	if len(value) > maxBytes || strings.ContainsRune(value, 0) {
		return fmt.Errorf("%s exceeds persistence limit", name)
	}
	return nil
}

func isLowerHex(value string) bool {
	for _, char := range value {
		if (char < '0' || char > '9') && (char < 'a' || char > 'f') {
			return false
		}
	}
	return true
}
