package sandboxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

func TestOpenSandboxProviderUsesOfficialLifecycleAndExecdContracts(t *testing.T) {
	const image = "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const runtimeIdentity = "opensandbox-docker-gvisor-runsc-20260721"
	var creates atomic.Int32
	var renews atomic.Int32
	var deletes atomic.Int32
	var createdMetadata map[string]string
	var executionStatusPath string
	statusBody := testSupervisorStatus(0)
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
			if request.Image == nil || request.Image.URI != image {
				t.Errorf("image = %+v", request.Image)
			}
			if !request.SecureAccess {
				t.Error("secureAccess was not enabled")
			}
			if request.Metadata["agentarea.isolation"] != "gvisor" {
				t.Errorf("isolation metadata = %q", request.Metadata["agentarea.isolation"])
			}
			if request.Metadata["agentarea.runtime_identity"] != runtimeIdentity {
				t.Errorf("runtime identity metadata = %q", request.Metadata["agentarea.runtime_identity"])
			}
			if request.NetworkPolicy != nil {
				t.Errorf("gVisor host-firewall profile must omit provider network policy: %+v", request.NetworkPolicy)
			}
			if len(request.Volumes) != 0 {
				t.Errorf("ephemeral sandbox unexpectedly requested volumes: %+v", request.Volumes)
			}
			createdMetadata = request.Metadata
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID:        "osb-1",
				Image:     &opensandbox.ImageSpec{URI: image},
				Metadata:  request.Metadata,
				Status:    opensandbox.SandboxStatus{State: opensandbox.StateRunning},
				CreatedAt: time.Now().UTC(),
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1":
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID:        "osb-1",
				Image:     &opensandbox.ImageSpec{URI: image},
				Metadata:  createdMetadata,
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
		case r.Method == http.MethodPost && r.URL.Path == "/directories":
			var request map[string]map[string]int
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			if request[WorkspaceRoot]["mode"] != 700 {
				t.Errorf("workspace directory request = %+v", request)
			}
			w.WriteHeader(http.StatusOK)
		case r.Method == http.MethodGet && r.URL.Path == "/directories/list":
			if r.URL.Query().Get("path") != WorkspaceRoot || r.URL.Query().Get("depth") != "1" {
				t.Errorf("workspace list query = %s", r.URL.RawQuery)
			}
			_ = json.NewEncoder(w).Encode([]opensandbox.FileInfo{})
		case r.Method == http.MethodGet && r.URL.Path == "/files/info":
			requested := r.URL.Query().Get("path")
			switch requested {
			case testSupervisorAttestation().Path:
				_ = json.NewEncoder(w).Encode(map[string]opensandbox.FileInfo{requested: {
					Path: requested, Type: "file", Size: int64(len(testSupervisorBinary)), Owner: "root", Group: "root", Mode: 755,
				}})
			case executionStatusPath:
				_ = json.NewEncoder(w).Encode(map[string]opensandbox.FileInfo{requested: {
					Path: requested, Type: "file", Size: int64(len(statusBody)), Owner: "root", Group: "root", Mode: 600,
				}})
			default:
				http.NotFound(w, r)
			}
		case r.Method == http.MethodGet && r.URL.Path == "/files/download":
			requested := r.URL.Query().Get("path")
			switch requested {
			case testSupervisorAttestation().Path:
				_, _ = w.Write(testSupervisorBinary)
			case executionStatusPath:
				_, _ = w.Write(statusBody)
			default:
				http.NotFound(w, r)
			}
		case r.Method == http.MethodDelete && r.URL.Path == "/files":
			if got := r.URL.Query().Get("path"); got != executionStatusPath {
				t.Errorf("deleted status path = %q", got)
			}
			w.WriteHeader(http.StatusNoContent)
		case r.Method == http.MethodPost && r.URL.Path == "/command":
			var request opensandbox.RunCommandRequest
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			validAttestation := request.Cwd == "/" && request.Command == "/bin/cat -- /proc/version"
			validExecution := request.Cwd == WorkspaceRoot && strings.Contains(request.Command, testSupervisorAttestation().Path)
			if !validAttestation && !validExecution {
				t.Errorf("command request = %+v", request)
			}
			if validExecution {
				executionStatusPath = supervisorStatusPathFromShell(request.Command)
				if executionStatusPath == "" || request.UID == nil || *request.UID != 0 || request.GID == nil || *request.GID != 0 {
					t.Errorf("unsupervised execution request = %+v", request)
				}
			}
			stdout := "ok"
			if validAttestation {
				stdout = "Linux version 4.4.0 (gVisor)"
			}
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte(strings.Join([]string{
				fmt.Sprintf(`{"type":"stdout","text":%q,"timestamp":1}`, stdout),
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
		Image:               image,
		ResourceStorage:     "2147483648",
		LeaseTTL:            time.Minute,
		Isolation:           "gvisor",
		RuntimeIdentity:     runtimeIdentity,
		AllowInsecure:       true,
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		PersistWorkspace:    false,
	})
	if err != nil {
		t.Fatal(err)
	}
	session, err := provider.Create(context.Background(), CreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
		Supervisor: testSupervisorAttestation(),
	})
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	result, err := provider.ExecuteQuiescent(context.Background(), session, testQuiescentExecution(warmpool.ExecuteRequest{
		CommandBody: "printf ok", TimeoutSeconds: 5, StdoutMaxBytes: 1,
	}))
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if result.Stdout != "o" || !result.StdoutTruncated || result.ExitCode != 0 || result.ExecutionTimeMs != 7 {
		t.Fatalf("Execute() = %+v", result)
	}
	statusBody = []byte(`{"protocol_version":1,"quiescent":true,"child_exit_code":0}`)
	if _, err := provider.ExecuteQuiescent(context.Background(), session, testQuiescentExecution(warmpool.ExecuteRequest{
		CommandBody: "printf ok", TimeoutSeconds: 5,
	})); err == nil || !strings.Contains(err.Error(), "status") {
		t.Fatalf("ExecuteQuiescent() error = %v, want authenticated-status failure", err)
	}
	statusBody = testSupervisorStatus(0)
	if _, err := provider.OpenFile(context.Background(), session, "/workspace/missing.txt"); !errors.Is(err, ErrFileNotFound) {
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

func TestOpenSandboxCreateDoesNotRetryNonIdempotentRequest(t *testing.T) {
	var creates atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/sandboxes" {
			http.Error(w, "unexpected request", http.StatusNotFound)
			return
		}
		creates.Add(1)
		http.Error(w, "ambiguous create failure", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	retry := opensandbox.DefaultRetryConfig()
	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain: server.URL, RequestTimeout: time.Second, Retry: &retry,
		},
		Image:    "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		LeaseTTL: time.Hour, AllowInsecure: true, Isolation: "gvisor",
		RuntimeIdentity: "runsc-release", EgressMode: "host-public", AllowInternetAccess: true, ResourceStorage: "2147483648",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.Create(context.Background(), CreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
		Supervisor: testSupervisorAttestation(),
	}); err == nil {
		t.Fatal("Create() unexpectedly succeeded")
	}
	if got := creates.Load(); got != 1 {
		t.Fatalf("create POSTs = %d, want exactly one", got)
	}
}

