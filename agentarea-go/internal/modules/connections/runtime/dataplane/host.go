package dataplane

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

// OwnerLabel marks every workload this data plane created; anything without
// it is answered as missing, so a shared host is no lever on other workloads.
const OwnerLabel = "agentarea.io/dataplane-id"

const (
	proxyStartupTimeout = 3 * time.Minute
	pollInterval        = 250 * time.Millisecond
	dialTimeout         = 2 * time.Second
	maxSpecBytes        = 1 << 20
)

// HostConfig is the whole configuration of a data-plane host.
type HostConfig struct {
	ID    string
	Token string
	Addr  string
}

// LoadHostConfig reads AGENTAREA_MCP_DATAPLANE_TOKEN, AGENTAREA_MCP_DATAPLANE_ID
// and AGENTAREA_MCP_DATAPLANE_ADDR. The token has no default and no bypass.
func LoadHostConfig(l *config.Loader) HostConfig {
	token := l.RequiredEnv("AGENTAREA_MCP_DATAPLANE_TOKEN")
	if token != "" && len(token) < minTokenLength {
		l.Fail("AGENTAREA_MCP_DATAPLANE_TOKEN", fmt.Errorf("must be at least %d characters, got %d", minTokenLength, len(token)))
	}
	return HostConfig{
		ID:    l.RequiredEnv("AGENTAREA_MCP_DATAPLANE_ID"),
		Token: token,
		Addr:  l.StringEnv("AGENTAREA_MCP_DATAPLANE_ADDR", ":8090"),
	}
}

type host struct {
	cfg     HostConfig
	backend workload.Backend
	log     *slog.Logger
}

// NewHost serves backend to a remote control plane. /healthz is open; every
// other route sits under /dataplane/v1 behind the bearer token, and so do the
// routes extra registers (patterns relative to /dataplane/v1).
func NewHost(cfg HostConfig, backend workload.Backend, log *slog.Logger, extra func(r httpx.Router) error) (http.Handler, error) {
	if cfg.ID == "" {
		return nil, errors.New("data-plane host needs an id: it marks the workloads it owns")
	}
	if len(cfg.Token) < minTokenLength {
		return nil, fmt.Errorf("data-plane token must be at least %d characters", minTokenLength)
	}
	if backend == nil || log == nil {
		return nil, errors.New("data-plane host needs a backend and a logger")
	}
	h := &host{cfg: cfg, backend: backend, log: log}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "agent_id": cfg.ID})
	})
	r := authed{mux: mux, auth: h.authenticate}
	r.Handle("POST /instances", http.HandlerFunc(h.create))
	r.Handle("GET /reservation", http.HandlerFunc(h.reservation))
	r.Handle("GET /instances/{id}", http.HandlerFunc(h.get))
	r.Handle("DELETE /instances/{id}", http.HandlerFunc(h.delete))
	r.Handle("/instances/{id}/proxy/{path...}", http.HandlerFunc(h.proxy))
	if extra != nil {
		if err := extra(r); err != nil {
			return nil, fmt.Errorf("data-plane host routes: %w", err)
		}
	}
	return mux, nil
}

// authed mounts patterns under /dataplane/v1 behind the token.
type authed struct {
	mux  *http.ServeMux
	auth func(http.Handler) http.Handler
}

func (a authed) Handle(pattern string, h http.Handler) {
	method, path, ok := strings.Cut(pattern, " ")
	if !ok {
		method, path = "", pattern
	}
	full := apiPrefix + "/" + strings.TrimLeft(strings.TrimSpace(path), "/")
	if method != "" {
		full = method + " " + full
	}
	a.mux.Handle(full, a.auth(h))
}

func (h *host) authenticate(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		presented := strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
		if presented == "" || subtle.ConstantTimeCompare([]byte(presented), []byte(h.cfg.Token)) != 1 {
			h.log.Warn("rejected unauthenticated data-plane request", "path", r.URL.Path, "remote_addr", r.RemoteAddr)
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// owned resolves an instance this data plane created. A missing instance and
// another owner's are answered alike, so the API cannot enumerate the host.
func (h *host) owned(w http.ResponseWriter, r *http.Request) (workload.Status, bool) {
	id := r.PathValue("id")
	st, err := h.backend.Status(r.Context(), id)
	if err != nil && !errors.Is(err, workload.ErrNotFound) {
		h.log.Error("data-plane instance lookup failed", "instance_id", id, "error", err)
		writeError(w, http.StatusInternalServerError, err.Error())
		return workload.Status{}, false
	}
	if err != nil || st.Labels[OwnerLabel] != h.cfg.ID {
		writeError(w, http.StatusNotFound, "instance not found")
		return workload.Status{}, false
	}
	return st, true
}

func (h *host) create(w http.ResponseWriter, r *http.Request) {
	var spec workload.Spec
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxSpecBytes))
	if err := dec.Decode(&spec); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid instance spec: %v", err))
		return
	}
	if strings.TrimSpace(spec.ServiceName) == "" {
		writeError(w, http.StatusBadRequest, "instance spec requires a service_name")
		return
	}
	if spec.Labels == nil {
		spec.Labels = make(map[string]string, 1)
	}
	spec.Labels[OwnerLabel] = h.cfg.ID
	st, err := h.backend.Create(r.Context(), spec)
	if err != nil {
		h.log.Error("data plane failed to create instance", "instance_id", spec.InstanceID, "error", err)
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	h.log.Info("data plane created instance", "instance_id", spec.InstanceID, "image", spec.Image, "runtime_class", spec.RuntimeClass)
	writeJSON(w, http.StatusCreated, st)
}

