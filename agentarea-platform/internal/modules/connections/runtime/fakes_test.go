package runtime

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/otel/metric/noop"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

const testSecret = "0123456789abcdef0123456789abcdef"

type statusReply struct {
	status      string
	internalURL string
	message     string
	err         error
}

// fakeBackend answers Status from a script (the last reply repeats) and
// counts creations and deletions.
type fakeBackend struct {
	mu        sync.Mutex
	statuses  []statusReply
	calls     int
	creates   int
	deletes   int
	specs     []workload.Spec
	createErr error
	deleteErr error
}

func (b *fakeBackend) Create(_ context.Context, s workload.Spec) (workload.Status, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.creates++
	b.specs = append(b.specs, s)
	return workload.Status{}, b.createErr
}

func (b *fakeBackend) Delete(context.Context, string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.deletes++
	return b.deleteErr
}

func (b *fakeBackend) Status(context.Context, string) (workload.Status, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.statuses) == 0 {
		return workload.Status{}, workload.ErrNotFound
	}
	r := b.statuses[min(b.calls, len(b.statuses)-1)]
	b.calls++
	if r.err != nil {
		return workload.Status{}, r.err
	}
	return workload.Status{Status: r.status, InternalURL: r.internalURL, Message: r.message}, nil
}

func (b *fakeBackend) Reservation(context.Context) (workload.Reservation, error) {
	return workload.Reservation{}, nil
}

func (b *fakeBackend) counts() (creates, deletes int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.creates, b.deletes
}

// fakeSpecs serves server specs by id.
type fakeSpecs struct {
	catalogapi.MCPSpecs
	specs map[string]catalogapi.MCPSpec
}

func (f fakeSpecs) Get(_ context.Context, _ scope.Workspace, id string, _ catalogapi.MCPSpecGet) (catalogapi.MCPSpec, bool, error) {
	s, ok := f.specs[id]
	return s, ok, nil
}

// fakeSecrets serves workspace secrets (references) and instance secrets by name.
type fakeSecrets struct{ values map[string]string }

func (f fakeSecrets) Manager(db.Session, string) ksecrets.Manager { return fakeManager(f) }

func (f fakeSecrets) UserSecrets(db.Session) ksecrets.UserSecrets { return fakeManager(f) }

type fakeManager struct{ values map[string]string }

func (m fakeManager) Get(_ context.Context, name string) (string, error) {
	v, ok := m.values[name]
	if !ok {
		return "", ksecrets.ErrNotFound
	}
	return v, nil
}

func (m fakeManager) GetUserOwned(ctx context.Context, name string) (string, error) {
	return m.Get(ctx, name)
}

func (fakeManager) Set(context.Context, string, string) error { return errors.New("read-only") }

func (fakeManager) Delete(context.Context, string) (bool, error) {
	return false, errors.New("read-only")
}

func (m fakeManager) Has(_ context.Context, name string) (bool, error) {
	_, ok := m.values[name]
	return ok, nil
}

func (fakeManager) ExternalRef(string) (string, bool) { return "", false }

type fakeStorage struct{ env map[string]string }

func (s fakeStorage) Environment(string, string, map[string]any) (map[string]string, error) {
	return s.env, nil
}

// readOnlyDB serves Read with a session no query reaches (the secrets are
// fakes); anything else is a test that needs the real database.
type readOnlyDB struct{ db.Database }

func (readOnlyDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func testConfig(startup time.Duration) Config {
	return Config{Backend: BackendDocker, GatewaySecret: testSecret, LeaseTTL: 30 * time.Second,
		StartupTimeout: startup, IdleTimeout: time.Minute, SweepInterval: time.Minute, BaseImage: "agentarea/agentarea-mcp-base:test"}
}

func testDeps(b workload.Backend, startup time.Duration) Deps {
	return Deps{
		Config: testConfig(startup), DB: readOnlyDB{}, Specs: fakeSpecs{}, Secrets: fakeSecrets{}, Backend: b,
		Storage: fakeStorage{}, Workloads: http.DefaultTransport, URLs: http.DefaultTransport,
		Meter: noop.NewMeterProvider().Meter("test"), Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func newRuntime(t *testing.T, d Deps) *Runtime {
	t.Helper()
	r, err := New(d)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func dockerInstance() *instance {
	return &instance{ID: "4f4ad5a0-8e8b-4d3a-9b0c-0c7f1e1e9a11", WorkspaceID: "ws-1",
		Spec: map[string]any{"type": "docker", "image": "ghcr.io/acme/mcp:1"}}
}

// listening is an address that accepts connections until the test ends.
func listening(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	return "http://" + ln.Addr().String()
}

// closedAddress is an address nothing listens on.
func closedAddress(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()
	return "http://" + addr
}

type recordingObserver struct {
	mu         sync.Mutex
	operations []Operation
	boundaries []Boundary
	refuse     error
}

func (o *recordingObserver) Operation(_ context.Context, op Operation) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.operations = append(o.operations, op)
	if op.Phase == OperationStarted {
		return o.refuse
	}
	return nil
}

func (o *recordingObserver) Boundary(_ context.Context, b BoundaryObservation) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.boundaries = append(o.boundaries, b.Boundary)
	return nil
}
