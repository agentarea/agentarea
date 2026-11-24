package publishedsecrets

import (
	"strings"
	"testing"
)

func env(vars map[string]string) func(string) string {
	return func(name string) string { return vars[name] }
}

func TestRejectRefusesAValueFromTheRepository(t *testing.T) {
	for _, name := range Envs() {
		t.Run(name, func(t *testing.T) {
			err := Reject(env(map[string]string{name: "dev-sandbox-cleanup-hmac-secret-change-in-prod-00"})) // pragma: allowlist secret

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
	if err := Reject(env(map[string]string{"AGENTAREA_MCP_GATEWAY_SECRET": "agentarea-dev-mcp-gateway-secret-change-me"})); err == nil { // pragma: allowlist secret
		t.Fatal("Reject() accepted the old docker-compose.dev.yaml default")
	}
}

func TestRejectAcceptsGeneratedAndUnsetValues(t *testing.T) {
	if err := Reject(env(map[string]string{"AGENTAREA_SANDBOX_FILE_SECRET": "q7Xk0m3v9Zr2Lp8sWc4Nh6Ty1Bd5Fg0J"})); err != nil { // pragma: allowlist secret
		t.Fatalf("Reject() = %v, want nil", err)
	}
}
