package config

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Config holds all configuration for the MCP Manager
type Config struct {
	// Server configuration
	Server ServerConfig `json:"server"`

	// Container runtime configuration
	Container ContainerConfig `json:"container"`

	// Logging configuration
	Logging LoggingConfig `json:"logging"`

	// Redis configuration for events
	Redis RedisConfig `json:"redis"`

	// Core API configuration
	CoreAPIURL string `json:"core_api_url"`

	// Kubernetes configuration
	Kubernetes KubernetesConfig `json:"kubernetes"`

	// Environment override (for forcing backend selection)
	Environment string `json:"environment"`

	// Feature flags configuration
	Features FeaturesConfig `json:"features"`
}

// FeaturesConfig holds feature flag configuration
type FeaturesConfig struct {
	Enabled  []string                     `json:"enabled"`
	Variants map[string]map[string]string `json:"variants"`
}

// ServerConfig holds HTTP server configuration
type ServerConfig struct {
	Host         string        `json:"host"`
	Port         int           `json:"port"`
	ReadTimeout  time.Duration `json:"read_timeout"`
	WriteTimeout time.Duration `json:"write_timeout"`
	// CORS configuration
	CORSEnabled        bool     `json:"cors_enabled"`
	CORSAllowedOrigins []string `json:"cors_allowed_origins"`
}

// ContainerConfig holds container runtime configuration
type ContainerConfig struct {
	Runtime string `json:"runtime"`
	Network string `json:"network"` // Docker network for container-to-container communication

	// Management settings
	NamePrefix      string        `json:"name_prefix"`
	ManagedByLabel  string        `json:"managed_by_label"`
	MaxContainers   int           `json:"max_containers"`
	StartupTimeout  time.Duration `json:"startup_timeout"`
	ShutdownTimeout time.Duration `json:"shutdown_timeout"`

	// Resource limits
	DefaultMemoryLimit string `json:"default_memory_limit"`
	DefaultCPULimit    string `json:"default_cpu_limit"`
	// Include a failed workload's own output in the manager log. Off by default:
	// that text belongs to third-party code and holds whatever credentials the
	// process had.
	LogWorkloadOutput bool   `json:"log_workload_output"`
	MaxMemoryLimit    string `json:"max_memory_limit"`
	MaxCPULimit       string `json:"max_cpu_limit"`

	// DefaultIsolationTier is the confinement applied to instances whose spec
	// does not name one. Third-party MCP images are untrusted unless an explicit
	// call-site policy proves otherwise.
	DefaultIsolationTier string `json:"default_isolation_tier"`

	// MCPIdleTimeout stops a lazily-provisioned instance whose container has
	// gone unused for this long; the next call provisions it again. Zero
	// disables reaping, which is the pre-existing behaviour of running forever.
	MCPIdleTimeout time.Duration `json:"mcp_idle_timeout"`
	// MCPIdleSweepInterval is how often the reaper looks for idle instances.
	MCPIdleSweepInterval time.Duration `json:"mcp_idle_sweep_interval"`

	// SandboxExecutorURL is the HTTP endpoint of the sandbox-executor data
	// plane used by the docker backend (dev/compose). When set, sandbox
	// executions are routed here instead of a Kubernetes warm pod.
	SandboxExecutorURL string `json:"sandbox_executor_url"`
}

// LoggingConfig holds logging configuration
type LoggingConfig struct {
	Level  string `json:"level"`
	Format string `json:"format"`
}

// RedisConfig holds Redis configuration for event handling
type RedisConfig struct {
	URL string `json:"url"`
}

