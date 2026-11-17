package handlers

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/sandbox"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/service"
)

// Server implements the files and sandboxes routes (api/v1/files.py,
// api/v1/sandboxes.py).
type Server struct {
	svc *service.Service
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service) *Server { return &Server{svc: svc} }

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var he *service.HTTPError
	var ip *service.InvalidPathError
	switch {
	case errors.As(err, &he):
		return httpx.HTTPError(he.Status, he.Detail), true
	case errors.As(err, &ip):
		return httpx.NewError(http.StatusUnprocessableEntity, "invalid_artifact_path", ip.Error()), true
	}
	return nil, false
}

func itoa(n int) string { return strconv.Itoa(n) }

type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitListWorkspaceFilesV1FilesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateWorkspaceDirectoryV1FilesDirectoriesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitWorkspaceFileHistoryV1FilesHistoryGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitMoveWorkspaceFileV1FilesMovePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRestoreWorkspaceFileV1FilesRestoreFilePathPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateAttachmentUploadUrlV1FilesUploadUrlPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitPlanWorkspaceUploadsV1FilesUploadUrlsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteWorkspaceFileV1FilesFilePathDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDownloadWorkspaceFileV1FilesFilePathGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListSandboxesV1SandboxesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func ok(body any) response { return response{status: http.StatusOK, body: body} }

func (s *Server) ListWorkspaceFilesV1FilesGet(ctx context.Context, _ gen.ListWorkspaceFilesV1FilesGetRequestObject) (gen.ListWorkspaceFilesV1FilesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	l, err := s.svc.ListWorkspace(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	files := make([]any, len(l.Files))
	for i, f := range l.Files {
		files[i] = wirejson.Object{
			{Key: "path", Value: f.Path}, {Key: "size", Value: f.Size},
			{Key: "content_type", Value: f.ContentType}, {Key: "last_modified", Value: f.LastModified},
		}
	}
	dirs := make([]any, len(l.Directories))
	for i, d := range l.Directories {
		dirs[i] = d
	}
	return ok(wirejson.Object{{Key: "files", Value: files}, {Key: "directories", Value: dirs}, {Key: "truncated", Value: l.Truncated}}), nil
}

func (s *Server) CreateWorkspaceDirectoryV1FilesDirectoriesPost(ctx context.Context, _ gen.CreateWorkspaceDirectoryV1FilesDirectoriesPostRequestObject) (gen.CreateWorkspaceDirectoryV1FilesDirectoriesPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	dir, err := s.svc.CreateDirectory(ctx, c.Workspace, c.UserID, inputFrom(ctx).dirPath)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: wirejson.Object{{Key: "path", Value: dir}}}, nil
}

func (s *Server) CreateAttachmentUploadUrlV1FilesUploadUrlPost(ctx context.Context, _ gen.CreateAttachmentUploadUrlV1FilesUploadUrlPostRequestObject) (gen.CreateAttachmentUploadUrlV1FilesUploadUrlPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p := inputFrom(ctx).presign
	out, err := s.svc.PresignAttachment(ctx, c.Workspace, p.filename, p.contentType, p.sha256, p.size)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "ref", Value: out.Ref}, {Key: "upload_url", Value: out.UploadURL}, {Key: "expires_in", Value: out.ExpiresIn}}), nil
}

func plannedJSON(p api.PlannedUpload) wirejson.Object {
	var headers any
	if p.Headers != nil {
		h := wirejson.Object{}
		for _, k := range []string{"Content-Type", "x-amz-checksum-sha256", "x-amz-meta-sha256"} {
			if v, has := p.Headers[k]; has {
				h = append(h, wirejson.Member{Key: k, Value: v})
			}
		}
		headers = h
	}
	return wirejson.Object{
		{Key: "path", Value: p.Path}, {Key: "status", Value: p.Status}, {Key: "upload_url", Value: p.UploadURL},
		{Key: "method", Value: p.Method}, {Key: "headers", Value: headers}, {Key: "expires_in", Value: p.ExpiresIn},
		{Key: "error", Value: p.Error},
	}
}

func (s *Server) PlanWorkspaceUploadsV1FilesUploadUrlsPost(ctx context.Context, _ gen.PlanWorkspaceUploadsV1FilesUploadUrlsPostRequestObject) (gen.PlanWorkspaceUploadsV1FilesUploadUrlsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	planned, err := s.svc.PlanUploads(ctx, c.Workspace, c.UserID, inputFrom(ctx).uploads)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(planned))
	for i, p := range planned {
		out[i] = plannedJSON(p)
	}
	return ok(wirejson.Object{{Key: "uploads", Value: out}}), nil
}

