package sandboxruntime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
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
// proxying, renewal, live inventory, and ephemeral task workspace behavior
// through the same adapter used by the manager.
func TestOpenSandboxLiveConformance(t *testing.T) {
	endpoint := os.Getenv("OPENSANDBOX_LIVE_URL")
	if endpoint == "" {
		t.Skip("OPENSANDBOX_LIVE_URL is not set")
	}
	apiKey := os.Getenv("OPENSANDBOX_LIVE_API_KEY")
	image := os.Getenv("OPENSANDBOX_LIVE_IMAGE")
	runtimeIdentity := os.Getenv("OPENSANDBOX_LIVE_RUNTIME_IDENTITY")
	manifestJSON := os.Getenv("OPENSANDBOX_LIVE_MANIFEST")
	if apiKey == "" || image == "" || runtimeIdentity == "" || manifestJSON == "" {
		t.Fatal("OPENSANDBOX_LIVE_API_KEY, OPENSANDBOX_LIVE_IMAGE, OPENSANDBOX_LIVE_RUNTIME_IDENTITY, and OPENSANDBOX_LIVE_MANIFEST are required")
	}
	var manifest runtimeinfo.Manifest
	if err := json.Unmarshal([]byte(manifestJSON), &manifest); err != nil {
		t.Fatalf("OPENSANDBOX_LIVE_MANIFEST: %v", err)
	}
	if err := manifest.Validate(); err != nil {
		t.Fatalf("OPENSANDBOX_LIVE_MANIFEST is invalid: %v", err)
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
		Image:               image,
		ResourceCPU:         "500m",
		ResourceMemory:      "512Mi",
		ResourceStorage:     "2147483648",
		LeaseTTL:            2 * time.Minute,
		Isolation:           "gvisor",
		RuntimeIdentity:     runtimeIdentity,
		AllowInsecure:       strings.HasPrefix(endpoint, "http://"),
		SecureAccess:        &secureAccess,
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		PersistWorkspace:    false,
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
			ProvisioningID: "live-" + taskID,
			Supervisor:     manifest.ExecutionSupervisor,
		})
		if createErr != nil {
			t.Fatalf("Create() error = %v", createErr)
		}
		t.Logf("sandbox_id=%s task_id=%s", session.ID, taskID)
		return session
	}

	first := create()
	deleted := false
	defer func() {
		if !deleted {
			if err := provider.Delete(context.Background(), first); err != nil {
				t.Errorf("Delete() error = %v", err)
			}
		}
	}()
	sandbox, err := provider.connect(ctx, first)
	if err != nil {
		t.Fatalf("connect sandbox for isolation probe: %v", err)
	}
	capabilities, err := sandbox.IsolationCapabilities(ctx)
	if err != nil {
		t.Fatalf("IsolationCapabilities() error = %v", err)
	}
	t.Logf("isolated_execution available=%v isolator=%s version=%s setpriv=%v userns=%v", capabilities.Available, capabilities.Isolator, capabilities.Version, capabilities.SetprivAvailable, capabilities.UsernsAvailable)
	result, err := provider.ExecuteQuiescent(ctx, first, QuiescentExecution{
		Request: warmpool.ExecuteRequest{
			CommandBody:    "printf persistent > persisted.txt && printf agentarea-live",
			TimeoutSeconds: 30,
		},
		Supervisor: manifest.ExecutionSupervisor, MaxFileBytes: 268435456,
	})
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if result.ExitCode != 0 || result.Stdout != "agentarea-live" {
		t.Fatalf("Execute() = %+v", result)
	}
	escapeMarker := WorkspaceRoot + "/escaped-after-return"
	escape, err := provider.ExecuteQuiescent(ctx, first, QuiescentExecution{
		Request: warmpool.ExecuteRequest{
			CommandBody:    "setsid /bin/sh -c 'sleep 1; printf escaped > " + escapeMarker + "' >/dev/null 2>&1 & printf quiescent",
			TimeoutSeconds: 30,
		},
		Supervisor: manifest.ExecutionSupervisor, MaxFileBytes: 268435456,
	})
	if err != nil || escape.ExitCode != 0 || escape.Stdout != "quiescent" {
		t.Fatalf("detached-process execution = %+v, %v", escape, err)
	}
	time.Sleep(1500 * time.Millisecond)
	if leaked, err := provider.OpenFile(ctx, first, escapeMarker); leaked != nil || !errors.Is(err, ErrFileNotFound) {
		if leaked != nil {
			_ = leaked.Content.Close()
		}
		t.Fatalf("detached process mutated workspace after ExecuteQuiescent returned: file=%v error=%v", leaked, err)
	}
	digest := sha256.Sum256([]byte("file-roundtrip"))
	if err := provider.PutFile(ctx, first, FileUpload{
		Path: WorkspaceRoot + "/upload.txt", Size: int64(len("file-roundtrip")), SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, strings.NewReader("file-roundtrip")); err != nil {
		t.Fatalf("PutFile() error = %v", err)
	}
	download, err := provider.OpenFile(ctx, first, WorkspaceRoot+"/upload.txt")
	if err != nil {
		t.Fatalf("OpenFile() error=%v", err)
	}
	content, err := io.ReadAll(download.Content)
	download.Content.Close()
	if err != nil || string(content) != "file-roundtrip" {
		t.Fatalf("GetFile() content=%q error=%v", content, err)
	}
	usage, err := provider.AuditWorkspace(ctx, first)
	if err != nil {
		t.Fatalf("AuditWorkspace() error = %v", err)
	}
	if usage != (WorkspaceUsage{Entries: 2, TotalBytes: 24, LargestBytes: 14}) {
		t.Fatalf("AuditWorkspace() = %+v", usage)
	}
	if err := provider.Renew(ctx, first, 4*time.Minute); err != nil {
		t.Fatalf("Renew() error = %v", err)
	}
	assertLiveSandbox(t, ctx, provider, workspaceID, first.ID)

	if hold := os.Getenv("OPENSANDBOX_LIVE_HOLD"); hold != "" {
		duration, parseErr := time.ParseDuration(hold)
		if parseErr != nil {
			t.Fatalf("OPENSANDBOX_LIVE_HOLD: %v", parseErr)
		}
		t.Logf("holding sandbox %s for %s for runtime inspection", first.ID, duration)
		select {
		case <-time.After(duration):
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		}
	}
	if err := provider.Delete(context.Background(), first); err != nil {
		t.Errorf("Delete() error = %v", err)
	} else {
		deleted = true
	}
	assertLiveSandboxAbsent(t, ctx, provider, workspaceID, first.ID)
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

func assertLiveSandboxAbsent(t *testing.T, ctx context.Context, provider *OpenSandboxProvider, workspaceID, sandboxID string) {
	t.Helper()
	items, err := provider.List(ctx, workspaceID)
	if err != nil {
		t.Fatalf("List() after delete error = %v", err)
	}
	for _, item := range items {
		if item.ID == sandboxID {
			t.Fatalf("deleted sandbox %s remains in live inventory", sandboxID)
		}
	}
}
