package environment

import (
	"fmt"
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
	// EnvironmentDataplane runs containers on a remote data plane instead of on this
	// host. It is never auto-detected: nothing about a machine indicates that
	// workloads belong somewhere else, so it has to be declared.
	EnvironmentDataplane Environment = "dataplane"
)

// Detector handles environment detection logic
type Detector struct {
	logger      *slog.Logger
	stat        func(string) (os.FileInfo, error)
	getenv      func(string) string
	userHomeDir func() (string, error)
}

// NewDetector creates a new environment detector
func NewDetector(logger *slog.Logger) *Detector {
	return &Detector{
		logger:      logger,
		stat:        os.Stat,
		getenv:      os.Getenv,
		userHomeDir: os.UserHomeDir,
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
	if _, err := d.stat(tokenPath); err == nil {
		d.logger.Debug("Found Kubernetes service account token", slog.String("path", tokenPath))
		return true
	}
	return false
}

// checkKubernetesServiceHost checks for KUBERNETES_SERVICE_HOST environment variable
func (d *Detector) checkKubernetesServiceHost() bool {
	if host := d.getenv("KUBERNETES_SERVICE_HOST"); host != "" {
		d.logger.Debug("Found KUBERNETES_SERVICE_HOST", slog.String("host", host))
		return true
	}
	return false
}

// checkKubeconfig checks for KUBECONFIG environment variable or default kubeconfig file
func (d *Detector) checkKubeconfig() bool {
	// Check KUBECONFIG environment variable
	if kubeconfig := d.getenv("KUBECONFIG"); kubeconfig != "" {
		if _, err := d.stat(kubeconfig); err == nil {
			d.logger.Debug("Found KUBECONFIG file", slog.String("path", kubeconfig))
			return true
		}
	}

	// Check default kubeconfig location
	if homeDir, err := d.userHomeDir(); err == nil {
		defaultKubeconfig := filepath.Join(homeDir, ".kube", "config")
		if _, err := d.stat(defaultKubeconfig); err == nil {
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
		if _, err := d.stat(path); err == nil {
			d.logger.Debug("Found Kubernetes path", slog.String("path", path))
			return true
		}
	}

	return false
}

// ForceEnvironment allows overriding environment detection via configuration
func (d *Detector) ForceEnvironment(env string) (Environment, error) {
	switch env {
	case "kubernetes", "k8s":
		d.logger.Info("Forced Kubernetes environment via configuration")
		return EnvironmentKubernetes, nil
	case "docker", "podman":
		d.logger.Info("Forced Docker environment via configuration")
		return EnvironmentDocker, nil
	case "dataplane":
		d.logger.Info("Forced remote data-plane environment via configuration")
		return EnvironmentDataplane, nil
	default:
		// Auto-detecting past an unrecognised value is the wrong recovery: the
		// operator said where workloads should run, and a typo like
		// "kubernets" would otherwise start the docker backend, quietly
		// creating untrusted workloads on the control plane's own host.
		return "", fmt.Errorf(
			"unknown backend environment %q (expected one of: kubernetes, k8s, docker, podman, dataplane)", env)
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
			"KUBERNETES_SERVICE_HOST": d.getenv("KUBERNETES_SERVICE_HOST"),
			"KUBERNETES_SERVICE_PORT": d.getenv("KUBERNETES_SERVICE_PORT"),
			"KUBECONFIG":              d.getenv("KUBECONFIG"),
		},
	}

	return info
}

// DetectEnvironment is a simple function that matches the main.go interface
func DetectEnvironment(forceEnv string, logger *slog.Logger) (string, error) {
	detector := NewDetector(logger)

	// A declared environment is honoured or refused — never quietly replaced by
	// a guess. Only an absent one is detected.
	if forceEnv != "" {
		env, err := detector.ForceEnvironment(forceEnv)
		if err != nil {
			return "", err
		}
		return string(env), nil
	}

	return string(detector.DetectEnvironment()), nil
}
