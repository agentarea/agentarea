// Package connectorsandbox adapts a managed sandbox runtime to outbound agent
// commands. It deliberately owns no network transport or provider client: a
// connector can decode its protocol into Command and send Result back over any
// outbound channel.
package connectorsandbox

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

const (
	defaultInlineFileBytes   int64 = 1024 * 1024
	defaultInlineOutputBytes int64 = 1024 * 1024
	defaultOperationTimeout        = time.Minute
)

var (
	ErrCapabilityUnavailable = errors.New("sandbox capability unavailable")
	ErrExecutionIDConflict   = errors.New("execution ID was previously used for a different command")
	ErrInlinePayloadLimit    = errors.New("inline sandbox payload exceeds configured limit")
)

// CapabilityError reports a requested optional runtime surface that was not
// installed. Callers can use errors.Is(err, ErrCapabilityUnavailable) without
// relying on a transport-specific error representation.
type CapabilityError struct {
	Capability string
}

func (e *CapabilityError) Error() string {
	return fmt.Sprintf("%s: %s", ErrCapabilityUnavailable, e.Capability)
}

func (e *CapabilityError) Is(target error) bool { return target == ErrCapabilityUnavailable }

// Operation names the provider-neutral operation encoded in a Command.
type Operation string

const (
	OperationExecute          Operation = "execute"
	OperationWorkspaceEnsure  Operation = "workspace_ensure"
	OperationWorkspaceHydrate Operation = "workspace_hydrate"
	OperationFilePut          Operation = "file_put"
	OperationFileGet          Operation = "file_get"
	OperationFileList         Operation = "file_list"
	OperationTaskRetire       Operation = "task_retire"
)

// Command is an in-memory protocol boundary. A transport is responsible for
// authenticating it and mapping its wire message to this type; the dispatcher
// only enforces sandbox lifecycle and payload invariants.
type Command struct {
	Operation   Operation
	WorkspaceID string
	TaskID      string
	Timeout     time.Duration

	// ExecutionID is mandatory for execute and makes completed executions
	// replayable without invoking the runtime a second time.
	ExecutionID string
	Execute     *sandboxcontract.ExecuteRequest

	// Hydrate is selected by the connector's workspace integration. Keeping it
	// as a callback avoids embedding provider URLs or credentials in this
	// package or its command contract.
	Hydration *HydrationRequest

	FilePut *sandboxcontract.FilePutRequest
	Path    string
	Prefix  string
	IdleTTL time.Duration
}

// HydrationRequest describes a runtime hydration attempt. Revision is the
// immutable workspace revision understood by sandboxruntime.
type HydrationRequest struct {
	Revision string
	Hydrate  func(context.Context) error
}

// Result carries exactly one response matching Command.Operation.
type Result struct {
	Execute  *sandboxcontract.ExecuteResponse
	FilePut  *sandboxcontract.FilePutResponse
	FileGet  *sandboxcontract.FileGetResponse
	FileList *sandboxcontract.FileListResponse
}

// Config bounds all inline material and execution lifetime managed by this
// adapter. A caller-provided parent deadline always wins over Timeout.
type Config struct {
	MaxInlineFileBytes   int64
	MaxInlineOutputBytes int64
	DefaultTimeout       time.Duration
	MaxTimeout           time.Duration
}

func (c Config) normalized() (Config, error) {
	if c.MaxInlineFileBytes == 0 {
		c.MaxInlineFileBytes = defaultInlineFileBytes
	}
	if c.MaxInlineOutputBytes == 0 {
		c.MaxInlineOutputBytes = defaultInlineOutputBytes
	}
	if c.DefaultTimeout == 0 {
		c.DefaultTimeout = defaultOperationTimeout
	}
	if c.MaxTimeout == 0 {
		c.MaxTimeout = c.DefaultTimeout
	}
	if c.MaxInlineFileBytes <= 0 || c.MaxInlineOutputBytes <= 0 || c.DefaultTimeout <= 0 || c.MaxTimeout <= 0 {
		return Config{}, fmt.Errorf("connector sandbox limits and timeouts must be positive")
	}
	if c.DefaultTimeout > c.MaxTimeout {
		return Config{}, fmt.Errorf("default timeout must not exceed maximum timeout")
	}
	return c, nil
}

