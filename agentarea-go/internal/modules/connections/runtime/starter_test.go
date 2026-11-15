package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

func TestStartFailureBackoffGrowsExponentiallyToCap(t *testing.T) {
	want := []time.Duration{0, time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second, 16 * time.Second, 30 * time.Second, 30 * time.Second}
	for n, w := range want {
		if got := backoff(n); got != w {
			t.Errorf("backoff(%d) = %v, want %v", n, got, w)
		}
	}
}

func TestStartFailureBackoffPreventsRepeatedCreation(t *testing.T) {
	b := &fakeBackend{createErr: errors.New("daemon refused")}
	r := newRuntime(t, testDeps(b, time.Second))
	_, err := r.ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	var failure *StartupFailureError
	if !errors.As(err, &failure) || failure.RetryDelay() != time.Second {
		t.Fatalf("first start: %v, want a startup failure retried in 1s", err)
	}
	_, err = r.ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	var backoffErr *StartBackoffError
	if !errors.As(err, &backoffErr) || backoffErr.RetryDelay() <= 0 || backoffErr.FailureReason() != failure.FailureReason() {
		t.Fatalf("second start: %v, want the backoff with the first failure's reason", err)
	}
	if creates, _ := b.counts(); creates != 1 {
		t.Fatalf("creates = %d, want the backoff to refuse a second creation", creates)
	}
}

func TestOnlyAMissingInstanceTriggersCreation(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: errors.New("daemon unreachable")}}}
	r := newRuntime(t, testDeps(b, time.Second))
	if _, err := r.ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{}); err == nil {
		t.Fatal("an unreadable status started a workload")
	}
	if creates, _ := b.counts(); creates != 0 {
		t.Fatalf("creates = %d, want none on a status error", creates)
	}
}

func TestColdStartWaitsForTheWorkloadToListen(t *testing.T) {
	url := listening(t)
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "created"}, {status: "running", internalURL: url}}}
	r := newRuntime(t, testDeps(b, 10*time.Second))
	report := &gateway.ColdStart{}
	upstream, err := r.ensureReady(context.Background(), dockerInstance(), report)
	if err != nil {
		t.Fatal(err)
	}
	if upstream != url+"/mcp" {
		t.Fatalf("upstream = %q", upstream)
	}
	if creates, deletes := b.counts(); creates != 1 || deletes != 0 {
		t.Fatalf("creates=%d deletes=%d", creates, deletes)
	}
	if !report.Activated || report.FailedIn != "" {
		t.Fatalf("report = %+v, want an activation that failed nowhere", report)
	}
}

func TestWorkloadThatNeverListensIsTornDown(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "running", internalURL: closedAddress(t)}}}
	r := newRuntime(t, testDeps(b, 600*time.Millisecond))
	report := &gateway.ColdStart{}
	_, err := r.ensureReady(context.Background(), dockerInstance(), report)
	var failure *StartupFailureError
	if !errors.As(err, &failure) || !strings.Contains(failure.FailureReason(), "did not listen") {
		t.Fatalf("err = %v, want a listen failure", err)
	}
	if creates, deletes := b.counts(); creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the silent workload removed", creates, deletes)
	}
	if report.FailedIn != gateway.StepListening {
		t.Fatalf("failed in %q", report.FailedIn)
	}
}

func TestStoppedWorkloadIsReplacedNotWaitedOn(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{status: "exited"}, {status: "running", internalURL: listening(t)}}}
	r := newRuntime(t, testDeps(b, 5*time.Second))
	if _, err := r.ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{}); err != nil {
		t.Fatal(err)
	}
	if creates, deletes := b.counts(); creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the stopped workload replaced", creates, deletes)
	}
}

func TestWorkloadThatStopsWhileStartingFailsFast(t *testing.T) {
	for name, statuses := range map[string][]statusReply{
		"before running":   {{err: workload.ErrNotFound}, {status: "stopped"}},
		"while installing": {{err: workload.ErrNotFound}, {status: "running", internalURL: closedAddress(t)}, {status: "stopped"}},
	} {
		t.Run(name, func(t *testing.T) {
			b := &fakeBackend{statuses: statuses}
			began := time.Now()
			_, err := newRuntime(t, testDeps(b, 30*time.Second)).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
			if err == nil || !strings.Contains(err.Error(), "stopped") {
				t.Fatalf("err = %v, want the stopped workload reported", err)
			}
			if waited := time.Since(began); waited > 5*time.Second {
				t.Fatalf("waited %v on a stopped start", waited)
			}
			if creates, deletes := b.counts(); creates != 1 || deletes != 1 {
				t.Fatalf("creates=%d deletes=%d, want the failed start cleaned up", creates, deletes)
			}
		})
	}
}

