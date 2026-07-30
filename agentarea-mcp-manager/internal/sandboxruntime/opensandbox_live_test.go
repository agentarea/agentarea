package sandboxruntime

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// TestOpenSandboxLiveConformance is skipped in normal unit runs. Operators can
// point it at a real OpenSandbox deployment to prove lifecycle, exec, file
// proxying, renewal, live inventory, and persistent task workspace behavior
// through the same adapter used by the manager.
func TestOpenSandboxLiveConformance(t *testing.T) {
	endpoint := os.Getenv("OPENSANDBOX_LIVE_URL")
	if endpoint == "" {
		t.Skip("OPENSANDBOX_LIVE_URL is not set")
	}
	apiKey := os.Getenv("OPENSANDBOX_LIVE_API_KEY")
	image := os.Getenv("OPENSANDBOX_LIVE_IMAGE")
	if apiKey == "" || image == "" {
		t.Fatal("OPENSANDBOX_LIVE_API_KEY and OPENSANDBOX_LIVE_IMAGE are required")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Minute)
	defer cancel()
	secureAccess := false
	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain:         endpoint,
			APIKey:         apiKey,
			AuthHeader:     "OPEN-SANDBOX-API-KEY",
			UseServerProxy: true,
			RequestTimeout: 30 * time.Second,
		},
		Images: map[string]string{
			runtimeinfo.PackageInstallAllowed: image,
		},
		ResourceCPU:      "500m",
		ResourceMemory:   "512Mi",
		LeaseTTL:         2 * time.Minute,
		Isolation:        "gvisor",
		AllowInsecure:    strings.HasPrefix(endpoint, "http://"),
		SecureAccess:     &secureAccess,
		EgressMode:       "host-public",
		PersistWorkspace: true,
		VolumePrefix:     "agentarea-live-smoke",
	})
	if err != nil {
		t.Fatal(err)
	}

	workspaceID := "live-smoke-workspace"
	taskID := "live-smoke-" + strconv.FormatInt(time.Now().UnixNano(), 10)
	create := func() *Session {
		t.Helper()
		session, createErr := provider.Create(ctx, CreateRequest{
			WorkspaceID:    workspaceID,
			TaskID:         taskID,
			PackageInstall: runtimeinfo.PackageInstallAllowed,
		})
		if createErr != nil {
			t.Fatalf("Create() error = %v", createErr)
		}
		t.Logf("sandbox_id=%s task_id=%s", session.ID, taskID)
		return session
	}

	first := create()
	result, err := provider.Execute(ctx, first, warmpool.ExecuteRequest{
		CommandBody:    "printf persistent > persisted.txt && printf agentarea-live",
		TimeoutSeconds: 30,
	})
	if err != nil {
		_ = provider.Delete(context.Background(), first)
		t.Fatalf("Execute() error = %v", err)
	}
	if result.ExitCode != 0 || result.Stdout != "agentarea-live" {
		_ = provider.Delete(context.Background(), first)
		t.Fatalf("Execute() = %+v", result)
	}
	if err := provider.PutFile(ctx, first, WorkspaceRoot+"/upload.txt", []byte("file-roundtrip")); err != nil {
		_ = provider.Delete(context.Background(), first)
		t.Fatalf("PutFile() error = %v", err)
	}
	content, err := provider.GetFile(ctx, first, WorkspaceRoot+"/upload.txt")
	if err != nil || string(content) != "file-roundtrip" {
		_ = provider.Delete(context.Background(), first)
		t.Fatalf("GetFile() content=%q error=%v", content, err)
	}
	if err := provider.Renew(ctx, first, 4*time.Minute); err != nil {
		_ = provider.Delete(context.Background(), first)
		t.Fatalf("Renew() error = %v", err)
	}
	assertLiveSandbox(t, ctx, provider, workspaceID, first.ID)

	if err := provider.Delete(ctx, first); err != nil {
		t.Fatalf("Delete(first) error = %v", err)
	}
	second := create()
	defer func() {
		if err := provider.Delete(context.Background(), second); err != nil {
			t.Errorf("Delete(second) error = %v", err)
		}
	}()
	content, err = provider.GetFile(ctx, second, WorkspaceRoot+"/persisted.txt")
	if err != nil || string(content) != "persistent" {
		t.Fatalf("persistent workspace content=%q error=%v", content, err)
	}
	assertLiveSandbox(t, ctx, provider, workspaceID, second.ID)

	if hold := os.Getenv("OPENSANDBOX_LIVE_HOLD"); hold != "" {
		duration, parseErr := time.ParseDuration(hold)
		if parseErr != nil {
			t.Fatalf("OPENSANDBOX_LIVE_HOLD: %v", parseErr)
		}
		t.Logf("holding sandbox %s for %s for runtime inspection", second.ID, duration)
		select {
		case <-time.After(duration):
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		}
	}
}

func assertLiveSandbox(t *testing.T, ctx context.Context, provider *OpenSandboxProvider, workspaceID, sandboxID string) {
	t.Helper()
	items, err := provider.List(ctx, workspaceID)
	if err != nil {
		t.Fatalf("List() error = %v", err)
	}
	for _, item := range items {
		if item.ID == sandboxID {
			if item.State != strings.ToLower(string(opensandbox.StateRunning)) {
				t.Fatalf("sandbox %s state=%s", sandboxID, item.State)
			}
			if item.ExpiresAt == nil || !item.ExpiresAt.After(time.Now()) {
				t.Fatalf("sandbox %s expiration=%v", sandboxID, item.ExpiresAt)
			}
			return
		}
	}
	t.Fatal(fmt.Errorf("sandbox %s missing from live workspace inventory", sandboxID))
}