// WorkspaceEnsurer is optional because a bare ManagedRuntime cannot know how
// to obtain a durable workspace mount. sandboxruntime.WorkspaceRuntime
// implements it.
type WorkspaceEnsurer interface {
	EnsureWorkspace(context.Context, string, string) error
}

type executionRecord struct {
	fingerprint string
	done        chan struct{}
	result      Result
	err         error
}

// Dispatcher wraps one runtime binding. Its completed-execution cache is kept
// for the lifetime of the dispatcher, so a stable execution ID has stable
// replay semantics while that agent process remains alive. Durable replay
// across agent restarts belongs to the future outbound transport/store.
type Dispatcher struct {
	runtime sandboxruntime.ManagedRuntime
	cfg     Config

	mu         sync.Mutex
	executions map[string]*executionRecord
}

func New(runtime sandboxruntime.ManagedRuntime, cfg Config) (*Dispatcher, error) {
	if runtime == nil {
		return nil, fmt.Errorf("managed sandbox runtime is required")
	}
	normalized, err := cfg.normalized()
	if err != nil {
		return nil, err
	}
	return &Dispatcher{
		runtime:    runtime,
		cfg:        normalized,
		executions: make(map[string]*executionRecord),
	}, nil
}

// Dispatch runs one command. Execution commands are single-flight and replay
// their completed result for the same stable ID and command fingerprint.
func (d *Dispatcher) Dispatch(ctx context.Context, command Command) (Result, error) {
	if d == nil {
		return Result{}, fmt.Errorf("sandbox dispatcher is nil")
	}
	if err := validateIdentity(command.WorkspaceID, command.TaskID); err != nil {
		return Result{}, err
	}
	operationCtx, cancel, err := d.operationContext(ctx, command.Timeout)
	if err != nil {
		return Result{}, err
	}
	defer cancel()

	if command.Operation == OperationExecute {
		return d.dispatchExecution(operationCtx, command)
	}
	return d.dispatch(operationCtx, command)
}

func (d *Dispatcher) operationContext(ctx context.Context, requested time.Duration) (context.Context, context.CancelFunc, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	if requested == 0 {
		requested = d.cfg.DefaultTimeout
	}
	if requested < 0 || requested > d.cfg.MaxTimeout {
		return nil, nil, fmt.Errorf("operation timeout must be positive and no greater than %s", d.cfg.MaxTimeout)
	}
	operationCtx, cancel := context.WithTimeout(ctx, requested)
	return operationCtx, cancel, nil
}

func (d *Dispatcher) dispatchExecution(ctx context.Context, command Command) (Result, error) {
	request, fingerprint, err := d.prepareExecution(command)
	if err != nil {
		return Result{}, err
	}

	d.mu.Lock()
	record := d.executions[command.ExecutionID]
	if record == nil {
		record = &executionRecord{fingerprint: fingerprint, done: make(chan struct{})}
		d.executions[command.ExecutionID] = record
		d.mu.Unlock()
		result, executeErr := d.execute(ctx, command.WorkspaceID, command.TaskID, request)
		d.mu.Lock()
		record.result = cloneResult(result)
		record.err = executeErr
		close(record.done)
		d.mu.Unlock()
		return result, executeErr
	}
	if record.fingerprint != fingerprint {
		d.mu.Unlock()
		return Result{}, ErrExecutionIDConflict
	}
	d.mu.Unlock()

	select {
	case <-record.done:
		d.mu.Lock()
		result, executeErr := cloneResult(record.result), record.err
		d.mu.Unlock()
		return result, executeErr
	case <-ctx.Done():
		return Result{}, ctx.Err()
	}
}

