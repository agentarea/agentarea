package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

const serverSpecID = "spec-docker"

func testPools(t *testing.T) *db.Pools {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	if err := sqlDB.Close(); err != nil {
		t.Fatal(err)
	}
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatal(err)
	}
	password, _ := u.User.Password()
	p, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: u.Path[1:], User: u.User.Username(), Password: password,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 10, PoolTimeout: 5 * time.Second,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(p.Close)
	return p
}

type dbRig struct {
	t       *testing.T
	pools   *db.Pools
	backend *fakeBackend
	r       *Runtime
	ws      string
}

func newDBRig(t *testing.T, mutate func(*Deps)) *dbRig {
	t.Helper()
	p := testPools(t)
	b := &fakeBackend{}
	d := testDeps(b, 5*time.Second)
	d.DB = p
	d.Specs = fakeSpecs{specs: map[string]catalogapi.MCPSpec{serverSpecID: {ID: serverSpecID, JSONSpec: map[string]any{}}}}
	d.Config.IdleTimeout = 50 * time.Millisecond
	if mutate != nil {
		mutate(&d)
	}
	return &dbRig{t: t, pools: p, backend: b, r: newRuntime(t, d), ws: uuid.NewString()}
}

func (g *dbRig) exec(sql string, args ...any) {
	g.t.Helper()
	if err := g.pools.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, sql, args...)
		return err
	}); err != nil {
		g.t.Fatal(err)
	}
}

func (g *dbRig) scan(sql string, args []any, dest ...any) {
	g.t.Helper()
	if err := g.pools.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		return q.QueryRow(ctx, sql, args...).Scan(dest...)
	}); err != nil {
		g.t.Fatal(err)
	}
}

// instance inserts a docker instance of the rig's workspace.
func (g *dbRig) instance() uuid.UUID {
	g.t.Helper()
	id := uuid.New()
	g.exec(`INSERT INTO mcp_server_instances (id, server_spec_id, name, json_spec, workspace_id, created_by, transport)
		VALUES ($1, $2, 'mcp', '{"image": "ghcr.io/acme/mcp:1"}', $3, 'u1', 'docker')`, id, serverSpecID, g.ws)
	return id
}

func (g *dbRig) state(id uuid.UUID) (state string, generation int64) {
	g.t.Helper()
	g.scan(`SELECT state, generation FROM mcp_runtime_instances WHERE instance_id = $1`, []any{id}, &state, &generation)
	return state, generation
}

// ready puts id in the ready state, last used an hour ago.
func (g *dbRig) ready(id uuid.UUID) {
	g.t.Helper()
	ctx := context.Background()
	if err := g.r.markStarting(ctx, id); err != nil {
		g.t.Fatal(err)
	}
	if err := g.r.markReadyAndBeginRequest(ctx, id, uuid.New()); err != nil {
		g.t.Fatal(err)
	}
	g.exec(`DELETE FROM mcp_runtime_request_leases WHERE instance_id = $1`, id)
	g.exec(`UPDATE mcp_runtime_instances SET last_used_at = now() - interval '1 hour' WHERE instance_id = $1`, id)
}

func TestMarkStartingAdvancesTheGenerationOnlyFromRest(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	id := g.instance()
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if s, gen := g.state(id); s != "starting" || gen != 1 {
		t.Fatalf("first start: %s gen %d", s, gen)
	}
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if _, gen := g.state(id); gen != 1 {
		t.Fatalf("a start while starting advanced to gen %d", gen)
	}
	if err := g.r.markFailed(ctx, id, errors.New("boom")); err != nil {
		t.Fatal(err)
	}
	var lastError string
	g.scan(`SELECT last_error FROM mcp_runtime_instances WHERE instance_id = $1`, []any{id}, &lastError)
	if lastError != "boom" {
		t.Fatalf("last_error = %q", lastError)
	}
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if s, gen := g.state(id); s != "starting" || gen != 2 {
		t.Fatalf("restart: %s gen %d", s, gen)
	}
}

func TestWarmRequestKeepsInstanceReadyAndGeneration(t *testing.T) {
	g := newDBRig(t, nil)
	id := g.instance()
	g.ready(id)
	if err := g.r.markStarting(context.Background(), id); err != nil {
		t.Fatal(err)
	}
	if s, gen := g.state(id); s != "ready" || gen != 1 {
		t.Fatalf("warm request: %s gen %d", s, gen)
	}
}

