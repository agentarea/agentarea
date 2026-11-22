package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/activationauth"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/publishedsecrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	execsupervisor "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/supervisor"
	"github.com/google/uuid"
)

type activationPolicy struct {
	MaxExecutionTimeoutSeconds int
	IdleTimeout                time.Duration
	WorkspaceLimits            sandboxruntime.WorkspaceLimits
}

// config is everything the service reads from its environment, loaded once in main.
type config struct {
	// workspaceRoot is the parent directory for hydrated task workspaces.
	// In K8s pods this is mounted as an emptyDir so it dies with the pod;
	// in compose it's a plain directory inside the container with the same
	// effect (container removed -> directory gone).
	workspaceRoot       string
	port                string
	activationSecret    []byte
	manifestPath        string
	sandboxUID          string
	sandboxGID          string
	objectStoreEndpoint string
	processEnv          []string
	policy              activationPolicy
}

type server struct {
	config
	logger *slog.Logger
	// incarnation changes on every executor process start. The manager
	// uses it to invalidate hydration records backed by this process's ephemeral
	// filesystem instead of assuming a restarted executor still has the files.
	incarnation string
	statusMu    sync.Mutex
	status      string
	mcpProcess  *os.Process

	// Mutating operations for one task workspace are serialized. This makes the
	// live file-count check authoritative even when shell and file requests arrive
	// concurrently; fixed stripes avoid an unbounded lock registry.
	mutationStripes [256]sync.Mutex

	// s.lastRequest tracks the wall-clock time of the most recent /execute
	// or /activate call. The idle-timeout watchdog reads this to decide when
	// to self-exit, which lets K8s reclaim the pod if mcp-manager never
	// issues an explicit DELETE (worker crash, network partition, etc.). Active
	// requests are tracked separately so a long-running command is never killed
	// just because it has been quiet for longer than the idle TTL.
	lastRequestMu  sync.Mutex
	lastRequest    time.Time
	activeRequests int

	runSandboxCommand  supervisedCommandRunner
	invalidateExecutor func()
}

func newServer(cfg config, logger *slog.Logger) *server {
	return &server{
		config:            cfg,
		logger:            logger,
		incarnation:       uuid.NewString(),
		status:            "waiting",
		lastRequest:       time.Now(),
		runSandboxCommand: runAttestedSandboxCommand,
		invalidateExecutor: func() {
			_ = syscall.Kill(os.Getpid(), syscall.SIGTERM)
		},
	}
}

func loadConfig() (config, error) {
	policy, err := loadActivationPolicy()
	if err != nil {
		return config{}, err
	}
	workspaceRoot := os.Getenv("AGENTAREA_SANDBOX_ROOT")
	if workspaceRoot == "" {
		workspaceRoot = "/workspace"
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	return config{
		workspaceRoot:       workspaceRoot,
		port:                port,
		activationSecret:    loadActivationSecret(),
		manifestPath:        os.Getenv("AGENTAREA_SANDBOX_MANIFEST_PATH"),
		sandboxUID:          os.Getenv("AGENTAREA_SANDBOX_UID"),
		sandboxGID:          os.Getenv("AGENTAREA_SANDBOX_GID"),
		objectStoreEndpoint: loadObjectStoreEndpoint(),
		processEnv:          os.Environ(),
		policy:              policy,
	}, nil
}

func loadActivationSecret() []byte {
	return []byte(strings.TrimSpace(os.Getenv(activationauth.SecretEnv)))
}

func loadObjectStoreEndpoint() string {
	endpoint := os.Getenv("AGENTAREA_SANDBOX_S3_ENDPOINT")
	if endpoint == "" {
		endpoint = os.Getenv("AGENTAREA_S3_ENDPOINT")
	}
	return endpoint
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	logger.Info("Activation service starting", "status", "waiting")
	if err := publishedsecrets.Reject(os.Getenv); err != nil {
		logger.Error("Refusing to start", "error", err)
		os.Exit(1)
	}
	cfg, err := loadConfig()
	if err != nil {
		logger.Error("Activation service policy is invalid", "error", err)
		os.Exit(1)
	}
	s := newServer(cfg, logger)

	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.healthHandler)
	mux.HandleFunc("/activate", s.activateHandler)
	mux.HandleFunc("/execute", s.executeHandler)
	mux.HandleFunc("/files", s.filesHandler)
	mux.HandleFunc("/files/content", s.fileContentHandler)
	mux.HandleFunc("/workspace/task", s.workspaceTaskHandler)
	mux.HandleFunc("/workspace/writeback", s.workspaceWritebackHandler)
	mux.HandleFunc("/runtime/manifest", s.runtimeManifestHandler)

	s.startIdleWatchdog(cfg.policy.IdleTimeout)

	// Security: Configure server with timeouts to prevent Slowloris attacks
	httpServer := &http.Server{
		Addr:              ":" + cfg.port,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       10 * time.Minute,
		WriteTimeout:      time.Duration(cfg.policy.MaxExecutionTimeoutSeconds)*time.Second + execsupervisor.TransportGrace,
		IdleTimeout:       120 * time.Second,
	}

	logger.Info("Listening", "port", cfg.port)
	if err := httpServer.ListenAndServe(); err != nil {
		logger.Error("Server failed", "error", err)
		os.Exit(1)
	}
}

func (s *server) lockWorkspaceMutation(workspaceID, taskID string) func() {
	digest := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	lock := &s.mutationStripes[int(digest[0])]
	lock.Lock()
	return lock.Unlock
}