func (d *Dispatcher) prepareExecution(command Command) (sandboxcontract.ExecuteRequest, string, error) {
	if strings.TrimSpace(command.ExecutionID) == "" {
		return sandboxcontract.ExecuteRequest{}, "", fmt.Errorf("execution_id is required")
	}
	if command.Execute == nil {
		return sandboxcontract.ExecuteRequest{}, "", fmt.Errorf("execute request is required")
	}
	request := *command.Execute
	if err := bindIdentity(&request.WorkspaceID, &request.TaskID, command.WorkspaceID, command.TaskID); err != nil {
		return sandboxcontract.ExecuteRequest{}, "", err
	}
	if request.CommandBody == "" {
		return sandboxcontract.ExecuteRequest{}, "", fmt.Errorf("command_body is required")
	}
	if request.WorkspaceManifestRef != nil {
		if request.WorkspaceManifestRef.WorkspaceID != command.WorkspaceID || request.WorkspaceManifestRef.TaskID != command.TaskID {
			return sandboxcontract.ExecuteRequest{}, "", fmt.Errorf("workspace manifest does not match command identity")
		}
	}
	if len(request.CommandBody) > sandboxcontract.MaxCommandBodyBytes {
		return sandboxcontract.ExecuteRequest{}, "", fmt.Errorf("command body: %w", ErrInlinePayloadLimit)
	}
	if request.StdoutMaxBytes <= 0 || request.StdoutMaxBytes > d.cfg.MaxInlineOutputBytes {
		request.StdoutMaxBytes = d.cfg.MaxInlineOutputBytes
	}
	if request.StderrMaxBytes <= 0 || request.StderrMaxBytes > d.cfg.MaxInlineOutputBytes {
		request.StderrMaxBytes = d.cfg.MaxInlineOutputBytes
	}
	fingerprint, err := executionFingerprint(command, request)
	if err != nil {
		return sandboxcontract.ExecuteRequest{}, "", err
	}
	return request, fingerprint, nil
}

func (d *Dispatcher) execute(ctx context.Context, workspaceID, taskID string, request sandboxcontract.ExecuteRequest) (Result, error) {
	result, err := d.withFence(ctx, workspaceID, taskID, func(operationCtx context.Context) (Result, error) {
		response, executeErr := d.runtime.ExecuteSandbox(operationCtx, request)
		if executeErr != nil {
			return Result{}, executeErr
		}
		if response == nil {
			return Result{}, fmt.Errorf("sandbox runtime returned an empty execution response")
		}
		return Result{Execute: limitOutput(response, d.cfg.MaxInlineOutputBytes)}, nil
	})
	return result, err
}

func (d *Dispatcher) dispatch(ctx context.Context, command Command) (Result, error) {
	switch command.Operation {
	case OperationWorkspaceEnsure:
		ensurer, ok := d.runtime.(WorkspaceEnsurer)
		if !ok {
			return Result{}, &CapabilityError{Capability: "workspace ensure"}
		}
		return d.withFence(ctx, command.WorkspaceID, command.TaskID, func(operationCtx context.Context) (Result, error) {
			return Result{}, ensurer.EnsureWorkspace(operationCtx, command.WorkspaceID, command.TaskID)
		})
	case OperationWorkspaceHydrate:
		if command.Hydration == nil || command.Hydration.Hydrate == nil || command.Hydration.Revision == "" {
			return Result{}, fmt.Errorf("workspace hydration revision and callback are required")
		}
		return d.withFence(ctx, command.WorkspaceID, command.TaskID, func(operationCtx context.Context) (Result, error) {
			return Result{}, d.runtime.EnsureWorkspaceHydrated(operationCtx, command.WorkspaceID, command.TaskID, command.Hydration.Revision, command.Hydration.Hydrate)
		})
	case OperationFilePut:
		writer, ok := d.runtime.(sandboxruntime.WorkspaceFileWriter)
		if !ok {
			return Result{}, &CapabilityError{Capability: "workspace file write"}
		}
		request, err := d.prepareFilePut(command)
		if err != nil {
			return Result{}, err
		}
		return d.withFence(ctx, command.WorkspaceID, command.TaskID, func(operationCtx context.Context) (Result, error) {
			response, putErr := writer.PutWorkspaceFile(operationCtx, request)
			if putErr != nil {
				return Result{}, putErr
			}
			if response == nil {
				return Result{}, fmt.Errorf("sandbox runtime returned an empty file put response")
			}
			return Result{FilePut: cloneFilePut(response)}, nil
		})
	case OperationFileGet:
		reader, ok := d.runtime.(sandboxruntime.WorkspaceFileReader)
		if !ok {
			return Result{}, &CapabilityError{Capability: "workspace file read"}
		}
		if err := validatePath(command.Path, false); err != nil {
			return Result{}, err
		}
		return d.withFence(ctx, command.WorkspaceID, command.TaskID, func(operationCtx context.Context) (Result, error) {
			download, openErr := reader.OpenWorkspaceFile(operationCtx, sandboxruntime.WorkspaceFileRead{
				WorkspaceFileDemand: sandboxruntime.WorkspaceFileDemand{WorkspaceID: command.WorkspaceID, TaskID: command.TaskID, Ensure: true},
				Path:                command.Path,
			})
			if openErr != nil {
				return Result{}, openErr
			}
			return d.inlineFile(download)
		})
	case OperationFileList:
		reader, ok := d.runtime.(sandboxruntime.WorkspaceFileReader)
		if !ok {
			return Result{}, &CapabilityError{Capability: "workspace file read"}
		}
		if err := validatePath(command.Prefix, true); err != nil {
			return Result{}, err
		}
		return d.withFence(ctx, command.WorkspaceID, command.TaskID, func(operationCtx context.Context) (Result, error) {
			response, listErr := reader.ListWorkspaceFiles(operationCtx, sandboxruntime.WorkspaceFileList{
				WorkspaceFileDemand: sandboxruntime.WorkspaceFileDemand{WorkspaceID: command.WorkspaceID, TaskID: command.TaskID, Ensure: true},
				Prefix:              command.Prefix,
			})
			if listErr != nil {
				return Result{}, listErr
			}
			if response == nil {
				return Result{}, fmt.Errorf("sandbox runtime returned an empty file list response")
			}
			return Result{FileList: cloneFileList(response)}, nil
		})
	case OperationTaskRetire:
		if command.IdleTTL < 0 {
			return Result{}, fmt.Errorf("task retirement idle TTL must not be negative")
		}
		// RetireSandboxTask owns the write-side task fence. Taking the read-side
		// fence here would deadlock against that required retirement fence.
		return Result{}, d.runtime.RetireSandboxTask(ctx, command.WorkspaceID, command.TaskID, command.IdleTTL)
	default:
		return Result{}, fmt.Errorf("unsupported sandbox operation %q", command.Operation)
	}
}

