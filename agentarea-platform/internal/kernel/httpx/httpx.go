// Package httpx is the HTTP edge: RFC 9457 problem bodies identical to
// Python's (exceptions/errors.py, handlers.py) including the 422 shape, the
// middleware chain in Python's order (CORS, body size 413 with
// AGENTAREA_API_MAX_BODY, NUL refusal, audit request context), route groups
// (public, principal, /v1/workspaces/{workspace}, A2A host routes ahead of
// paths), pagination, rate limits and the SSE writer.
//
// Bodies are written with wirejson so the bytes equal Starlette's.
package httpx

import (
	"context"
	"net/http"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// ProblemMediaType is the content type of every error body.
const ProblemMediaType = "application/problem+json"

// Codes Python's fixed handlers emit.
const (
	CodeValidation = "validation_error"
	CodeHTTP       = "http_error"
	CodeConflict   = "conflict"
	CodeInternal   = "internal_error"
	CodeNotFound   = "not_found"
	CodePermission = "permission_denied"
	CodeAuth       = "authentication_failed"
	CodeBadRequest = "bad_request"
	CodeMissingCtx = "missing_context"
	CodeNUL        = "nul_character"
)

// Problem is an RFC 9457 body: type, title, status, code, detail, plus
// extension members at the top level, in order, that never overwrite the
// standard ones. Title is Python's HTTPStatus phrase when empty, which
// differs from net/http's in places (422 "Unprocessable Content").
type Problem struct {
	Type       string
	Title      string
	Status     int
	Code       string
	Detail     string
	Extensions wirejson.Object
}

// Title is the status phrase problem_dict uses for status, "Error" for a
// status Python does not know.
func Title(status int) string {
	if p, ok := statusPhrase(status); ok {
		return p
	}
	return "Error"
}

func (p Problem) object() wirejson.Object {
	typ := p.Type
	if typ == "" {
		typ = "about:blank"
	}
	title := p.Title
	if title == "" {
		title = Title(p.Status)
	}
	body := wirejson.Object{
		{Key: "type", Value: typ},
		{Key: "title", Value: title},
		{Key: "status", Value: p.Status},
		{Key: "code", Value: p.Code},
		{Key: "detail", Value: p.Detail},
	}
	for _, m := range p.Extensions {
		body.SetDefault(m.Key, m.Value)
	}
	return body
}

// Body is the problem as Starlette's JSONResponse writes it.
func (p Problem) Body() ([]byte, error) { return wirejson.Marshal(p.object(), wirejson.Compact) }

// MarshalJSON writes the standard members, then the extensions in order.
// encoding/json re-escapes <, > and & in it; write Body to the wire instead.
func (p Problem) MarshalJSON() ([]byte, error) { return p.object().MarshalJSON() }

// WriteProblem writes p with status p.Status and the given extra headers.
// A body that cannot be rendered (a NaN extension) becomes the 500 body.
func WriteProblem(w http.ResponseWriter, p Problem, header http.Header) {
	body, err := p.Body()
	if err != nil {
		p = Problem{Status: http.StatusInternalServerError, Code: CodeInternal, Detail: "Internal Server Error"}
		body, _ = p.Body()
		header = nil
	}
	h := w.Header()
	for k, vs := range header {
		h[k] = append([]string(nil), vs...)
	}
	h.Set("Content-Type", ProblemMediaType)
	h.Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(p.Status)
	_, _ = w.Write(body)
}

// FieldError is one entry of a 422 body's "errors" extension: pydantic's
// error dict without "input" (the echo is dropped, never redacted) and
// without "url" (FastAPI asks pydantic for none).
type FieldError struct {
	Type string
	Loc  []any
	Msg  string
	Ctx  wirejson.Object
}

func (e FieldError) object() wirejson.Object {
	loc := e.Loc
	if loc == nil {
		loc = []any{}
	}
	o := wirejson.Object{{Key: "type", Value: e.Type}, {Key: "loc", Value: loc}, {Key: "msg", Value: e.Msg}}
	if e.Ctx != nil {
		o = append(o, wirejson.Member{Key: "ctx", Value: e.Ctx})
	}
	return o
}

// MarshalJSON writes type, loc, msg and ctx in pydantic's order.
func (e FieldError) MarshalJSON() ([]byte, error) { return e.object().MarshalJSON() }

// Page is PaginatedResponse.
type Page[T any] struct {
	Items    []T  `json:"items"`
	Total    int  `json:"total"`
	Page     int  `json:"page"`
	PageSize int  `json:"page_size"`
	HasNext  bool `json:"has_next"`
}

// Bounds Python applies to paging parameters (422 past them, not a database overflow).
const (
	MaxPage         = 1_000_000
	MaxOffset       = 1_000_000_000
	MaxBigint       = 1<<63 - 1
	MaxPageSize     = 100
	DefaultPageSize = 50
)

// Router registers handlers on a route group; patterns use net/http's
// syntax ("GET /agents/{id}"), and handlers read parameters with
// r.PathValue whichever router serves them.
type Router interface {
	Handle(pattern string, h http.Handler)
}

// Middleware wraps a handler.
type Middleware func(http.Handler) http.Handler

// ErrorMapper turns a typed error of a module into the error the edge
// renders; ok is false for errors it does not know. Each module's
// handlers/errors.go provides one.
type ErrorMapper func(err error) (e *Error, ok bool)

// RateLimiter takes one token from the bucket of (scope, identity): limit
// tokens a minute, refilled continuously (api/rate_limit.py's Lua script).
// retryAfter is whole seconds, at least 1 when refused.
type RateLimiter interface {
	Take(ctx context.Context, scope, identity string, limit int) (allowed bool, retryAfter int, err error)
}