func TestOpenSandboxDeleteUsesLifecycleAPIWithoutExecdResolution(t *testing.T) {
	var endpointCalls atomic.Int32
	var deletes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodDelete && r.URL.Path == "/v1/sandboxes/osb-1":
			deletes.Add(1)
			w.WriteHeader(http.StatusNoContent)
		case r.URL.Path == "/v1/sandboxes/osb-1/endpoints/44772":
			endpointCalls.Add(1)
			http.Error(w, "execd unavailable", http.StatusServiceUnavailable)
		default:
			http.Error(w, "unexpected request", http.StatusNotFound)
		}
	}))
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection:          opensandbox.ConnectionConfig{Domain: server.URL},
		LeaseTTL:            time.Minute,
		AllowInsecure:       true,
		Isolation:           "gvisor",
		RuntimeIdentity:     "runsc-release",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceStorage:     "2147483648",
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := provider.Delete(context.Background(), &Session{ID: "osb-1"}); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if endpointCalls.Load() != 0 || deletes.Load() != 1 {
		t.Fatalf("endpoint calls=%d deletes=%d, want lifecycle delete only", endpointCalls.Load(), deletes.Load())
	}
}

func TestOpenSandboxRejectsDifferentDigestFromControlPlane(t *testing.T) {
	const expectedImage = "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const actualImage = "agentarea/runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	var metadata map[string]string
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/v1/sandboxes":
			var request opensandbox.CreateSandboxRequest
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			metadata = request.Metadata
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID: "osb-1", Image: &opensandbox.ImageSpec{URI: expectedImage}, Metadata: metadata,
				Status: opensandbox.SandboxStatus{State: opensandbox.StateRunning},
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1":
			_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
				ID: "osb-1", Image: &opensandbox.ImageSpec{URI: actualImage}, Metadata: metadata,
				Status: opensandbox.SandboxStatus{State: opensandbox.StateRunning},
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1/endpoints/44772":
			_ = json.NewEncoder(w).Encode(opensandbox.Endpoint{Endpoint: server.URL})
		case r.Method == http.MethodGet && r.URL.Path == "/ping":
			w.WriteHeader(http.StatusOK)
		default:
			http.Error(w, "unexpected request", http.StatusNotFound)
		}
	}))
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection:          opensandbox.ConnectionConfig{Domain: server.URL},
		Image:               expectedImage,
		LeaseTTL:            time.Minute,
		AllowInsecure:       true,
		Isolation:           "gvisor",
		RuntimeIdentity:     "runsc-release",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceStorage:     "2147483648",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = provider.Create(context.Background(), CreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
		Supervisor: testSupervisorAttestation(),
	})
	if err == nil || !strings.Contains(err.Error(), "bound image") {
		t.Fatalf("Create() error = %v, want strict digest mismatch", err)
	}
}