func TestLifecycleLockSerializesTheInstance(t *testing.T) {
	g := newDBRig(t, nil)
	id := g.instance().String()
	held, release := make(chan struct{}), make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		_ = g.r.withInstanceLock(context.Background(), id, func(context.Context) error {
			close(held)
			<-release
			return nil
		})
	}()
	<-held
	began := time.Now()
	err := g.r.withInstanceLock(context.Background(), id, func(context.Context) error { return nil })
	if !errors.Is(err, gateway.ErrStartInProgress) {
		t.Fatalf("err = %v, want ErrStartInProgress", err)
	}
	if waited := time.Since(began); waited < lockWait {
		t.Fatalf("gave up after %v", waited)
	}
	close(release)
	wg.Wait()
	if err := g.r.withInstanceLock(context.Background(), id, func(context.Context) error { return nil }); err != nil {
		t.Fatalf("the released lock is still held: %v", err)
	}
}

func TestRequestLeaseHeartbeatAndFinish(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	id, rid := g.instance(), uuid.New()
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if err := g.r.markReadyAndBeginRequest(ctx, id, rid); err != nil {
		t.Fatal(err)
	}
	var live bool
	g.scan(`SELECT expires_at > now() + interval '20 seconds' FROM mcp_runtime_request_leases WHERE request_id = $1`, []any{rid}, &live)
	if !live {
		t.Fatal("the lease does not run for its TTL")
	}
	g.exec(`UPDATE mcp_runtime_request_leases SET expires_at = now() + interval '1 second' WHERE request_id = $1`, rid)
	if err := g.r.heartbeat(ctx, rid); err != nil {
		t.Fatal(err)
	}
	g.scan(`SELECT expires_at > now() + interval '20 seconds' FROM mcp_runtime_request_leases WHERE request_id = $1`, []any{rid}, &live)
	if !live {
		t.Fatal("the heartbeat did not extend the lease")
	}
	if err := g.r.finishRequest(ctx, id, rid); err != nil {
		t.Fatal(err)
	}
	if err := g.r.finishRequest(ctx, id, rid); err == nil {
		t.Fatal("a finished lease finished twice")
	}
	if err := g.r.heartbeat(ctx, rid); err == nil {
		t.Fatal("a finished lease took a heartbeat")
	}
}

func TestIdleSelectionSkipsLiveLeasesAndDropsExpiredOnes(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	idle, busy, expired := g.instance(), g.instance(), g.instance()
	for _, id := range []uuid.UUID{idle, busy, expired} {
		g.ready(id)
	}
	g.exec(`INSERT INTO mcp_runtime_request_leases (request_id, instance_id, expires_at) VALUES ($1, $2, now() + interval '1 minute')`, uuid.New(), busy)
	g.exec(`INSERT INTO mcp_runtime_request_leases (request_id, instance_id, expires_at) VALUES ($1, $2, now() - interval '1 second')`, uuid.New(), expired)
	ids, err := g.r.idleCandidates(ctx)
	if err != nil {
		t.Fatal(err)
	}
	found := map[uuid.UUID]bool{}
	for _, id := range ids {
		found[id] = true
	}
	if !found[idle] || found[busy] || !found[expired] {
		t.Fatalf("idle=%v busy=%v expired=%v", found[idle], found[busy], found[expired])
	}
	var n int
	g.scan(`SELECT count(*) FROM mcp_runtime_request_leases WHERE instance_id = $1`, []any{expired}, &n)
	if n != 0 {
		t.Fatal("the expired lease was kept")
	}
}

func TestReaperRemovesIdleInstanceAndMarksItDormant(t *testing.T) {
	g := newDBRig(t, nil)
	id := g.instance()
	g.ready(id)
	removed, err := g.r.reapIfIdle(context.Background(), id)
	if err != nil || !removed {
		t.Fatalf("removed=%v err=%v", removed, err)
	}
	if s, _ := g.state(id); s != "dormant" {
		t.Fatalf("state %s", s)
	}
	if _, deletes := g.backend.counts(); deletes != 1 {
		t.Fatalf("deletes = %d", deletes)
	}
}

func TestReaperIsFencedByALiveLease(t *testing.T) {
	g := newDBRig(t, nil)
	id := g.instance()
	g.ready(id)
	g.exec(`INSERT INTO mcp_runtime_request_leases (request_id, instance_id, expires_at) VALUES ($1, $2, now() + interval '1 minute')`, uuid.New(), id)
	removed, err := g.r.reapIfIdle(context.Background(), id)
	if err != nil || removed {
		t.Fatalf("removed=%v err=%v", removed, err)
	}
	if _, deletes := g.backend.counts(); deletes != 0 {
		t.Fatal("a leased workload was deleted")
	}
}

