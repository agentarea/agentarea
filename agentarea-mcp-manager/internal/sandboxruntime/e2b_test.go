package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"path"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"

	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	process "github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto/processconnect"
)

type fakeE2BProcess struct {
	t     *testing.T
	mu    *sync.Mutex
	files map[string][]byte
}

func testAttestation(providerName string) string {
	document, err := json.Marshal(IsolationAttestation{
		Provider:          providerName,
		ProviderVersion:   "0.6.4",
		Isolation:         "firecracker",
		RuntimeIdentity:   providerName + "-envd-0.6.4",
		AttestationSource: "template-build",
	})
	if err != nil {
		panic(err)
	}
	return string(document)
}

func testE2BConfig(providerName, serverURL string) E2BConfig {
	return E2BConfig{
		ProviderName:        providerName,
		APIURL:              serverURL,
		APIKey:              "e2b_test",
		SandboxURL:          serverURL,
		Template:            "runtime-template",
		LeaseTTL:            15 * time.Minute,
		AllowInternetAccess: true,
		AllowInsecure:       true,
		Isolation:           "firecracker",
		AttestationPath:     DefaultIsolationAttestationPath,
	}
}

func (f fakeE2BProcess) Start(_ context.Context, req *connect.Request[process.StartRequest], stream *connect.ServerStream[process.StartResponse]) error {
	if req.Header().Get("E2b-Sandbox-Id") != "sbx-1" {
		f.t.Errorf("sandbox header = %q", req.Header().Get("E2b-Sandbox-Id"))
	}
	if req.Header().Get("X-Access-Token") != "envd-token" {
		f.t.Errorf("envd token = %q", req.Header().Get("X-Access-Token"))
	}
	command := req.Msg.GetProcess().GetCmd()
	if command != "/bin/bash" && command != "/bin/chmod" && command != testSupervisorAttestation().Path {
		f.t.Errorf("command = %q, want platform command", command)
	}
	if err := stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_Start{Start: &process.ProcessEvent_StartEvent{Pid: 42}},
	}}); err != nil {
		return err
	}
	stdout := []byte("ok\n")
	if command == "/bin/chmod" {
		stdout = nil
	}
	if command == testSupervisorAttestation().Path {
		args := req.Msg.GetProcess().GetArgs()
		for index, value := range args {
			if value == "--status" && index+1 < len(args) {
				f.mu.Lock()
				f.files[args[index+1]] = testSupervisorStatus(0)
				f.mu.Unlock()
				break
			}
		}
	}
	if err := stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_Data{Data: &process.ProcessEvent_DataEvent{
			Output: &process.ProcessEvent_DataEvent_Stdout{Stdout: stdout},
		}},
	}}); err != nil {
		return err
	}
	return stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_End{End: &process.ProcessEvent_EndEvent{ExitCode: 0, Exited: true}},
	}})
}

