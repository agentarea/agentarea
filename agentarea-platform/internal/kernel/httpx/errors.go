package httpx

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Error is an error the edge renders as a problem: Python's AppError and
// its subclasses, and Starlette's HTTPException (HTTPError).
type Error struct {
	Status     int
	Code       string
	Title      string
	Detail     string
	Extensions wirejson.Object
	Header     http.Header
	// plain is an HTTPException: it carries only its own headers, where an
	// AppError 401 also gets the bearer challenge (handlers.py:107-114).
	plain bool
	cause error
}

func (e *Error) Error() string { return e.Detail }

func (e *Error) Unwrap() error { return e.cause }

// Problem is the body e renders.
func (e *Error) Problem() Problem {
	return Problem{Title: e.Title, Status: e.Status, Code: e.Code, Detail: e.Detail, Extensions: e.Extensions}
}

// With adds an extension member (problem_response's extra=).
func (e *Error) With(key string, value any) *Error {
	e.Extensions = append(e.Extensions, wirejson.Member{Key: key, Value: value})
	return e
}

// WithHeader adds a response header.
func (e *Error) WithHeader(key, value string) *Error {
	if e.Header == nil {
		e.Header = http.Header{}
	}
	e.Header.Add(key, value)
	return e
}

// Wrap records the error e stands for, for logs and errors.Is.
func (e *Error) Wrap(cause error) *Error {
	e.cause = cause
	return e
}

// NewError is AppError(detail, status_code=, code=): an empty detail falls
// back to the status phrase.
func NewError(status int, code, detail string) *Error {
	if detail == "" {
		detail = Title(status)
	}
	return &Error{Status: status, Code: code, Detail: detail}
}

// NewTitledError is AppError with a title: an empty detail falls back to it.
func NewTitledError(status int, code, title, detail string) *Error {
	if detail == "" {
		detail = title
	}
	e := NewError(status, code, detail)
	e.Title = title
	return e
}

// BadRequest is BadRequestError (400 bad_request).
func BadRequest(detail string) *Error { return NewError(http.StatusBadRequest, CodeBadRequest, detail) }

// Unauthorized is AuthenticationError (401 authentication_failed, bearer challenge).
func Unauthorized(detail string) *Error {
	return NewError(http.StatusUnauthorized, CodeAuth, detail)
}

// Forbidden is PermissionDeniedError (403 permission_denied).
func Forbidden(detail string) *Error {
	return NewError(http.StatusForbidden, CodePermission, detail)
}

// NotFound is NotFoundError (404 not_found).
func NotFound(detail string) *Error { return NewError(http.StatusNotFound, CodeNotFound, detail) }

// Conflict is ConflictError (409 conflict).
func Conflict(detail string) *Error { return NewError(http.StatusConflict, CodeConflict, detail) }

// HTTPError is Starlette's HTTPException(status_code, detail): code
// http_error, the status phrase when detail is empty, no challenge added.
func HTTPError(status int, detail string) *Error {
	e := NewError(status, CodeHTTP, detail)
	e.plain = true
	return e
}

// PermissionError is Python's builtin PermissionError raised by a
// write-protection layer: 403 permission_denied.
type PermissionError struct{ Msg string }

func (e *PermissionError) Error() string {
	if e.Msg == "" {
		return "You do not have permission to perform this action"
	}
	return e.Msg
}

// ValidationError is FastAPI's RequestValidationError: 422 with the field
// errors as the "errors" extension.
type ValidationError struct{ Errors []FieldError }

func (e *ValidationError) Error() string {
	msgs := make([]string, len(e.Errors))
	for i, f := range e.Errors {
		msgs[i] = fmt.Sprintf("%v: %s", f.Loc, f.Msg)
	}
	return "request validation failed: " + strings.Join(msgs, "; ")
}

// Validation returns a *ValidationError for errs, nil when there is none.
func Validation(errs ...FieldError) error {
	if len(errs) == 0 {
		return nil
	}
	return &ValidationError{Errors: errs}
}

// ErrBodyTooLarge is returned by a request body read past AGENTAREA_API_MAX_BODY.
var ErrBodyTooLarge = errors.New("request body too large")

// sqlStateError is pgconn.PgError's view of a database error.
type sqlStateError interface {
	error
	SQLState() string
}

// Errors renders an error a handler returns, as handlers.py does: module
// mappers first, then the fixed set (AppError, PermissionError, validation,
// HTTPException, integrity violations), then the catch-all 500.
type Errors struct {
	mappers   []ErrorMapper
	challenge string
	log       *slog.Logger
}

// NewErrors builds the renderer. apiURL is AGENTAREA_API_URL, which names
// the RFC 9728 metadata in a 401's WWW-Authenticate.
func NewErrors(apiURL string, log *slog.Logger, mappers ...ErrorMapper) *Errors {
	return &Errors{
		mappers:   mappers,
		challenge: `Bearer resource_metadata="` + strings.TrimRight(apiURL, "/") + `/.well-known/oauth-protected-resource"`,
		log:       log,
	}
}

