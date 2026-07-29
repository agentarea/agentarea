package config

import (
	"encoding/json"
	"fmt"
	"log/slog"
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

	// DefaultIsolationTier is the confinement applied to instances whose spec
	// does not name one. It defaults to "standard" rather than "trusted"
	// because the containers this manager starts are third-party MCP servers.
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

// Load loads configuration from environment variables with sensible defaults
func Load() *Config {
	return &Config{
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

			DefaultIsolationTier: getEnv("DEFAULT_ISOLATION_TIER", IsolationStandard),

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
		Environment: getEnv("BACKEND_ENVIRONMENT", ""),
		Features:    loadFeaturesConfig(),
	}
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
	}
	return defaultValue
}

func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if duration, err := time.ParseDuration(value); err == nil {
			return duration
		}
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if boolValue, err := strconv.ParseBool(value); err == nil {
			return boolValue
		}
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
		if user, err := strconv.ParseInt(runAsUser, 10, 64); err == nil {
			config.SecurityContext.RunAsUser = user
		}
	}
	config.SecurityContext.ReadOnlyRootFilesystem = getEnvBool("KUBERNETES_READ_ONLY_ROOT_FS", config.SecurityContext.ReadOnlyRootFilesystem)
	config.SecurityContext.AllowPrivilegeEscalation = getEnvBool("KUBERNETES_ALLOW_PRIVILEGE_ESCALATION", config.SecurityContext.AllowPrivilegeEscalation)

	// Network policy
	config.NetworkPolicy.Enabled = getEnvBool("KUBERNETES_NETWORK_POLICY_ENABLED", config.NetworkPolicy.Enabled)

	// Operator-supplied instance pod customization (labels/annotations/scheduling),
	// passed by the chart as one JSON blob. Parse failures are logged and ignored
	// so a malformed value cannot break instance creation.
	if raw := getEnv("KUBERNETES_INSTANCE_POD", ""); raw != "" {
		if err := json.Unmarshal([]byte(raw), &config.InstancePod); err != nil {
			slog.Warn("ignoring invalid KUBERNETES_INSTANCE_POD", slog.String("error", err.Error()))
			config.InstancePod = InstancePodConfig{}
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
		if timeout, err := time.ParseDuration(deploymentTimeout); err == nil {
			config.DeploymentTimeout = timeout
		}
	}
	if readinessTimeout := getEnv("KUBERNETES_READINESS_TIMEOUT", ""); readinessTimeout != "" {
		if timeout, err := time.ParseDuration(readinessTimeout); err == nil {
			config.ReadinessTimeout = timeout
		}
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
