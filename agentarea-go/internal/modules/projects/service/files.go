package service

import (
	"context"
	"errors"
	"net/http"
	"path"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// ErrFileNotFound is the routes' HTTPException(404, "File not found").
var ErrFileNotFound = errors.New("project file not found")

// projectPath is _project_path.
func projectPath(id uuid.UUID, rel string) string {
	rel = strings.TrimLeft(rel, "/")
	if rel == "" {
		return "projects/" + id.String() + "/"
	}
	return "projects/" + id.String() + "/" + rel
}

func (s *Service) exists(ctx context.Context, ws scope.Workspace, id uuid.UUID) error {
	_, err := s.Get(ctx, ws, id)
	return err
}

// PlanUploads is plan_project_uploads: entries are planned under the
// project's prefix and come back relative to it.
func (s *Service) PlanUploads(ctx context.Context, ws scope.Workspace, userID string, id uuid.UUID, entries []sandboxapi.UploadEntry) ([]sandboxapi.PlannedUpload, error) {
	if err := s.exists(ctx, ws, id); err != nil {
		return nil, err
	}
	prefix := projectPath(id, "")
	scoped := make([]sandboxapi.UploadEntry, len(entries))
	for i, e := range entries {
		e.Path = prefix + e.Path
		scoped[i] = e
	}
	planned, err := s.d.Files.PlanUploads(ctx, ws, userID, scoped)
	if err != nil {
		return nil, err
	}
	for i := range planned {
		planned[i].Path = strings.TrimPrefix(planned[i].Path, prefix)
	}
	return planned, nil
}

// ListFiles is list_project_files: directory markers are dropped.
func (s *Service) ListFiles(ctx context.Context, ws scope.Workspace, id uuid.UUID) ([]sandboxapi.FileInfo, error) {
	if err := s.exists(ctx, ws, id); err != nil {
		return nil, err
	}
	prefix := projectPath(id, "")
	objects, err := s.d.Files.List(ctx, ws, prefix)
	if err != nil {
		return nil, err
	}
	out := []sandboxapi.FileInfo{}
	for _, o := range objects {
		if strings.HasSuffix(o.Path, "/") {
			continue
		}
		o.Path = o.Path[len(prefix):]
		out = append(out, o)
	}
	return out, nil
}

// Download is stream_project_file: the whole object and its headers.
func (s *Service) Download(ctx context.Context, ws scope.Workspace, id uuid.UUID, filePath string) (sandboxapi.File, http.Header, error) {
	if err := s.exists(ctx, ws, id); err != nil {
		return sandboxapi.File{}, nil, err
	}
	f, err := s.d.Files.Get(ctx, ws, projectPath(id, filePath))
	if errors.Is(err, sandboxapi.ErrFileNotFound) || errors.Is(err, sandboxapi.ErrInvalidPath) {
		return sandboxapi.File{}, nil, ErrFileNotFound
	}
	if err != nil {
		return sandboxapi.File{}, nil, err
	}
	name := path.Base("/" + filePath)
	if name == "/" || name == "." {
		name = "file.bin"
	}
	return f, s.d.Files.DownloadHeaders(f.ContentType, name), nil
}

// FileURL is download_project_file: the API URL that streams the file.
func (s *Service) FileURL(ctx context.Context, ws scope.Workspace, id uuid.UUID, filePath string) (string, error) {
	if err := s.exists(ctx, ws, id); err != nil {
		return "", err
	}
	ok, err := s.d.Files.Exists(ctx, ws, projectPath(id, filePath))
	if errors.Is(err, sandboxapi.ErrInvalidPath) {
		return "", ErrFileNotFound
	}
	if err != nil {
		return "", err
	}
	if !ok {
		return "", ErrFileNotFound
	}
	encoded := quote(strings.TrimLeft(filePath, "/"))
	return strings.TrimRight(s.d.APIURL, "/") + "/v1/workspaces/" + ws.Slug() + "/projects/" + id.String() + "/files/download/" + encoded, nil
}

// DeleteFile is delete_project_file: an invalid path is "File not found".
func (s *Service) DeleteFile(ctx context.Context, ws scope.Workspace, userID string, id uuid.UUID, filePath string) error {
	if err := s.exists(ctx, ws, id); err != nil {
		return err
	}
	err := s.d.Files.Delete(ctx, ws, userID, projectPath(id, filePath))
	if errors.Is(err, sandboxapi.ErrInvalidPath) {
		return ErrFileNotFound
	}
	return err
}

// quote is urllib.parse.quote(s, safe="/") over UTF-8.
func quote(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := range len(s) {
		c := s[i]
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.IndexByte("_.-~/", c) >= 0 {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hex[c>>4])
		b.WriteByte(hex[c&15])
	}
	return b.String()
}
