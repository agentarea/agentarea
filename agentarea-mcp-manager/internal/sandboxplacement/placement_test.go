package sandboxplacement

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// stubExecutor is a no-op data plane used to assert routing without running code.
type stubExecutor struct{ id string }

func (s *stubExecutor) ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	return &warmpool.ExecuteResponse{}, nil
}

func TestNewRegistryValidation(t *testing.T) {
	exec := &stubExecutor{}
	cases := []struct {
		name    string
		targets []Target
		wantErr string
	}{
		{name: "no targets", targets: nil, wantErr: "at least one target"},
		{
			name:    "missing name",
			targets: []Target{{Executor: exec, Capabilities: Capabilities{Region: "eu"}}},
			wantErr: "must have a name",
		},
		{
			name:    "nil executor",
			targets: []Target{{Capabilities: Capabilities{Name: "eu"}}},
			wantErr: "has no executor",
		},
		{
			name: "duplicate names",
			targets: []Target{
				{Executor: exec, Capabilities: Capabilities{Name: "dup", Region: "eu"}},
				{Executor: exec, Capabilities: Capabilities{Name: "dup", Region: "us"}},
			},
			wantErr: "duplicate sandbox placement target name",
		},
		{
			name: "duplicate region",
			targets: []Target{
				{Executor: exec, Capabilities: Capabilities{Name: "a", Region: "eu-central"}},
				{Executor: exec, Capabilities: Capabilities{Name: "b", Region: "eu-central"}},
			},
			wantErr: "duplicate sandbox placement target region",
		},
		{
			name: "duplicate empty region",
			targets: []Target{
				{Executor: exec, Capabilities: Capabilities{Name: "a"}},
				{Executor: exec, Capabilities: Capabilities{Name: "b"}},
			},
			wantErr: "duplicate sandbox placement target region",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewRegistry(tc.targets...)
			if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
				t.Fatalf("NewRegistry error = %v, want containing %q", err, tc.wantErr)
			}
		})
	}
}

func TestSelectSingleTargetNoConstraints(t *testing.T) {
	exec := &stubExecutor{id: "only"}
	reg, err := NewRegistry(Target{Executor: exec, Capabilities: Capabilities{Name: "default"}})
	if err != nil {
		t.Fatalf("NewRegistry: %v", err)
	}
	target, err := reg.Select(context.Background(), Constraints{})
	if err != nil {
		t.Fatalf("Select: %v", err)
	}
	if target.Executor.(*stubExecutor) != exec {
		t.Fatalf("Select returned the wrong executor")
	}
}

func TestSelectByRegion(t *testing.T) {
	eu := &stubExecutor{id: "eu"}
	us := &stubExecutor{id: "us"}
	reg, err := NewRegistry(
		Target{Executor: eu, Capabilities: Capabilities{Name: "k8s-eu", Region: "eu-central"}},
		Target{Executor: us, Capabilities: Capabilities{Name: "k8s-us", Region: "us-east"}},
	)
	if err != nil {
		t.Fatalf("NewRegistry: %v", err)
	}

	target, err := reg.Select(context.Background(), Constraints{Region: "us-east"})
	if err != nil {
		t.Fatalf("Select us-east: %v", err)
	}
	if target.Executor.(*stubExecutor) != us {
		t.Fatalf("region routing picked %q, want us", target.Capabilities.Name)
	}

	target, err = reg.Select(context.Background(), Constraints{Region: "eu-central"})
	if err != nil {
		t.Fatalf("Select eu-central: %v", err)
	}
	if target.Executor.(*stubExecutor) != eu {
		t.Fatalf("region routing picked %q, want eu", target.Capabilities.Name)
	}
}

// A task pinned to a region with no matching target must fail rather than run in
// the wrong region — the residency invariant and the no-silent-fallback rule.
func TestSelectUnsatisfiableRegionFailsHard(t *testing.T) {
	eu := &stubExecutor{id: "eu"}
	reg, err := NewRegistry(Target{Executor: eu, Capabilities: Capabilities{Name: "k8s-eu", Region: "eu-central"}})
	if err != nil {
		t.Fatalf("NewRegistry: %v", err)
	}
	_, err = reg.Select(context.Background(), Constraints{Region: "us-east"})
	if err == nil {
		t.Fatal("expected Select to fail for an unsatisfiable region, got nil")
	}
	if !errors.Is(err, ErrNoEligibleTarget) {
		t.Fatalf("Select error = %v, want ErrNoEligibleTarget sentinel", err)
	}
}

// Asymmetric matching: a non-empty region constraint must NOT be satisfied by a
// target that declares no region. An undeclared-region target is not a wildcard;
// treating it as one would be the exact silent residency bypass we guard against.
func TestSelectNonEmptyRegionRejectsUndeclaredTarget(t *testing.T) {
	exec := &stubExecutor{}
	reg, err := NewRegistry(Target{Executor: exec, Capabilities: Capabilities{Name: "default"}})
	if err != nil {
		t.Fatalf("NewRegistry: %v", err)
	}
	if _, err := reg.Select(context.Background(), Constraints{Region: "eu-central"}); !errors.Is(err, ErrNoEligibleTarget) {
		t.Fatalf("a region-pinned task must not run on an undeclared-region target; err = %v", err)
	}
	// The same target still serves an unconstrained task.
	if _, err := reg.Select(context.Background(), Constraints{}); err != nil {
		t.Fatalf("unconstrained task should match the default target: %v", err)
	}
}

func TestTargetsExposesCapabilities(t *testing.T) {
	reg, err := NewRegistry(
		Target{Executor: &stubExecutor{}, Capabilities: Capabilities{Name: "k8s-eu", Region: "eu-central"}},
		Target{Executor: &stubExecutor{}, Capabilities: Capabilities{Name: "hostpool-us", Region: "us-east"}},
	)
	if err != nil {
		t.Fatalf("NewRegistry: %v", err)
	}
	caps := reg.Targets()
	if len(caps) != 2 || caps[0].Name != "k8s-eu" || caps[1].Region != "us-east" {
		t.Fatalf("Targets() = %+v, want the two registered capabilities in declaration order", caps)
	}
}
