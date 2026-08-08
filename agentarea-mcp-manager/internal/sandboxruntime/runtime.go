// Package sandboxruntime owns the stable control-plane contract for agent
// sandboxes. Provider-specific SDKs live behind ExternalProvider; callers only
// see execution, files, runtime discovery, and retirement.
package sandboxruntime

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"path"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

const WorkspaceRoot = "/workspace"

const (
	defaultOutputCaptureBytes int64 = 1024 * 1024
	maxOutputCaptureBytes     int64 = 16 * 1024 * 1024
	maxInlineSandboxFileBytes       = 16 * 1024 * 1024
)

var (
	ErrSessionNotFound          = errors.New("sandbox session not found")
	ErrSessionQuarantined       = errors.New("sandbox session quarantined")
	ErrProvisioningUnresolved   = errors.New("sandbox provisioning outcome is unresolved")
	ErrWorkspaceRehydration     = errors.New("sandbox workspace must be rehydrated before retry")
	ErrFileNotFound             = errors.New("sandbox file not found")
	ErrExecutionHeartbeatFailed = errors.New("sandbox execution heartbeat failed")
	ErrLeaseHeartbeatFailed     = errors.New("sandbox lease heartbeat failed")
	ErrInventoryUnavailable     = errors.New("sandbox inventory unavailable")
)

// Runtime is the provider-neutral surface consumed by the HTTP control plane
// and the asynchronous sandbox runner.
type Runtime interface {
	ExecuteSandbox(context.Context, sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error)
	SandboxFilePut(context.Context, sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error)
	SandboxFileGet(context.Context, string, string, string) (*sandboxcontract.FileGetResponse, error)
	SandboxFileList(context.Context, string, string, string) (*sandboxcontract.FileListResponse, error)
	RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error)
}

// FileTransferRuntime moves file bodies without JSON/base64 buffering. Every
// shipped runtime must implement it before it can be wrapped with the durable
// workspace layer; absence is a startup error, never a small-file fallback.
type FileTransferRuntime interface {
	SandboxFileUpload(context.Context, FileUpload, io.Reader) (*FileWriteResult, error)
	SandboxFileDownload(context.Context, string, string, string) (*FileDownload, error)
}

// WorkspaceHydrationCoordinator owns control-plane hydration state and
// serialization for one live runtime binding. The agent-writable filesystem is
// deliberately not authoritative for this state.
type WorkspaceHydrationCoordinator interface {
	EnsureWorkspaceHydrated(
		context.Context,
		string,
		string,
		string,
		func(context.Context) error,
	) error
}

// FileUpload is the provider-neutral immutable identity of one file commit.
// Adapters must stage the body and make Path visible atomically only after the
// declared size, digest, and mode have been applied.
type FileUpload struct {
	WorkspaceID string
	TaskID      string
	Path        string
	Size        int64
	SHA256      string
	Mode        fs.FileMode
}

type FileWriteResult struct {
	Path string
	Size int64
}

type FileDownload struct {
	Content io.ReadCloser
	Size    int64
	Mode    fs.FileMode
}

// SandboxLister exposes the provider bindings currently owned by this manager.
// The HTTP API always applies workspace scoping before returning these records.
type SandboxLister interface {
	ListSandboxes(context.Context, string) ([]SandboxStatus, error)
}

// TaskRetirer is implemented by runtimes that own per-task lifecycle.
type TaskRetirer interface {
	RetireSandboxTask(context.Context, string, string, time.Duration) error
}

// OperationFencer lets a composing layer hold one retirement fence across a
// multi-step operation. Workspace hydration followed by execution has to be one
// fenced unit: without it retirement can land between the two steps and the
// command then runs in a freshly created, unhydrated workspace.
type OperationFencer interface {
	BeginOperation(context.Context, string, string) (context.Context, func(), error)
}

// ManagedRuntime is the complete lifecycle contract required before the
// durable workspace decorator can be constructed. Required capabilities are
// explicit here instead of recovered through runtime type assertions.
type ManagedRuntime interface {
	Runtime
	FileTransferRuntime
	WorkspaceHydrationCoordinator
	TaskRetirer
	OperationFencer
}

