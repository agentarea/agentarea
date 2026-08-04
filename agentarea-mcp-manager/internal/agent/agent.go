// Package agent runs the manager binary as a data plane.
//
// The same binary is the control plane in its normal mode: it holds the
// database, Redis, secret-manager and policy wiring. None of that belongs on a
// host that also runs untrusted MCP containers, because the container runtime
// there is the trust boundary. Agent mode is the other half of that split — the
// process keeps only a container backend and answers a narrow HTTP API, so a
// compromised host yields container control and nothing else.
//
// What agent mode deliberately does NOT construct: no database, no Redis, no
// secret resolver, no event bus, no sandbox runtime, no provider manager. The
// caller sends a fully-resolved InstanceSpec; the agent never learns where the
// values came from.
package agent

import (
	"crypto/subtle"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// OwnerLabel marks every instance this agent created. Operations on anything
// without it are refused: an agent sharing a host with other workloads must not
// become a lever for touching them.
const OwnerLabel = "agentarea.io/agent-id"

// ErrDisabled reports that agent mode was not requested.
var ErrDisabled = errors.New("agent mode not enabled")

// Config is the whole of the agent's configuration. Its smallness is the point.
type Config struct {
	// AgentID names this data plane. It is stamped on created instances and is
	// what makes ownership checkable after a restart.
	AgentID string
	// AuthToken gates every instance route. Required — see ConfigFromEnv.
	AuthToken string
	// ListenAddr is where the agent serves.
	ListenAddr string
}

// ConfigFromEnv reads agent configuration, refusing anything half-specified.
//
// The token has no default and no development bypass. An agent reachable
// without one hands container creation on a gVisor host to whoever finds the
// port, so starting without it is never the more helpful outcome.
func ConfigFromEnv() (*Config, error) {
	if !Enabled() {
		return nil, ErrDisabled
	}

	token := os.Getenv("MCP_AGENT_AUTH_TOKEN")
	if token == "" {
		return nil, errors.New("MCP_AGENT_AUTH_TOKEN is required in agent mode")
	}
	if len(token) < 32 {
		return nil, fmt.Errorf("MCP_AGENT_AUTH_TOKEN must be at least 32 characters, got %d", len(token))
	}

	agentID := os.Getenv("MCP_AGENT_ID")
	if agentID == "" {
		return nil, errors.New("MCP_AGENT_ID is required in agent mode: it is what marks this agent's instances as its own")
	}

	listen := os.Getenv("MCP_AGENT_LISTEN_ADDR")
	if listen == "" {
		listen = ":8090"
	}

	return &Config{AgentID: agentID, AuthToken: token, ListenAddr: listen}, nil
}

// Enabled reports whether the process was asked to run as a data plane.
func Enabled() bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("MCP_MANAGER_MODE")), "agent")
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

// Routes registers the agent API. Liveness is deliberately outside the
// authenticated group so an orchestrator can probe without holding the token.
func (s *Server) Routes(router gin.IRouter) {
	router.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "agent_id": s.cfg.AgentID})
	})

	group := router.Group("/agent/v1", s.authenticate)
	group.POST("/instances", s.createInstance)
	group.GET("/instances", s.listInstances)
	group.GET("/instances/:id", s.getInstance)
	group.DELETE("/instances/:id", s.deleteInstance)
	group.GET("/instances/:id/health", s.healthCheck)
}

// authenticate compares the bearer token in constant time.
func (s *Server) authenticate(c *gin.Context) {
	header := c.GetHeader("Authorization")
	presented := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	if presented == "" || subtle.ConstantTimeCompare([]byte(presented), []byte(s.cfg.AuthToken)) != 1 {
		s.logger.Warn("Rejected unauthenticated agent request",
			slog.String("path", c.Request.URL.Path),
			slog.String("remote_addr", c.ClientIP()),
		)
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	c.Next()
}

// owns reports whether an instance carries this agent's label.
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

// requireOwned resolves an instance and refuses it unless this agent created it.
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

	// Stamped after binding so a caller cannot claim another agent's instances
	// by sending the label itself.
	if spec.Labels == nil {
		spec.Labels = make(map[string]string, 1)
	}
	spec.Labels[OwnerLabel] = s.cfg.AgentID

	result, err := s.backend.CreateInstance(c.Request.Context(), &spec)
	if err != nil {
		s.logger.Error("Agent failed to create instance",
			slog.String("instance_id", spec.InstanceID),
			slog.String("error", err.Error()),
		)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	s.logger.Info("Agent created instance",
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
		s.logger.Error("Agent failed to delete instance",
			slog.String("instance_id", id),
			slog.String("error", err.Error()),
		)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	s.logger.Info("Agent deleted instance", slog.String("instance_id", id))
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