func TestOpenSandboxTagReadbackRequiresExactHostImageAttestation(t *testing.T) {
	const expectedImage = "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const providerReadback = "agentarea/runtime:release-1"
	for _, test := range []struct {
		name           string
		inspectionCode int
		inspectionBody string
		wantError      string
	}{
		{
			name:           "exact immutable engine reference",
			inspectionCode: http.StatusOK,
			inspectionBody: "Container ID: osb-1\nImage:          " + expectedImage + "\nStatus: running\n",
		},
		{
			name:           "different digest",
			inspectionCode: http.StatusOK,
			inspectionBody: "Image: agentarea/runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n",
			wantError:      "host bound image",
		},
		{
			name:           "diagnostics unavailable",
			inspectionCode: http.StatusNotFound,
			wantError:      "attest OpenSandbox host image",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			var metadata map[string]string
			var server *httptest.Server
			server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case r.Method == http.MethodPost && r.URL.Path == "/v1/sandboxes":
					var request opensandbox.CreateSandboxRequest
					if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
						t.Error(err)
					}
					if request.Image == nil || request.Image.URI != expectedImage {
						t.Errorf("create image = %+v", request.Image)
					}
					metadata = request.Metadata
					w.WriteHeader(http.StatusCreated)
					_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
						ID: "osb-1", Image: &opensandbox.ImageSpec{URI: providerReadback}, Metadata: metadata,
						Status: opensandbox.SandboxStatus{State: opensandbox.StateRunning},
					})
				case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1":
					_ = json.NewEncoder(w).Encode(opensandbox.SandboxInfo{
						ID: "osb-1", Image: &opensandbox.ImageSpec{URI: providerReadback}, Metadata: metadata,
						Status: opensandbox.SandboxStatus{State: opensandbox.StateRunning},
					})
				case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1/diagnostics/inspect":
					w.WriteHeader(test.inspectionCode)
					_, _ = w.Write([]byte(test.inspectionBody))
				case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1/endpoints/44772":
					_ = json.NewEncoder(w).Encode(opensandbox.Endpoint{Endpoint: server.URL})
				case r.Method == http.MethodGet && r.URL.Path == "/ping":
					w.WriteHeader(http.StatusOK)
				case r.Method == http.MethodGet && r.URL.Path == "/files/info" && r.URL.Query().Get("path") == testSupervisorAttestation().Path:
					_ = json.NewEncoder(w).Encode(map[string]opensandbox.FileInfo{
						testSupervisorAttestation().Path: {
							Path: testSupervisorAttestation().Path, Type: "file", Size: int64(len(testSupervisorBinary)),
							Owner: "root", Group: "root", Mode: 755,
						},
					})
				case r.Method == http.MethodGet && r.URL.Path == "/files/download" && r.URL.Query().Get("path") == testSupervisorAttestation().Path:
					_, _ = w.Write(testSupervisorBinary)
				case r.Method == http.MethodPost && r.URL.Path == "/command":
					w.Header().Set("Content-Type", "text/event-stream")
					_, _ = w.Write([]byte("{\"type\":\"stdout\",\"text\":\"Linux version 4.4.0 (gVisor)\",\"timestamp\":1}\n\n{\"type\":\"execution_complete\",\"timestamp\":2}\n\n"))
				case r.Method == http.MethodPost && r.URL.Path == "/directories":
					w.WriteHeader(http.StatusOK)
				case r.Method == http.MethodGet && r.URL.Path == "/directories/list":
					_ = json.NewEncoder(w).Encode([]opensandbox.FileInfo{})
				default:
					http.Error(w, "unexpected request", http.StatusNotFound)
				}
			}))
			defer server.Close()

			provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
				Connection:          opensandbox.ConnectionConfig{Domain: server.URL},
				Image:               expectedImage,
				LeaseTTL:            time.Minute,
				AllowInsecure:       true,
				Isolation:           "gvisor",
				RuntimeIdentity:     "runsc-release",
				EgressMode:          "host-public",
				AllowInternetAccess: true,
				ResourceStorage:     "2147483648",
			})
			if err != nil {
				t.Fatal(err)
			}
			_, err = provider.Create(context.Background(), CreateRequest{
				WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
				Supervisor: testSupervisorAttestation(),
			})
			if test.wantError == "" && err != nil {
				t.Fatalf("Create() error = %v", err)
			}
			if test.wantError != "" && (err == nil || !strings.Contains(err.Error(), test.wantError)) {
				t.Fatalf("Create() error = %v, want %q", err, test.wantError)
			}
		})
	}
}

