package api

import (
	"context"
	"io"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

type controlRuntimeStub struct {
	runtimeManifest func(context.Context) (*runtimeinfo.Manifest, error)
}

func (r *controlRuntimeStub) ExecuteSandbox(context.Context, sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error) {
	return &sandboxcontract.ExecuteResponse{}, nil
}

func (r *controlRuntimeStub) SandboxFilePut(context.Context, sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	return &sandboxcontract.FilePutResponse{}, nil
}

func (r *controlRuntimeStub) PutWorkspaceFile(context.Context, sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	return &sandboxcontract.FilePutResponse{}, nil
}

func (r *controlRuntimeStub) SandboxFileGet(context.Context, string, string, string) (*sandboxcontract.FileGetResponse, error) {
	return &sandboxcontract.FileGetResponse{}, nil
}

func (r *controlRuntimeStub) SandboxFileList(context.Context, string, string, string) (*sandboxcontract.FileListResponse, error) {
	return &sandboxcontract.FileListResponse{}, nil
}

func (r *controlRuntimeStub) RuntimeManifest(ctx context.Context) (*runtimeinfo.Manifest, error) {
	if r.runtimeManifest != nil {
		return r.runtimeManifest(ctx)
	}
	return &runtimeinfo.Manifest{}, nil
}

func (r *controlRuntimeStub) SandboxFileUpload(context.Context, sandboxruntime.FileUpload, io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return &sandboxruntime.FileWriteResult{}, nil
}

func (r *controlRuntimeStub) UploadWorkspaceFile(context.Context, sandboxruntime.FileUpload, io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return &sandboxruntime.FileWriteResult{}, nil
}

func (r *controlRuntimeStub) SandboxFileDownload(context.Context, string, string, string) (*sandboxruntime.FileDownload, error) {
	return &sandboxruntime.FileDownload{Content: io.NopCloser(strings.NewReader(""))}, nil
}

func (r *controlRuntimeStub) EnsureWorkspaceHydrated(
	ctx context.Context,
	_, _, _ string,
	hydrate func(context.Context) error,
) error {
	if hydrate == nil {
		return nil
	}
	return hydrate(ctx)
}

func (r *controlRuntimeStub) RetireSandboxTask(context.Context, string, string, time.Duration) error {
	return nil
}

func (r *controlRuntimeStub) BeginOperation(ctx context.Context, _, _ string) (context.Context, func(), error) {
	return ctx, func() {}, nil
}

func (r *controlRuntimeStub) GetWorkspaceFile(context.Context, sandboxruntime.WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error) {
	return &sandboxcontract.FileGetResponse{}, nil
}

func (r *controlRuntimeStub) OpenWorkspaceFile(context.Context, sandboxruntime.WorkspaceFileRead) (*sandboxruntime.FileDownload, error) {
	return &sandboxruntime.FileDownload{Content: io.NopCloser(strings.NewReader(""))}, nil
}

func (r *controlRuntimeStub) ListWorkspaceFiles(context.Context, sandboxruntime.WorkspaceFileList) (*sandboxcontract.FileListResponse, error) {
	return &sandboxcontract.FileListResponse{}, nil
}

var _ sandboxruntime.ControlRuntime = (*controlRuntimeStub)(nil)

func TestControlRuntimeDoesNotExposeProviderPrimitives(t *testing.T) {
	port := reflect.TypeOf((*sandboxruntime.ControlRuntime)(nil)).Elem()
	for _, forbidden := range []string{
		"BeginOperation",
		"EnsureWorkspaceHydrated",
		"ExecuteSandbox",
		"SandboxFileDownload",
		"SandboxFileGet",
		"SandboxFileList",
		"SandboxFilePut",
		"SandboxFileUpload",
	} {
		if _, exposed := port.MethodByName(forbidden); exposed {
			t.Fatalf("ControlRuntime exposes provider primitive %s", forbidden)
		}
	}
}