func TestStoppedStartReportsTheServerOutput(t *testing.T) {
	output := strings.Repeat("npm notice\n", 400) + "\x1b[31msh: 1: some-server: not found\x1b[0m\n"
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "failed", message: output}}}
	_, err := newRuntime(t, testDeps(b, 30*time.Second)).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	var failure *StartupFailureError
	if !errors.As(err, &failure) {
		t.Fatalf("err = %v, want a classified startup failure", err)
	}
	reason := failure.FailureReason()
	if !strings.Contains(reason, "sh: 1: some-server: not found") {
		t.Fatalf("reason = %q, want the server output in it", reason)
	}
	if strings.ContainsAny(reason, "\x1b\n\r") {
		t.Fatalf("reason = %q carries control characters", reason)
	}
	if len(reason) > 1200 {
		t.Fatalf("reason is %d bytes, want it bounded", len(reason))
	}
}

func TestReadyWorkloadIsNeitherRecreatedNorTornDown(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{status: "running", internalURL: "http://10.0.0.7:8000"}}}
	report := &gateway.ColdStart{}
	upstream, err := newRuntime(t, testDeps(b, time.Second)).ensureReady(context.Background(), dockerInstance(), report)
	if err != nil || upstream != "http://10.0.0.7:8000/mcp" {
		t.Fatalf("upstream=%q err=%v", upstream, err)
	}
	if creates, deletes := b.counts(); creates != 0 || deletes != 0 || report.Activated {
		t.Fatalf("creates=%d deletes=%d activated=%v, want the ready workload untouched", creates, deletes, report.Activated)
	}
}

func TestAbandonedColdStartCleansUpAndNamesTheLastState(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "pending"}}}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	_, err := newRuntime(t, testDeps(b, time.Minute)).ensureReady(ctx, dockerInstance(), &gateway.ColdStart{})
	if err == nil || !strings.Contains(err.Error(), "pending") {
		t.Fatalf("err = %v, want the last state named", err)
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want it to still be the deadline", err)
	}
	if creates, deletes := b.counts(); creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the abandoned start torn down", creates, deletes)
	}
}

func TestStatusErrorDuringStartCleansUpTheWorkload(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {err: errors.New("daemon gone")}}}
	_, err := newRuntime(t, testDeps(b, time.Second)).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	if err == nil {
		t.Fatal("an unreadable start reported success")
	}
	if _, deletes := b.counts(); deletes != 1 {
		t.Fatalf("deletes = %d, want the workload removed", deletes)
	}
}

func TestCleanupToleratesAnAlreadyGoneWorkload(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "stopped"}}, deleteErr: workload.ErrNotFound}
	_, err := newRuntime(t, testDeps(b, time.Second)).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	if err == nil || strings.Contains(err.Error(), "cleanup") {
		t.Fatalf("err = %v, want the start failure without a cleanup failure", err)
	}
}

func TestFailedCleanupKeepsTheClassifiedReason(t *testing.T) {
	gone := errors.New("daemon gone")
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "stopped"}}, deleteErr: gone}
	_, err := newRuntime(t, testDeps(b, time.Second)).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{})
	var failure *StartupFailureError
	if !errors.As(err, &failure) || !strings.Contains(failure.FailureReason(), "stopped during startup") {
		t.Fatalf("err = %v", err)
	}
	if !errors.Is(err, gone) {
		t.Fatalf("err = %v, want the cleanup failure joined", err)
	}
}

func TestNonContainerInstancesAreRefusedBeforeAnyWorkload(t *testing.T) {
	b := &fakeBackend{}
	inst := &instance{ID: "x", WorkspaceID: "ws-1", Spec: map[string]any{"type": "url"}}
	if _, err := newRuntime(t, testDeps(b, time.Second)).ensureReady(context.Background(), inst, &gateway.ColdStart{}); err == nil {
		t.Fatal("a url instance was started")
	}
	if b.calls != 0 {
		t.Fatalf("status calls = %d, want none", b.calls)
	}
}

func TestObserverRefusalStopsTheCreation(t *testing.T) {
	b := &fakeBackend{}
	d := testDeps(b, time.Second)
	obs := &recordingObserver{refuse: errors.New("over quota")}
	d.Observers = []Observer{obs}
	report := &gateway.ColdStart{}
	_, err := newRuntime(t, d).ensureReady(context.Background(), dockerInstance(), report)
	if err == nil || !strings.Contains(err.Error(), "over quota") {
		t.Fatalf("err = %v, want the observer's refusal", err)
	}
	if creates, _ := b.counts(); creates != 0 || report.FailedIn != gateway.StepObserver {
		t.Fatalf("creates=%d failed in %q", creates, report.FailedIn)
	}
}

