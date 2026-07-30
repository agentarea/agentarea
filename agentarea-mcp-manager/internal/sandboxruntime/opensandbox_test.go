package sandboxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

func TestOpenSandboxProviderUsesOfficialLifecycleAndExecdContracts(t *testing.T) {
	var creates atomic.Int32
	var renews atomic.Int32
	var deletes atomic.Int32
	var server *httptest.Server
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/ping" && r.Header.Get("OPEN-SANDBOX-API-KEY") != "osb-key" && r.Header.Get("X-EXECD-ACCESS-TOKEN") != "osb-key" {
			t.Errorf("missing OpenSandbox authorization on %s", r.URL.Path)
		}
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/v1/sandboxes":
			creates.Add(1)
			var request opensandbox.CreateSandboxRequest
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			if request.Image == nil || request.Image.URI != "agentarea/runtime:allowed" {
				t.Errorf("image = %+v", request.Image)
			}
			if !request.SecureAccess {
				t.Error("secureAccess was not enabled")
			}
			if request.Metadata["agentarea.isolation"] != "gvisor" {
				t.Errorf("isolation metadata = %q", request.Metadata["agentarea.isolation"])
			}
			if request.NetworkPolicy != nil {
				t.Errorf("gVisor host-firewall profile must omit provider network policy: %+v", request.NetworkPolicy)
			}
			if len(request.Volumes) != 1 || request.Volumes[0].PVC == nil {
				t.Fatalf("workspace volume = %+v", request.Volumes)
			}
			if request.Volumes[0].MountPath != WorkspaceRoot ||
				request.Volumes[0].PVC.DeleteOnSandboxTermination == nil ||
				*request.Volumes[0].PVC.DeleteOnSandboxTermination {
				t.Errorf("persistent workspace volume = %+v", request.Volumes[0])
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID:        "osb-1",
				Status:    opensandbox.SandboxStatus{State: opensandbox.StateRunning},
				CreatedAt: time.Now().UTC(),
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1":
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID:        "osb-1",
				Status:    opensandbox.SandboxStatus{State: opensandbox.StateRunning},
				CreatedAt: time.Now().UTC(),
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1/endpoints/44772":
			if r.URL.Query().Get("use_server_proxy") != "true" {
				t.Errorf("use_server_proxy = %q", r.URL.Query().Get("use_server_proxy"))
			}
			_ = json.NewEncoder(w).Encode(opensandbox.Endpoint{Endpoint: server.URL})
		case r.Method == http.MethodGet && r.URL.Path == "/ping":
			w.WriteHeader(http.StatusOK)
		case r.Method == http.MethodPost && r.URL.Path == "/command":
			var request opensandbox.RunCommandRequest
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			validInitialization := request.Cwd == "/" && strings.HasPrefix(request.Command, "mkdir -p -- ")
			validExecution := request.Cwd == WorkspaceRoot && request.Command == "printf ok"
			if !validInitialization && !validExecution {
				t.Errorf("command request = %+v", request)
			}
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte(strings.Join([]string{
				`{"type":"stdout","text":"ok","timestamp":1}`,
				"",
				`{"type":"execution_complete","timestamp":2,"execution_time":7}`,
				"",
			}, "\n")))
		case r.Method == http.MethodPost && r.URL.Path == "/v1/sandboxes/osb-1/renew-expiration":
			renews.Add(1)
			_ = json.NewEncoder(w).Encode(opensandbox.RenewExpirationResponse{ExpiresAt: time.Now().Add(time.Minute)})
		case r.Method == http.MethodDelete && r.URL.Path == "/v1/sandboxes/osb-1":
			deletes.Add(1)
			w.WriteHeader(http.StatusNoContent)
		default:
			http.Error(w, "unexpected "+r.Method+" "+r.URL.String(), http.StatusNotFound)
		}
	})
	server = httptest.NewServer(handler)
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain:         server.URL,
			APIKey:         "osb-key",
			UseServerProxy: true,
		},
		Images:           map[string]string{"allowed": "agentarea/runtime:allowed"},
		LeaseTTL:         time.Minute,
		Isolation:        "gvisor",
		AllowInsecure:    true,
		EgressMode:       "host-public",
		PersistWorkspace: true,
		VolumePrefix:     "test-task",
	})
	if err != nil {
		t.Fatal(err)
	}
	session, err := provider.Create(context.Background(), CreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", PackageInstall: "allowed",
	})
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	result, err := provider.Execute(context.Background(), session, warmpool.ExecuteRequest{
		CommandBody: "printf ok", TimeoutSeconds: 5, StdoutMaxBytes: 1,
	})
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if result.Stdout != "o" || !result.StdoutTruncated || result.ExitCode != 0 || result.ExecutionTimeMs != 7 {
		t.Fatalf("Execute() = %+v", result)
	}
	if _, err := provider.GetFile(context.Background(), session, "/workspace/missing.txt"); !errors.Is(err, ErrFileNotFound) {
		t.Fatalf("GetFile(missing) error = %v, want ErrFileNotFound", err)
	}
	if err := provider.Renew(context.Background(), session, time.Minute); err != nil {
		t.Fatalf("Renew() error = %v", err)
	}
	if err := provider.Delete(context.Background(), session); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if creates.Load() != 1 || renews.Load() != 1 || deletes.Load() != 1 {
		t.Fatalf("calls create=%d renew=%d delete=%d", creates.Load(), renews.Load(), deletes.Load())
	}
}

