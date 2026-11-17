package router_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/router"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type rig struct {
	t      *testing.T
	ctx    context.Context
	db     storetest.DB
	ws     scope.Workspace
	svc    *service.Service
	r      *router.Router
	deps   router.Deps
	tasks  *storetest.Tasks
	firing *storetest.FiringTasks
	bus    *storetest.Bus
	broker *storetest.Broker
	known  map[string]bool
	agent  string
	stream string
}

func newRig(t *testing.T, runner service.ProcessorRunner) *rig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	g := &rig{t: t, ctx: ctx, db: storetest.DB{Pool: pool}, ws: ws, tasks: &storetest.Tasks{}, firing: &storetest.FiringTasks{},
		bus: &storetest.Bus{}, broker: &storetest.Broker{}, agent: uuid.NewString()}
	g.known = map[string]bool{g.agent: true}
	g.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true}, Agents: storetest.Agents{Known: g.known},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", Bus: g.bus, Broker: g.broker,
		Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{}, Blob: &storetest.Blob{}, Tasks: g.tasks,
		FiringTasks: g.firing, Executor: &storetest.Executor{}, Settings: service.DefaultSettings(),
	})
	g.deps = router.Deps{Service: g.svc, DB: storetest.DB{Pool: pool}, Broker: g.broker, Runner: runner,
		Settings: service.DefaultSettings()}
	g.r = router.New(g.deps)
	g.stream = g.newStream("in")
	return g
}

func (g *rig) newStream(prefix string) string {
	g.t.Helper()
	st, err := g.svc.CreateStream(g.ctx, prefix+"-"+uuid.NewString()[:8], "")
	if err != nil {
		g.t.Fatal(err)
	}
	return st.ID
}

func (g *rig) streamTrigger(filter map[string]any) domain.Subscription {
	g.t.Helper()
	stream := g.stream
	if _, err := g.svc.Create(g.ctx, domain.NewTrigger{Name: "on-event", AgentID: g.agent, Type: domain.TypeStream,
		StreamID: &stream, EventFilter: filter, TaskParameters: map[string]any{"text": "handle it"}, Enabled: true,
		FailureThreshold: 5}); err != nil {
		g.t.Fatal(err)
	}
	return g.only(domain.SubTrigger)
}

func (g *rig) only(kind string) domain.Subscription {
	g.t.Helper()
	subs, err := store.Streams{}.ListSubscriptions(g.ctx, db.NewSession(g.ws, g.db.Pool), uuid.MustParse(g.stream))
	if err != nil {
		g.t.Fatal(err)
	}
	for _, s := range subs {
		if s.Kind == kind {
			return s
		}
	}
	g.t.Fatalf("no %s subscription in %+v", kind, subs)
	return domain.Subscription{}
}

func (g *rig) event(kind string, data map[string]any) domain.Event {
	id := uuid.NewString()
	return domain.Event{ID: id, Kind: kind, Source: "test", OccurredAt: time.Now().UTC(), Data: data,
		StreamID: g.stream, WorkspaceID: g.ws.ID(), CreatedBy: "u1", EventKey: "k-" + id,
		ReceivedAt: time.Now().UTC().Add(time.Millisecond)}
}

func (g *rig) handle(e domain.Event) error {
	return g.r.Handle(g.ctx, service.BusEvent(e))
}

func (g *rig) reaction(sub domain.Subscription, e domain.Event) (storetest.Reaction, bool) {
	g.t.Helper()
	r, ok, err := g.db.ReactionOf(g.ctx, sub.ID, e.ID)
	if err != nil {
		g.t.Fatal(err)
	}
	return r, ok
}

func (g *rig) tally(e domain.Event) storetest.Tally {
	g.t.Helper()
	t, err := g.db.TallyOf(g.ctx, e.ID)
	if err != nil {
		g.t.Fatal(err)
	}
	return t
}

func TestTriggerFiresOnceAndRecordsTheReaction(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(nil)
	e := g.event("msg", map[string]any{"text": "hi"})
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	reqs := g.tasks.Submitted()
	if len(reqs) != 1 || reqs[0].TaskID != domain.TaskIDFor(sub.ID, e.ID) || reqs[0].Provenance.OriginType != "trigger" ||
		reqs[0].Provenance.CausationID != e.ID || !strings.Contains(reqs[0].Description, "handle it") {
		t.Fatalf("requests = %+v", reqs)
	}
	r, ok := g.reaction(sub, e)
	if !ok || r.Verdict != domain.VerdictReacted || r.TaskID == nil || *r.TaskID != reqs[0].TaskID {
		t.Fatalf("reaction = %+v ok=%v", r, ok)
	}
	if tl := g.tally(e); tl.Subscribers == nil || *tl.Subscribers != 1 || tl.Reacted != 1 {
		t.Fatalf("tally = %+v", tl)
	}
	if len(g.broker.Notices) < 2 || g.broker.Notices[0]["type"] != router.NoticeRecorded {
		t.Fatalf("notices = %v", g.broker.Notices)
	}
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	if n := len(g.tasks.Submitted()); n != 1 {
		t.Fatalf("redelivery submitted again: %d", n)
	}
}

