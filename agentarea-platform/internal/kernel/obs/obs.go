// Package obs is logging, tracing and metrics: JSON log lines with the
// fields and order of Python's WorkspaceContextFormatter (logging/config.py),
// its secret-redacting and sanitizing filters (filters.py), trace ids from
// the active span, and the instrument table of ADR-0048
// (observability/telemetry.py, plus the mcp-manager and event-service
// instruments that fold in). One OpenTelemetry setup per process, gated by
// AGENTAREA_OTEL_ENABLED, lives in profiles/cluster/obs.
package obs

import (
	"context"
	"log/slog"
)

// Log line keys shared with the Python JSON formatter, so one log query
// finds both backends' lines. timestamp, level, logger and message come
// first, then user_id, workspace_id, trace_id, span_id, exception, then
// every other attribute in the order it was added.
const (
	KeyTimestamp   = "timestamp"
	KeyLevel       = "level"
	KeyLogger      = "logger"
	KeyMessage     = "message"
	KeyUserID      = "user_id"
	KeyWorkspaceID = "workspace_id"
	KeyTraceID     = "trace_id"
	KeySpanID      = "span_id"
	KeyException   = "exception"
	KeyTaskID      = "task_id"
)

// LevelCritical is Python's CRITICAL.
const LevelCritical = slog.Level(12)

// Telemetry is the process's OpenTelemetry setup; Shutdown flushes it.
type Telemetry interface {
	Shutdown(ctx context.Context) error
}

// Redactor masks secret-looking values before a record is written.
type Redactor interface {
	Redact(key string, value slog.Value) slog.Value
}

// Logging builds the process's loggers: level from AGENTAREA_LOG_LEVEL,
// format from AGENTAREA_LOG_FORMAT, the Redactor applied, trace ids and
// workspace context from ctx. component is the "logger" field.
type Logging interface {
	Logger(component string) *slog.Logger
}

type requestKey struct{}

type requestContext struct{ workspaceID, userID string }

// WithRequest returns ctx carrying the workspace and user a request acts
// for; every line logged with it names them, as the WorkspaceContextFilter
// and the error handler's extra= did.
func WithRequest(ctx context.Context, workspaceID, userID string) context.Context {
	return context.WithValue(ctx, requestKey{}, requestContext{workspaceID: workspaceID, userID: userID})
}

// RequestFrom returns the workspace and user WithRequest stored.
func RequestFrom(ctx context.Context) (workspaceID, userID string, ok bool) {
	rc, ok := ctx.Value(requestKey{}).(requestContext)
	return rc.workspaceID, rc.userID, ok
}