// ControlRuntime is the narrow use-case port consumed by HTTP handlers.
// Provider primitives such as BeginOperation, EnsureWorkspaceHydrated, raw
// downloads, and execution are deliberately absent: only the workspace
// decorator can implement the complete fence -> hydrate -> file protocol.
type ControlRuntime interface {
	WorkspaceFileWriter
	WorkspaceFileReader
	TaskRetirer
	RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error)
}

// ComposedRuntime is visible only at the composition root and to the async
// runner. Passing it to NewHandler narrows it to ControlRuntime, keeping the
// provider/lifecycle primitives outside the HTTP adapter.
type ComposedRuntime interface {
	ManagedRuntime
	ControlRuntime
}

type Session struct {
	Provider    string            `json:"provider"`
	ID          string            `json:"id"`
	WorkspaceID string            `json:"workspace_id"`
	TaskID      string            `json:"task_id"`
	Data        map[string]string `json:"data,omitempty"`
	CreatedAt   time.Time         `json:"created_at"`
	LastUsedAt  time.Time         `json:"last_used_at"`
	ExpiresAt   time.Time         `json:"expires_at"`
}

type SandboxStatus struct {
	ID          string            `json:"id"`
	Provider    string            `json:"provider"`
	WorkspaceID string            `json:"workspace_id"`
	TaskID      string            `json:"task_id"`
	State       string            `json:"state"`
	CreatedAt   time.Time         `json:"created_at"`
	ExpiresAt   *time.Time        `json:"expires_at"`
	Resources   map[string]string `json:"resources"`
	Isolation   string            `json:"isolation"`
}

// ExternalSandboxLister is optional because not every provider exposes a
// trustworthy live inventory endpoint. The manager fails loudly when it is
// absent instead of returning stale Redis bindings as if they were live.
type ExternalSandboxLister interface {
	List(context.Context, string) ([]SandboxStatus, error)
}

type CreateRequest struct {
	WorkspaceID    string
	TaskID         string
	ProvisioningID string
	Supervisor     execsupervisor.Attestation
}

// QuiescentExecution is the provider boundary for untrusted command execution.
// Returning a response asserts that the attested supervisor has reaped every
// descendant and durably published its authenticated status. Transport errors,
// missing status, or an unverifiable supervisor are ambiguous execution
// outcomes and require the Manager to discard the complete sandbox binding.
type QuiescentExecution struct {
	Request      sandboxcontract.ExecuteRequest
	Supervisor   execsupervisor.Attestation
	MaxFileBytes int64
}

// ProvisioningIntent is persisted before the control plane calls a remote
// create API. ProvisioningID is also attached to provider metadata, allowing a
// later process to find and remove a sandbox even when the create response was
// lost. ExpiresAt is the remote lease boundary; until then, an empty inventory
// result is not sufficient proof that no delayed create can become visible.
type ProvisioningIntent struct {
	Provider       string    `json:"provider"`
	ProvisioningID string    `json:"provisioning_id"`
	WorkspaceID    string    `json:"workspace_id"`
	TaskID         string    `json:"task_id"`
	StartedAt      time.Time `json:"started_at"`
	ExpiresAt      time.Time `json:"expires_at"`
}

func (intent ProvisioningIntent) validate(provider string) error {
	if provider == "" || intent.Provider != provider || intent.ProvisioningID == "" ||
		intent.WorkspaceID == "" || intent.TaskID == "" ||
		intent.StartedAt.IsZero() || intent.ExpiresAt.IsZero() ||
		!intent.ExpiresAt.After(intent.StartedAt) {
		return fmt.Errorf("sandbox provisioning intent identity is invalid")
	}
	return nil
}

