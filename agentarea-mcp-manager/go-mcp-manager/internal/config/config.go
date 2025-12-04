package config

import (
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

	// Traefik configuration
	Traefik TraefikConfig `json:"traefik"`

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

	// Path to MCP providers YAML file
	MCPProvidersPath string `json:"mcp_providers_path"`
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
	Runtime          string `json:"runtime"`
	StorageDriver    string `json:"storage_driver"`
	StorageRunroot   string `json:"storage_runroot"`
	StorageGraphroot string `json:"storage_graphroot"`

	// Management settings
	NamePrefix      string        `json:"name_prefix"`
	ManagedByLabel  string        `json:"managed_by_label"`
	MaxContainers   int           `json:"max_containers"`
	StartupTimeout  time.Duration `json:"startup_timeout"`
	ShutdownTimeout time.Duration `json:"shutdown_timeout"`

	// Resource limits
	DefaultMemoryLimit string `json:"default_memory_limit"`
	DefaultCPULimit    string `json:"default_cpu_limit"`
}

// TraefikConfig holds Traefik configuration
type TraefikConfig struct {
	Network           string `json:"network"`
	ProxyPort         int    `json:"proxy_port"`
	DefaultDomain     string `json:"default_domain"`
	ProxyHost         string `json:"proxy_host"`
	ManagerServiceURL string `json:"manager_service_url"`
	ConfigPath        string `json:"config_path"`
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
			WriteTimeout: getEnvDuration("SERVER_WRITE_TIMEOUT", 30*time.Second),
			// CORS disabled by default for security
			CORSEnabled:        getEnvBool("CORS_ENABLED", false),
			CORSAllowedOrigins: getEnvStringSlice("CORS_ALLOWED_ORIGINS", []string{}),
		},
		Container: ContainerConfig{
			Runtime:            getEnv("CONTAINER_RUNTIME", "podman"),
			StorageDriver:      getEnv("CONTAINERS_STORAGE_DRIVER", "overlay"),
			StorageRunroot:     getEnv("CONTAINERS_STORAGE_RUNROOT", "/tmp/containers"),
			StorageGraphroot:   getEnv("CONTAINERS_STORAGE_GRAPHROOT", "/var/lib/containers/storage"),
			NamePrefix:         getEnv("CONTAINER_NAME_PREFIX", "mcp-"),
			ManagedByLabel:     getEnv("CONTAINER_MANAGED_BY_LABEL", "mcp-manager"),
			MaxContainers:      getEnvInt("MAX_CONTAINERS", 50),
			StartupTimeout:     getEnvDuration("STARTUP_TIMEOUT", 120*time.Second),
			ShutdownTimeout:    getEnvDuration("SHUTDOWN_TIMEOUT", 30*time.Second),
			DefaultMemoryLimit: getEnv("DEFAULT_MEMORY_LIMIT", "512m"),
			DefaultCPULimit:    getEnv("DEFAULT_CPU_LIMIT", "1.0"),
		},
		Traefik: TraefikConfig{
			Network:           getEnv("TRAEFIK_NETWORK", "podman"),
			ProxyPort:         getEnvInt("TRAEFIK_PROXY_PORT", 81),
			DefaultDomain:     getEnv("DEFAULT_DOMAIN", "localhost"),
			ProxyHost:         getEnv("MCP_PROXY_HOST", "http://localhost:7999"),
			ManagerServiceURL: getEnv("MANAGER_SERVICE_URL", "http://localhost:8000"),
			ConfigPath:        getEnv("TRAEFIK_CONFIG_PATH", "/etc/traefik/dynamic.yml"),
		},
		Logging: LoggingConfig{
			Level:  getEnv("LOG_LEVEL", "INFO"),
			Format: getEnv("LOG_FORMAT", "json"),
		},
		Redis: RedisConfig{
			URL: getEnv("REDIS_URL", "redis://localhost:6379"),
		},
		CoreAPIURL:       getEnv("CORE_API_URL", "http://localhost:8000"),
		Kubernetes:       loadKubernetesConfig(),
		Environment:      getEnv("BACKEND_ENVIRONMENT", ""),
		MCPProvidersPath: getEnv("MCP_PROVIDERS_YAML", "/app/data/mcp_providers.yaml"),
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

// GetServiceHost generates a service hostname
func (c *Config) GetServiceHost(serviceName string) string {
	return fmt.Sprintf("%s:%d", c.Traefik.DefaultDomain, c.Traefik.ProxyPort)
}
