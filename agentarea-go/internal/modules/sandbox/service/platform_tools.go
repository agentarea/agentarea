package service

import (
	"context"
	"errors"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// PlatformFiles is api.PlatformFiles over the artifact store.
func (s *Service) PlatformFiles() api.PlatformFiles { return platformFiles{s} }

type platformFiles struct{ s *Service }

func (f platformFiles) ListFiles(ctx context.Context, ws scope.Workspace, prefix string, maxItems int) ([]api.PlatformFile, error) {
	if maxItems <= 0 {
		return []api.PlatformFile{}, nil
	}
	objs, err := f.s.art.List(ctx, ws.ID(), prefix, maxItems, nil)
	if err != nil {
		return nil, apiErr(err)
	}
	out := make([]api.PlatformFile, len(objs))
	for i, o := range objs {
		out[i] = api.PlatformFile{Path: o.Path, Size: o.Size, ContentType: o.ContentType, LastModified: o.LastModified}
	}
	return out, nil
}

func (f platformFiles) FileExists(ctx context.Context, ws scope.Workspace, path string) (bool, error) {
	ok, err := f.s.art.Exists(ctx, ws.ID(), path)
	var ip *InvalidPathError
	if errors.As(err, &ip) {
		return false, nil
	}
	return ok, err
}

func (f platformFiles) ReadFile(ctx context.Context, ws scope.Workspace, path string) ([]byte, error) {
	data, _, err := f.s.art.Get(ctx, ws.ID(), path)
	return data, apiErr(err)
}

func (f platformFiles) PlanUploads(ctx context.Context, ws scope.Workspace, actorUserID string, entries []api.UploadEntry) ([]api.PlannedUpload, error) {
	return f.s.PlanUploads(ctx, ws, actorUserID, entries)
}

func (f platformFiles) DeleteFile(ctx context.Context, ws scope.Workspace, path string) error {
	if err := domain.EnsureNotReadOnly(path); err != nil {
		return &api.ReadOnlyError{Msg: err.Error()}
	}
	ok, err := f.FileExists(ctx, ws, path)
	if err != nil {
		return err
	}
	if !ok {
		return api.ErrFileNotFound
	}
	return apiErr(f.s.art.Delete(ctx, ws.ID(), path, nil))
}

func (f platformFiles) DownloadURL(ws scope.Workspace, path string) string {
	return strings.TrimRight(f.s.d.APIURL, "/") + "/v1/workspaces/" + ws.Slug() + "/files/download/" + QuotePath(strings.TrimLeft(path, "/"))
}