func TestSameImmutableOCIImage(t *testing.T) {
	tests := map[string]struct {
		actual   string
		expected string
		want     bool
	}{
		"exact digest": {
			actual:   "registry.example:5000/agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			expected: "registry.example:5000/agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			want:     true,
		},
		"provider tag readback is not an attestation": {
			actual:   "registry.example:5000/agentarea/runtime:release",
			expected: "registry.example:5000/agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		},
		"different digest": {
			actual:   "agentarea/runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
			expected: "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		},
		"different repository": {
			actual:   "attacker/runtime:release",
			expected: "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		},
		"unpinned expectation": {
			actual:   "agentarea/runtime:release",
			expected: "agentarea/runtime:release",
		},
	}
	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			if got := sameImmutableOCIImage(test.actual, test.expected); got != test.want {
				t.Fatalf("sameImmutableOCIImage(%q, %q) = %t, want %t", test.actual, test.expected, got, test.want)
			}
		})
	}
}

func TestOpenSandboxHostInspectionRejectsRedirectWithoutLeakingCredential(t *testing.T) {
	var redirected atomic.Bool
	credentialSink := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirected.Store(true)
		if credential := r.Header.Get("OPEN-SANDBOX-API-KEY"); credential != "" {
			t.Errorf("cross-origin redirect leaked OpenSandbox credential %q", credential)
		}
		_, _ = w.Write([]byte("Image: agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"))
	}))
	defer credentialSink.Close()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, credentialSink.URL+"/stolen", http.StatusTemporaryRedirect)
	}))
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain: server.URL, APIKey: "must-not-leak",
		},
		Image:    "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		LeaseTTL: time.Minute, AllowInsecure: true, Isolation: "gvisor",
		RuntimeIdentity: "runsc-release", EgressMode: "host-public", AllowInternetAccess: true, ResourceStorage: "2147483648",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.inspectSandboxImage(context.Background(), "osb-1"); err == nil || !strings.Contains(err.Error(), "HTTP 307") {
		t.Fatalf("inspectSandboxImage() error = %v, want redirect rejection", err)
	}
	if redirected.Load() {
		t.Fatal("diagnostics client followed a cross-origin redirect")
	}
}

