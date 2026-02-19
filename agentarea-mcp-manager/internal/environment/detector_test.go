package environment

import (
	"io"
	"log/slog"
	"os"
	"testing"

	"github.com/agentarea/mcp-manager/internal/backends"
)

func newTestDetector(
	stat func(string) (os.FileInfo, error),
	getenv func(string) string,
	userHomeDir func() (string, error),
) *Detector {
	logger := slog.New(slog.NewTextHandler(io.Discard, &slog.HandlerOptions{Level: slog.LevelDebug}))
	return &Detector{
		logger:      logger,
		stat:        stat,
		getenv:      getenv,
		userHomeDir: userHomeDir,
	}
}

func TestDetectEnvironment_DefaultsToDocker(t *testing.T) {
	detector := newTestDetector(
		func(string) (os.FileInfo, error) { return nil, os.ErrNotExist },
		func(string) string { return "" },
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentDocker {
		t.Fatalf("expected %q, got %q", EnvironmentDocker, got)
	}
}

func TestDetectEnvironment_ServiceAccountTokenIndicatesKubernetes(t *testing.T) {
	detector := newTestDetector(
		func(path string) (os.FileInfo, error) {
			if path == "/var/run/secrets/kubernetes.io/serviceaccount/token" {
				return nil, nil
			}
			return nil, os.ErrNotExist
		},
		func(string) string { return "" },
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestDetectEnvironment_ServiceHostEnvIndicatesKubernetes(t *testing.T) {
	detector := newTestDetector(
		func(string) (os.FileInfo, error) { return nil, os.ErrNotExist },
		func(key string) string {
			if key == "KUBERNETES_SERVICE_HOST" {
				return "10.0.0.1"
			}
			return ""
		},
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestDetectEnvironment_KubeconfigEnvFileIndicatesKubernetes(t *testing.T) {
	detector := newTestDetector(
		func(path string) (os.FileInfo, error) {
			if path == "/tmp/kubeconfig" {
				return nil, nil
			}
			return nil, os.ErrNotExist
		},
		func(key string) string {
			if key == "KUBECONFIG" {
				return "/tmp/kubeconfig"
			}
			return ""
		},
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestDetectEnvironment_DefaultKubeconfigIndicatesKubernetes(t *testing.T) {
	detector := newTestDetector(
		func(path string) (os.FileInfo, error) {
			if path == "/home/test/.kube/config" {
				return nil, nil
			}
			return nil, os.ErrNotExist
		},
		func(string) string { return "" },
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestDetectEnvironment_KubernetesMountPathIndicatesKubernetes(t *testing.T) {
	detector := newTestDetector(
		func(path string) (os.FileInfo, error) {
			if path == "/etc/kubernetes" {
				return nil, nil
			}
			return nil, os.ErrNotExist
		},
		func(string) string { return "" },
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectEnvironment(); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestForceEnvironment_RespectsAliases(t *testing.T) {
	detector := newTestDetector(
		func(string) (os.FileInfo, error) { return nil, os.ErrNotExist },
		func(string) string { return "" },
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.ForceEnvironment("k8s"); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}

	if got := detector.ForceEnvironment("podman"); got != EnvironmentDocker {
		t.Fatalf("expected %q, got %q", EnvironmentDocker, got)
	}
}

func TestForceEnvironment_InvalidFallsBackToDetection(t *testing.T) {
	detector := newTestDetector(
		func(string) (os.FileInfo, error) { return nil, os.ErrNotExist },
		func(key string) string {
			if key == "KUBERNETES_SERVICE_HOST" {
				return "10.0.0.1"
			}
			return ""
		},
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.ForceEnvironment("not-a-real-env"); got != EnvironmentKubernetes {
		t.Fatalf("expected %q, got %q", EnvironmentKubernetes, got)
	}
}

func TestDetectBackendType_MapsFromEnvironment(t *testing.T) {
	detector := newTestDetector(
		func(string) (os.FileInfo, error) { return nil, os.ErrNotExist },
		func(key string) string {
			if key == "KUBERNETES_SERVICE_HOST" {
				return "10.0.0.1"
			}
			return ""
		},
		func() (string, error) { return "/home/test", nil },
	)

	if got := detector.DetectBackendType(); got != backends.BackendTypeKubernetes {
		t.Fatalf("expected %q, got %q", backends.BackendTypeKubernetes, got)
	}
}

func TestGetEnvironmentInfo_IncludesChecksAndEnvironmentVars(t *testing.T) {
	detector := newTestDetector(
		func(path string) (os.FileInfo, error) {
			if path == "/tmp/kubeconfig" {
				return nil, nil
			}
			return nil, os.ErrNotExist
		},
		func(key string) string {
			switch key {
			case "KUBECONFIG":
				return "/tmp/kubeconfig"
			case "KUBERNETES_SERVICE_HOST":
				return "10.0.0.1"
			default:
				return ""
			}
		},
		func() (string, error) { return "/home/test", nil },
	)

	info := detector.GetEnvironmentInfo()

	if info["detected_environment"] != string(EnvironmentKubernetes) {
		t.Fatalf("expected detected_environment=%q, got %v", EnvironmentKubernetes, info["detected_environment"])
	}

	checks, ok := info["checks"].(map[string]bool)
	if !ok {
		t.Fatalf("expected checks to be map[string]bool, got %T", info["checks"])
	}
	if !checks["kubeconfig"] {
		t.Fatalf("expected kubeconfig check to be true")
	}

	envVars, ok := info["environment_variables"].(map[string]string)
	if !ok {
		t.Fatalf("expected environment_variables to be map[string]string, got %T", info["environment_variables"])
	}
	if envVars["KUBECONFIG"] != "/tmp/kubeconfig" {
		t.Fatalf("expected KUBECONFIG=%q, got %q", "/tmp/kubeconfig", envVars["KUBECONFIG"])
	}
}
