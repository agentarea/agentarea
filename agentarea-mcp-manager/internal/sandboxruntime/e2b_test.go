package sandboxruntime

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"

	process "github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto/processconnect"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type fakeE2BProcess struct {
	t *testing.T
}

func (f fakeE2BProcess) Start(_ context.Context, req *connect.Request[process.StartRequest], stream *connect.ServerStream[process.StartResponse]) error {
	if req.Header().Get("E2b-Sandbox-Id") != "sbx-1" {
		f.t.Errorf("sandbox header = %q", req.Header().Get("E2b-Sandbox-Id"))
	}
	if req.Header().Get("X-Access-Token") != "envd-token" {
		f.t.Errorf("envd token = %q", req.Header().Get("X-Access-Token"))
	}
	if got := req.Msg.GetProcess().GetCmd(); got != "/bin/bash" {
		f.t.Errorf("command = %q, want /bin/bash", got)
	}
	if err := stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_Start{Start: &process.ProcessEvent_StartEvent{Pid: 42}},
	}}); err != nil {
		return err
	}
	if err := stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_Data{Data: &process.ProcessEvent_DataEvent{
			Output: &process.ProcessEvent_DataEvent_Stdout{Stdout: []byte("ok\n")},
		}},
	}}); err != nil {
		return err
	}
	return stream.Send(&process.StartResponse{Event: &process.ProcessEvent{
		Event: &process.ProcessEvent_End{End: &process.ProcessEvent_EndEvent{ExitCode: 0, Exited: true}},
	}})
}

func TestE2BAndCubeUseTheSameCompatibleContract(t *testing.T) {
	for _, providerName := range []string{"e2b", "cube"} {
		t.Run(providerName, func(t *testing.T) {
			var mu sync.Mutex
			files := map[string][]byte{}
			lifecycleCalls := map[string]int{}
			mux := http.NewServeMux()
			processPath, processHandler := processconnect.NewProcessHandler(fakeE2BProcess{t: t})
			mux.Handle(processPath, processHandler)
			mux.HandleFunc("/sandboxes", func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("X-API-KEY") != "e2b_test" {
					t.Errorf("API key = %q", r.Header.Get("X-API-KEY"))
				}
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Fatal(err)
				}
				if body["templateID"] != "template-allowed" {
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
					content, _ := io.ReadAll(r.Body)
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

			provider, err := NewE2BProvider(E2BConfig{
				ProviderName:   providerName,
				APIURL:         server.URL,
				APIKey:         "e2b_test",
				SandboxURL:     server.URL,
				Templates:      map[string]string{"allowed": "template-allowed"},
				LeaseTTL:       15 * time.Minute,
				InternetAccess: map[string]bool{"allowed": true},
				AllowInsecure:  true,
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
			if err := provider.Renew(context.Background(), session, time.Minute); err != nil {
				t.Fatalf("Renew() error = %v", err)
			}
			result, err := provider.Execute(context.Background(), session, warmpool.ExecuteRequest{
				CommandBody: "printf ok", TimeoutSeconds: 5, StdoutMaxBytes: 1,
			})
			if err != nil {
				t.Fatalf("Execute() error = %v", err)
			}
			if result.ExitCode != 0 || result.Stdout != "o" || !result.StdoutTruncated {
				t.Fatalf("Execute() = exit %d stdout %q", result.ExitCode, result.Stdout)
			}
			if err := provider.PutFile(context.Background(), session, "/workspace/input.txt", []byte("hello")); err != nil {
				t.Fatalf("PutFile() error = %v", err)
			}
			content, err := provider.GetFile(context.Background(), session, "/workspace/input.txt")
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

func TestE2BProviderFailsClosedOnMissingCredentialsOrTemplate(t *testing.T) {
	if _, err := NewE2BProvider(E2BConfig{
		ProviderName: "e2b", APIURL: "https://api.e2b.app", LeaseTTL: time.Minute,
	}); err == nil {
		t.Fatal("missing API key unexpectedly accepted")
	}
	provider, err := NewE2BProvider(E2BConfig{
		ProviderName: "cube", APIURL: "https://cube.example", APIKey: "key", LeaseTTL: time.Minute,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.Create(context.Background(), CreateRequest{PackageInstall: "allowed"}); err == nil {
		t.Fatal("missing template unexpectedly accepted")
	}
	if _, err := NewE2BProvider(E2BConfig{
		ProviderName: "cube", APIURL: "https://cube.example", APIKey: "key",
		LeaseTTL: time.Minute, InternetAccess: map[string]bool{"locked": true},
	}); err == nil {
		t.Fatal("locked profile internet access unexpectedly accepted")
	}
}