func TestObserverSeesCreationAndActivation(t *testing.T) {
	b := &fakeBackend{statuses: []statusReply{{err: workload.ErrNotFound}, {status: "running", internalURL: listening(t)}}}
	d := testDeps(b, 5*time.Second)
	obs := &recordingObserver{}
	d.Observers = []Observer{obs}
	if _, err := newRuntime(t, d).ensureReady(context.Background(), dockerInstance(), &gateway.ColdStart{}); err != nil {
		t.Fatal(err)
	}
	if len(obs.operations) != 2 || obs.operations[0].Phase != OperationStarted || obs.operations[1].Phase != OperationCompleted ||
		obs.operations[0].OperationID != obs.operations[1].OperationID {
		t.Fatalf("operations = %+v", obs.operations)
	}
	if len(obs.boundaries) != 1 || obs.boundaries[0] != BoundaryActivation {
		t.Fatalf("boundaries = %v", obs.boundaries)
	}
}

func TestOutputTailStripsAndBounds(t *testing.T) {
	if got := outputTail("\x1b[1mhello\x1b[0m\n\tworld"); got != "hello world" {
		t.Fatalf("got %q", got)
	}
	long := outputTail(strings.Repeat("é", 2000))
	if !strings.HasPrefix(long, "...") || len(long) > maxServerOutput+3 || !strings.HasSuffix(long, "é") {
		t.Fatalf("tail of %d bytes: %q...", len(long), long[:10])
	}
}

func TestHealthReportsTheWorkload(t *testing.T) {
	for name, tc := range map[string]struct {
		reply   statusReply
		healthy bool
		status  string
		err     error
	}{
		"absent":    {reply: statusReply{err: workload.ErrNotFound}, err: service.ErrRuntimeNotRunning},
		"starting":  {reply: statusReply{status: "created"}, status: "created"},
		"listening": {reply: statusReply{status: "running", internalURL: listening(t)}, healthy: true, status: "running"},
		"silent":    {reply: statusReply{status: "running", internalURL: closedAddress(t)}, status: "unreachable"},
	} {
		t.Run(name, func(t *testing.T) {
			h, err := newRuntime(t, testDeps(&fakeBackend{statuses: []statusReply{tc.reply}}, time.Second)).Health(context.Background(), "id")
			if !errors.Is(err, tc.err) || h.Healthy != tc.healthy || h.Status != tc.status {
				t.Fatalf("health=%+v err=%v", h, err)
			}
		})
	}
}

func TestValidateHandsTheDryRunPlainNumbers(t *testing.T) {
	d := testDeps(&fakeBackend{}, time.Second)
	var got map[string]any
	d.Validator = func(_ context.Context, spec map[string]any) (service.RuntimeValidation, error) {
		got = spec
		return service.RuntimeValidation{Valid: true}, nil
	}
	spec := map[string]any{"port": json.Number("8080"), "resources": map[string]any{"cpus": []any{json.Number("1.5")}}}
	v, err := newRuntime(t, d).Validate(context.Background(), "n", spec)
	if err != nil || !v.Valid {
		t.Fatalf("v=%+v err=%v", v, err)
	}
	if got["port"] != float64(8080) {
		t.Fatalf("port = %#v", got["port"])
	}
	if cpus := got["resources"].(map[string]any)["cpus"].([]any); cpus[0] != 1.5 {
		t.Fatalf("nested = %#v", cpus[0])
	}
}

func TestValidateWithoutADryRunIsAnError(t *testing.T) {
	if _, err := newRuntime(t, testDeps(&fakeBackend{}, time.Second)).Validate(context.Background(), "n", map[string]any{}); err == nil {
		t.Fatal("a backend without a dry run validated")
	}
}

func TestRetirementErrorIsTheServiceError(t *testing.T) {
	for name, tc := range map[string]struct {
		cause    error
		conflict bool
	}{
		"busy":     {cause: gateway.ErrInstanceBusy, conflict: true},
		"starting": {cause: gateway.ErrStartInProgress, conflict: true},
		"backend":  {cause: errors.New("daemon gone")},
	} {
		t.Run(name, func(t *testing.T) {
			var err error = &retirementError{conflict: tc.conflict, err: tc.cause}
			var svc *service.RuntimeRetirementError
			if !errors.As(err, &svc) || svc.Conflict != tc.conflict || svc.Msg != tc.cause.Error() {
				t.Fatalf("as service error: %+v", svc)
			}
			if !errors.Is(err, tc.cause) {
				t.Fatal("the gateway can no longer classify the cause")
			}
		})
	}
}

func TestNewRefusesAnIncompleteRuntime(t *testing.T) {
	for name, mutate := range map[string]func(*Deps){
		"no backend":   func(d *Deps) { d.Backend = nil },
		"short secret": func(d *Deps) { d.Config.GatewaySecret = "short" },
		"no lease":     func(d *Deps) { d.Config.LeaseTTL = 0 },
		"no image":     func(d *Deps) { d.Config.BaseImage = "" },
		"no storage":   func(d *Deps) { d.Storage = nil },
	} {
		t.Run(name, func(t *testing.T) {
			d := testDeps(&fakeBackend{}, time.Second)
			mutate(&d)
			if _, err := New(d); err == nil {
				t.Fatal("built")
			}
		})
	}
}
