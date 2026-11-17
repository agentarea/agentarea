package app

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

func TestAWorkloadHookSeesTheExitTheInstanceLeavesThrough(t *testing.T) {
	var seen ext.MCPWorkload
	var rd runtime.Deps
	applyWorkloadHooks(&rd, []ext.WorkloadHooks{{MCPWorkload: func(_ context.Context, _, _ string, w *ext.MCPWorkload) error {
		seen = *w
		w.Environment = map[string]string{"HTTPS_PROXY": "http://mcp:t@proxy:3128"}
		w.Labels = map[string]string{"agentarea.io/egress": "exit"}
		return nil
	}}})
	spec := workload.Spec{EgressExit: "exit-1", EgressRequired: true, Environment: map[string]string{}}
	if err := rd.SpecHook(context.Background(), "inst", "ws", &spec); err != nil {
		t.Fatal(err)
	}
	if seen.EgressExit != "exit-1" || !seen.EgressRequired {
		t.Fatalf("hook saw %+v", seen)
	}
	if spec.Environment["HTTPS_PROXY"] == "" || spec.Labels["agentarea.io/egress"] != "exit" {
		t.Fatalf("spec %+v", spec)
	}
}

func TestAnExtensionReadsAWorkspaceSecretByName(t *testing.T) {
	ctx := context.Background()
	d := pulseDB(t)
	f, err := secrets.NewFactory(ksecrets.Config{Backend: ksecrets.BackendDatabase, EncryptionKey: "48pCGWLB98XVpxnYbIedmj9j43n2SXLAu8oCQePXx1g="}, http.DefaultClient)
	if err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		return f.Manager(s, "u1").Set(ctx, "proxy-password", "hunter2")
	}); err != nil {
		t.Fatal(err)
	}
	var lookup ext.WorkspaceSecrets = workspaceSecrets{db: d, secrets: f}
	if v, err := lookup.WorkspaceSecret(ctx, ws.ID(), "proxy-password"); err != nil || v != "hunter2" {
		t.Fatalf("secret = %q %v", v, err)
	}
	if _, err := lookup.WorkspaceSecret(ctx, uuid.NewString(), "proxy-password"); !errors.Is(err, ksecrets.ErrNotFound) {
		t.Fatalf("another workspace's secret: %v", err)
	}
}