func TestOpenSandboxAuditUsesAuthenticatedFilesystemAPI(t *testing.T) {
	var commandCalls atomic.Int32
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/v1/sandboxes/osb-1/endpoints/44772":
			_ = json.NewEncoder(w).Encode(opensandbox.Endpoint{Endpoint: server.URL})
		case r.Method == http.MethodGet && r.URL.Path == "/ping":
			w.WriteHeader(http.StatusOK)
		case r.Method == http.MethodGet && r.URL.Path == "/directories/list":
			directory := r.URL.Query().Get("path")
			if r.URL.Query().Get("depth") != "1" {
				t.Errorf("depth = %q", r.URL.Query().Get("depth"))
			}
			entries := map[string][]opensandbox.FileInfo{
				WorkspaceRoot: {
					{Path: WorkspaceRoot + "/input.txt", Type: "file", Size: 5},
					{Path: WorkspaceRoot + "/nested", Type: "directory"},
				},
				WorkspaceRoot + "/nested": {
					{Path: WorkspaceRoot + "/nested/result.bin", Type: "file", Size: 12},
				},
			}
			_ = json.NewEncoder(w).Encode(entries[directory])
		case r.Method == http.MethodPost && r.URL.Path == "/command":
			commandCalls.Add(1)
			http.Error(w, "workspace audit must not execute guest commands", http.StatusInternalServerError)
		default:
			http.Error(w, "unexpected "+r.Method+" "+r.URL.String(), http.StatusNotFound)
		}
	}))
	defer server.Close()

	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain: server.URL, APIKey: "osb-key", UseServerProxy: true,
		},
		Image:               "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ResourceStorage:     "2147483648",
		LeaseTTL:            time.Minute,
		Isolation:           "gvisor",
		RuntimeIdentity:     "opensandbox-docker-gvisor-runsc-20260721",
		AllowInsecure:       true,
		EgressMode:          "host-public",
		AllowInternetAccess: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	usage, err := provider.AuditWorkspace(context.Background(), &Session{ID: "osb-1"})
	if err != nil {
		t.Fatalf("AuditWorkspace() error = %v", err)
	}
	if usage != (WorkspaceUsage{Entries: 3, TotalBytes: 17, LargestBytes: 12}) {
		t.Fatalf("AuditWorkspace() = %+v", usage)
	}
	if commandCalls.Load() != 0 {
		t.Fatalf("workspace audit executed %d guest commands", commandCalls.Load())
	}
}

func TestOpenSandboxProviderRejectsUnmanagedPersistentWorkspace(t *testing.T) {
	_, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection:          opensandbox.ConnectionConfig{Domain: "https://opensandbox.example"},
		LeaseTTL:            time.Minute,
		Isolation:           "gvisor",
		RuntimeIdentity:     "opensandbox-docker-gvisor-runsc-20260721",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		PersistWorkspace:    true,
		ResourceStorage:     "2147483648",
	})
	if err == nil || !strings.Contains(err.Error(), "persistent workspaces are disabled") {
		t.Fatalf("NewOpenSandboxProvider() error = %v", err)
	}
}

