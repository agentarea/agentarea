package packages

import (
	"archive/tar"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	v1 "github.com/google/go-containerregistry/pkg/v1"
	"github.com/google/go-containerregistry/pkg/v1/random"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

type testWorkloads struct {
	spec     workload.Spec
	jsonSpec map[string]any
	err      error
}

func (w testWorkloads) Workload(context.Context, string) (workload.Spec, map[string]any, error) {
	return w.spec, w.jsonSpec, w.err
}

type testBackend struct {
	mu      sync.Mutex
	server  string
	created []workload.Spec
	deleted []string
}

func (b *testBackend) Create(_ context.Context, spec workload.Spec) (workload.Status, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.created = append(b.created, spec)
	return workload.Status{ID: spec.InstanceID, Status: workload.StatusStarting}, nil
}

func (b *testBackend) Delete(_ context.Context, id string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.deleted = append(b.deleted, id)
	return nil
}

func (b *testBackend) Status(_ context.Context, id string) (workload.Status, error) {
	return workload.Status{ID: id, Status: workload.StatusRunning, InternalURL: b.server}, nil
}

func (b *testBackend) Reservation(context.Context) (workload.Reservation, error) {
	return workload.Reservation{}, nil
}

func (b *testBackend) counts() (int, int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.created), len(b.deleted)
}

type testStore struct {
	mu     sync.Mutex
	built  bool
	puts   int
	stored StoredImage
	base   v1.Image
	baseOf string
}

func (s *testStore) Lookup(context.Context, Package) (StoredImage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.built {
		return StoredImage{}, ErrImageNotFound
	}
	return s.stored, nil
}

func (s *testStore) Base(_ context.Context, ref string) (v1.Image, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.baseOf = ref
	return s.base, nil
}

func (s *testStore) Put(_ context.Context, _ Package, entrypoint []string, _ v1.Image) (StoredImage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.puts++
	s.built = true
	s.stored = StoredImage{Ref: "repo@sha256:abc", Digest: "sha256:abc", Entrypoint: entrypoint}
	return s.stored, nil
}

type testRemote struct{ base string }

func (r testRemote) InstanceProxyURL(id string) string {
	return r.base + "/instances/" + id + "/proxy/mcp"
}

func (r testRemote) Authorize(req *http.Request) bool {
	if !strings.HasPrefix(req.URL.String(), r.base+"/instances/") {
		return false
	}
	req.Header.Set("Authorization", "Bearer machine")
	return true
}

func commandSpec() (workload.Spec, map[string]any) {
	spec := workload.Spec{
		InstanceID: "instance", WorkspaceID: "workspace", Image: "mcp-base:test", Port: 8080,
		Environment: map[string]string{"API_KEY": "secret"}, Labels: map[string]string{"agentarea.io/instance": "instance"},
		Command: []string{"npx", "pkg", "--flag"}, IsolationTier: workload.IsolationUntrusted,
	}
	return spec, map[string]any{"type": "command", "command": "npx", "args": []any{"pkg", "--flag"}}
}

func newTestImporter(t *testing.T, w Workloads, backend workload.Backend, store ImageStore, remote Remote, versions string) *Importer {
	t.Helper()
	importer, err := New(Options{
		Config:     Config{Timeout: 2 * time.Second, NPMRegistry: versions, PyPI: versions},
		Workloads:  w,
		Backend:    backend,
		Remote:     remote,
		Registries: http.DefaultClient,
		Pack:       http.DefaultClient,
		Store:      store,
		Log:        slog.New(slog.NewTextHandler(io.Discard, nil)),
	})
	if err != nil {
		t.Fatal(err)
	}
	return importer
}