func (s *server) currentStatus() string {
	s.statusMu.Lock()
	defer s.statusMu.Unlock()
	return s.status
}

func (s *server) setStatus(status string) {
	s.statusMu.Lock()
	defer s.statusMu.Unlock()
	s.status = status
}

// claimActivation moves a waiting pod to activating; false when another
// activation got there first.
func (s *server) claimActivation() bool {
	s.statusMu.Lock()
	defer s.statusMu.Unlock()
	if s.status != "waiting" {
		return false
	}
	s.status = "activating"
	return true
}

func (s *server) healthHandler(w http.ResponseWriter, r *http.Request) {
	response := map[string]string{
		"status":      s.currentStatus(),
		"incarnation": s.incarnation,
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		s.logger.Error("Failed to encode response", "error", err)
	}
}

func (s *server) requireExecutorIncarnation(w http.ResponseWriter, expected string) bool {
	if expected == "" {
		return true
	}
	if _, err := uuid.Parse(expected); err != nil {
		http.Error(w, `{"error": "executor_incarnation is invalid"}`, http.StatusBadRequest)
		return false
	}
	if expected != s.incarnation {
		http.Error(w, `{"error": "executor_incarnation_changed"}`, http.StatusPreconditionFailed)
		return false
	}
	return true
}

// beginRequest/endRequest record activity for the idle watchdog.
func (s *server) beginRequest() {
	s.lastRequestMu.Lock()
	s.lastRequest = time.Now()
	s.activeRequests++
	s.lastRequestMu.Unlock()
}

func (s *server) endRequest() {
	s.lastRequestMu.Lock()
	if s.activeRequests > 0 {
		s.activeRequests--
	}
	s.lastRequest = time.Now()
	s.lastRequestMu.Unlock()
}

func loadActivationPolicy() (activationPolicy, error) {
	maxExecution, err := requiredPositiveIntEnv("AGENTAREA_SANDBOX_MAX_EXEC_SECONDS")
	if err != nil {
		return activationPolicy{}, err
	}
	maxFiles, err := requiredPositiveIntEnv("AGENTAREA_SANDBOX_MAX_FILES")
	if err != nil {
		return activationPolicy{}, err
	}
	maxFileBytes, err := requiredPositiveInt64Env("AGENTAREA_SANDBOX_MAX_FILE_SIZE")
	if err != nil {
		return activationPolicy{}, err
	}
	maxBytes, err := requiredPositiveInt64Env("AGENTAREA_SANDBOX_MAX_TOTAL_SIZE")
	if err != nil {
		return activationPolicy{}, err
	}
	workspaceLimits := sandboxruntime.WorkspaceLimits{
		MaxFiles: maxFiles, MaxFileBytes: maxFileBytes, MaxBytes: maxBytes,
	}
	if err := workspaceLimits.Validate(); err != nil {
		return activationPolicy{}, fmt.Errorf("sandbox workspace limits are invalid: %w", err)
	}
	idleRaw := os.Getenv("AGENTAREA_SANDBOX_IDLE_SHUTDOWN")
	if idleRaw == "" {
		return activationPolicy{}, fmt.Errorf("AGENTAREA_SANDBOX_IDLE_SHUTDOWN is required; use 0s to disable")
	}
	idleTimeout, err := time.ParseDuration(idleRaw)
	if err != nil || idleTimeout < 0 {
		return activationPolicy{}, fmt.Errorf("AGENTAREA_SANDBOX_IDLE_SHUTDOWN must be a non-negative duration (e.g. 15m, 0s)")
	}
	return activationPolicy{
		MaxExecutionTimeoutSeconds: maxExecution,
		IdleTimeout:                idleTimeout,
		WorkspaceLimits:            workspaceLimits,
	}, nil
}

func requiredPositiveIntEnv(name string) (int, error) {
	raw := os.Getenv(name)
	value, err := strconv.Atoi(raw)
	if raw == "" || err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}

func requiredPositiveInt64Env(name string) (int64, error) {
	raw := os.Getenv(name)
	value, err := strconv.ParseInt(raw, 10, 64)
	if raw == "" || err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}

// startIdleWatchdog launches a goroutine that exits the process when no
// /execute or /activate request has arrived for AGENTAREA_SANDBOX_IDLE_SHUTDOWN. This
// bounds the lifetime of an unused activation process. Task state is safe to
// discard because the canonical workspace is stored in object storage.
// Disabled when AGENTAREA_SANDBOX_IDLE_SHUTDOWN=0s.
func (s *server) startIdleWatchdog(timeout time.Duration) {
	if timeout == 0 {
		return
	}
	s.logger.Info("idle watchdog enabled", "timeout_seconds", int(timeout.Seconds()))

	go func() {
		check := time.NewTicker(30 * time.Second)
		defer check.Stop()
		for range check.C {
			s.lastRequestMu.Lock()
			idle := time.Since(s.lastRequest)
			active := s.activeRequests
			s.lastRequestMu.Unlock()
			if active == 0 && idle >= timeout {
				s.logger.Info("idle timeout reached, exiting", "idle_seconds", int(idle.Seconds()))
				os.Exit(0)
			}
		}
	}()
}

func (s *server) authorizeActivationRequest(w http.ResponseWriter, r *http.Request, scope string, identity activationauth.Identity, bodySHA256 string) bool {
	token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
	if err == nil {
		err = activationauth.Verify(token, s.activationSecret, scope, identity, bodySHA256, time.Now())
	}
	if err != nil {
		http.Error(w, `{"error": "unauthorized"}`, http.StatusUnauthorized)
		return false
	}
	return true
}