// Load loads configuration from environment variables. Missing operational
// values may use documented defaults; malformed values always stop startup.
func Load() *Config {
	config := &Config{
		Server: ServerConfig{
			Host:         getEnv("HOST", "0.0.0.0"),
			Port:         getEnvInt("PORT", 8000),
			ReadTimeout:  getEnvDuration("AGENTAREA_HTTP_READ_TIMEOUT", 30*time.Second),
			WriteTimeout: getEnvDuration("AGENTAREA_HTTP_WRITE_TIMEOUT", 35*time.Minute),
			// CORS disabled by default for security
			CORSEnabled:        getEnvBool("AGENTAREA_MCP_CORS_ENABLED", false),
			CORSAllowedOrigins: getEnvStringSlice("AGENTAREA_CORS_ORIGINS", []string{}),
		},
		Container: ContainerConfig{
			Runtime:            getEnv("AGENTAREA_MCP_RUNTIME", "docker"),
			Network:            getEnv("AGENTAREA_MCP_NETWORK", "agentarea_default"),
			NamePrefix:         getEnv("AGENTAREA_MCP_NAME_PREFIX", "mcp-"),
			ManagedByLabel:     getEnv("AGENTAREA_MCP_LABEL", "mcp-manager"),
			MaxContainers:      getEnvInt("AGENTAREA_MCP_MAX_CONTAINERS", 50),
			StartupTimeout:     getEnvDuration("AGENTAREA_STARTUP_TIMEOUT", 120*time.Second),
			ShutdownTimeout:    getEnvDuration("AGENTAREA_SHUTDOWN_TIMEOUT", 30*time.Second),
			DefaultMemoryLimit: getEnv("AGENTAREA_MCP_MEMORY", "512m"),
			DefaultCPULimit:    getEnv("AGENTAREA_MCP_CPU", "1.0"),
			// The most a single workload may ask for. Defaults to the default:
			// a caller may size an instance down, never up, unless this host
			// says otherwise.
			LogWorkloadOutput:  getEnv("AGENTAREA_LOG_WORKLOAD", "false") == "true",
			MaxMemoryLimit:     getEnv("AGENTAREA_MCP_MAX_MEMORY", getEnv("AGENTAREA_MCP_MEMORY", "512m")),
			MaxCPULimit:        getEnv("AGENTAREA_MCP_MAX_CPU", getEnv("AGENTAREA_MCP_CPU", "1.0")),
			SandboxExecutorURL: getEnv("AGENTAREA_SBX_EXECUTOR_URL", ""),

			DefaultIsolationTier: getEnv("AGENTAREA_MCP_ISOLATION", IsolationUntrusted),

			// Off by default: enabling reaping changes how long an instance
			// lives, so an operator opts in rather than discovering it.
			MCPIdleTimeout:       getEnvDuration("AGENTAREA_MCP_IDLE_TIMEOUT", 0),
			MCPIdleSweepInterval: getEnvDuration("AGENTAREA_MCP_SWEEP_INTERVAL", 60*time.Second),
		},
		Logging: LoggingConfig{
			Level:  getEnv("AGENTAREA_LOG_LEVEL", "INFO"),
			Format: getEnv("AGENTAREA_LOG_FORMAT", "json"),
		},
		Redis: RedisConfig{
			URL: getEnv("AGENTAREA_REDIS_URL", "redis://localhost:6379"),
		},
		CoreAPIURL:  getEnv("AGENTAREA_API_URL", "http://localhost:8000"),
		Kubernetes:  loadKubernetesConfig(),
		Environment: backendEnvironment(),
		Features:    loadFeaturesConfig(),
	}
	if config.Server.Port <= 0 || config.Server.ReadTimeout <= 0 || config.Server.WriteTimeout <= 0 {
		panic("server port and timeouts must be positive")
	}
	if config.Container.MaxContainers <= 0 || config.Container.StartupTimeout <= 0 || config.Container.ShutdownTimeout <= 0 {
		panic("container limits and startup/shutdown timeouts must be positive")
	}
	if config.Container.MCPIdleTimeout < 0 || config.Container.MCPIdleSweepInterval <= 0 {
		panic("MCP idle timeout must be non-negative and sweep interval must be positive")
	}
	if _, err := ResolveIsolation(config.Container.DefaultIsolationTier); err != nil {
		panic(err)
	}
	if _, err := config.Kubernetes.InstancePod.ScratchSizeLimitQuantity(); err != nil {
		panic(err)
	}
	return config
}

// Helper functions for environment variable parsing
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
		panic(fmt.Sprintf("%s must be an integer", key))
	}
	return defaultValue
}

