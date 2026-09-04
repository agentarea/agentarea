// Package dataplane runs the manager binary as a data plane.
//
// The same binary is the control plane in its normal mode: it holds the
// database, Redis, secret-manager and policy wiring. None of that belongs on a
// host that also runs untrusted MCP containers, because the container runtime
// there is the trust boundary. Data-plane mode is the other half of that split — the
// process keeps only a container backend and answers a narrow HTTP API, so a
// compromised host yields container control and nothing else.
//
// What data-plane mode deliberately does NOT construct: no database, no Redis, no
// secret resolver, no event bus, no sandbox runtime, no provider manager. The
// caller sends a fully-resolved InstanceSpec; the data plane never learns where the
// values came from.
package dataplane

import (
	"context"
	"crypto/subtle"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// OwnerLabel marks every instance this data plane created. Operations on anything
// without it are refused: a data plane sharing a host with other workloads must not
// become a lever for touching them.
const OwnerLabel = "agentarea.io/dataplane-id"

// startupTimeout bounds how long a proxied call waits for a cold instance.
// Generous because an MCP image that installs on boot takes far longer than one
// that is already built.
const startupTimeout = 3 * time.Minute

// ErrDisabled reports that agent mode was not requested.
var ErrDisabled = errors.New("data-plane mode not enabled")

// Config is the whole of the agent's configuration. Its smallness is the point.
type Config struct {
	// ID names this data plane. It is stamped on created instances and is
	// what makes ownership checkable after a restart.
	AgentID string
	// AuthToken gates every instance route. Required — see ConfigFromEnv.
	AuthToken string
	// ListenAddr is where the agent serves.
	ListenAddr string
}

// ConfigFromEnv reads agent configuration, refusing anything half-specified.
//
// The token has no default and no development bypass. A data plane reachable
// without one hands container creation on a gVisor host to whoever finds the
// port, so starting without it is never the more helpful outcome.
func ConfigFromEnv() (*Config, error) {
	if !Enabled() {
		return nil, ErrDisabled
	}

	token := os.Getenv("MCP_DATAPLANE_AUTH_TOKEN")
	if token == "" {
		return nil, errors.New("MCP_DATAPLANE_AUTH_TOKEN is required in data-plane mode")
	}
	if len(token) < 32 {
		return nil, fmt.Errorf("MCP_DATAPLANE_AUTH_TOKEN must be at least 32 characters, got %d", len(token))
	}

	agentID := os.Getenv("MCP_DATAPLANE_ID")
	if agentID == "" {
		return nil, errors.New("MCP_DATAPLANE_ID is required in data-plane mode: it is what marks this data plane's instances as its own")
	}

	listen := os.Getenv("MCP_DATAPLANE_LISTEN_ADDR")
	if listen == "" {
		listen = ":8090"
	}

	return &Config{AgentID: agentID, AuthToken: token, ListenAddr: listen}, nil
}

// Enabled reports whether the process was asked to run as a data plane.
func Enabled() bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("MCP_MANAGER_MODE")), "dataplane")
}

// Server exposes a container backend over HTTP for a remote control plane.
type Server struct {
	cfg     *Config
	backend backends.Backend
	logger  *slog.Logger
}

func NewServer(cfg *Config, backend backends.Backend, logger *slog.Logger) *Server {
	return &Server{cfg: cfg, backend: backend, logger: logger}
}

// Routes registers the data-plane API. Liveness is deliberately outside the
// authenticated group so an orchestrator can probe without holding the token.
func (s *Server) Routes(router gin.IRouter) {
	router.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "agent_id": s.cfg.AgentID})
	})

	group := router.Group("/dataplane/v1", s.authenticate)
	group.POST("/instances", s.createInstance)
	group.GET("/instances", s.listInstances)
	group.GET("/instances/:id", s.getInstance)
	group.DELETE("/instances/:id", s.deleteInstance)
	group.GET("/instances/:id/health", s.healthCheck)
	group.Any("/instances/:id/proxy/*path", s.proxy)
}

// instanceStarter is implemented by backends that can restart an instance whose
// container still exists. Optional on purpose: a backend without it still
// serves traffic to running instances, and says so plainly when asked to wake
// a stopped one.
type instanceStarter interface {
	StartInstance(ctx context.Context, instanceID string) error
}

