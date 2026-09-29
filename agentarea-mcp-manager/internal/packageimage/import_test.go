package packageimage

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
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/google/go-containerregistry/pkg/v1"
	"github.com/google/go-containerregistry/pkg/v1/random"
)

type importTestRepository struct {
	instance *models.MCPServerInstance
}

func (r importTestRepository) LoadInstance(context.Context, string) (*models.MCPServerInstance, error) {
	return r.instance, nil
}

const testAuthSecret = "0123456789abcdef0123456789abcdef"

type importTestBackend struct {
	mu      sync.Mutex
	server  string
	created []*backends.InstanceSpec
	deleted []string
}

func (b *importTestBackend) CreateInstance(_ context.Context, spec *backends.InstanceSpec) (*backends.InstanceResult, error) {
	b.mu.Lock()
	b.created = append(b.created, spec)
	b.mu.Unlock()
	return &backends.InstanceResult{ID: spec.InstanceID, Name: spec.Name, Status: "running"}, nil
}
func (b *importTestBackend) DeleteInstance(_ context.Context, instanceID string) error {
	b.mu.Lock()
	b.deleted = append(b.deleted, instanceID)
	b.mu.Unlock()
	return nil
}
func (b *importTestBackend) GetInstanceStatus(_ context.Context, instanceID string) (*backends.InstanceStatus, error) {
	return &backends.InstanceStatus{ID: instanceID, Status: "running", InternalURL: b.server}, nil
}
func (b *importTestBackend) ListInstances(context.Context) ([]*backends.InstanceStatus, error) {
	return nil, nil
}
func (b *importTestBackend) UpdateInstance(context.Context, string, *backends.InstanceSpec) error {
	return nil
}
func (b *importTestBackend) PerformHealthCheck(context.Context, string) (*backends.HealthCheckResult, error) {
	return &backends.HealthCheckResult{Healthy: true}, nil
}
func (b *importTestBackend) Initialize(context.Context) error { return nil }
func (b *importTestBackend) Shutdown(context.Context) error   { return nil }

type importTestStore struct {
	mu      sync.Mutex
	built   bool
	lookups int
	puts    int
	stored  StoredImage
	base    v1.Image
}

func (s *importTestStore) Lookup(context.Context, Package) (*StoredImage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.lookups++
	if !s.built {
		return nil, ErrImageNotFound
	}
	return &s.stored, nil
}
func (s *importTestStore) Base(context.Context) (v1.Image, error) { return s.base, nil }
func (s *importTestStore) Put(_ context.Context, _ Package, command []string, _ v1.Image) (*StoredImage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.puts++
	s.built = true
	s.stored = StoredImage{Ref: "repo@sha256:abc", Digest: "sha256:abc", Entrypoint: command}
	return &s.stored, nil
}

func TestImportBuildsOnceAndDeletesPackWorkload(t *testing.T) {
	layer := testLayer(t)
	server := packServer(t, layer, false)
	defer server.Close()
	backend := &importTestBackend{server: server.URL}
	store := &importTestStore{base: testBaseImage(t)}
	versionServer := npmVersionServer(t)
	defer versionServer.Close()
	service, err := NewService(Options{
		Repository:     importTestRepository{instance: commandInstance()},
		AuthSecret:     testAuthSecret,
		Backend:        backend,
		Store:          store,
		ImportTimeout:  time.Second,
		NPMRegistryURL: versionServer.URL,
		Logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
	})
	if err != nil {
		t.Fatal(err)
	}

	first, err := service.Import(t.Context(), "instance")
	if err != nil {
		t.Fatal(err)
	}
	second, err := service.Import(t.Context(), "instance")
	if err != nil {
		t.Fatal(err)
	}
	if !first.Built || second.Built || first.Image != second.Image {
		t.Fatalf("first=%+v second=%+v", first, second)
	}
	backend.mu.Lock()
	created, deleted := len(backend.created), len(backend.deleted)
	backend.mu.Unlock()
	if created != 1 || deleted != 1 {
		t.Fatalf("pack workloads created/deleted = %d/%d", created, deleted)
	}
}

func TestImportRejectsLayerHashMismatchAndDeletesPackWorkload(t *testing.T) {
	layer := testLayer(t)
	server := packServer(t, layer, true)
	defer server.Close()
	backend := &importTestBackend{server: server.URL}
	store := &importTestStore{base: testBaseImage(t)}
	versionServer := npmVersionServer(t)
	defer versionServer.Close()
	service, err := NewService(Options{
		Repository:     importTestRepository{instance: commandInstance()},
		AuthSecret:     testAuthSecret,
		Backend:        backend,
		Store:          store,
		ImportTimeout:  time.Second,
		NPMRegistryURL: versionServer.URL,
		Logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
	})
	if err != nil {
		t.Fatal(err)
	}

	_, err = service.Import(t.Context(), "instance")
	if err == nil {
		t.Fatal("Import() error = nil, want sha mismatch")
	}
	var responseErr *HTTPError
	if !errors.As(err, &responseErr) || responseErr.Code != http.StatusUnprocessableEntity {
		t.Fatalf("Import() error = %v, want 422", err)
	}
	backend.mu.Lock()
	deleted := len(backend.deleted)
	backend.mu.Unlock()
	if deleted != 1 {
		t.Fatalf("deleted workloads = %d, want 1", deleted)
	}
}

func commandInstance() *models.MCPServerInstance {
	return &models.MCPServerInstance{InstanceID: "instance", WorkspaceID: "workspace", JSONSpec: map[string]interface{}{
		"type": "command", "command": "npx", "args": []interface{}{"pkg"},
	}}
}

func npmVersionServer(t *testing.T) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"dist-tags":{"latest":"1.2.3"},"versions":{"1.2.3":{}}}`))
	}))
}

func packServer(t *testing.T, layer []byte, mismatch bool) *httptest.Server {
	hash := sha256.Sum256(layer)
	sha := hex.EncodeToString(hash[:])
	if mismatch {
		sha = "0000000000000000000000000000000000000000000000000000000000000000"
	}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
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
}

func testLayer(t *testing.T) []byte {
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
	image, err := random.Image(1, 8)
	if err != nil {
		t.Fatal(err)
	}
	return image
}