// ExternalProvider is a thin adapter over one sandbox service. The Manager
// below owns sticky task routing and lease renewal; providers only translate the
// common operations to their native API.
//
// AuditWorkspace is part of the required contract rather than an optional
// capability: without live usage the control plane cannot hold a provider to the
// declared workspace limits, and a limit it cannot enforce is not a limit.
//
// Create has an ownership handoff rule: once the provider has received an
// allocation identity, it returns a non-nil Session even if post-create
// validation fails. A nil Session with an error is still ambiguous because the
// HTTP response may have been lost after allocation. ResolveProvisioning must
// therefore find every live sandbox carrying the durable ProvisioningID; the
// Manager owns reconciliation, quarantine, and compensating deletion.
type ExternalProvider interface {
	Name() string
	ProvisioningTimeout() time.Duration
	Create(context.Context, CreateRequest) (*Session, error)
	ResolveProvisioning(context.Context, ProvisioningIntent) ([]*Session, error)
	Renew(context.Context, *Session, time.Duration) error
	ExecuteQuiescent(context.Context, *Session, QuiescentExecution) (*sandboxcontract.ExecuteResponse, error)
	PutFile(context.Context, *Session, FileUpload, io.Reader) error
	OpenFile(context.Context, *Session, string) (*FileDownload, error)
	ListFiles(context.Context, *Session, string) ([]string, error)
	AuditWorkspace(context.Context, *Session) (WorkspaceUsage, error)
	Delete(context.Context, *Session) error
}

func sandboxPath(relative string) (string, error) {
	normalized, err := workspace.NormalizeRelativePath(relative)
	if err != nil {
		return "", fmt.Errorf("invalid sandbox path: %w", err)
	}
	return path.Join(WorkspaceRoot, normalized), nil
}

func relativeSandboxPath(absolute string) (string, error) {
	clean := path.Clean(absolute)
	prefix := WorkspaceRoot + "/"
	if !strings.HasPrefix(clean, prefix) {
		return "", fmt.Errorf("provider returned path outside the workspace")
	}
	relative := strings.TrimPrefix(clean, prefix)
	normalized, err := workspace.NormalizeRelativePath(relative)
	if err != nil || normalized != relative {
		return "", fmt.Errorf("provider returned a non-canonical workspace path")
	}
	return normalized, nil
}

func normalizeFileMode(mode fs.FileMode) (fs.FileMode, error) {
	if mode == 0 {
		return 0o600, nil
	}
	if mode&^fs.FileMode(0o777) != 0 {
		return 0, fmt.Errorf("file mode must contain only permission bits")
	}
	return mode, nil
}

func stagingPath(target string) (string, error) {
	random := make([]byte, 16)
	if _, err := rand.Read(random); err != nil {
		return "", fmt.Errorf("generate provider upload identity: %w", err)
	}
	return path.Join(path.Dir(target), "."+path.Base(target)+".agentarea-upload-"+hex.EncodeToString(random)), nil
}

type countingReader struct {
	reader io.Reader
	count  int64
}

func (r *countingReader) Read(buffer []byte) (int, error) {
	n, err := r.reader.Read(buffer)
	r.count += int64(n)
	return n, err
}

func outputCaptureLimit(requested int64) (int64, error) {
	if requested == 0 {
		return defaultOutputCaptureBytes, nil
	}
	if requested < 0 || requested > maxOutputCaptureBytes {
		return 0, fmt.Errorf("output capture limit must be between 1 and %d bytes", maxOutputCaptureBytes)
	}
	return requested, nil
}

type boundedOutput struct {
	builder   strings.Builder
	limit     int64
	truncated bool
	messages  int
}

func newBoundedOutput(limit int64) *boundedOutput {
	return &boundedOutput{limit: limit}
}

func (b *boundedOutput) Write(data []byte) {
	if int64(b.builder.Len()) >= b.limit {
		if len(data) > 0 {
			b.truncated = true
		}
		return
	}
	remaining := int(b.limit - int64(b.builder.Len()))
	if len(data) > remaining {
		data = data[:remaining]
		b.truncated = true
	}
	_, _ = b.builder.Write(data)
}

func (b *boundedOutput) WriteMessage(message string) {
	if b.messages > 0 {
		b.Write([]byte{'\n'})
	}
	b.messages++
	b.Write([]byte(message))
}

func (b *boundedOutput) String() string  { return b.builder.String() }
func (b *boundedOutput) Truncated() bool { return b.truncated }