// Resolve is the error a handler's err renders as, and whether it is the
// catch-all (an error nothing maps).
func (x *Errors) Resolve(err error) (*Error, bool) {
	for _, m := range x.mappers {
		if e, ok := m(err); ok && e != nil {
			return e, false
		}
	}
	if e, ok := errors.AsType[*Error](err); ok {
		return e, false
	}
	if e, ok := errors.AsType[*scope.AccessDeniedError](err); ok {
		return NotFound(scope.AccessDeniedSafeDetail).Wrap(e), false
	}
	if e, ok := errors.AsType[*scope.MissingContextError](err); ok {
		return NewError(http.StatusBadRequest, CodeMissingCtx, e.SafeDetail()).Wrap(e), false
	}
	if e, ok := errors.AsType[*PermissionError](err); ok {
		return Forbidden(e.Error()).Wrap(e), false
	}
	if e, ok := errors.AsType[*ValidationError](err); ok {
		v := NewError(http.StatusUnprocessableEntity, CodeValidation, "Request validation failed").Wrap(e)
		return v.With("errors", e.Errors), false
	}
	if errors.Is(err, ErrBodyTooLarge) {
		return HTTPError(http.StatusRequestEntityTooLarge, "Request body too large").Wrap(err), false
	}
	if e, ok := errors.AsType[sqlStateError](err); ok && strings.HasPrefix(e.SQLState(), "23") {
		// IntegrityError: unique and foreign key violations are 409, the
		// rest (not-null) a server bug (handlers.py:30,171-189).
		if s := e.SQLState(); s == "23505" || s == "23503" {
			return Conflict("The request conflicts with the current state of the resource").Wrap(err), false
		}
		return NewError(http.StatusInternalServerError, CodeInternal, "Internal Server Error").Wrap(err), false
	}
	return NewError(http.StatusInternalServerError, CodeInternal, "Internal Server Error").Wrap(err), true
}

// Write renders err on w. The catch-all 500 is written as Starlette's
// ServerErrorMiddleware writes it, outside CORS: it carries no CORS headers.
func (x *Errors) Write(w http.ResponseWriter, r *http.Request, err error) {
	if v := paramValidation(r, err); v != nil {
		err = v
	}
	e, unhandled := x.Resolve(err)
	x.logError(r, err, e.Status, e.Status >= http.StatusInternalServerError)
	header := e.Header.Clone()
	if e.Status == http.StatusUnauthorized && !e.plain && header.Get("WWW-Authenticate") == "" {
		if header == nil {
			header = http.Header{}
		}
		header.Set("WWW-Authenticate", x.challenge)
	}
	if unhandled {
		markOutsideCORS(r.Context())
	}
	WriteProblem(w, e.Problem(), header)
}

// Handler adapts a handler that returns an error.
func (x *Errors) Handler(h func(w http.ResponseWriter, r *http.Request) error) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := h(w, r); err != nil {
			x.Write(w, r, err)
		}
	})
}

// logLevel is _log_level_for: 5xx ERROR, 401/403/404 INFO, else WARNING.
func logLevel(status int) slog.Level {
	switch {
	case status >= 500:
		return slog.LevelError
	case status == http.StatusUnauthorized || status == http.StatusForbidden || status == http.StatusNotFound:
		return slog.LevelInfo
	default:
		return slog.LevelWarn
	}
}

// logError is _log_error: one line per failed request with its context.
func (x *Errors) logError(r *http.Request, err error, status int, withCause bool) {
	if x.log == nil {
		return
	}
	typ := errorType(err)
	attrs := []slog.Attr{
		slog.String("error_type", typ),
		slog.String("error_message", err.Error()),
		slog.String("request_method", r.Method),
		slog.String("request_path", r.URL.Path),
	}
	if e, ok := errors.AsType[*scope.AccessDeniedError](err); ok {
		attrs = append(attrs, slog.String("resource_type", e.ResourceType), slog.String("resource_id", e.ResourceID))
	}
	if e, ok := errors.AsType[*scope.MissingContextError](err); ok {
		attrs = append(attrs, slog.String("missing_field", e.Field))
	}
	if withCause {
		attrs = append(attrs, slog.String(obs.KeyException, fmt.Sprintf("%+v", err)))
	}
	x.log.LogAttrs(r.Context(), logLevel(status), "Request failed: "+typ, attrs...)
}

func errorType(err error) string {
	t := fmt.Sprintf("%T", err)
	t = strings.TrimLeft(t, "*")
	if i := strings.LastIndexByte(t, '.'); i >= 0 {
		t = t[i+1:]
	}
	return t
}

type edgeStateKey struct{}

// edgeState is what the outer middleware learns from the inner layers.
type edgeState struct{ outsideCORS bool }

func withEdgeState(ctx context.Context) (context.Context, *edgeState) {
	st := &edgeState{}
	return context.WithValue(ctx, edgeStateKey{}, st), st
}

func markOutsideCORS(ctx context.Context) {
	if st, ok := ctx.Value(edgeStateKey{}).(*edgeState); ok {
		st.outsideCORS = true
	}
}