func TestOpenSandboxProviderRejectsImplicitWeakIsolation(t *testing.T) {
	base := OpenSandboxConfig{
		Connection:    opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:      time.Minute,
		AllowInsecure: true,
		EgressMode:    "provider",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil {
		t.Fatal("missing isolation unexpectedly accepted")
	}
	base.Isolation = "container-dev"
	if _, err := NewOpenSandboxProvider(base); err == nil {
		t.Fatal("weak development isolation unexpectedly accepted without opt-in")
	}
	base.AllowWeakDev = true
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("explicit weak development isolation rejected: %v", err)
	}
}

func TestOpenSandboxGVisorRequiresExplicitHostEgressProfile(t *testing.T) {
	base := OpenSandboxConfig{
		Connection:    opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:      time.Minute,
		AllowInsecure: true,
		Isolation:     "gvisor",
		EgressMode:    "provider",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "incompatible with gVisor") {
		t.Fatalf("provider policy with gVisor error = %v", err)
	}
	base.EgressMode = "host-public"
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("explicit host egress profile rejected: %v", err)
	}
}

func TestOpenSandboxDisabledSecureAccessRequiresServerProxy(t *testing.T) {
	secureAccess := false
	base := OpenSandboxConfig{
		Connection:    opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:      time.Minute,
		AllowInsecure: true,
		SecureAccess:  &secureAccess,
		Isolation:     "gvisor",
		EgressMode:    "host-public",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "requires server proxy") {
		t.Fatalf("disabled secure access without proxy error = %v", err)
	}
	base.Connection.UseServerProxy = true
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("explicit Docker server-proxy mode rejected: %v", err)
	}
}

func TestOpenSandboxHostEgressProfileRejectsLockedSandbox(t *testing.T) {
	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection:    opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		Images:        map[string]string{"locked": "agentarea/runtime:locked"},
		LeaseTTL:      time.Minute,
		AllowInsecure: true,
		Isolation:     "gvisor",
		EgressMode:    "host-public",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = provider.Create(context.Background(), CreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", PackageInstall: "locked",
	})
	if err == nil || !strings.Contains(err.Error(), "refusing weaker isolation") {
		t.Fatalf("locked profile error = %v", err)
	}
}

func TestOpenSandboxLockedProfileDeniesEgressByDefault(t *testing.T) {
	policy := openSandboxNetworkPolicy("locked")
	if policy == nil || policy.DefaultAction != "deny" || len(policy.Egress) != 0 {
		t.Fatalf("locked network policy = %+v", policy)
	}
}

func TestOpenSandboxListUsesLiveWorkspaceFilteredInventory(t *testing.T) {
	expiresAt := time.Now().UTC().Add(time.Hour).Truncate(time.Second)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v1/sandboxes" {
			http.Error(w, "unexpected request", http.StatusNotFound)
			return
		}
		metadata := r.URL.Query().Get("metadata")
		if !strings.Contains(metadata, "agentarea.workspace_id=workspace-1") {
			t.Errorf("metadata filter = %q", metadata)
		}
		_ = json.NewEncoder(w).Encode(opensandbox.ListSandboxesResponse{
			Items: []opensandbox.SandboxInfo{
				{
					ID:        "osb-running",
					Status:    opensandbox.SandboxStatus{State: opensandbox.StateRunning},
					CreatedAt: expiresAt.Add(-time.Hour),
					ExpiresAt: &expiresAt,
					Metadata: map[string]string{
						"agentarea.workspace_id":    "workspace-1",
						"agentarea.task_id":         "task-1",
						"agentarea.package_install": "allowed",
						"agentarea.isolation":       "gvisor",
						"agentarea.resource_cpu":    "750m",
						"agentarea.resource_memory": "1Gi",
					},
				},
				{
					ID:        "osb-terminated",
					Status:    opensandbox.SandboxStatus{State: opensandbox.StateTerminated},
					CreatedAt: expiresAt.Add(-2 * time.Hour),
				},
			},
			Pagination: opensandbox.PaginationInfo{Page: 1, PageSize: 100},
		})
	}))
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection:     opensandbox.ConnectionConfig{Domain: server.URL},
		LeaseTTL:       time.Hour,
		AllowInsecure:  true,
		Isolation:      "gvisor",
		EgressMode:     "host-public",
		ResourceCPU:    "500m",
		ResourceMemory: "512Mi",
	})
	if err != nil {
		t.Fatal(err)
	}
	items, err := provider.List(context.Background(), "workspace-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("items = %+v", items)
	}
	item := items[0]
	if item.ID != "osb-running" || item.TaskID != "task-1" || item.State != "running" {
		t.Fatalf("item = %+v", item)
	}
	if item.Resources["cpu"] != "750m" || item.Resources["memory"] != "1Gi" {
		t.Fatalf("resources = %+v", item.Resources)
	}
}