func TestImportBuildsOnceAndDeletesPackWorkload(t *testing.T) {
	layer := testLayer(t)
	pack := packServer(t, layer, false, "")
	versions := npmVersionServer(t)
	backend := &testBackend{server: pack.URL}
	store := &testStore{base: testBaseImage(t)}
	spec, jsonSpec := commandSpec()
	importer := newTestImporter(t, testWorkloads{spec: spec, jsonSpec: jsonSpec}, backend, store, nil, versions.URL)

	first, err := importer.Import(t.Context(), "instance")
	if err != nil {
		t.Fatal(err)
	}
	second, err := importer.Import(t.Context(), "instance")
	if err != nil {
		t.Fatal(err)
	}
	if first.Image != "repo@sha256:abc" || second.Image != first.Image || store.puts != 1 {
		t.Fatalf("first=%+v second=%+v puts=%d", first, second, store.puts)
	}
	if got := strings.Join(first.Command, " "); got != "/opt/mcp-pkg/bin --flag" {
		t.Fatalf("command = %q", got)
	}
	if first.Port != 8080 || first.Package["version"] != "1.2.3" || first.Package["ecosystem"] != "npm" {
		t.Fatalf("imported = %+v", first)
	}
	if store.baseOf != "mcp-base:test" {
		t.Fatalf("base image = %q", store.baseOf)
	}
	if created, deleted := backend.counts(); created != 1 || deleted != 1 {
		t.Fatalf("pack workloads created/deleted = %d/%d", created, deleted)
	}
	packed := backend.created[0]
	if packed.Environment["MCP_BASE_PACK_PACKAGE"] != "pkg" || packed.Environment["API_KEY"] != "secret" ||
		packed.Labels[packageRoleLabel] != packageRoleValue || packed.InstanceID != packInstanceID(Package{Ecosystem: EcosystemNPM, Name: "pkg", Version: "1.2.3"}) ||
		strings.Join(packed.Command, " ") != "--flag" || packed.Environment["PORT"] != "8080" {
		t.Fatalf("pack spec = %+v", packed)
	}
}

func TestImportRejectsLayerHashMismatchAndDeletesPackWorkload(t *testing.T) {
	layer := testLayer(t)
	pack := packServer(t, layer, true, "")
	versions := npmVersionServer(t)
	backend := &testBackend{server: pack.URL}
	spec, jsonSpec := commandSpec()
	importer := newTestImporter(t, testWorkloads{spec: spec, jsonSpec: jsonSpec}, backend, &testStore{base: testBaseImage(t)}, nil, versions.URL)

	_, err := importer.Import(t.Context(), "instance")
	var rejected *service.PackageRejectedError
	if !errors.As(err, &rejected) || !strings.Contains(rejected.Msg, "sha256 mismatch") {
		t.Fatalf("Import() error = %v, want sha mismatch rejection", err)
	}
	if _, deleted := backend.counts(); deleted != 1 {
		t.Fatalf("deleted workloads = %d, want 1", deleted)
	}
}

func TestImportThroughRemoteAuthorizesPackRequests(t *testing.T) {
	layer := testLayer(t)
	pack := packServer(t, layer, false, "/instances/"+packInstanceID(Package{Ecosystem: EcosystemNPM, Name: "pkg", Version: "1.2.3"})+"/proxy")
	versions := npmVersionServer(t)
	backend := &testBackend{}
	spec, jsonSpec := commandSpec()
	importer := newTestImporter(t, testWorkloads{spec: spec, jsonSpec: jsonSpec}, backend, &testStore{base: testBaseImage(t)}, testRemote{base: pack.URL}, versions.URL)

	if _, err := importer.Import(t.Context(), "instance"); err != nil {
		t.Fatal(err)
	}
}

func TestImportRejections(t *testing.T) {
	versions := npmVersionServer(t)
	spec, jsonSpec := commandSpec()
	private := spec
	private.Environment = map[string]string{"NPM_CONFIG_REGISTRY": "https://npm.example"}
	cases := []struct {
		name string
		w    testWorkloads
		want string
	}{
		{"not a command", testWorkloads{spec: spec, jsonSpec: map[string]any{"type": "docker"}}, "requires a command instance"},
		{"unsupported command", testWorkloads{spec: spec, jsonSpec: map[string]any{"type": "command", "command": "node", "args": []any{"x"}}}, "unsupported package command"},
		{"private registry", testWorkloads{spec: private, jsonSpec: jsonSpec}, "NPM_CONFIG_REGISTRY"},
		{"missing version", testWorkloads{spec: spec, jsonSpec: map[string]any{"type": "command", "command": "npx", "args": []any{"pkg@9.9.9"}}}, "package was not found"},
		{"spec refused", testWorkloads{err: refusal{"stdio image"}}, "stdio image"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			backend := &testBackend{}
			importer := newTestImporter(t, tc.w, backend, &testStore{}, nil, versions.URL)
			_, err := importer.Import(t.Context(), "instance")
			var rejected *service.PackageRejectedError
			if !errors.As(err, &rejected) || !strings.Contains(rejected.Msg, tc.want) {
				t.Fatalf("Import() error = %v, want rejection containing %q", err, tc.want)
			}
			if created, _ := backend.counts(); created != 0 {
				t.Fatalf("created %d pack workloads", created)
			}
		})
	}
}

