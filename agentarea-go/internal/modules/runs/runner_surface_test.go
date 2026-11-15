package runs

import (
	"slices"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

type tokens struct{}

func (*tokens) Issue(authn.TurnClaims, time.Duration) (string, error) { return "", nil }
func (*tokens) Decode(string) (authn.TurnClaims, bool)                { return authn.TurnClaims{}, false }

func TestRunnerRoutesNeedTheGatewaySecret(t *testing.T) {
	var unset *tokens
	missing := NewRunnerSurface(RunnerDeps{Tokens: unset}).Missing()
	if !slices.Contains(missing, "turn tokens (AGENTAREA_MCP_GATEWAY_SECRET)") || !slices.Contains(missing, "live turns") {
		t.Fatalf("a nil token issuer counts as present: %v", missing)
	}
	if got := NewRunnerSurface(RunnerDeps{Tokens: &tokens{}}).Missing(); slices.Contains(got, "turn tokens (AGENTAREA_MCP_GATEWAY_SECRET)") {
		t.Fatalf("a token issuer counts as missing: %v", got)
	}
}
