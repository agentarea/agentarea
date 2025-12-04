package environment

import (
	"log/slog"
	"os"
	"path/filepath"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// Environment represents the runtime environment
type Environment string

const (
	EnvironmentDocker     Environment = "docker"
	EnvironmentKubernetes Environment = "kubernetes"
)

// Detector handles environment detection logic
type Detector struct {
	logger *slog.Logger
}

// NewDetector creates a new environment detector
func NewDetector(logger *slog.Logger) *Detector {
	return &Detector{
		logger: logger,
	}
}

// DetectEnvironment automatically detects the current runtime environment
func (d *Detector) DetectEnvironment() Environment {
	d.logger.Info("Detecting runtime environment...")

	// Check for Kubernetes environment indicators
	if d.isKubernetesEnvironment() {
		d.logger.Info("Detected Kubernetes environment")
		return EnvironmentKubernetes
	}

	d.logger.Info("Detected Docker environment (default)")
	return EnvironmentDocker
}

// DetectBackendType returns the appropriate backend type for the detected environment
func (d *Detector) DetectBackendType() backends.BackendType {
	env := d.DetectEnvironment()
	switch env {
	case EnvironmentKubernetes:
		return backends.BackendTypeKubernetes
	default:
		return backends.BackendTypeDocker
	}
}

// isKubernetesEnvironment checks multiple indicators to determine if running in Kubernetes
func (d *Detector) isKubernetesEnvironment() bool {
	checks := []struct {
		name  string
		check func() bool
	}{
		{"service account token", d.checkServiceAccountToken},
		{"KUBERNETES_SERVICE_HOST", d.checkKubernetesServiceHost},
		{"KUBECONFIG", d.checkKubeconfig},
		{"container environment", d.checkContainerEnvironment},
	}

	for _, check := range checks {
		if check.check() {
			d.logger.Debug("Kubernetes environment detected",
				slog.String("indicator", check.name))
			return true
		}
	}

	return false
}

// checkServiceAccountToken checks for Kubernetes service account token
func (d *Detector) checkServiceAccountToken() bool {
	tokenPath := "/var/run/secrets/kubernetes.io/serviceaccount/token"
	if _, err := os.Stat(tokenPath); err == nil {
		d.logger.Debug("Found Kubernetes service account token", slog.String("path", tokenPath))
		return true
	}
	return false
}

// checkKubernetesServiceHost checks for KUBERNETES_SERVICE_HOST environment variable
func (d *Detector) checkKubernetesServiceHost() bool {
	if host := os.Getenv("KUBERNETES_SERVICE_HOST"); host != "" {
		d.logger.Debug("Found KUBERNETES_SERVICE_HOST", slog.String("host", host))
		return true
	}
	return false
}

// checkKubeconfig checks for KUBECONFIG environment variable or default kubeconfig file
func (d *Detector) checkKubeconfig() bool {
	// Check KUBECONFIG environment variable
	if kubeconfig := os.Getenv("KUBECONFIG"); kubeconfig != "" {
		if _, err := os.Stat(kubeconfig); err == nil {
			d.logger.Debug("Found KUBECONFIG file", slog.String("path", kubeconfig))
			return true
		}
	}

	// Check default kubeconfig location
	if homeDir, err := os.UserHomeDir(); err == nil {
		defaultKubeconfig := filepath.Join(homeDir, ".kube", "config")
		if _, err := os.Stat(defaultKubeconfig); err == nil {
			d.logger.Debug("Found default kubeconfig", slog.String("path", defaultKubeconfig))
			return true
		}
	}

	return false
}

// checkContainerEnvironment checks if running inside a container with Kubernetes-specific mounts
func (d *Detector) checkContainerEnvironment() bool {
	// Check for typical Kubernetes volume mounts
	kubernetesPaths := []string{
		"/var/run/secrets/kubernetes.io",
		"/etc/kubernetes",
	}

	for _, path := range kubernetesPaths {
		if _, err := os.Stat(path); err == nil {
			d.logger.Debug("Found Kubernetes path", slog.String("path", path))
			return true
		}
	}

	return false
}

// ForceEnvironment allows overriding environment detection via configuration
func (d *Detector) ForceEnvironment(env string) Environment {
	switch env {
	case "kubernetes", "k8s":
		d.logger.Info("Forced Kubernetes environment via configuration")
		return EnvironmentKubernetes
	case "docker", "podman":
		d.logger.Info("Forced Docker environment via configuration")
		return EnvironmentDocker
	default:
		d.logger.Warn("Invalid forced environment, falling back to auto-detection",
			slog.String("forced_env", env))
		return d.DetectEnvironment()
	}
}

// GetEnvironmentInfo returns detailed environment information for debugging
func (d *Detector) GetEnvironmentInfo() map[string]interface{} {
	info := map[string]interface{}{
		"detected_environment": string(d.DetectEnvironment()),
		"checks": map[string]bool{
			"service_account_token":   d.checkServiceAccountToken(),
			"kubernetes_service_host": d.checkKubernetesServiceHost(),
			"kubeconfig":              d.checkKubeconfig(),
			"container_environment":   d.checkContainerEnvironment(),
		},
		"environment_variables": map[string]string{
			"KUBERNETES_SERVICE_HOST": os.Getenv("KUBERNETES_SERVICE_HOST"),
			"KUBERNETES_SERVICE_PORT": os.Getenv("KUBERNETES_SERVICE_PORT"),
			"KUBECONFIG":              os.Getenv("KUBECONFIG"),
		},
	}

	return info
}

// DetectEnvironment is a simple function that matches the main.go interface
func DetectEnvironment(forceEnv string, logger *slog.Logger) string {
	detector := NewDetector(logger)

	// Check for forced environment override
	if forceEnv != "" {
		env := detector.ForceEnvironment(forceEnv)
		return string(env)
	}

	// Auto-detect environment
	env := detector.DetectEnvironment()
	return string(env)
}