func TestOpenSandboxFileModeTranslation(t *testing.T) {
	for _, test := range []struct {
		name string
		mode int
		api  int
	}{
		{name: "owner read write", mode: 0o600, api: 600},
		{name: "executable", mode: 0o755, api: 755},
		{name: "provider neutral default", mode: 0, api: 600},
	} {
		t.Run(test.name, func(t *testing.T) {
			encoded, err := openSandboxModeToAPI(os.FileMode(test.mode))
			if err != nil {
				t.Fatal(err)
			}
			if encoded != test.api {
				t.Fatalf("openSandboxModeToAPI(%#o) = %d, want %d", test.mode, encoded, test.api)
			}
			decoded, err := openSandboxModeFromAPI(test.api)
			if err != nil {
				t.Fatal(err)
			}
			if decoded.Perm() != os.FileMode(test.mode).Perm() && test.mode != 0 {
				t.Fatalf("openSandboxModeFromAPI(%d) = %#o, want %#o", test.api, decoded.Perm(), test.mode)
			}
		})
	}
	for _, invalid := range []int{-1, 384, 888, 1000} {
		if _, err := openSandboxModeFromAPI(invalid); err == nil {
			t.Fatalf("openSandboxModeFromAPI(%d) unexpectedly succeeded", invalid)
		}
	}
}

func TestOpenSandboxProviderRejectsImplicitWeakIsolation(t *testing.T) {
	base := OpenSandboxConfig{
		Connection:      opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:        time.Minute,
		AllowInsecure:   true,
		EgressMode:      "provider",
		ResourceStorage: "2147483648",
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

// The RU deployment exposes the lifecycle API over HTTPS only, while
// server-proxy endpoints come back without a scheme. If the SDK restores the
// wrong one, a 301 rewrites streaming POSTs such as /command into GETs and the
// command silently returns nothing.
func TestOpenSandboxProviderDerivesProxyProtocolFromDomain(t *testing.T) {
	base := OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{
			Domain:         "https://opensandbox.example.com",
			UseServerProxy: true,
		},
		LeaseTTL:            time.Minute,
		Isolation:           "gvisor",
		RuntimeIdentity:     "runsc",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceStorage:     "2147483648",
	}

	provider, err := NewOpenSandboxProvider(base)
	if err != nil {
		t.Fatal(err)
	}
	if provider.cfg.Connection.Protocol != "https" {
		t.Fatalf("protocol = %q, want https", provider.cfg.Connection.Protocol)
	}

	base.Connection.Protocol = "http"
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "does not match") {
		t.Fatalf("mismatched protocol error = %v", err)
	}
}

func TestOpenSandboxGVisorRequiresExplicitHostEgressProfile(t *testing.T) {
	base := OpenSandboxConfig{
		Connection:      opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:        time.Minute,
		AllowInsecure:   true,
		Isolation:       "gvisor",
		RuntimeIdentity: "opensandbox-docker-gvisor-runsc-20260721",
		EgressMode:      "provider",
		ResourceStorage: "2147483648",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "incompatible with gVisor") {
		t.Fatalf("provider policy with gVisor error = %v", err)
	}
	base.EgressMode = "host-public"
	base.AllowInternetAccess = true
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("explicit host egress profile rejected: %v", err)
	}
}

func TestOpenSandboxStrongIsolationRequiresPinnedRuntimeAndImmutableImages(t *testing.T) {
	base := OpenSandboxConfig{
		Connection:          opensandbox.ConnectionConfig{Domain: "https://opensandbox.example"},
		Image:               "agentarea/runtime:latest",
		LeaseTTL:            time.Minute,
		Isolation:           "gvisor",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceStorage:     "2147483648",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "runtime identity") {
		t.Fatalf("missing runtime identity error = %v", err)
	}
	base.RuntimeIdentity = "opensandbox-docker-gvisor-runsc-20260721"
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "immutable digest") {
		t.Fatalf("mutable image error = %v", err)
	}
	base.Image = "agentarea/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("pinned strong-isolation profile rejected: %v", err)
	}
}