func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if duration, err := time.ParseDuration(value); err == nil {
			return duration
		}
		panic(fmt.Sprintf("%s must be a duration", key))
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if boolValue, err := strconv.ParseBool(value); err == nil {
			return boolValue
		}
		panic(fmt.Sprintf("%s must be true or false", key))
	}
	return defaultValue
}

func getEnvStringSlice(key string, defaultValue []string) []string {
	if value := os.Getenv(key); value != "" {
		// Split by comma and trim spaces
		values := strings.Split(value, ",")
		for i, v := range values {
			values[i] = strings.TrimSpace(v)
		}
		return values
	}
	return defaultValue
}

// loadKubernetesConfig loads Kubernetes configuration from environment variables
func loadKubernetesConfig() KubernetesConfig {
	config := DefaultKubernetesConfig()

	// Override with environment variables
	config.Enabled = getEnvBool("AGENTAREA_K8S_ENABLED", config.Enabled)
	config.Namespace = getEnv("AGENTAREA_K8S_NAMESPACE", config.Namespace)
	config.RuntimeClass = getEnv("AGENTAREA_K8S_RUNTIME_CLASS", config.RuntimeClass)
	config.Kubeconfig = getEnv("AGENTAREA_K8S_KUBECONFIG", config.Kubeconfig)
	config.PodServiceAccountName = getEnv("AGENTAREA_K8S_SERVICE_ACCOUNT", config.PodServiceAccountName)
	config.ImagePullPolicy = getEnv("AGENTAREA_K8S_PULL_POLICY", config.ImagePullPolicy)
	config.GatewayName = getEnv("AGENTAREA_K8S_GATEWAY", config.GatewayName)
	config.GatewayNamespace = getEnv("AGENTAREA_K8S_GATEWAY_NS", config.GatewayNamespace)
	config.Domain = getEnv("AGENTAREA_K8S_DOMAIN", config.Domain)
	config.IngressClass = getEnv("AGENTAREA_K8S_INGRESS_CLASS", config.IngressClass)
	config.StorageClass = getEnv("AGENTAREA_K8S_STORAGE_CLASS", config.StorageClass)

	// Resource defaults
	config.DefaultRequests.CPU = getEnv("AGENTAREA_K8S_CPU_REQUEST", config.DefaultRequests.CPU)
	config.DefaultRequests.Memory = getEnv("AGENTAREA_K8S_MEMORY_REQUEST", config.DefaultRequests.Memory)
	config.DefaultLimits.CPU = getEnv("AGENTAREA_K8S_CPU_LIMIT", config.DefaultLimits.CPU)
	config.DefaultLimits.Memory = getEnv("AGENTAREA_K8S_MEMORY_LIMIT", config.DefaultLimits.Memory)

	// Security context
	config.SecurityContext.RunAsNonRoot = getEnvBool("AGENTAREA_K8S_NON_ROOT", config.SecurityContext.RunAsNonRoot)
	if runAsUser := getEnv("AGENTAREA_K8S_RUN_AS_USER", ""); runAsUser != "" {
		user, err := strconv.ParseInt(runAsUser, 10, 64)
		if err != nil {
			panic("AGENTAREA_K8S_RUN_AS_USER must be an integer")
		}
		config.SecurityContext.RunAsUser = user
	}
	config.SecurityContext.ReadOnlyRootFilesystem = getEnvBool("AGENTAREA_K8S_READONLY_ROOT", config.SecurityContext.ReadOnlyRootFilesystem)
	config.SecurityContext.AllowPrivilegeEscalation = getEnvBool("AGENTAREA_K8S_PRIV_ESCALATION", config.SecurityContext.AllowPrivilegeEscalation)

	// Network policy
	config.NetworkPolicy.Enabled = getEnvBool("AGENTAREA_K8S_NETWORK_POLICY", config.NetworkPolicy.Enabled)

	// Operator-supplied instance pod customization (labels/annotations/scheduling),
	// passed by the chart as one JSON blob. Malformed placement policy is a
	// deployment error rather than permission to run elsewhere.
	if raw := getEnv("AGENTAREA_K8S_INSTANCE_POD", ""); raw != "" {
		if err := json.Unmarshal([]byte(raw), &config.InstancePod); err != nil {
			panic(fmt.Sprintf("AGENTAREA_K8S_INSTANCE_POD must be valid JSON: %v", err))
		}
	}

	// Monitoring
	config.Monitoring.Enabled = getEnvBool("AGENTAREA_K8S_MONITORING", config.Monitoring.Enabled)
	config.Monitoring.PrometheusEnabled = getEnvBool("AGENTAREA_K8S_PROMETHEUS", config.Monitoring.PrometheusEnabled)
	config.Monitoring.ServiceMonitor.Enabled = getEnvBool("AGENTAREA_K8S_SERVICE_MONITOR", config.Monitoring.ServiceMonitor.Enabled)

	// TLS
	config.TLS.Enabled = getEnvBool("AGENTAREA_K8S_TLS", config.TLS.Enabled)
	config.TLS.SecretName = getEnv("AGENTAREA_K8S_TLS_SECRET", config.TLS.SecretName)
	config.TLS.CertManager.Enabled = getEnvBool("AGENTAREA_K8S_CERT_MANAGER", config.TLS.CertManager.Enabled)
	config.TLS.CertManager.ClusterIssuer = getEnv("AGENTAREA_K8S_CLUSTER_ISSUER", config.TLS.CertManager.ClusterIssuer)

	// Timeouts
	if deploymentTimeout := getEnv("AGENTAREA_K8S_DEPLOY_TIMEOUT", ""); deploymentTimeout != "" {
		timeout, err := time.ParseDuration(deploymentTimeout)
		if err != nil || timeout <= 0 {
			panic("AGENTAREA_K8S_DEPLOY_TIMEOUT must be a positive duration")
		}
		config.DeploymentTimeout = timeout
	}
	if readinessTimeout := getEnv("AGENTAREA_K8S_READY_TIMEOUT", ""); readinessTimeout != "" {
		timeout, err := time.ParseDuration(readinessTimeout)
		if err != nil || timeout <= 0 {
			panic("AGENTAREA_K8S_READY_TIMEOUT must be a positive duration")
		}
		config.ReadinessTimeout = timeout
	}

	return config
}

