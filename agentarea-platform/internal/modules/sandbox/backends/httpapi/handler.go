// Package httpapi serves the sandbox control API the platform calls:
// executions, task files, published artifacts, task retirement, inventory and
// the runtime manifest (mcp-manager's sandbox routes).
package httpapi

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxcontrol"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
)

// SandboxPolicy is the part of the sandbox policy the routes enforce.
type SandboxPolicy struct {
	TaskIdleTTL  time.Duration
	MaxFileBytes int64
}

// Secrets are the bearer secrets of the route families; an empty one refuses
// every request of its routes.
type Secrets struct {
	Cleanup string
	Inspect string
	File    string
	Control string
}

// LoadSecrets reads the route secrets.
func LoadSecrets(l *config.Loader) Secrets {
	return Secrets{
		Cleanup: l.StringEnv("AGENTAREA_SANDBOX_CLEANUP_SECRET", ""),
		Inspect: l.StringEnv("AGENTAREA_SANDBOX_INSPECT_SECRET", ""),
		File:    l.StringEnv("AGENTAREA_SANDBOX_FILE_SECRET", ""),
		Control: l.StringEnv("AGENTAREA_SANDBOX_CONTROL_SECRET", ""),
	}
}

// Handler serves the sandbox routes over one composed runtime.
type Handler struct {
	sandboxControl   *sandboxcontrol.Service
	sandboxRuntime   sandboxruntime.ControlRuntime
	sandboxArtifacts sandboxArtifactStore
	logger           *slog.Logger
	sandboxPolicy    SandboxPolicy
	secrets          Secrets
}

// New builds the handler; a control store that cannot be built is a startup
// error, not a service answering 503 for the process lifetime.
func New(runtime sandboxruntime.ControlRuntime, store *sandboxcontrol.RedisStore, controlConfig sandboxcontrol.Config, policy SandboxPolicy, secrets Secrets, logger *slog.Logger) (*Handler, error) {
	if runtime == nil {
		return nil, fmt.Errorf("sandbox control runtime is required")
	}
	control, err := sandboxcontrol.NewService(store, controlConfig.ExecutionPolicy())
	if err != nil {
		return nil, fmt.Errorf("sandbox control service: %w", err)
	}
	return &Handler{sandboxControl: control, sandboxRuntime: runtime, logger: logger, sandboxPolicy: policy, secrets: secrets}, nil
}

// Routes mounts the sandbox routes on mux.
func (h *Handler) Routes(mux *http.ServeMux) {
	handle := func(pattern string, fn func(*reqctx)) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) { fn(&reqctx{Writer: w, Request: r}) })
	}
	handle("GET /runtime/manifest", h.runtimeManifest)
	handle("GET /sandbox/sessions", h.listSandboxes)
	handle("POST /sandbox/executions", h.createSandboxExecution)
	handle("GET /sandbox/executions/{id}", h.getSandboxExecution)
	handle("DELETE /sandbox/executions/{id}", h.cancelSandboxExecution)
	handle("PUT /sandbox/files", h.sandboxFiles)
	handle("GET /sandbox/files", h.sandboxFiles)
	handle("PUT /sandbox/file-content", h.sandboxFileContent)
	handle("GET /sandbox/file-content", h.sandboxFileContent)
	handle("POST /sandbox/artifacts", h.sandboxArtifactsCollection)
	handle("GET /sandbox/artifacts", h.sandboxArtifactsCollection)
	handle("GET /sandbox/artifacts/{id}", h.getSandboxArtifact)
	handle("DELETE /sandbox/task/{id}", h.deleteSandboxTask)
}

func (h *Handler) runtimeManifest(c *reqctx) {
	manifest, err := h.sandboxRuntime.RuntimeManifest(c.Request.Context())
	if err != nil {
		h.logger.Warn("Runtime manifest discovery failed", slog.String("error", err.Error()))
		c.JSON(http.StatusServiceUnavailable, jsonObject{"error": "runtime_manifest_unavailable", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, manifest)
}

type jsonObject map[string]any

// reqctx is one request and its response, with the accessors the routes use.
type reqctx struct {
	Writer  http.ResponseWriter
	Request *http.Request
}

func (c *reqctx) JSON(status int, v any) {
	c.Writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	c.Writer.WriteHeader(status)
	_ = json.NewEncoder(c.Writer).Encode(v)
}

func (c *reqctx) Query(key string) string { return c.Request.URL.Query().Get(key) }

func (c *reqctx) GetQuery(key string) (string, bool) {
	values, ok := c.Request.URL.Query()[key]
	if !ok || len(values) == 0 {
		return "", false
	}
	return values[0], true
}

func (c *reqctx) Param(key string) string { return c.Request.PathValue(key) }

func (c *reqctx) GetHeader(key string) string { return c.Request.Header.Get(key) }

func (c *reqctx) Header(key, value string) { c.Writer.Header().Set(key, value) }

func (c *reqctx) Status(status int) { c.Writer.WriteHeader(status) }

func (c *reqctx) ShouldBindJSON(v any) error {
	if c.Request.Body == nil {
		return fmt.Errorf("invalid request")
	}
	return json.NewDecoder(c.Request.Body).Decode(v)
}

func (c *reqctx) DataFromReader(status int, size int64, contentType string, body io.Reader, headers map[string]string) {
	for k, v := range headers {
		c.Writer.Header().Set(k, v)
	}
	c.Writer.Header().Set("Content-Type", contentType)
	if size >= 0 {
		c.Writer.Header().Set("Content-Length", strconv.FormatInt(size, 10))
	}
	c.Writer.WriteHeader(status)
	_, _ = io.Copy(c.Writer, body)
}
