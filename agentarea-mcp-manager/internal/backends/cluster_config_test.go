package backends

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func quietLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

const testKubeconfig = `apiVersion: v1
kind: Config
clusters:
  - name: execution
    cluster:
      server: https://execution.example:6443
contexts:
  - name: execution
    context:
      cluster: execution
      user: manager
current-context: execution
users:
  - name: manager
    user:
      token: test-token
`

func writeKubeconfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "kubeconfig")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("writing test kubeconfig: %v", err)
	}
	return path
}

// A configured kubeconfig names the cluster workloads run in. It must be used,
// not merely consulted — otherwise a manager running inside the control-plane
// cluster creates untrusted workloads there instead of on the execution cluster.
func TestConfiguredKubeconfigIsUsed(t *testing.T) {
	path := writeKubeconfig(t, testKubeconfig)

	cfg, err := resolveClusterConfig(path, quietLogger())
	if err != nil {
		t.Fatalf("resolving configured kubeconfig: %v", err)
	}
	if cfg.Host != "https://execution.example:6443" {
		t.Errorf("targeting %q; the configured execution cluster was ignored", cfg.Host)
	}
}

// The regression that matters: a broken or missing kubeconfig must abort. If it
// fell through to in-cluster credentials, the operator would have declared one
// cluster and silently got another — with untrusted code landing next to the
// control plane and nothing in the logs saying so.
func TestBrokenKubeconfigIsFatalRatherThanIgnored(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "does-not-exist")

	_, err := resolveClusterConfig(missing, quietLogger())
	if err == nil {
		t.Fatal("a missing configured kubeconfig was accepted; the manager would silently use its own cluster")
	}
	if !strings.Contains(err.Error(), missing) {
		t.Errorf("error does not name the offending path, so the operator cannot fix it: %v", err)
	}
	if !strings.Contains(err.Error(), "refusing to fall back") {
		t.Errorf("error does not state that no fallback happened: %v", err)
	}
}

func TestMalformedKubeconfigIsFatal(t *testing.T) {
	path := writeKubeconfig(t, "this is not: [valid yaml\n")

	if _, err := resolveClusterConfig(path, quietLogger()); err == nil {
		t.Fatal("a malformed configured kubeconfig was accepted")
	}
}