func TestEventBeforeStartIsSkipped(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(nil)
	e := g.event("msg", map[string]any{})
	e.ReceivedAt = sub.StartedAt.Add(-time.Minute)
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	r, ok := g.reaction(sub, e)
	if !ok || r.Verdict != domain.VerdictSkipped || r.Reason == nil || *r.Reason != domain.BeforeStartReason {
		t.Fatalf("reaction = %+v", r)
	}
	if len(g.tasks.Submitted()) != 0 {
		t.Fatal("fired before start")
	}
}

func TestFilterThatDoesNotAdmitRecordsNothing(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(map[string]any{"kinds": []any{"wanted"}})
	e := g.event("other", map[string]any{})
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	if _, ok := g.reaction(sub, e); ok {
		t.Fatal("a filtered event reacted")
	}
	if tl := g.tally(e); tl.Subscribers == nil || *tl.Subscribers != 0 {
		t.Fatalf("tally = %+v", tl)
	}
}

func TestAgentGoneStopsTheTrigger(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(nil)
	delete(g.known, g.agent)
	e := g.event("msg", map[string]any{})
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	r, _ := g.reaction(sub, e)
	if r.Verdict != domain.VerdictError || r.Reason == nil || !strings.HasPrefix(*r.Reason, "agent_unavailable: agent "+g.agent) {
		t.Fatalf("reaction = %+v", r)
	}
	if tr, err := g.svc.Trigger(g.ctx, g.ws, *sub.TriggerID); err != nil || tr.NeedsNewOwnerAt == nil {
		t.Fatalf("needs_new_owner = %+v %v", tr, err)
	}
}

func TestRetryableFailureRedeliversThenGivesUp(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(nil)
	g.tasks.Err = errors.New("temporal unreachable")
	e := g.event("msg", map[string]any{})
	if err := g.handle(e); !errors.Is(err, router.ErrReactionsFailed) {
		t.Fatalf("handle = %v", err)
	}
	if _, ok := g.reaction(sub, e); ok {
		t.Fatal("a retryable failure was recorded")
	}
	if err := g.r.GiveUp(g.ctx, service.BusEvent(e)); err != nil {
		t.Fatal(err)
	}
	r, ok := g.reaction(sub, e)
	if !ok || r.Verdict != domain.VerdictError || r.Reason == nil || *r.Reason != domain.GaveUpReason {
		t.Fatalf("given up = %+v", r)
	}
	if tl := g.tally(e); tl.Errors != 1 {
		t.Fatalf("tally = %+v", tl)
	}
	g.tasks.Err = nil
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	if r, _ := g.reaction(sub, e); r.Verdict != domain.VerdictReacted {
		t.Fatalf("rerun after give-up = %+v", r)
	}
}

func TestLoopGuardSkipsTheTriggersOwnTask(t *testing.T) {
	g := newRig(t, nil)
	sub := g.streamTrigger(nil)
	task := uuid.NewString()
	g.firing.Origins = map[string]api.TaskOrigin{task: {OriginType: "trigger", OriginID: *sub.TriggerID}}
	e := g.event("task.completed", map[string]any{})
	platform := domain.PlatformSourceType
	e.SourceType, e.Subject = &platform, &task
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	r, _ := g.reaction(sub, e)
	if r.Verdict != domain.VerdictSkipped || r.Reason == nil || !strings.Contains(*r.Reason, "which this trigger started") {
		t.Fatalf("reaction = %+v", r)
	}
}

func TestForwardCopiesIntoOutputs(t *testing.T) {
	g := newRig(t, nil)
	out := g.newStream("out")
	if _, err := g.svc.CreateForward(g.ctx, g.stream, []string{out}, domain.EventFilter{}); err != nil {
		t.Fatal(err)
	}
	sub := g.only(domain.SubForward)
	e := g.event("msg", map[string]any{"a": "b"})
	e.Depth = 2
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	copyID, _ := domain.DerivedEventID(sub.ID, e.ID)
	want, _ := domain.DerivedEventID(copyID, out)
	r, _ := g.reaction(sub, e)
	if r.Verdict != domain.VerdictReacted || len(r.Derived) != 1 || r.Derived[0] != want {
		t.Fatalf("reaction = %+v want %s", r, want)
	}
	pub := g.bus.Events()
	last := pub[len(pub)-1].Event
	if last.ID != want || last.CausationID != e.ID || last.Extensions["depth"] != "3" || last.Source != "stream:"+g.stream {
		t.Fatalf("copy = %+v", last)
	}
	deep := g.event("msg", map[string]any{})
	deep.Depth = service.DefaultSettings().ForwardDepth
	if err := g.handle(deep); err != nil {
		t.Fatal(err)
	}
	if r, _ := g.reaction(sub, deep); r.Verdict != domain.VerdictError || !strings.HasPrefix(*r.Reason, "causation depth 9 exceeds 8") {
		t.Fatalf("deep = %+v", r)
	}
}