// loadFeaturesConfig loads feature flag configuration from environment
func loadFeaturesConfig() FeaturesConfig {
	config := FeaturesConfig{
		Enabled:  []string{},
		Variants: make(map[string]map[string]string),
	}

	// Parse enabled features from comma-separated list
	if features := getEnv("AGENTAREA_MCP_FEATURES", ""); features != "" {
		config.Enabled = strings.Split(features, ",")
		// Trim whitespace
		for i, f := range config.Enabled {
			config.Enabled[i] = strings.TrimSpace(f)
		}
	}

	return config
}

// sanitizeServiceName sanitizes a service name to be valid for container names
func sanitizeServiceName(serviceName string) string {
	// Convert to lowercase
	sanitized := strings.ToLower(serviceName)

	// Replace any non-alphanumeric characters with hyphens
	reg := regexp.MustCompile(`[^a-z0-9]+`)
	sanitized = reg.ReplaceAllString(sanitized, "-")

	// Remove leading/trailing hyphens
	sanitized = strings.Trim(sanitized, "-")

	// Ensure it's not empty and starts with alphanumeric
	if sanitized == "" || !regexp.MustCompile(`^[a-z0-9]`).MatchString(sanitized) {
		sanitized = "container-" + sanitized
	}

	return sanitized
}

// GetContainerName generates a container name for a service
func (c *Config) GetContainerName(serviceName string) string {
	sanitizedName := sanitizeServiceName(serviceName)
	return fmt.Sprintf("%s%s", c.Container.NamePrefix, sanitizedName)
}

// GetServiceURL generates a service URL for Traefik routing
func (c *Config) GetServiceURL(serviceName string, port int) string {
	return fmt.Sprintf("http://%s:%d", c.GetContainerName(serviceName), port)
}

// GetServiceHost generates a service hostname (Traefik handles routing)
func (c *Config) GetServiceHost(serviceName string) string {
	return c.GetContainerName(serviceName)
}
