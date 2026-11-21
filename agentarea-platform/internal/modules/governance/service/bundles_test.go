package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func TestSameJSONWireObjects(t *testing.T) {
	stored := wirejson.Object{{Key: "approvers", Value: []any{"user:a"}}, {Key: "n", Value: 1}}
	wanted := wirejson.Object{{Key: "n", Value: 1.0}, {Key: "approvers", Value: []any{"user:a"}}}
	if same, err := sameJSON(stored, wanted); err != nil || !same {
		t.Fatalf("sameJSON = %v, %v", same, err)
	}
	if same, _ := sameJSON(wirejson.Object{}, wirejson.Object{{Key: "n", Value: 1}}); same {
		t.Fatal("different params compared equal")
	}
}

func TestBundleRulesRuleProblem(t *testing.T) {
	approver := []any{"user:3f2b8c1e-9d4a-4c55-8a1e-6b7d2f0c9a11"}
	for name, tc := range map[string]struct {
		effect string
		params wirejson.Object
		bad    bool
	}{
		"approval without params":   {"approval", wirejson.Object{}, false},
		"approval with approver":    {"approval", wirejson.Object{{Key: "approvers", Value: approver}}, false},
		"approval with unknown key": {"approval", wirejson.Object{{Key: "nope", Value: true}}, true},
		"cap without params":        {"cap", wirejson.Object{}, true},
	} {
		t.Run(name, func(t *testing.T) {
			got := BundleRules{}.RuleProblem(catalogapi.BundleRule{Enabled: true, SubjectType: "workspace", SubjectID: "ws", Target: "tool:mcp:telegram:*", Effect: tc.effect, Params: tc.params})
			if (got != "") != tc.bad {
				t.Fatalf("RuleProblem = %q, want problem=%v", got, tc.bad)
			}
		})
	}
}