func TestFailedReapRestoresTheStateItFound(t *testing.T) {
	g := newDBRig(t, nil)
	g.backend.deleteErr = errors.New("daemon gone")
	id := g.instance()
	g.ready(id)
	if removed, err := g.r.reapIfIdle(context.Background(), id); err == nil || removed {
		t.Fatalf("removed=%v err=%v", removed, err)
	}
	if s, _ := g.state(id); s != "ready" {
		t.Fatalf("state %s, want ready restored", s)
	}
}

func TestDeletionIsRefusedWhileARequestIsInFlight(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	id := g.instance()
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if err := g.r.markReadyAndBeginRequest(ctx, id, uuid.New()); err != nil {
		t.Fatal(err)
	}
	err := g.r.Retire(ctx, id.String())
	var svc *service.RuntimeRetirementError
	if !errors.Is(err, gateway.ErrInstanceBusy) || !errors.As(err, &svc) || !svc.Conflict {
		t.Fatalf("err = %v, want a conflict", err)
	}
	if _, deletes := g.backend.counts(); deletes != 0 {
		t.Fatal("a busy workload was deleted")
	}
}

func TestRetireRemovesTheWorkloadAndRestsTheInstance(t *testing.T) {
	g := newDBRig(t, nil)
	id := g.instance()
	g.ready(id)
	if err := g.r.Retire(context.Background(), id.String()); err != nil {
		t.Fatal(err)
	}
	if s, _ := g.state(id); s != "dormant" {
		t.Fatalf("state %s", s)
	}
	if _, deletes := g.backend.counts(); deletes != 1 {
		t.Fatalf("deletes = %d", deletes)
	}
}

func TestRetireOfARemovedInstanceDeletesItsWorkload(t *testing.T) {
	g := newDBRig(t, nil)
	if err := g.r.Retire(context.Background(), uuid.NewString()); err != nil {
		t.Fatal(err)
	}
	if _, deletes := g.backend.counts(); deletes != 1 {
		t.Fatalf("deletes = %d, want the orphan workload removed", deletes)
	}
}

func TestParticipantRunsInTheTransitionTransaction(t *testing.T) {
	var seen []LifecycleChange
	refuse := false
	g := newDBRig(t, func(d *Deps) {
		d.Participant = func(ctx context.Context, q db.Querier, c LifecycleChange) error {
			var state string
			if err := q.QueryRow(ctx, `SELECT state FROM mcp_runtime_instances WHERE instance_id = $1`, c.InstanceID).Scan(&state); err != nil {
				return err
			}
			if state != c.State {
				return errors.New("the participant does not see the transition's row")
			}
			seen = append(seen, c)
			if refuse {
				return errors.New("ledger refused")
			}
			return nil
		}
	})
	ctx := context.Background()
	id := g.instance()
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 1 || seen[0].Transition != TransitionStarting || seen[0].WorkspaceID != g.ws || seen[0].Generation != 1 || seen[0].Reason != ReasonDemand {
		t.Fatalf("seen = %+v", seen)
	}
	refuse = true
	if err := g.r.markFailed(ctx, id, errors.New("boom")); err == nil {
		t.Fatal("a refused transition committed")
	}
	if s, _ := g.state(id); s != "starting" {
		t.Fatalf("state %s, want the refused transition rolled back", s)
	}
}

func TestEveryTransitionEmitsStatusChanged(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	id := g.instance()
	if err := g.r.markStarting(ctx, id); err != nil {
		t.Fatal(err)
	}
	if err := g.r.markFailed(ctx, id, errors.New("boom")); err != nil {
		t.Fatal(err)
	}
	var raw []byte
	var workspace, createdBy string
	g.scan(`SELECT payload, workspace_id, created_by FROM event_outbox
		WHERE event_type = $1 AND payload->'data'->>'instance_id' = $2 AND payload->'data'->>'transition' = 'failed'`,
		[]any{StatusChanged, id.String()}, &raw, &workspace, &createdBy)
	var payload struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"instance_id": id.String(), "workspace_id": g.ws, "generation": float64(1),
		"state": "failed", "transition": "failed", "reason": ReasonActivation, "error": "boom"}
	for k, v := range want {
		if payload.Data[k] != v {
			t.Errorf("data.%s = %#v, want %#v", k, payload.Data[k], v)
		}
	}
	if workspace != g.ws || createdBy != EventPrincipal {
		t.Fatalf("row workspace=%s created_by=%s", workspace, createdBy)
	}
	var n int
	g.scan(`SELECT count(*) FROM event_outbox WHERE event_type = $1 AND payload->'data'->>'instance_id' = $2`, []any{StatusChanged, id.String()}, &n)
	if n != 2 {
		t.Fatalf("%d events, want one per transition", n)
	}
}