// proxy forwards a request to the instance's own port.
//
// This is what makes the data plane usable rather than merely controllable.
// Without it a control plane can start and stop containers on this host but
// cannot reach them: they sit on a Docker network that only this host resolves,
// and publishing a port per instance would put an unauthenticated door to each
// one on a machine that also runs production workloads. Routing through here
// means the token that already gates management gates traffic too, and the
// ownership check applies to both.
func (s *Server) proxy(c *gin.Context) {
	status, ok := s.requireOwned(c)
	if !ok {
		return
	}

	status, err := s.ensureRunning(c, status)
	if err != nil {
		s.logger.Error("Failed to bring instance up for a proxied call",
			slog.String("instance_id", c.Param("id")),
			slog.String("error", err.Error()),
		)
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}

	target, err := url.Parse(status.InternalURL)
	if err != nil || target.Host == "" {
		c.JSON(http.StatusBadGateway, gin.H{
			"error": fmt.Sprintf("instance %s reports no usable address (%q)", c.Param("id"), status.InternalURL),
		})
		return
	}

	forwardPath := c.Param("path")
	if forwardPath == "" {
		forwardPath = "/"
	}

	reverse := &httputil.ReverseProxy{
		// -1 flushes each write straight through. MCP's Streamable HTTP answers
		// over SSE, and any buffering here turns a live stream into a response
		// that arrives only when the server is done.
		FlushInterval: -1,
		Rewrite: func(r *httputil.ProxyRequest) {
			r.SetURL(target)
			r.Out.URL.Path = forwardPath
			r.Out.URL.RawQuery = c.Request.URL.RawQuery
			r.Out.Host = target.Host
			// Our credential ends here. The MCP server has no use for it, and
			// forwarding it would hand this host's key to third-party code.
			r.Out.Header.Del("Authorization")
		},
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			s.logger.Error("Proxying to instance failed",
				slog.String("instance_id", c.Param("id")),
				slog.String("target", target.String()),
				slog.String("error", err.Error()),
			)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			// An empty 502 reads as "the proxy is broken". Saying which hop
			// failed is the difference between debugging this and guessing.
			fmt.Fprintf(w, `{"error":%q}`, "proxying to instance failed: "+err.Error())
		},
	}

	reverse.ServeHTTP(c.Writer, c.Request)
}

