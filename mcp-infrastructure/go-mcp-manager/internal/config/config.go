package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config holds all configuration for the MCP Manager
type Config struct {
	// Server configuration
	Server ServerConfig `json:"server"`

	// Container runtime configuration
	Container ContainerConfig `json:"container"`

	// Caddy configuration
	Caddy CaddyConfig `json:"caddy"`

	// Logging configuration
	Logging LoggingConfig `json:"logging"`
}

// ServerConfig holds HTTP server configuration
type ServerConfig struct {
	Host         string        `json:"host"`
	Port         int           `json:"port"`
	ReadTimeout  time.Duration `json:"read_timeout"`
	WriteTimeout time.Duration `json:"write_timeout"`
}

// ContainerConfig holds container runtime configuration
type ContainerConfig struct {
	Runtime          string `json:"runtime"`
	StorageDriver    string `json:"storage_driver"`
	StorageRunroot   string `json:"storage_runroot"`
	StorageGraphroot string `json:"storage_graphroot"`

	// Management settings
	Prefix          string        `json:"prefix"`
	MaxContainers   int           `json:"max_containers"`
	StartupTimeout  time.Duration `json:"startup_timeout"`
	ShutdownTimeout time.Duration `json:"shutdown_timeout"`

	// Resource limits
	DefaultMemoryLimit string `json:"default_memory_limit"`
	DefaultCPULimit    string `json:"default_cpu_limit"`

	// Templates
	TemplatesDir string `json:"templates_dir"`
}

// CaddyConfig holds Caddy API configuration
type CaddyConfig struct {
	APIURL        string        `json:"api_url"`
	Host          string        `json:"host"`
	Timeout       time.Duration `json:"timeout"`
	DefaultDomain string        `json:"default_domain"`
}

// LoggingConfig holds logging configuration
type LoggingConfig struct {
	Level  string `json:"level"`
	Format string `json:"format"`
}

// Load loads configuration from environment variables with sensible defaults
func Load() *Config {
	return &Config{
		Server: ServerConfig{
			Host:         getEnv("SERVER_HOST", "0.0.0.0"),
			Port:         getEnvInt("SERVER_PORT", 8000),
			ReadTimeout:  getEnvDuration("SERVER_READ_TIMEOUT", 30*time.Second),
			WriteTimeout: getEnvDuration("SERVER_WRITE_TIMEOUT", 30*time.Second),
		},
		Container: ContainerConfig{
			Runtime:            getEnv("CONTAINER_RUNTIME", "podman"),
			StorageDriver:      getEnv("CONTAINERS_STORAGE_DRIVER", "overlay"),
			StorageRunroot:     getEnv("CONTAINERS_STORAGE_RUNROOT", "/tmp/containers"),
			StorageGraphroot:   getEnv("CONTAINERS_STORAGE_GRAPHROOT", "/var/lib/containers/storage"),
			Prefix:             getEnv("CONTAINER_PREFIX", "mcp-"),
			MaxContainers:      getEnvInt("MAX_CONTAINERS", 50),
			StartupTimeout:     getEnvDuration("STARTUP_TIMEOUT", 120*time.Second),
			ShutdownTimeout:    getEnvDuration("SHUTDOWN_TIMEOUT", 30*time.Second),
			DefaultMemoryLimit: getEnv("DEFAULT_MEMORY_LIMIT", "512m"),
			DefaultCPULimit:    getEnv("DEFAULT_CPU_LIMIT", "1.0"),
			TemplatesDir:       getEnv("TEMPLATES_DIR", "/app/templates"),
		},
		Caddy: CaddyConfig{
			APIURL:        getEnv("CADDY_API_URL", "http://caddy:2019"),
			Host:          getEnv("CADDY_HOST", "caddy"),
			Timeout:       getEnvDuration("CADDY_API_TIMEOUT", 10*time.Second),
			DefaultDomain: getEnv("DEFAULT_DOMAIN", "localhost"),
		},
		Logging: LoggingConfig{
			Level:  getEnv("LOG_LEVEL", "INFO"),
			Format: getEnv("LOG_FORMAT", "json"),
		},
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

// GetContainerName generates a container name for a service
func (c *Config) GetContainerName(serviceName string) string {
	return fmt.Sprintf("%s%s", c.Container.Prefix, serviceName)
}

// GetServiceURL generates a service URL for Caddy routing
func (c *Config) GetServiceURL(serviceName string, port int) string {
	return fmt.Sprintf("http://%s:%d", c.GetContainerName(serviceName), port)
}

// GetServiceHost generates a service hostname
func (c *Config) GetServiceHost(serviceName string) string {
	return fmt.Sprintf("%s.%s", serviceName, c.Caddy.DefaultDomain)
}