func (d *Dispatcher) prepareFilePut(command Command) (sandboxcontract.FilePutRequest, error) {
	if command.FilePut == nil {
		return sandboxcontract.FilePutRequest{}, fmt.Errorf("file put request is required")
	}
	request := *command.FilePut
	if err := bindIdentity(&request.WorkspaceID, &request.TaskID, command.WorkspaceID, command.TaskID); err != nil {
		return sandboxcontract.FilePutRequest{}, err
	}
	if err := validatePath(request.Path, false); err != nil {
		return sandboxcontract.FilePutRequest{}, err
	}
	if int64(base64.StdEncoding.DecodedLen(len(request.ContentBase64))) > d.cfg.MaxInlineFileBytes {
		return sandboxcontract.FilePutRequest{}, fmt.Errorf("file put: %w", ErrInlinePayloadLimit)
	}
	content, err := base64.StdEncoding.DecodeString(request.ContentBase64)
	if err != nil {
		return sandboxcontract.FilePutRequest{}, fmt.Errorf("decode file content: %w", err)
	}
	if int64(len(content)) > d.cfg.MaxInlineFileBytes {
		return sandboxcontract.FilePutRequest{}, fmt.Errorf("file put: %w", ErrInlinePayloadLimit)
	}
	return request, nil
}

func (d *Dispatcher) inlineFile(download *sandboxruntime.FileDownload) (Result, error) {
	if download == nil || download.Content == nil || download.Size < 0 {
		return Result{}, fmt.Errorf("sandbox runtime returned an invalid file stream")
	}
	defer download.Content.Close()
	if download.Size > d.cfg.MaxInlineFileBytes {
		return Result{}, fmt.Errorf("file get: %w", ErrInlinePayloadLimit)
	}
	content, err := io.ReadAll(io.LimitReader(download.Content, d.cfg.MaxInlineFileBytes+1))
	if err != nil {
		return Result{}, err
	}
	if int64(len(content)) != download.Size || int64(len(content)) > d.cfg.MaxInlineFileBytes {
		return Result{}, fmt.Errorf("file get: %w", ErrInlinePayloadLimit)
	}
	return Result{FileGet: &sandboxcontract.FileGetResponse{
		ContentBase64: base64.StdEncoding.EncodeToString(content),
		Size:          int64(len(content)),
	}}, nil
}