func (h *host) reservation(w http.ResponseWriter, r *http.Request) {
	res, err := h.backend.Reservation(r.Context())
	if err != nil {
		h.log.Error("data plane failed to report its reservation", "error", err)
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
}

func (h *host) get(w http.ResponseWriter, r *http.Request) {
	if st, ok := h.owned(w, r); ok {
		writeJSON(w, http.StatusOK, st)
	}
}

func (h *host) delete(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.owned(w, r); !ok {
		return
	}
	id := r.PathValue("id")
	if err := h.backend.Delete(r.Context(), id); err != nil {
		h.log.Error("data plane failed to delete instance", "instance_id", id, "error", err)
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	h.log.Info("data plane deleted instance", "instance_id", id)
	w.WriteHeader(http.StatusNoContent)
}

// proxy forwards to the workload's own port, so the token that gates
// management gates traffic too and no per-instance port is published.
func (h *host) proxy(w http.ResponseWriter, r *http.Request) {
	st, ok := h.owned(w, r)
	if !ok {
		return
	}
	id := r.PathValue("id")
	st, err := h.awaitServing(r.Context(), id, st)
	if err != nil {
		h.log.Error("data-plane instance is not serving a proxied call", "instance_id", id, "error", err)
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	target, err := url.Parse(st.InternalURL)
	if err != nil || target.Host == "" {
		writeError(w, http.StatusBadGateway, fmt.Sprintf("instance %s reports no usable address (%q)", id, st.InternalURL))
		return
	}
	forward := "/" + r.PathValue("path")
	reverse := &httputil.ReverseProxy{
		FlushInterval: -1,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.Out.URL.Path, pr.Out.URL.RawPath = forward, ""
			pr.Out.URL.RawQuery = r.URL.RawQuery
			pr.Out.Host = target.Host
			pr.Out.Header.Del("Authorization")
		},
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			h.log.Error("proxying to data-plane instance failed", "instance_id", id, "target", target.String(), "error", err)
			writeError(w, http.StatusBadGateway, "proxying to instance failed: "+err.Error())
		},
	}
	reverse.ServeHTTP(w, r)
}

// awaitServing waits for a starting workload to run with an address and for
// its process to accept a connection: "running" is the container's state, not
// the server's. A stopped workload is the control plane's to recreate.
func (h *host) awaitServing(ctx context.Context, id string, st workload.Status) (workload.Status, error) {
	deadline := time.Now().Add(proxyStartupTimeout)
	for {
		switch {
		case st.Status == workload.StatusRunning && st.InternalURL != "":
			return st, waitListening(ctx, st.InternalURL, deadline)
		case st.Status == workload.StatusStopped:
			return workload.Status{}, fmt.Errorf("instance %s is stopped", id)
		case time.Now().After(deadline):
			return workload.Status{}, fmt.Errorf("instance %s did not report a usable address within %s", id, proxyStartupTimeout)
		}
		select {
		case <-ctx.Done():
			return workload.Status{}, ctx.Err()
		case <-time.After(pollInterval):
		}
		next, err := h.backend.Status(ctx, id)
		if err != nil {
			return workload.Status{}, fmt.Errorf("inspect instance %s: %w", id, err)
		}
		st = next
	}
}

func waitListening(ctx context.Context, internalURL string, deadline time.Time) error {
	target, err := url.Parse(internalURL)
	if err != nil || target.Host == "" {
		return fmt.Errorf("instance address %q is not usable", internalURL)
	}
	dialer := &net.Dialer{Timeout: dialTimeout}
	for {
		conn, err := dialer.DialContext(ctx, "tcp", target.Host)
		if err == nil {
			return conn.Close()
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("instance at %s never accepted a connection: %w", target.Host, err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(pollInterval):
		}
	}
}
