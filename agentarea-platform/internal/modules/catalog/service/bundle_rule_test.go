package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// governance only accepts wirejson.Object as params.
func TestPolicyAsRuleParamsAreWireObjects(t *testing.T) {
	for name, params := range map[string]wirejson.Object{
		"absent":  nil,
		"present": {{Key: "approvers", Value: []any{"user:u"}}},
	} {
		t.Run(name, func(t *testing.T) {
			r := policyAsRule(BundlePolicy{Target: "tool:x", Effect: "approval", Params: params}, "agent-1")
			if _, ok := any(r.Params).(wirejson.Object); !ok {
				t.Fatalf("Params is %T, want wirejson.Object", r.Params)
			}
		})
	}
}
