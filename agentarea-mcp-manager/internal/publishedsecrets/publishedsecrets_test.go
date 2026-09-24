package publishedsecrets

import (
	"strings"
	"testing"
)

func clearEnvs(t *testing.T) {
	t.Helper()
	for _, name := range Envs {
		t.Setenv(name, "")
	}
}

func TestRejectRefusesAValueFromTheRepository(t *testing.T) {
	for _, name := range Envs {
		t.Run(name, func(t *testing.T) {
			clearEnvs(t)
			t.Setenv(name, "dev-sandbox-cleanup-hmac-secret-change-in-prod-00") // pragma: allowlist secret

			err := Reject()

			if err == nil {
				t.Fatalf("Reject() accepted a published %s", name)
			}
			if !strings.Contains(err.Error(), name) {
				t.Fatalf("error %q does not name %s", err, name)
			}
		})
	}
}

func TestRejectRefusesTheOldComposeDefaults(t *testing.T) {
	clearEnvs(t)
	t.Setenv("MCP_GATEWAY_AUTH_SECRET", "agentarea-dev-mcp-gateway-secret-change-me") // pragma: allowlist secret

	if err := Reject(); err == nil {
		t.Fatal("Reject() accepted the old docker-compose.dev.yaml default")
	}
}

func TestRejectAcceptsGeneratedAndUnsetValues(t *testing.T) {
	clearEnvs(t)
	t.Setenv("SANDBOX_FILE_AUTH_SECRET", "q7Xk0m3v9Zr2Lp8sWc4Nh6Ty1Bd5Fg0J") // pragma: allowlist secret

	if err := Reject(); err != nil {
		t.Fatalf("Reject() = %v, want nil", err)
	}
}