func registerE2BFilesystemHandlers(
	t *testing.T,
	mux *http.ServeMux,
	mu *sync.Mutex,
	files map[string][]byte,
) {
	t.Helper()
	mux.HandleFunc("/filesystem.Filesystem/MakeDir", func(w http.ResponseWriter, r *http.Request) {
		assertE2BFilesystemHeaders(t, r)
		var request struct {
			Path string `json:"path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		_ = json.NewEncoder(w).Encode(e2bStatResponse{Entry: e2bFilesystemEntry{
			Name: path.Base(request.Path), Type: "FILE_TYPE_DIRECTORY", Path: request.Path, Mode: 0o755,
		}})
	})
	mux.HandleFunc("/filesystem.Filesystem/Stat", func(w http.ResponseWriter, r *http.Request) {
		assertE2BFilesystemHeaders(t, r)
		var request struct {
			Path string `json:"path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		mu.Lock()
		content, ok := files[request.Path]
		mu.Unlock()
		if !ok {
			http.NotFound(w, r)
			return
		}
		mode := uint32(0o600)
		if request.Path == testSupervisorAttestation().Path {
			mode = 0o755
		}
		_ = json.NewEncoder(w).Encode(e2bStatResponse{Entry: e2bFilesystemEntry{
			Name: path.Base(request.Path), Type: "FILE_TYPE_FILE", Path: request.Path,
			Size: int64(len(content)), Mode: mode,
		}})
	})
	mux.HandleFunc("/filesystem.Filesystem/ListDir", func(w http.ResponseWriter, r *http.Request) {
		assertE2BFilesystemHeaders(t, r)
		var request struct {
			Path  string `json:"path"`
			Depth int    `json:"depth"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		if request.Depth != 1 {
			t.Errorf("ListDir depth = %d", request.Depth)
		}
		entriesByPath := make(map[string]e2bFilesystemEntry)
		prefix := strings.TrimRight(request.Path, "/") + "/"
		mu.Lock()
		for filePath, content := range files {
			if !strings.HasPrefix(filePath, prefix) {
				continue
			}
			relative := strings.TrimPrefix(filePath, prefix)
			if slash := strings.IndexByte(relative, '/'); slash >= 0 {
				directoryPath := prefix + relative[:slash]
				entriesByPath[directoryPath] = e2bFilesystemEntry{
					Name: path.Base(directoryPath), Type: "FILE_TYPE_DIRECTORY", Path: directoryPath, Mode: 0o755,
				}
				continue
			}
			entriesByPath[filePath] = e2bFilesystemEntry{
				Name: path.Base(filePath), Type: "FILE_TYPE_FILE", Path: filePath,
				Size: int64(len(content)), Mode: 0o600,
			}
		}
		mu.Unlock()
		response := e2bListDirResponse{Entries: make([]e2bFilesystemEntry, 0, len(entriesByPath))}
		for _, entry := range entriesByPath {
			response.Entries = append(response.Entries, entry)
		}
		_ = json.NewEncoder(w).Encode(response)
	})
	mux.HandleFunc("/filesystem.Filesystem/Move", func(w http.ResponseWriter, r *http.Request) {
		assertE2BFilesystemHeaders(t, r)
		var request struct {
			Source      string `json:"source"`
			Destination string `json:"destination"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		mu.Lock()
		content, ok := files[request.Source]
		if ok {
			files[request.Destination] = content
			delete(files, request.Source)
		}
		mu.Unlock()
		if !ok {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(e2bStatResponse{Entry: e2bFilesystemEntry{
			Name: path.Base(request.Destination), Type: "FILE_TYPE_FILE", Path: request.Destination,
			Size: int64(len(content)), Mode: 0o600,
		}})
	})
	mux.HandleFunc("/filesystem.Filesystem/Remove", func(w http.ResponseWriter, r *http.Request) {
		assertE2BFilesystemHeaders(t, r)
		var request struct {
			Path string `json:"path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		mu.Lock()
		delete(files, request.Path)
		mu.Unlock()
		_, _ = w.Write([]byte(`{}`))
	})
}

func assertE2BFilesystemHeaders(t *testing.T, r *http.Request) {
	t.Helper()
	if r.Header.Get("Connect-Protocol-Version") != "1" || r.Header.Get("X-Access-Token") != "envd-token" {
		t.Errorf("filesystem headers = %+v", r.Header)
	}
}

func TestE2BAndCubeUseTheSameCompatibleContract(t *testing.T) {
	for _, providerName := range []string{"e2b", "cube"} {
		t.Run(providerName, func(t *testing.T) {
			var mu sync.Mutex
			files := map[string][]byte{
				DefaultIsolationAttestationPath:  []byte(testAttestation(providerName)),
				testSupervisorAttestation().Path: testSupervisorBinary,
			}
			lifecycleCalls := map[string]int{}
			mux := http.NewServeMux()
			processPath, processHandler := processconnect.NewProcessHandler(
				fakeE2BProcess{t: t, mu: &mu, files: files},
			)
			mux.Handle(processPath, processHandler)
			registerE2BFilesystemHandlers(t, mux, &mu, files)
			mux.HandleFunc("/sandboxes", func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("X-API-KEY") != "e2b_test" {
					t.Errorf("API key = %q", r.Header.Get("X-API-KEY"))
				}
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Fatal(err)
				}
				if body["templateID"] != "runtime-template" {
					t.Errorf("templateID = %v", body["templateID"])
				}
				if body["allow_internet_access"] != true {
					t.Errorf("allow_internet_access = %v", body["allow_internet_access"])
				}
				mu.Lock()
				lifecycleCalls["create"]++
				mu.Unlock()
				_ = json.NewEncoder(w).Encode(e2bCreateResponse{
					SandboxID: "sbx-1", Domain: "example.test",
					EnvdVersion: "0.6.4", EnvdAccessToken: "envd-token",
				})
			})
			mux.HandleFunc("/sandboxes/sbx-1/timeout", func(w http.ResponseWriter, _ *http.Request) {
				mu.Lock()
				lifecycleCalls["renew"]++
				mu.Unlock()
				w.WriteHeader(http.StatusNoContent)
			})
			mux.HandleFunc("/sandboxes/sbx-1", func(w http.ResponseWriter, r *http.Request) {
				if r.Method != http.MethodDelete {
					t.Fatalf("unexpected method %s", r.Method)
				}
				mu.Lock()
				lifecycleCalls["delete"]++
				mu.Unlock()
				w.WriteHeader(http.StatusNoContent)
			})
			mux.HandleFunc("/files", func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("E2b-Sandbox-Id") != "sbx-1" {
					t.Errorf("file sandbox header = %q", r.Header.Get("E2b-Sandbox-Id"))
				}
				filePath := r.URL.Query().Get("path")
				switch r.Method {
				case http.MethodPost:
					file, _, err := r.FormFile("file")
					if err != nil {
						t.Fatalf("multipart file: %v", err)
					}
					content, _ := io.ReadAll(file)
					file.Close()
					mu.Lock()
					files[filePath] = content
					mu.Unlock()
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte(`[{"path":"` + filePath + `"}]`))
				case http.MethodGet:
					mu.Lock()
					content, ok := files[filePath]
					mu.Unlock()
					if !ok {
						http.NotFound(w, r)
						return
					}
					_, _ = w.Write(content)
				default:
					http.Error(w, "method", http.StatusMethodNotAllowed)
				}
			})
			server := httptest.NewServer(mux)
			defer server.Close()

			provider, err := NewE2BProvider(testE2BConfig(providerName, server.URL))
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
			if err := provider.Renew(context.Background(), session, time.Minute); err != nil {
				t.Fatalf("Renew() error = %v", err)
			}
			result, err := provider.ExecuteQuiescent(context.Background(), session, testQuiescentExecution(sandboxcontract.ExecuteRequest{
				CommandBody: "printf ok", TimeoutSeconds: 5, StdoutMaxBytes: 1,
			}))
			if err != nil {
				t.Fatalf("Execute() error = %v", err)
			}
			if result.ExitCode != 0 || result.Stdout != "o" || !result.StdoutTruncated {
				t.Fatalf("Execute() = exit %d stdout %q", result.ExitCode, result.Stdout)
			}
			digest := sha256.Sum256([]byte("hello"))
			if err := provider.PutFile(context.Background(), session, FileUpload{
				Path: "/workspace/input.txt", Size: int64(len("hello")), SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
			}, strings.NewReader("hello")); err != nil {
				t.Fatalf("PutFile() error = %v", err)
			}
			download, err := provider.OpenFile(context.Background(), session, "/workspace/input.txt")
			if err != nil {
				t.Fatalf("OpenFile() error = %v", err)
			}
			content, err := io.ReadAll(download.Content)
			download.Content.Close()
			if err != nil || string(content) != "hello" {
				t.Fatalf("GetFile() = %q, %v", content, err)
			}
			if err := provider.Delete(context.Background(), session); err != nil {
				t.Fatalf("Delete() error = %v", err)
			}
			mu.Lock()
			defer mu.Unlock()
			if lifecycleCalls["create"] != 1 || lifecycleCalls["renew"] != 1 || lifecycleCalls["delete"] != 1 {
				t.Fatalf("lifecycle calls = %v", lifecycleCalls)
			}
			if !strings.HasPrefix(session.Data["envd_url"], server.URL) {
				t.Fatalf("envd URL = %q", session.Data["envd_url"])
			}
		})
	}
}

func TestE2BMultipartUploadDoesNotDeadlockOnEarlyRejection(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusRequestEntityTooLarge)
	}))
	defer server.Close()
	config := testE2BConfig("e2b", server.URL)
	config.APIKey = "test"
	config.AllowInternetAccess = false
	provider, err := NewE2BProvider(config)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	err = provider.uploadFile(ctx, &Session{ID: "sbx", Data: map[string]string{"envd_url": server.URL}}, "/workspace/large.bin", bytes.NewReader(bytes.Repeat([]byte("x"), 4*1024*1024)), 4*1024*1024)
	if err == nil || !strings.Contains(err.Error(), "returned 413") {
		t.Fatalf("uploadFile() error = %v", err)
	}
}

func TestE2BArtifactInspectionFailureIsAResultNotAnExecutionFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/filesystem.Filesystem/Stat" {
			http.NotFound(w, r)
			return
		}
		http.Error(w, "temporary metadata failure", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	artifacts, err := provider.artifacts(context.Background(), &Session{
		ID: "sbx-1", Data: map[string]string{
			"envd_url": server.URL, "envd_access_token": "envd-token",
		},
	}, []string{"result.txt"})
	if err != nil {
		t.Fatalf("artifact metadata failure escaped as provider execution error: %v", err)
	}
	if len(artifacts) != 1 || artifacts[0].Path != "result.txt" || artifacts[0].Error != "artifact inspection failed" {
		t.Fatalf("artifacts = %#v, want one per-artifact inspection error", artifacts)
	}
}

func TestE2BProviderFailsClosedOnMissingCredentialsOrTemplate(t *testing.T) {
	noKey := testE2BConfig("e2b", "https://api.e2b.app")
	noKey.APIKey = ""
	if _, err := NewE2BProvider(noKey); err == nil {
		t.Fatal("missing API key unexpectedly accepted")
	}
	noTemplate := testE2BConfig("cube", "https://cube.example")
	noTemplate.Template = ""
	provider, err := NewE2BProvider(noTemplate)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.Create(context.Background(), CreateRequest{
		ProvisioningID: "provision-1", Supervisor: testSupervisorAttestation(),
	}); err == nil {
		t.Fatal("missing template unexpectedly accepted")
	}
}

func TestE2BProviderRefusesUndeclaredOrWeakIsolation(t *testing.T) {
	for name, isolation := range map[string]string{
		"undeclared": "",
		"runc":       "runc",
		"unknown":    "unknown",
		"container":  "container-dev",
	} {
		t.Run(name, func(t *testing.T) {
			config := testE2BConfig("e2b", "https://api.e2b.app")
			config.Isolation = isolation
			_, err := NewE2BProvider(config)
			if !errors.Is(err, ErrIsolationUnavailable) {
				t.Fatalf("NewE2BProvider() error = %v, want isolation_unavailable", err)
			}
		})
	}
	noPath := testE2BConfig("e2b", "https://api.e2b.app")
	noPath.AttestationPath = ""
	if _, err := NewE2BProvider(noPath); err == nil {
		t.Fatal("missing attestation path unexpectedly accepted")
	}
}

func TestE2BCreateRefusesSandboxThatCannotAttestIsolation(t *testing.T) {
	mismatched := testAttestation("e2b")
	tests := map[string]string{
		"missing":        "",
		"not json":       "not-json",
		"wrong provider": testAttestation("someone-else"),
		"weak isolation": `{"provider":"e2b","provider_version":"1","isolation":"runc","runtime_identity":"x","attestation_source":"y"}`,
		"missing field":  `{"provider":"e2b","provider_version":"1","isolation":"firecracker","runtime_identity":"","attestation_source":"y"}`,
		"unknown field":  strings.Replace(mismatched, `{`, `{"extra":1,`, 1),
	}
	for name, attestation := range tests {
		t.Run(name, func(t *testing.T) {
			deletes := 0
			var mu sync.Mutex
			files := map[string][]byte{DefaultIsolationAttestationPath: []byte(attestation)}
			mux := http.NewServeMux()
			registerE2BFilesystemHandlers(t, mux, &mu, files)
			mux.HandleFunc("/sandboxes", func(w http.ResponseWriter, _ *http.Request) {
				_ = json.NewEncoder(w).Encode(e2bCreateResponse{
					SandboxID: "sbx-1", Domain: "example.test",
					EnvdVersion: "0.6.4", EnvdAccessToken: "envd-token",
				})
			})
			mux.HandleFunc("/sandboxes/sbx-1", func(w http.ResponseWriter, _ *http.Request) {
				mu.Lock()
				deletes++
				mu.Unlock()
				w.WriteHeader(http.StatusNoContent)
			})
			mux.HandleFunc("/files", func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				content, ok := files[r.URL.Query().Get("path")]
				mu.Unlock()
				if !ok {
					http.NotFound(w, r)
					return
				}
				_, _ = w.Write(content)
			})
			server := httptest.NewServer(mux)
			defer server.Close()

			provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
			if err != nil {
				t.Fatal(err)
			}
			session, err := provider.Create(context.Background(), CreateRequest{
				WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
				Supervisor: testSupervisorAttestation(),
			})
			if !errors.Is(err, ErrIsolationUnavailable) {
				t.Fatalf("Create() error = %v, want isolation_unavailable", err)
			}
			if session == nil || session.ID != "sbx-1" {
				t.Fatalf("Create() session = %+v, want allocated resource returned to manager", session)
			}
			mu.Lock()
			defer mu.Unlock()
			if deletes != 0 {
				t.Fatalf("provider adapter performed %d compensating deletes; manager owns cleanup", deletes)
			}
		})
	}
}

func TestE2BAuditsLiveWorkspaceUsage(t *testing.T) {
	var mu sync.Mutex
	files := map[string][]byte{
		WorkspaceRoot + "/largest.bin":          bytes.Repeat([]byte("x"), 400),
		WorkspaceRoot + "/one.bin":              bytes.Repeat([]byte("x"), 100),
		WorkspaceRoot + "/two.bin":              bytes.Repeat([]byte("x"), 100),
		WorkspaceRoot + "/nested/three.bin":     bytes.Repeat([]byte("x"), 100),
		WorkspaceRoot + "/nested/four.bin":      bytes.Repeat([]byte("x"), 100),
		WorkspaceRoot + "/nested/deep/five.bin": bytes.Repeat([]byte("x"), 50),
		WorkspaceRoot + "/nested/deep/six.bin":  bytes.Repeat([]byte("x"), 50),
	}
	mux := http.NewServeMux()
	registerE2BFilesystemHandlers(t, mux, &mu, files)
	server := httptest.NewServer(mux)
	defer server.Close()

	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	usage, err := provider.AuditWorkspace(context.Background(), &Session{
		ID:   "sbx-1",
		Data: map[string]string{"envd_url": server.URL, "envd_access_token": "envd-token"},
	})
	if err != nil {
		t.Fatalf("AuditWorkspace() error = %v", err)
	}
	if usage.Entries != 9 || usage.TotalBytes != 900 || usage.LargestBytes != 400 {
		t.Fatalf("AuditWorkspace() = %+v", usage)
	}
}

func TestE2BInventoryScopesToWorkspaceWithoutLeakingTokens(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v2/sandboxes" {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		if metadata := r.URL.Query().Get("metadata"); metadata != "agentarea.workspace_id=workspace-1" {
			t.Errorf("metadata filter = %q", metadata)
		}
		_, _ = w.Write([]byte(`[
			{"sandboxID":"sbx-1","templateID":"tpl","state":"running","cpuCount":2,"memoryMB":512,
			 "envdAccessToken":"secret-envd","trafficAccessToken":"secret-traffic",
			 "metadata":{"agentarea.provisioning_id":"provision-1","agentarea.workspace_id":"workspace-1","agentarea.task_id":"task-1"}}
		]`))
	}))
	defer server.Close()

	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	items, err := provider.List(context.Background(), "workspace-1")
	if err != nil {
		t.Fatalf("List() error = %v", err)
	}
	if len(items) != 1 || items[0].ID != "sbx-1" || items[0].TaskID != "task-1" {
		t.Fatalf("List() = %+v, want only the requested workspace", items)
	}
	if items[0].Isolation != "firecracker" || items[0].State != "running" {
		t.Fatalf("List() = %+v", items[0])
	}
	rendered, err := json.Marshal(items)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(rendered), "secret-") {
		t.Fatalf("inventory leaked provider access tokens: %s", rendered)
	}
}

func TestE2BResolveProvisioningUsesFilteredPaginatedInventory(t *testing.T) {
	now := time.Now().UTC()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v2/sandboxes" {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		metadata := r.URL.Query().Get("metadata")
		for _, expected := range []string{
			"agentarea.provisioning_id=provision-1",
			"agentarea.task_id=task-1",
			"agentarea.workspace_id=workspace-1",
		} {
			if !strings.Contains(metadata, expected) {
				t.Errorf("metadata filter %q missing %q", metadata, expected)
			}
		}
		if r.URL.Query().Get("nextToken") == "" {
			w.Header().Set("X-Next-Token", "page-2")
			_, _ = w.Write([]byte(`[{
				"sandboxID":"sbx-1","state":"running",
				"metadata":{"agentarea.provisioning_id":"provision-1","agentarea.workspace_id":"workspace-1","agentarea.task_id":"task-1"}
			}]`))
			return
		}
		_, _ = w.Write([]byte(`[{
			"sandboxID":"sbx-2","state":"paused",
			"metadata":{"agentarea.provisioning_id":"provision-1","agentarea.workspace_id":"workspace-1","agentarea.task_id":"task-1"}
		}]`))
	}))
	defer server.Close()
	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	sessions, err := provider.ResolveProvisioning(context.Background(), ProvisioningIntent{
		Provider: "e2b", ProvisioningID: "provision-1", WorkspaceID: "workspace-1",
		TaskID: "task-1", StartedAt: now, ExpiresAt: now.Add(time.Hour),
	})
	if err != nil || len(sessions) != 2 || sessions[0].ID != "sbx-1" || sessions[1].ID != "sbx-2" {
		t.Fatalf("ResolveProvisioning() = %+v, %v", sessions, err)
	}
}
