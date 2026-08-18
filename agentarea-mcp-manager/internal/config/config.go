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

	// Connector contains the outbound-control-plane selection. It is kept
	// separate from CoreAPIURL because connector authentication defaults to TLS
	// and must never silently inherit an unrelated HTTP development endpoint.
	Connector ConnectorConfig `json:"connector"`

	// SandboxEnabled controls only the control-plane sandbox API and its
	// storage/runner dependencies. MCP lifecycle and the outbound connector do
	// not require Redis, S3, or a sandbox provider when this is false.
	SandboxEnabled bool `json:"sandbox_enabled"`
}

// FeaturesConfig holds feature flag configuration
type FeaturesConfig struct {
	Enabled  []string                     `json:"enabled"`
	Variants map[string]map[string]string `json:"variants"`
}

// ConnectorConfig identifies the one logical data plane driven by the
// outbound connector backend and the platform endpoint that authenticates
// inbound connector sessions. It intentionally contains no data-plane URL or
// shared credential.
type ConnectorConfig struct {
	DataPlaneID              string        `json:"data_plane_id"`
	PlatformAPIURL           string        `json:"platform_api_url"`
	AllowInsecureDevelopment bool          `json:"allow_insecure_development"`
	AuthTimeout              time.Duration `json:"auth_timeout"`
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
			Host:         getEnv("SERVER_HOST", "0.0.0.0"),
			Port:         getEnvInt("SERVER_PORT", 8000),
			ReadTimeout:  getEnvDuration("SERVER_READ_TIMEOUT", 30*time.Second),
			WriteTimeout: getEnvDuration("SERVER_WRITE_TIMEOUT", 35*time.Minute),
			// CORS disabled by default for security
			CORSEnabled:        getEnvBool("CORS_ENABLED", false),
			CORSAllowedOrigins: getEnvStringSlice("CORS_ALLOWED_ORIGINS", []string{}),
		},
		Container: ContainerConfig{
			Runtime:            getEnv("CONTAINER_RUNTIME", "docker"),
			Network:            getEnv("MCP_NETWORK", "agentarea_default"),
			NamePrefix:         getEnv("CONTAINER_NAME_PREFIX", "mcp-"),
			ManagedByLabel:     getEnv("CONTAINER_MANAGED_BY_LABEL", "mcp-manager"),
			MaxContainers:      getEnvInt("MAX_CONTAINERS", 50),
			StartupTimeout:     getEnvDuration("STARTUP_TIMEOUT", 120*time.Second),
			ShutdownTimeout:    getEnvDuration("SHUTDOWN_TIMEOUT", 30*time.Second),
			DefaultMemoryLimit: getEnv("DEFAULT_MEMORY_LIMIT", "512m"),
			DefaultCPULimit:    getEnv("DEFAULT_CPU_LIMIT", "1.0"),
			SandboxExecutorURL: getEnv("SANDBOX_EXECUTOR_URL", ""),

			DefaultIsolationTier: getEnv("DEFAULT_ISOLATION_TIER", IsolationUntrusted),

			// Off by default: enabling reaping changes how long an instance
			// lives, so an operator opts in rather than discovering it.
			MCPIdleTimeout:       getEnvDuration("MCP_IDLE_TIMEOUT", 0),
			MCPIdleSweepInterval: getEnvDuration("MCP_IDLE_SWEEP_INTERVAL", 60*time.Second),
		},
		Logging: LoggingConfig{
			Level:  getEnv("LOG_LEVEL", "INFO"),
			Format: getEnv("LOG_FORMAT", "json"),
		},
		Redis: RedisConfig{
			URL: getEnv("REDIS_URL", "redis://localhost:6379"),
		},
		CoreAPIURL:  getEnv("CORE_API_URL", "http://localhost:8000"),
		Kubernetes:  loadKubernetesConfig(),
		Environment: backendEnvironment(),
		Features:    loadFeaturesConfig(),
		Connector: ConnectorConfig{
			DataPlaneID:              getEnv("MCP_CONNECTOR_DATA_PLANE_ID", ""),
			PlatformAPIURL:           getEnv("MCP_CONNECTOR_PLATFORM_API_URL", ""),
			AllowInsecureDevelopment: getEnvBool("MCP_CONNECTOR_ALLOW_INSECURE_DEVELOPMENT", false),
			AuthTimeout:              getEnvDuration("MCP_CONNECTOR_AUTH_TIMEOUT", 10*time.Second),
		},
		SandboxEnabled: getEnvBool("SANDBOX_ENABLED", true),
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
	config.Enabled = getEnvBool("KUBERNETES_ENABLED", config.Enabled)
	config.Namespace = getEnv("KUBERNETES_NAMESPACE", config.Namespace)
	config.RuntimeClass = getEnv("KUBERNETES_RUNTIME_CLASS", config.RuntimeClass)
	config.Kubeconfig = getEnv("KUBERNETES_KUBECONFIG", config.Kubeconfig)
	config.PodServiceAccountName = getEnv("KUBERNETES_POD_SERVICE_ACCOUNT_NAME", config.PodServiceAccountName)
	config.ImagePullPolicy = getEnv("K8S_IMAGE_PULL_POLICY", config.ImagePullPolicy)
	config.GatewayName = getEnv("KUBERNETES_GATEWAY_NAME", config.GatewayName)
	config.GatewayNamespace = getEnv("KUBERNETES_GATEWAY_NAMESPACE", config.GatewayNamespace)
	config.Domain = getEnv("KUBERNETES_DOMAIN", config.Domain)
	config.IngressClass = getEnv("KUBERNETES_INGRESS_CLASS", config.IngressClass)
	config.StorageClass = getEnv("KUBERNETES_STORAGE_CLASS", config.StorageClass)

	// Resource defaults
	config.DefaultRequests.CPU = getEnv("KUBERNETES_DEFAULT_CPU_REQUEST", config.DefaultRequests.CPU)
	config.DefaultRequests.Memory = getEnv("KUBERNETES_DEFAULT_MEMORY_REQUEST", config.DefaultRequests.Memory)
	config.DefaultLimits.CPU = getEnv("KUBERNETES_DEFAULT_CPU_LIMIT", config.DefaultLimits.CPU)
	config.DefaultLimits.Memory = getEnv("KUBERNETES_DEFAULT_MEMORY_LIMIT", config.DefaultLimits.Memory)

	// Security context
	config.SecurityContext.RunAsNonRoot = getEnvBool("KUBERNETES_RUN_AS_NON_ROOT", config.SecurityContext.RunAsNonRoot)
	if runAsUser := getEnv("KUBERNETES_RUN_AS_USER", ""); runAsUser != "" {
		user, err := strconv.ParseInt(runAsUser, 10, 64)
		if err != nil {
			panic("KUBERNETES_RUN_AS_USER must be an integer")
		}
		config.SecurityContext.RunAsUser = user
	}
	config.SecurityContext.ReadOnlyRootFilesystem = getEnvBool("KUBERNETES_READ_ONLY_ROOT_FS", config.SecurityContext.ReadOnlyRootFilesystem)
	config.SecurityContext.AllowPrivilegeEscalation = getEnvBool("KUBERNETES_ALLOW_PRIVILEGE_ESCALATION", config.SecurityContext.AllowPrivilegeEscalation)

	// Network policy
	config.NetworkPolicy.Enabled = getEnvBool("KUBERNETES_NETWORK_POLICY_ENABLED", config.NetworkPolicy.Enabled)

	// Operator-supplied instance pod customization (labels/annotations/scheduling),
	// passed by the chart as one JSON blob. Malformed placement policy is a
	// deployment error rather than permission to run elsewhere.
	if raw := getEnv("KUBERNETES_INSTANCE_POD", ""); raw != "" {
		if err := json.Unmarshal([]byte(raw), &config.InstancePod); err != nil {
			panic(fmt.Sprintf("KUBERNETES_INSTANCE_POD must be valid JSON: %v", err))
		}
	}

	// Monitoring
	config.Monitoring.Enabled = getEnvBool("KUBERNETES_MONITORING_ENABLED", config.Monitoring.Enabled)
	config.Monitoring.PrometheusEnabled = getEnvBool("KUBERNETES_PROMETHEUS_ENABLED", config.Monitoring.PrometheusEnabled)
	config.Monitoring.ServiceMonitor.Enabled = getEnvBool("KUBERNETES_SERVICE_MONITOR_ENABLED", config.Monitoring.ServiceMonitor.Enabled)

	// TLS
	config.TLS.Enabled = getEnvBool("KUBERNETES_TLS_ENABLED", config.TLS.Enabled)
	config.TLS.SecretName = getEnv("KUBERNETES_TLS_SECRET_NAME", config.TLS.SecretName)
	config.TLS.CertManager.Enabled = getEnvBool("KUBERNETES_CERT_MANAGER_ENABLED", config.TLS.CertManager.Enabled)
	config.TLS.CertManager.ClusterIssuer = getEnv("KUBERNETES_CERT_MANAGER_CLUSTER_ISSUER", config.TLS.CertManager.ClusterIssuer)

	// Timeouts
	if deploymentTimeout := getEnv("KUBERNETES_DEPLOYMENT_TIMEOUT", ""); deploymentTimeout != "" {
		timeout, err := time.ParseDuration(deploymentTimeout)
		if err != nil || timeout <= 0 {
			panic("KUBERNETES_DEPLOYMENT_TIMEOUT must be a positive duration")
		}
		config.DeploymentTimeout = timeout
	}
	if readinessTimeout := getEnv("KUBERNETES_READINESS_TIMEOUT", ""); readinessTimeout != "" {
		timeout, err := time.ParseDuration(readinessTimeout)
		if err != nil || timeout <= 0 {
			panic("KUBERNETES_READINESS_TIMEOUT must be a positive duration")
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
	if features := getEnv("MCP_FEATURES_ENABLED", ""); features != "" {
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