func (s *Server) MoveWorkspaceFileV1FilesMovePost(ctx context.Context, _ gen.MoveWorkspaceFileV1FilesMovePostRequestObject) (gen.MoveWorkspaceFileV1FilesMovePostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	m, err := s.svc.Move(ctx, c.Workspace, c.UserID, in.source, in.destination)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "source", Value: m.Source}, {Key: "destination", Value: m.Destination}, {Key: "moved", Value: m.Count}}), nil
}

func (s *Server) DeleteWorkspaceFileV1FilesFilePathDelete(ctx context.Context, _ gen.DeleteWorkspaceFileV1FilesFilePathDeleteRequestObject) (gen.DeleteWorkspaceFileV1FilesFilePathDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	clean, archived, err := s.svc.Archive(ctx, c.Workspace, c.UserID, inputFrom(ctx).filePath)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "path", Value: clean}, {Key: "archived_path", Value: archived}}), nil
}

func (s *Server) RestoreWorkspaceFileV1FilesRestoreFilePathPost(ctx context.Context, _ gen.RestoreWorkspaceFileV1FilesRestoreFilePathPostRequestObject) (gen.RestoreWorkspaceFileV1FilesRestoreFilePathPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	r, err := s.svc.Restore(ctx, c.Workspace, c.UserID, inputFrom(ctx).filePath)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "path", Value: r.Path}, {Key: "restored_from", Value: r.RestoredFrom}, {Key: "archived_current", Value: r.ArchivedCurrent}}), nil
}

func (s *Server) WorkspaceFileHistoryV1FilesHistoryGet(ctx context.Context, _ gen.WorkspaceFileHistoryV1FilesHistoryGetRequestObject) (gen.WorkspaceFileHistoryV1FilesHistoryGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	clean, evs, err := s.svc.History(ctx, c.Workspace, inputFrom(ctx).historyPath)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(evs))
	for i, e := range evs {
		out[i] = eventJSON(e)
	}
	return ok(wirejson.Object{{Key: "path", Value: clean}, {Key: "events", Value: out}}), nil
}

func eventJSON(e domain.ArtifactEvent) wirejson.Object {
	return wirejson.Object{
		{Key: "action", Value: e.Action}, {Key: "actor_type", Value: e.ActorType}, {Key: "created_by", Value: e.CreatedBy},
		{Key: "agent_id", Value: e.AgentID}, {Key: "task_id", Value: e.TaskID}, {Key: "created_at", Value: service.EventTime(e.CreatedAt)},
	}
}

// stream is the StreamingResponse of a verified body.
type stream struct {
	v        service.Verified
	filename string
}

func (x stream) VisitStreamWorkspaceFileV1FilesDownloadFilePathGetResponse(w http.ResponseWriter) error {
	defer func() { _ = x.v.Body.Close() }()
	h := w.Header()
	for k, vs := range service.DownloadHeaders(x.v.ContentType, x.filename, "file.bin") {
		h[k] = vs
	}
	h.Set("Content-Length", strconv.FormatInt(x.v.Size, 10))
	if ct := x.v.ContentType; ct != "" {
		if strings.HasPrefix(ct, "text/") && !strings.Contains(strings.ToLower(ct), "charset=") {
			ct += "; charset=utf-8"
		}
		h.Set("Content-Type", ct)
	}
	w.WriteHeader(http.StatusOK)
	_, err := io.Copy(w, x.v.Body)
	return err
}

func (s *Server) StreamWorkspaceFileV1FilesDownloadFilePathGet(ctx context.Context, _ gen.StreamWorkspaceFileV1FilesDownloadFilePathGetRequestObject) (gen.StreamWorkspaceFileV1FilesDownloadFilePathGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p := inputFrom(ctx).filePath
	v, err := s.svc.Download(ctx, c.Workspace, p)
	if err != nil {
		return nil, err
	}
	name := domain.PosixName(p)
	if name == "" {
		name = "file.bin"
	}
	return stream{v: v, filename: name}, nil
}

func (s *Server) DownloadWorkspaceFileV1FilesFilePathGet(ctx context.Context, _ gen.DownloadWorkspaceFileV1FilesFilePathGetRequestObject) (gen.DownloadWorkspaceFileV1FilesFilePathGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p := inputFrom(ctx).filePath
	u, err := s.svc.FileURL(ctx, c.Workspace, p)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "url", Value: u}, {Key: "path", Value: p}}), nil
}