// ensureRunning starts a stopped instance and waits for it to report an address.
//
// A caller that reaches a reclaimed instance should pay a cold start, not get an
// error: that is the whole point of stopping idle containers instead of deleting
// them.
func (s *Server) ensureRunning(c *gin.Context, status *backends.InstanceStatus) (*backends.InstanceStatus, error) {
	deadline := time.Now().Add(startupTimeout)

	// "Running" is the container's state, not the server's, so this branch waits
	// for the socket as well. A create returns as soon as the container runs and
	// has an address, which is before the process inside has bound: without the
	// wait, the very first request after a create proxied into that window and
	// came back as a bare 502 -- the shape of a broken instance, on a workload
	// that was seconds away from serving. A warm instance pays one local dial.
	if status.Status == "running" && status.InternalURL != "" {
		if err := waitForListener(c.Request.Context(), status.InternalURL, deadline); err != nil {
			return nil, err
		}
		return status, nil
	}

	instanceID := c.Param("id")
	if status.Status != "running" {
		starter, ok := s.backend.(instanceStarter)
		if !ok {
			return nil, fmt.Errorf("instance %s is %s and this backend cannot start it", instanceID, status.Status)
		}
		s.logger.Info("Starting instance for a proxied call",
			slog.String("instance_id", instanceID),
			slog.String("status", status.Status),
		)
		if err := starter.StartInstance(c.Request.Context(), instanceID); err != nil {
			return nil, err
		}
	}

	// An address appears only once the runtime has attached the container to the
	// network, so a started instance is polled for one before it is dialled.
	for {
		refreshed, err := s.backend.GetInstanceStatus(c.Request.Context(), instanceID)
		if err == nil && refreshed.Status == "running" && refreshed.InternalURL != "" {
			if err := waitForListener(c.Request.Context(), refreshed.InternalURL, deadline); err != nil {
				return nil, err
			}
			return refreshed, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("instance %s did not report a usable address within %s", instanceID, startupTimeout)
		}
		select {
		case <-c.Request.Context().Done():
			return nil, c.Request.Context().Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
}

// waitForListener blocks until the instance is accepting connections.
//
// "Running" is the container's state, not the server's. A freshly started MCP
// image reports running while its process is still binding, and proxying into
// that window returns a bare connection-refused to the caller — indistinguishable
// from a broken instance.
func waitForListener(ctx context.Context, internalURL string, deadline time.Time) error {
	target, err := url.Parse(internalURL)
	if err != nil || target.Host == "" {
		return fmt.Errorf("instance address %q is not usable", internalURL)
	}

	dialer := &net.Dialer{Timeout: 2 * time.Second}
	for {
		conn, err := dialer.DialContext(ctx, "tcp", target.Host)
		if err == nil {
			conn.Close()
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("instance at %s never accepted a connection: %w", target.Host, err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
}

// authenticate compares the bearer token in constant time.
func (s *Server) authenticate(c *gin.Context) {
	header := c.GetHeader("Authorization")
	presented := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	if presented == "" || subtle.ConstantTimeCompare([]byte(presented), []byte(s.cfg.AuthToken)) != 1 {
		s.logger.Warn("Rejected unauthenticated data-plane request",
			slog.String("path", c.Request.URL.Path),
			slog.String("remote_addr", c.ClientIP()),
		)
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	c.Next()
}

// owns reports whether an instance carries this data plane's label.
//
// A missing instance and an instance belonging to someone else are answered
// identically by the callers, so probing this endpoint cannot enumerate what
// else runs on the host.
func (s *Server) owns(status *backends.InstanceStatus) bool {
	if status == nil {
		return false
	}
	return status.Labels[OwnerLabel] == s.cfg.AgentID
}

// requireOwned resolves an instance and refuses it unless this data plane created it.
func (s *Server) requireOwned(c *gin.Context) (*backends.InstanceStatus, bool) {
	id := c.Param("id")
	status, err := s.backend.GetInstanceStatus(c.Request.Context(), id)
	if err != nil || !s.owns(status) {
		if err != nil {
			s.logger.Debug("Instance lookup failed", slog.String("instance_id", id), slog.String("error", err.Error()))
		}
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "instance not found"})
		return nil, false
	}
	return status, true
}

func (s *Server) createInstance(c *gin.Context) {
	var spec backends.InstanceSpec
	if err := c.ShouldBindJSON(&spec); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("invalid instance spec: %v", err)})
		return
	}

	// A backend keys its instances by service name. Accepting a spec without one
	// creates a container that no later request can name: inspection, health,
	// proxy, and delete all resolve an id to a service name first, and an empty
	// result is indistinguishable from "no such instance". The workload would run
	// with no way to reach or retire it through this API. Refuse it at the edge
	// rather than leave the host holding something unaddressable.
	if strings.TrimSpace(spec.ServiceName) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "instance spec requires a service_name"})
		return
	}

	// Stamped after binding so a caller cannot claim another agent's instances
	// by sending the label itself.
	if spec.Labels == nil {
		spec.Labels = make(map[string]string, 1)
	}
	spec.Labels[OwnerLabel] = s.cfg.AgentID

	result, err := s.backend.CreateInstance(c.Request.Context(), &spec)
	if err != nil {
		s.logger.Error("Data plane failed to create instance",
			slog.String("instance_id", spec.InstanceID),
			slog.String("error", err.Error()),
		)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	s.logger.Info("Data plane created instance",
		slog.String("instance_id", spec.InstanceID),
		slog.String("image", spec.Image),
		slog.String("runtime_class", spec.RuntimeClass),
	)
	c.JSON(http.StatusCreated, result)
}

func (s *Server) listInstances(c *gin.Context) {
	all, err := s.backend.ListInstances(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	owned := make([]*backends.InstanceStatus, 0, len(all))
	for _, status := range all {
		if s.owns(status) {
			owned = append(owned, status)
		}
	}
	c.JSON(http.StatusOK, gin.H{"instances": owned})
}

func (s *Server) getInstance(c *gin.Context) {
	status, ok := s.requireOwned(c)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, status)
}

func (s *Server) deleteInstance(c *gin.Context) {
	if _, ok := s.requireOwned(c); !ok {
		return
	}

	id := c.Param("id")
	if err := s.backend.DeleteInstance(c.Request.Context(), id); err != nil {
		s.logger.Error("Data plane failed to delete instance",
			slog.String("instance_id", id),
			slog.String("error", err.Error()),
		)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	s.logger.Info("Data plane deleted instance", slog.String("instance_id", id))
	c.Status(http.StatusNoContent)
}

func (s *Server) healthCheck(c *gin.Context) {
	if _, ok := s.requireOwned(c); !ok {
		return
	}

	result, err := s.backend.PerformHealthCheck(c.Request.Context(), c.Param("id"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, result)
}