func TestCountByState(t *testing.T) {
	g := newDBRig(t, nil)
	ctx := context.Background()
	before, err := g.r.countByState(ctx)
	if err != nil {
		t.Fatal(err)
	}
	g.ready(g.instance())
	if err := g.r.markStarting(ctx, g.instance()); err != nil {
		t.Fatal(err)
	}
	after, err := g.r.countByState(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if after["ready"]-before["ready"] != 1 || after["starting"]-before["starting"] != 1 {
		t.Fatalf("before=%v after=%v", before, after)
	}
}

func TestAdmitStartsTheWorkloadAndOpensALease(t *testing.T) {
	g := newDBRig(t, nil)
	g.backend.statuses = []statusReply{{err: workload.ErrNotFound}, {status: "running", internalURL: listening(t)}}
	ctx := context.Background()
	id := g.instance()
	target, err := g.r.Load(ctx, id.String())
	if err != nil {
		t.Fatal(err)
	}
	if target.WorkspaceID != g.ws || target.URL != nil {
		t.Fatalf("target = %+v", target)
	}
	report := &gateway.ColdStart{}
	adm, err := g.r.Admit(ctx, target, uuid.NewString(), report)
	if err != nil {
		t.Fatal(err)
	}
	if adm.Remote || adm.Upstream == "" || !report.Activated {
		t.Fatalf("admission = %+v report = %+v", adm, report)
	}
	if s, gen := g.state(id); s != "ready" || gen != 1 {
		t.Fatalf("state %s gen %d", s, gen)
	}
	if err := adm.Lease.Heartbeat(ctx); err != nil {
		t.Fatal(err)
	}
	if err := adm.Lease.Finish(ctx); err != nil {
		t.Fatal(err)
	}
	if specs := g.backend.specs; len(specs) != 1 || specs[0].Image != "ghcr.io/acme/mcp:1" || specs[0].Port != 8000 {
		t.Fatalf("created %+v", specs)
	}
}

func TestAdmitRecordsAFailedStart(t *testing.T) {
	g := newDBRig(t, nil)
	g.backend.createErr = errors.New("daemon refused")
	ctx := context.Background()
	id := g.instance()
	target, err := g.r.Load(ctx, id.String())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := g.r.Admit(ctx, target, uuid.NewString(), &gateway.ColdStart{}); err == nil {
		t.Fatal("a refused creation was admitted")
	}
	if s, _ := g.state(id); s != "failed" {
		t.Fatalf("state %s, want failed", s)
	}
}

func TestLoadOfAnUnknownInstanceIsNotFound(t *testing.T) {
	g := newDBRig(t, nil)
	for _, id := range []string{uuid.NewString(), "not-a-uuid"} {
		if _, err := g.r.Load(context.Background(), id); !errors.Is(err, gateway.ErrInstanceNotFound) {
			t.Errorf("%s: err = %v", id, err)
		}
	}
}

func TestLoadReadsAURLInstance(t *testing.T) {
	g := newDBRig(t, func(d *Deps) {
		remote := "https://mcp.example.com/mcp"
		d.Specs = fakeSpecs{specs: map[string]catalogapi.MCPSpec{"spec-url": {ID: "spec-url", RemoteURL: &remote, JSONSpec: map[string]any{}}}}
	})
	id := uuid.New()
	g.exec(`INSERT INTO mcp_server_instances (id, server_spec_id, name, json_spec, workspace_id, created_by, transport, managed_by)
		VALUES ($1, 'spec-url', 'u', '{"headers": {"X-Team": "a"}, "env_vars": ["TOKEN"]}', $2, 'u1', 'url', 'platform')`, id, g.ws)
	target, err := g.r.Load(context.Background(), id.String())
	if err != nil {
		t.Fatal(err)
	}
	u := target.URL
	if u == nil || u.EndpointURL != "https://mcp.example.com/mcp" || u.Headers["X-Team"] != "a" || u.ManagedBy != "platform" || len(u.EnvVars) != 1 {
		t.Fatalf("url = %+v", u)
	}
}