func TestImportRetriesTransientFailures(t *testing.T) {
	versions := npmVersionServer(t)
	_, jsonSpec := commandSpec()
	importer := newTestImporter(t, testWorkloads{err: errors.New("database unavailable")}, &testBackend{}, &testStore{}, nil, versions.URL)
	_, err := importer.Import(t.Context(), "instance")
	var rejected *service.PackageRejectedError
	if err == nil || errors.As(err, &rejected) {
		t.Fatalf("Import() error = %v, want a retryable error", err)
	}

	down := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusBadGateway) }))
	t.Cleanup(down.Close)
	spec, _ := commandSpec()
	importer = newTestImporter(t, testWorkloads{spec: spec, jsonSpec: jsonSpec}, &testBackend{}, &testStore{}, nil, down.URL)
	_, err = importer.Import(t.Context(), "instance")
	if err == nil || errors.As(err, &rejected) {
		t.Fatalf("Import() error = %v, want a retryable error", err)
	}
}

func TestNewNeedsRepositoryOffTheLocalRuntime(t *testing.T) {
	o := Options{
		Config: Config{Timeout: time.Second, Runtime: "docker"}, Workloads: testWorkloads{}, Backend: &testBackend{},
		Registries: http.DefaultClient, Pack: http.DefaultClient, Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	if _, err := New(o); err == nil {
		t.Fatal("New() without repository off the local runtime succeeded")
	}
	o.LocalImages = true
	importer, err := New(o)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := importer.store.(*LocalStore); !ok {
		t.Fatalf("store = %T, want *LocalStore", importer.store)
	}
	o.Config.Repository = "registry.example/mcp"
	if importer, err = New(o); err != nil {
		t.Fatal(err)
	}
	if _, ok := importer.store.(*RegistryStore); !ok {
		t.Fatalf("store = %T, want *RegistryStore", importer.store)
	}
}

func TestLoadConfig(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_MCP_PACKAGE_REPO": "registry.example/mcp", "AGENTAREA_MCP_IMPORT_TIMEOUT": "5m", "AGENTAREA_MCP_RUNTIME": "podman"})
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	want := Config{Repository: "registry.example/mcp", Runtime: "podman", Timeout: 5 * time.Minute, NPMRegistry: "https://registry.npmjs.org", PyPI: "https://pypi.org"}
	if cfg != want {
		t.Fatalf("config = %+v, want %+v", cfg, want)
	}
	bad := config.FromMap(map[string]string{"AGENTAREA_MCP_RUNTIME": "containerd"})
	LoadConfig(bad)
	if bad.Err() == nil {
		t.Fatal("LoadConfig accepted AGENTAREA_MCP_RUNTIME=containerd")
	}
}

type refusal struct{ reason string }

func (r refusal) Error() string         { return "refused: " + r.reason }
func (r refusal) FailureReason() string { return r.reason }

func npmVersionServer(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"dist-tags":{"latest":"1.2.3"},"versions":{"1.2.3":{}}}`))
	}))
	t.Cleanup(server.Close)
	return server
}

func packServer(t *testing.T, layer []byte, mismatch bool, prefix string) *httptest.Server {
	t.Helper()
	hash := sha256.Sum256(layer)
	sha := hex.EncodeToString(hash[:])
	if mismatch {
		sha = strings.Repeat("0", 64)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if prefix != "" && r.Header.Get("Authorization") != "Bearer machine" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		switch strings.TrimPrefix(r.URL.Path, prefix) {
		case "/health":
			w.WriteHeader(http.StatusOK)
		case "/report":
			_ = json.NewEncoder(w).Encode(PackReport{OK: true, Ecosystem: "npm", Package: "pkg", Version: "1.2.3", Entrypoint: []string{"/opt/mcp-pkg/bin"}, Layer: &PackLayerReport{SHA256: sha, Size: int64(len(layer))}})
		case "/layer.tar":
			w.Header().Set("Content-Type", "application/x-tar")
			_, _ = w.Write(layer)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func testLayer(t *testing.T) []byte {
	t.Helper()
	var buffer bytes.Buffer
	writer := tar.NewWriter(&buffer)
	if err := writer.WriteHeader(&tar.Header{Name: "opt/", Mode: 0o755, Typeflag: tar.TypeDir}); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

func testBaseImage(t *testing.T) v1.Image {
	t.Helper()
	image, err := random.Image(1, 8)
	if err != nil {
		t.Fatal(err)
	}
	return image
}