func TestProcessorWritesItsOutputsOrFails(t *testing.T) {
	runner := &switchRunner{}
	g := newRig(t, runner)
	out := g.newStream("out")
	code := "def process(event):\n    return [{\"stream\": \"x\", \"kind\": \"k\", \"data\": {}}]\n"
	if _, err := g.svc.CreateProcessor(g.ctx, g.stream, []string{out}, code, domain.EventFilter{}); err != nil {
		t.Fatal(err)
	}
	sub := g.only(domain.SubProcessor)
	runner.set(service.CodeRun{Stdout: `{"ok": true, "outputs": [{"stream": "` + out + `", "kind": "seen", "data": {"n": 1}}]}`})
	e := g.event("msg", map[string]any{})
	if err := g.handle(e); err != nil {
		t.Fatal(err)
	}
	want, _ := domain.ProcessorOutputID(sub.ID, e.ID, 0)
	r, _ := g.reaction(sub, e)
	if r.Verdict != domain.VerdictReacted || len(r.Derived) != 1 || r.Derived[0] != want {
		t.Fatalf("reaction = %+v", r)
	}
	if !strings.HasPrefix(runner.command, "python3 - <<'AGENTAREA_PROCESSOR_HARNESS'\n") || runner.session != "processor-"+sub.ID {
		t.Fatalf("run = %q %q", runner.session, runner.command[:40])
	}

	runner.set(service.CodeRun{Stdout: `{"ok": false, "error": "ValueError: nope (processor.py line 2)"}`})
	bad := g.event("msg", map[string]any{})
	if err := g.handle(bad); err != nil {
		t.Fatal(err)
	}
	if r, _ := g.reaction(sub, bad); r.Verdict != domain.VerdictError || *r.Reason != "ValueError: nope (processor.py line 2)" {
		t.Fatalf("failed = %+v", r)
	}

	runner.fail(service.ErrProcessorRuntimeUnavailable)
	down := g.event("msg", map[string]any{})
	if err := g.handle(down); !errors.Is(err, router.ErrReactionsFailed) {
		t.Fatalf("unavailable = %v", err)
	}
	if _, ok := g.reaction(sub, down); ok {
		t.Fatal("an unavailable sandbox was recorded")
	}
}

func TestExternalHandsTheEventToDelivery(t *testing.T) {
	broker := &storetest.Broker{}
	g := newRig(t, nil)
	g.deps.Broker = broker
	sub := domain.Subscription{ID: uuid.NewString(), WorkspaceID: g.ws.ID(), CreatedBy: "owner", Kind: domain.SubExternal}
	e := g.event("msg", map[string]any{"x": 1})
	finish, err := router.NewExternal(g.deps).Prepare(g.ctx, sub, e)
	if err != nil {
		t.Fatal(err)
	}
	res, err := finish(g.ctx, db.Session{})
	if err != nil || res.Verdict != domain.VerdictReacted || *res.Reason != router.HandedOver {
		t.Fatalf("result = %+v %v", res, err)
	}
	f := broker.Submitted[0]
	if f["subscription"] != sub.ID || f["owner"] != "owner" || f["attempt"] != "0" || f["due"] == "" {
		t.Fatalf("fields = %v", f)
	}
}

func TestCacheServesOnlyEventsReadBefore(t *testing.T) {
	g := newRig(t, nil)
	first := g.event("msg", map[string]any{})
	if err := g.handle(first); err != nil {
		t.Fatal(err)
	}
	sub := g.streamTrigger(nil)
	later := g.event("msg", map[string]any{})
	if err := g.handle(later); err != nil {
		t.Fatal(err)
	}
	if _, ok := g.reaction(sub, later); !ok {
		t.Fatal("a subscription made after the cache was read missed a later event")
	}
}

type switchRunner struct {
	mu      sync.Mutex
	result  service.CodeRun
	err     error
	session string
	command string
}

func (r *switchRunner) set(run service.CodeRun) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.result, r.err = run, nil
}

func (r *switchRunner) fail(err error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.err = err
}

func (r *switchRunner) Run(_ context.Context, _, session, command string, _ time.Duration, _ int) (service.CodeRun, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.session, r.command = session, command
	return r.result, r.err
}