func (d *Dispatcher) withFence(ctx context.Context, workspaceID, taskID string, operation func(context.Context) (Result, error)) (Result, error) {
	operationCtx, release, err := d.runtime.BeginOperation(ctx, workspaceID, taskID)
	if err != nil {
		return Result{}, err
	}
	defer release()
	return operation(operationCtx)
}

func validateIdentity(workspaceID, taskID string) error {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return err
	}
	return workspace.ValidateIdentifier("task_id", taskID)
}

func bindIdentity(requestWorkspaceID, requestTaskID *string, workspaceID, taskID string) error {
	if *requestWorkspaceID != "" && *requestWorkspaceID != workspaceID {
		return fmt.Errorf("workspace_id does not match command identity")
	}
	if *requestTaskID != "" && *requestTaskID != taskID {
		return fmt.Errorf("task_id does not match command identity")
	}
	*requestWorkspaceID = workspaceID
	*requestTaskID = taskID
	return nil
}

func validatePath(value string, allowEmpty bool) error {
	if value == "" && allowEmpty {
		return nil
	}
	normalized, err := workspace.NormalizeRelativePath(value)
	if err != nil || normalized != value {
		return fmt.Errorf("invalid workspace path")
	}
	return nil
}

func executionFingerprint(command Command, request sandboxcontract.ExecuteRequest) (string, error) {
	// JSON produces a canonical representation for these concrete contract
	// values (including sorted map keys). Hashing it avoids ambiguous delimiter
	// concatenation while keeping the stored replay key bounded.
	payload, err := json.Marshal(struct {
		Operation   Operation                      `json:"operation"`
		WorkspaceID string                         `json:"workspace_id"`
		TaskID      string                         `json:"task_id"`
		Request     sandboxcontract.ExecuteRequest `json:"request"`
	}{
		Operation: command.Operation, WorkspaceID: command.WorkspaceID, TaskID: command.TaskID, Request: request,
	})
	if err != nil {
		return "", fmt.Errorf("encode execution fingerprint: %w", err)
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), nil
}

func limitOutput(response *sandboxcontract.ExecuteResponse, maximum int64) *sandboxcontract.ExecuteResponse {
	copy := cloneExecute(response)
	copy.Stdout, copy.StdoutTruncated = truncateInline(copy.Stdout, copy.StdoutTruncated, maximum)
	copy.Stderr, copy.StderrTruncated = truncateInline(copy.Stderr, copy.StderrTruncated, maximum)
	return copy
}

func truncateInline(value string, alreadyTruncated bool, maximum int64) (string, bool) {
	if int64(len(value)) <= maximum {
		return value, alreadyTruncated
	}
	return value[:maximum], true
}

func cloneResult(result Result) Result {
	return Result{
		Execute:  cloneExecute(result.Execute),
		FilePut:  cloneFilePut(result.FilePut),
		FileGet:  cloneFileGet(result.FileGet),
		FileList: cloneFileList(result.FileList),
	}
}

func cloneExecute(response *sandboxcontract.ExecuteResponse) *sandboxcontract.ExecuteResponse {
	if response == nil {
		return nil
	}
	copy := *response
	if response.StdoutRef != nil {
		stdoutRef := *response.StdoutRef
		copy.StdoutRef = &stdoutRef
	}
	if response.StderrRef != nil {
		stderrRef := *response.StderrRef
		copy.StderrRef = &stderrRef
	}
	copy.Artifacts = append([]sandboxcontract.SandboxArtifact(nil), response.Artifacts...)
	copy.WorkspaceChanges = append([]workspace.ChangeDescriptor(nil), response.WorkspaceChanges...)
	return &copy
}

func cloneFilePut(response *sandboxcontract.FilePutResponse) *sandboxcontract.FilePutResponse {
	if response == nil {
		return nil
	}
	copy := *response
	return &copy
}

func cloneFileGet(response *sandboxcontract.FileGetResponse) *sandboxcontract.FileGetResponse {
	if response == nil {
		return nil
	}
	copy := *response
	return &copy
}

func cloneFileList(response *sandboxcontract.FileListResponse) *sandboxcontract.FileListResponse {
	if response == nil {
		return nil
	}
	copy := *response
	copy.Paths = append([]string(nil), response.Paths...)
	return &copy
}
