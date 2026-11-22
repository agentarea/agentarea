package plane

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

const testManifest = `{"schema_version": 2, "managed_environment": "mutable", "image_version": "test-runtime",
"python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
"node": {"version": "v22.1.0", "npm_version": "10.0.0"}, "tools": {}, "packages": {},
"features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
"execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}}`

// classClients answers every request itself and records the destination
// class of the transport that carried it.
type classClients struct{ sent *[]netguard.Destination }

func (c classClients) Transport(dest netguard.Destination) http.RoundTripper {
	return &http.Transport{DialContext: func(context.Context, string, string) (net.Conn, error) {
		*c.sent = append(*c.sent, dest)
		return nil, errors.New("no network in the class recorder")
	}}
}

func (classClients) Dialer() netguard.Dialer { return nil }

func sandboxEnv(extra map[string]string) map[string]string {
	vars := map[string]string{
		"AGENTAREA_REDIS_URL":                 "redis://127.0.0.1:6379",
		"AGENTAREA_SANDBOX_RECORD_TTL":        "1h",
		"AGENTAREA_SANDBOX_MAX_EXEC_SECONDS":  "1800",
		"AGENTAREA_SANDBOX_EXEC_SECONDS":      "120",
		"AGENTAREA_SANDBOX_QUEUE_TIMEOUT":     "5m",
		"AGENTAREA_SANDBOX_COMPLETION_GRACE":  "1m",
		"AGENTAREA_SANDBOX_LEASE_TTL":         "2h",
		"AGENTAREA_SANDBOX_IDLE_TTL":          "15m",
		"AGENTAREA_SANDBOX_PROVISION_TIMEOUT": "30s",
		"AGENTAREA_SANDBOX_SESSION_TTL":       "24h",
		"AGENTAREA_SANDBOX_STORAGE":           "s3",
		"AGENTAREA_S3_ARTIFACTS_BUCKET":       "artifacts",
		"AGENTAREA_SANDBOX_MAX_FILES":         "1000",
		"AGENTAREA_SANDBOX_MAX_FILE_SIZE":     "1048576",
		"AGENTAREA_SANDBOX_MAX_TOTAL_SIZE":    "10485760",
		"AGENTAREA_SANDBOX_S3_URL_TTL":        "1h",
		"AGENTAREA_SANDBOX_S3_PATH_STYLE":     "true",
		"AGENTAREA_SANDBOX_MANIFEST_JSON":     testManifest,
		"AGENTAREA_SANDBOX_ALLOW_INTERNET":    "false",
	}
	for k, v := range extra {
		vars[k] = v
	}
	return vars
}

func openWithClasses(t *testing.T, vars map[string]string) (*Plane, *[]netguard.Destination) {
	t.Helper()
	l := config.FromMap(sandboxEnv(vars))
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	rdb := redis.NewClient(&redis.Options{Addr: miniredis.RunT(t).Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	sent := &[]netguard.Destination{}
	p, err := Open(cfg, "", Deps{Redis: rdb, S3: s3.New(s3.Options{Region: "us-east-1"}), Out: classClients{sent: sent},
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err != nil {
		t.Fatal(err)
	}
	return p, sent
}

func TestE2BIsReachedAsAVendor(t *testing.T) {
	p, sent := openWithClasses(t, map[string]string{
		"AGENTAREA_SANDBOX_PROVIDER":      "e2b",
		"AGENTAREA_SANDBOX_E2B_URL":       "https://api.e2b.example",
		"AGENTAREA_SANDBOX_E2B_API_KEY":   "e2b_test",
		"AGENTAREA_SANDBOX_E2B_TEMPLATE":  "agentarea-runtime",
		"AGENTAREA_SANDBOX_E2B_ISOLATION": "firecracker",
	})
	_, _ = p.Allocations().SampleUsage(context.Background())
	if len(*sent) == 0 || (*sent)[0] != netguard.Vendor {
		t.Fatalf("E2B request classes = %v, want Vendor", *sent)
	}
}

func TestOpenSandboxIsReachedAsAnInternalService(t *testing.T) {
	p, sent := openWithClasses(t, map[string]string{
		"AGENTAREA_SANDBOX_PROVIDER":           "opensandbox",
		"AGENTAREA_SANDBOX_OSB_URL":            "https://osb.example",
		"AGENTAREA_SANDBOX_OSB_API_KEY":        "osb_test",
		"AGENTAREA_SANDBOX_OSB_ISOLATION":      "container-dev",
		"AGENTAREA_SANDBOX_OSB_WEAK_ISOLATION": "true",
		"AGENTAREA_SANDBOX_OSB_EGRESS":         "provider",
		"AGENTAREA_SANDBOX_OSB_IMAGE":          "opensandbox/code-interpreter:test",
	})
	_, _ = p.Allocations().SampleUsage(context.Background())
	if len(*sent) == 0 || (*sent)[0] != netguard.Internal {
		t.Fatalf("OpenSandbox request classes = %v, want Internal", *sent)
	}
}

func TestOpenRefusesMissingInfrastructure(t *testing.T) {
	l := config.FromMap(sandboxEnv(nil))
	cfg := LoadConfig(l)
	if _, err := Open(cfg, BuiltinDocker, Deps{Log: slog.New(slog.NewTextHandler(io.Discard, nil))}); err == nil {
		t.Fatal("plane opened without Redis, the object store or the outbound clients")
	}
}
