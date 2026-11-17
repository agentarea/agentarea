package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/domain"
)

// input is what a route's parameters and body validated to, kept in the
// request context for the strict handler.
type input struct {
	filePath    string
	historyPath string
	dirPath     string
	source      string
	destination string
	presign     presign
	uploads     []api.UploadEntry
}

type presign struct {
	filename, contentType, sha256 string
	size                          int64
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's parameters: the {file_path:path} tail, then query,
// then body, in FastAPI's order; every error is reported in one 422.
type request struct {
	filePath bool
	query    func(q url.Values, in *input, errs *[]httpx.FieldError)
	body     func(v any, in *input, errs *[]httpx.FieldError) any
}

// pathTail is Starlette's `.*$` over the decoded path: one trailing newline
// is dropped, any other newline means no route matched.
func pathTail(r *http.Request) (string, bool) {
	raw := chi.URLParam(r, "*")
	if r.URL.RawPath != "" {
		if dec, err := url.PathUnescape(raw); err == nil {
			raw = dec
		}
	}
	raw = strings.TrimSuffix(raw, "\n")
	return raw, !strings.Contains(raw, "\n")
}

func (rq request) middleware(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var fes []httpx.FieldError
			var in input
			if rq.filePath {
				p, ok := pathTail(r)
				if !ok {
					errs.Write(w, r, httpx.HTTPError(http.StatusNotFound, "Not Found"))
					return
				}
				in.filePath = p
			}
			if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
				fes = append(fes, *fe)
			}
			if rq.query != nil {
				rq.query(httpx.Query(r.URL.RawQuery), &in, &fes)
			}
			var canonical any
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				canonical = rq.body(v, &in, &fes)
			}
			if err := httpx.Validation(fes...); err != nil {
				errs.Write(w, r, err)
				return
			}
			if rq.body != nil {
				raw, err := json.Marshal(canonical)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				r.Body = io.NopCloser(bytes.NewReader(raw))
				r.ContentLength = int64(len(raw))
				r.Header.Set("Content-Type", "application/json")
			}
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), inputKey{}, in)))
		})
	}
}

func historyQuery(q url.Values, in *input, errs *[]httpx.FieldError) {
	vs := q["path"]
	if len(vs) == 0 {
		*errs = append(*errs, httpx.Missing("query", "path"))
		return
	}
	in.historyPath = vs[len(vs)-1]
}

// directoryBody is CreateWorkspaceDirectoryRequest (extra="forbid").
func directoryBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	in.dirPath = required(o, "path", 1, errs)
	extraForbidden(o, []string{"path"}, errs)
	return map[string]any{"path": in.dirPath}
}

// moveBody is MoveWorkspaceFileRequest (extra="forbid").
func moveBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	in.source = required(o, "source", 1, errs)
	in.destination = required(o, "destination", 1, errs)
	extraForbidden(o, []string{"source", "destination"}, errs)
	return map[string]any{"source": in.source, "destination": in.destination}
}

// presignBody is PresignUploadRequest (extra="forbid").
func presignBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	p := &in.presign
	p.filename = required(o, "filename", 1, errs)
	p.contentType = required(o, "content_type", 1, errs)
	p.sha256 = required(o, "sha256", 0, errs)
	p.size, _ = intField(o, "size", errs)
	extraForbidden(o, []string{"filename", "content_type", "sha256", "size"}, errs)
	return map[string]any{"filename": p.filename, "content_type": p.contentType, "sha256": p.sha256, "size": p.size}
}

func listLength(typ, words string, limit, actual int, loc ...any) httpx.FieldError {
	key, plural := "max_length", "s"
	if typ == "too_short" {
		key = "min_length"
	}
	if limit == 1 {
		plural = ""
	}
	return httpx.FieldError{
		Type: typ, Loc: loc,
		Msg: "List should have " + words + " " + itoa(limit) + " item" + plural + " after validation, not " + itoa(actual),
		Ctx: wirejson.Object{{Key: "field_type", Value: "List"}, {Key: key, Value: limit}, {Key: "actual_length", Value: actual}},
	}
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
			var entry api.UploadEntry
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
		} else if len(list) > domain.MaxUploadsPerPlan {
			*errs = append(*errs, listLength("too_long", "at most", domain.MaxUploadsPerPlan, len(list), "body", "files"))
		}
	}
	extraForbidden(o, []string{"files"}, errs)
	files := make([]map[string]any, len(in.uploads))
	for i, e := range in.uploads {
		files[i] = map[string]any{"path": e.Path, "sha256": e.SHA256, "content_type": e.ContentType}
	}
	return map[string]any{"files": files}
}
