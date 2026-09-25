// Package publishedsecrets refuses HMAC keys that the repository once shipped as values.
package publishedsecrets

import (
	"fmt"
	"os"
)

// Envs are the sandbox and MCP gateway HMAC keys that
// .env.example and docker-compose.dev.yaml once shipped with concrete values.
var Envs = []string{
	"SANDBOX_ACTIVATION_AUTH_SECRET",
	"SANDBOX_CLEANUP_AUTH_SECRET",
	"SANDBOX_FILE_AUTH_SECRET",
	"SANDBOX_CONTROL_AUTH_SECRET",
	"MCP_GATEWAY_AUTH_SECRET",
}

// Anyone can sign sandbox and gateway tokens with these, so a deployment that
// copied one must rotate it rather than keep running.
var values = map[string]struct{}{
	"dev-sandbox-activation-hmac-secret-change-in-prod":   {}, // pragma: allowlist secret
	"dev-sandbox-cleanup-hmac-secret-change-in-prod-00":   {}, // pragma: allowlist secret
	"dev-sandbox-file-auth-secret-change-in-prod-000000":  {}, // pragma: allowlist secret
	"dev-sandbox-control-auth-secret-change-in-prod-0000": {}, // pragma: allowlist secret
	"dev-mcp-gateway-auth-secret-change-in-prod-00000000": {}, // pragma: allowlist secret
	"agentarea-dev-sandbox-activation-secret-change-me":   {}, // pragma: allowlist secret
	"agentarea-dev-sandbox-cleanup-secret-change-me":      {}, // pragma: allowlist secret
	"agentarea-dev-sandbox-file-secret-change-me":         {}, // pragma: allowlist secret
	"agentarea-dev-sandbox-control-secret-change-me":      {}, // pragma: allowlist secret
	"agentarea-dev-mcp-gateway-secret-change-me":          {}, // pragma: allowlist secret
}

// Reject fails when any of Envs holds a value
// that was published in the AgentArea repository.
func Reject() error {
	for _, name := range Envs {
		if _, published := values[os.Getenv(name)]; published {
			return fmt.Errorf("%s is set to a value published in the AgentArea repository; generate a new one (scripts/gen-dev-secrets.sh rotates it) and restart every service that shares it", name)
		}
	}
	return nil
}
