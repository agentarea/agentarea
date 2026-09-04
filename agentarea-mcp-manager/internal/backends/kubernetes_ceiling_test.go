package backends

import (
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/config"
)

// The ceiling decides how much of a node one workload may take, and the limits it
// judges arrive in an instance spec. A deployment whose own ceiling is missing or
// unreadable therefore has to refuse the request: continuing would hand that
// decision to whoever wrote the spec, which is the control it was added to keep.
func TestAnUnusableCeilingRefusesTheRequestedLimit(t *testing.T) {
	requested := config.ResourceRequirements{CPU: "64", Memory: "100Gi"}

	for name, allowed := range map[string]config.ResourceRequirements{
		"no ceiling at all": {},
		"malformed memory":  {CPU: "1", Memory: "100 gigabytes"},
		"malformed cpu":     {CPU: "all", Memory: "512Mi"},
		"only cpu declared": {CPU: "1"},
	} {
		if err := ceilingWithin(allowed, requested); err == nil {
			t.Fatalf("%s: an oversized limit was accepted", name)
		}
	}

	// A readable ceiling still admits what fits under it and refuses what does not.
	allowed := config.ResourceRequirements{CPU: "2", Memory: "1Gi"}
	if err := ceilingWithin(allowed, config.ResourceRequirements{CPU: "1", Memory: "512Mi"}); err != nil {
		t.Fatalf("a request under the ceiling was refused: %v", err)
	}
	err := ceilingWithin(allowed, requested)
	if err == nil || !strings.Contains(err.Error(), "exceeds") {
		t.Fatalf("an oversized request was not refused as exceeding the ceiling: %v", err)
	}
}
