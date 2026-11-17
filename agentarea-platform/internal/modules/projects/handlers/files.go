package handlers

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/projects"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// MaxUploadsPerPlan is MAX_UPLOADS_PER_PLAN (workspace_writes.py).
const MaxUploadsPerPlan = 100

func listLength(typ, words string, limit, actual int, loc ...any) httpx.FieldError {
	return httpx.FieldError{
		Type: typ, Loc: loc,
		Msg: fmt.Sprintf("List should have %s %d item%s after validation, not %d", words, limit, map[bool]string{true: "", false: "s"}[limit == 1], actual),
		Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: words2key(typ), Value: limit}, {Key: "actual_length", Value: actual}},
	}
}

func words2key(typ string) string {
	if typ == "too_short" {
		return "min_length"
	}
	return "max_length"
}

// uploadPlanBody is UploadPlanRequest (extra="forbid") of UploadPlanEntry.
func uploadPlanBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	raw, present := o.Get("files")
	list, isList := raw.([]any)
	switch {
	case !present:
		*errs = append(*errs, httpx.Missing("body", "files"))
	case !isList:
		*errs = append(*errs, httpx.ListType("body", "files"))
	default:
		for i, item := range list {
			e, isObj := item.(wirejson.Object)
			if !isObj {
				*errs = append(*errs, httpx.ModelAttributesType("body", "files", i))
				continue
			}
			var entry sandboxapi.UploadEntry
			for _, f := range []struct {
				key string
				dst *string
			}{{"path", &entry.Path}, {"sha256", &entry.SHA256}} {
				fv, has := e.Get(f.key)
				s, isStr := fv.(string)
				switch {
				case !has:
					*errs = append(*errs, httpx.Missing("body", "files", i, f.key))
				case !isStr:
					*errs = append(*errs, httpx.StringType("body", "files", i, f.key))
				default:
					*f.dst = s
				}
			}
			if ct, has := e.Get("content_type"); has && ct != nil {
				if s, isStr := ct.(string); isStr {
					entry.ContentType = &s
				} else {
					*errs = append(*errs, httpx.StringType("body", "files", i, "content_type"))
				}
			}
			in.uploads = append(in.uploads, entry)
		}
		if len(list) < 1 {
			*errs = append(*errs, listLength("too_short", "at least", 1, len(list), "body", "files"))
		} else if len(list) > MaxUploadsPerPlan {
			*errs = append(*errs, listLength("too_long", "at most", MaxUploadsPerPlan, len(list), "body", "files"))
		}
	}
	extraForbidden(o, []string{"files"}, errs)
	files := make([]map[string]any, len(in.uploads))
	for i, e := range in.uploads {
		files[i] = map[string]any{"path": e.Path, "sha256": e.SHA256, "content_type": e.ContentType}
	}
	return map[string]any{"files": files}
}

func plannedJSON(p sandboxapi.PlannedUpload) wirejson.Object {
	var headers any
	if p.Headers != nil {
		h := wirejson.Object{}
		for k, v := range p.Headers {
			h = append(h, wirejson.Member{Key: k, Value: v})
		}
		headers = h
	}
	return wirejson.Object{
		{Key: "path", Value: p.Path}, {Key: "status", Value: p.Status}, {Key: "upload_url", Value: p.UploadURL},
		{Key: "method", Value: p.Method}, {Key: "headers", Value: headers}, {Key: "expires_in", Value: p.ExpiresIn},
		{Key: "error", Value: p.Error},
	}
}

func (s *Server) PlanProjectUploadsV1ProjectsProjectIdFilesUploadUrlsPost(ctx context.Context, rq gen.PlanProjectUploadsV1ProjectsProjectIdFilesUploadUrlsPostRequestObject) (gen.PlanProjectUploadsV1ProjectsProjectIdFilesUploadUrlsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	planned, err := s.svc.PlanUploads(ctx, c.Workspace, c.UserID, rq.ProjectId, inputFrom(ctx).uploads)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(planned))
	for i, p := range planned {
		out[i] = plannedJSON(p)
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "uploads", Value: out}}}, nil
}

func (s *Server) ListProjectFilesV1ProjectsProjectIdFilesGet(ctx context.Context, rq gen.ListProjectFilesV1ProjectsProjectIdFilesGetRequestObject) (gen.ListProjectFilesV1ProjectsProjectIdFilesGetResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	files, err := s.svc.ListFiles(ctx, ws, rq.ProjectId)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(files))
	for i, f := range files {
		out[i] = wirejson.Object{{Key: "path", Value: f.Path}, {Key: "size", Value: f.Size}, {Key: "last_modified", Value: f.LastModified}}
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "files", Value: out}}}, nil
}

// stream is the StreamingResponse of one buffered chunk.
type stream struct {
	file    sandboxapi.File
	headers http.Header
}

func (x stream) VisitStreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetResponse(w http.ResponseWriter) error {
	for k, vs := range x.headers {
		w.Header()[k] = vs
	}
	ct := x.file.ContentType
	if strings.HasPrefix(ct, "text/") && !strings.Contains(strings.ToLower(ct), "charset") {
		ct += "; charset=utf-8"
	}
	w.Header().Set("Content-Type", ct)
	w.WriteHeader(http.StatusOK)
	_, err := w.Write(x.file.Data)
	return err
}

func (s *Server) StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGet(ctx context.Context, rq gen.StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetRequestObject) (gen.StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGetResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	f, headers, err := s.svc.Download(ctx, ws, rq.ProjectId, rq.FilePath)
	if err != nil {
		return nil, err
	}
	return stream{file: f, headers: headers}, nil
}

func (s *Server) DownloadProjectFileV1ProjectsProjectIdFilesFilePathGet(ctx context.Context, rq gen.DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetRequestObject) (gen.DownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	u, err := s.svc.FileURL(ctx, ws, rq.ProjectId, rq.FilePath)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "url", Value: u}, {Key: "path", Value: rq.FilePath}}}, nil
}

func (s *Server) DeleteProjectFileV1ProjectsProjectIdFilesFilePathDelete(ctx context.Context, rq gen.DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteRequestObject) (gen.DeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteFile(ctx, c.Workspace, c.UserID, rq.ProjectId, rq.FilePath); err != nil {
		return nil, err
	}
	return noContent(), nil
}