func TestOpenSandboxDisabledSecureAccessRequiresServerProxy(t *testing.T) {
	secureAccess := false
	base := OpenSandboxConfig{
		Connection:          opensandbox.ConnectionConfig{Domain: "http://127.0.0.1:8080"},
		LeaseTTL:            time.Minute,
		AllowInsecure:       true,
		SecureAccess:        &secureAccess,
		Isolation:           "gvisor",
		RuntimeIdentity:     "opensandbox-docker-gvisor-runsc-20260721",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceStorage:     "2147483648",
	}
	if _, err := NewOpenSandboxProvider(base); err == nil || !strings.Contains(err.Error(), "requires server proxy") {
		t.Fatalf("disabled secure access without proxy error = %v", err)
	}
	base.Connection.UseServerProxy = true
	if _, err := NewOpenSandboxProvider(base); err != nil {
		t.Fatalf("explicit Docker server-proxy mode rejected: %v", err)
	}
}

func TestOpenSandboxNetworkPolicyUsesDeploymentInternetSetting(t *testing.T) {
	if policy := openSandboxNetworkPolicy(false); policy == nil || policy.DefaultAction != "deny" || len(policy.Egress) != 0 {
		t.Fatalf("deny network policy = %+v", policy)
	}
	if policy := openSandboxNetworkPolicy(true); policy == nil || policy.DefaultAction != "allow" {
		t.Fatalf("allow network policy = %+v", policy)
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
						"agentarea.provisioning_id":  "provision-1",
						"agentarea.workspace_id":     "workspace-1",
						"agentarea.task_id":          "task-1",
						"agentarea.isolation":        "gvisor",
						"agentarea.resource_cpu":     "750m",
						"agentarea.resource_memory":  "1Gi",
						"agentarea.resource_storage": "2147483648",
						"agentarea.egress_mode":      "host-public",
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
		Connection:          opensandbox.ConnectionConfig{Domain: server.URL},
		LeaseTTL:            time.Hour,
		AllowInsecure:       true,
		Isolation:           "gvisor",
		RuntimeIdentity:     "opensandbox-docker-gvisor-runsc-20260721",
		EgressMode:          "host-public",
		AllowInternetAccess: true,
		ResourceCPU:         "750m",
		ResourceMemory:      "1Gi",
		ResourceStorage:     "2147483648",
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

func TestOpenSandboxResolveProvisioningUsesDurableMetadata(t *testing.T) {
	now := time.Now().UTC()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v1/sandboxes" {
			http.Error(w, "unexpected request", http.StatusNotFound)
			return
		}
		metadata := r.URL.Query().Get("metadata")
		if !strings.Contains(metadata, "agentarea.provisioning_id=provision-1") {
			t.Errorf("metadata filter = %q", metadata)
		}
		_ = json.NewEncoder(w).Encode(opensandbox.ListSandboxesResponse{
			Items: []opensandbox.SandboxInfo{{
				ID: "osb-orphan", Status: opensandbox.SandboxStatus{State: opensandbox.StateRunning},
				Metadata: map[string]string{
					"agentarea.provisioning_id": "provision-1",
					"agentarea.workspace_id":    "workspace-1",
					"agentarea.task_id":         "task-1",
				},
			}},
			Pagination: opensandbox.PaginationInfo{Page: 1, PageSize: 100},
		})
	}))
	defer server.Close()
	provider, err := NewOpenSandboxProvider(OpenSandboxConfig{
		Connection: opensandbox.ConnectionConfig{Domain: server.URL}, LeaseTTL: time.Hour,
		AllowInsecure: true, Isolation: "gvisor", RuntimeIdentity: "runsc-release",
		EgressMode: "host-public", AllowInternetAccess: true, ResourceStorage: "2147483648",
	})
	if err != nil {
		t.Fatal(err)
	}
	sessions, err := provider.ResolveProvisioning(context.Background(), ProvisioningIntent{
		Provider: "opensandbox", ProvisioningID: "provision-1", WorkspaceID: "workspace-1",
		TaskID: "task-1", StartedAt: now, ExpiresAt: now.Add(time.Hour),
	})
	if err != nil || len(sessions) != 1 || sessions[0].ID != "osb-orphan" {
		t.Fatalf("ResolveProvisioning() = %+v, %v", sessions, err)
	}
}
