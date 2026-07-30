// Package sandboxruntime owns the stable control-plane contract for agent
// sandboxes. Provider-specific SDKs live behind ExternalProvider; callers only
// see execution, files, runtime discovery, and retirement.
package sandboxruntime

import (
	"context"
	"errors"
	"fmt"
	"path"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const WorkspaceRoot = "/workspace"

const (
	defaultOutputCaptureBytes int64 = 1024 * 1024
	maxOutputCaptureBytes     int64 = 16 * 1024 * 1024
	maxSandboxFileBytes             = 16 * 1024 * 1024
)

var (
	ErrSessionNotFound          = errors.New("sandbox session not found")
	ErrFileNotFound             = errors.New("sandbox file not found")
	ErrExecutionHeartbeatFailed = errors.New("sandbox execution heartbeat failed")
	ErrInventoryUnavailable     = errors.New("sandbox inventory unavailable")
)

// Runtime is the provider-neutral surface consumed by the HTTP control plane
// and the asynchronous sandbox runner.
type Runtime interface {
	ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error)
	SandboxFilePut(context.Context, warmpool.FilePutRequest) (*warmpool.FilePutResponse, error)
	SandboxFileGet(context.Context, string, string, string) (*warmpool.FileGetResponse, error)
	SandboxFileList(context.Context, string, string, string) (*warmpool.FileListResponse, error)
	RuntimeManifest(context.Context, string) (*runtimeinfo.Manifest, error)
}

// SandboxLister exposes the provider bindings currently owned by this manager.
// The HTTP API always applies workspace scoping before returning these records.
type SandboxLister interface {
	ListSandboxes(context.Context, string) ([]SandboxStatus, error)
}

// TaskRetirer is implemented by runtimes that own per-task lifecycle.
type TaskRetirer interface {
	RetireSandboxTask(context.Context, string, time.Duration) error
}

type Session struct {
	Provider       string            `json:"provider"`
	ID             string            `json:"id"`
	WorkspaceID    string            `json:"workspace_id"`
	TaskID         string            `json:"task_id"`
	PackageInstall string            `json:"package_install"`
	Data           map[string]string `json:"data,omitempty"`
	CreatedAt      time.Time         `json:"created_at"`
	LastUsedAt     time.Time         `json:"last_used_at"`
	ExpiresAt      time.Time         `json:"expires_at"`
}

type SandboxStatus struct {
	ID             string            `json:"id"`
	Provider       string            `json:"provider"`
	WorkspaceID    string            `json:"workspace_id"`
	TaskID         string            `json:"task_id"`
	PackageInstall string            `json:"package_install"`
	State          string            `json:"state"`
	CreatedAt      time.Time         `json:"created_at"`
	ExpiresAt      *time.Time        `json:"expires_at"`
	Resources      map[string]string `json:"resources"`
	Isolation      string            `json:"isolation"`
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
	PackageInstall string
}

// ExternalProvider is a thin adapter over one sandbox service. The Manager
// below owns sticky task routing and lease renewal; providers only translate the
// common operations to their native API.
type ExternalProvider interface {
	Name() string
	Create(context.Context, CreateRequest) (*Session, error)
	Renew(context.Context, *Session, time.Duration) error
	Execute(context.Context, *Session, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error)
	PutFile(context.Context, *Session, string, []byte) error
	GetFile(context.Context, *Session, string) ([]byte, error)
	ListFiles(context.Context, *Session, string) ([]string, error)
	Delete(context.Context, *Session) error
}

func sandboxPath(relative string) (string, error) {
	if relative == "" {
		return "", fmt.Errorf("sandbox path is required")
	}
	if strings.ContainsRune(relative, '\x00') || strings.HasPrefix(relative, "/") {
		return "", fmt.Errorf("sandbox path must be relative")
	}
	clean := path.Clean(relative)
	if clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
		return "", fmt.Errorf("sandbox path escapes the workspace")
	}
	return path.Join(WorkspaceRoot, clean), nil
}

func relativeSandboxPath(absolute string) (string, error) {
	clean := path.Clean(absolute)
	prefix := WorkspaceRoot + "/"
	if !strings.HasPrefix(clean, prefix) {
		return "", fmt.Errorf("provider returned path outside the workspace")
	}
	return strings.TrimPrefix(clean, prefix), nil
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
