package temporal

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

type itestIn struct {
	Query   string         `json:"query"`
	Timeout time.Duration  `json:"timeout"`
	Meta    map[string]any `json:"meta"`
}

type itestOut struct {
	Reply   string        `json:"reply"`
	Elapsed time.Duration `json:"elapsed"`
}

type itestState struct {
	Commands []string `json:"commands"`
	Bumps    int      `json:"bumps"`
	Reply    string   `json:"reply"`
	Denial   string   `json:"denial"`
}

func itestWorkflow(ctx workflow.Context, in itestIn) (itestState, error) {
	var st itestState
	if err := workflow.SetQueryHandler(ctx, "state", func() (itestState, error) { return st, nil }); err != nil {
		return st, err
	}
	if err := workflow.SetUpdateHandler(ctx, "bump", func(_ workflow.Context, by int) (int, error) {
		st.Bumps += by
		return st.Bumps, nil
	}); err != nil {
		return st, err
	}
	done := false
	workflow.GetSignalChannel(ctx, "done").Receive(ctx, &done)
	actx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second})
	var out itestOut
	if err := workflow.ExecuteActivity(actx, "itest_activity", in).Get(ctx, &out); err != nil {
		return st, err
	}
	st.Reply = fmt.Sprintf("%s/%s", out.Reply, out.Elapsed)
	err := workflow.ExecuteActivity(actx, "itest_deny", in).Get(ctx, nil)
	if appErr, ok := errors.AsType[*temporal.ApplicationError](err); ok {
		st.Denial = fmt.Sprintf("%s nonretryable=%t", appErr.Type(), appErr.NonRetryable())
	}
	return st, nil
}

// waitForever holds a run open for signals until it is cancelled.
func waitForever(ctx workflow.Context) error {
	return workflow.Await(ctx, func() bool { return false })
}

// signalInputs is the JSON of every argument of every signal in a run's history.
func signalInputs(ctx context.Context, t *testing.T, c *Client, id string) [][]string {
	t.Helper()
	var out [][]string
	it := c.SDK().GetWorkflowHistory(ctx, id, "", false, 0)
	for it.HasNext() {
		e, err := it.Next()
		if err != nil {
			t.Fatal(err)
		}
		if a := e.GetWorkflowExecutionSignaledEventAttributes(); a != nil {
			var args []string
			for _, p := range a.GetInput().GetPayloads() {
				args = append(args, string(p.GetData()))
			}
			out = append(out, args)
		}
	}
	return out
}

func testEnv(t *testing.T) Env {
	addr := os.Getenv("AGENTAREA_TEST_TEMPORAL_URL")
	if addr == "" {
		t.Skip("AGENTAREA_TEST_TEMPORAL_URL is not set")
	}
	return envMap{"TEMPORAL_ADDRESS": addr, "TEMPORAL_NAMESPACE": "default", "TEMPORAL_CONFIG_FILE": "/nonexistent/temporal.toml"}
}

func TestIntegration(t *testing.T) {
	env := testEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cfg := durable.Config{
		Queues:            durable.Queues{Agent: fmt.Sprintf("itest-%d", time.Now().UnixNano())},
		Limits:            durable.Limits{MaxActivities: 4, MaxWorkflows: 4, ActivityPollers: 4, WorkflowPollers: 4},
		MaxCached:         10,
		ShutdownGrace:     5 * time.Second,
		HeartbeatThrottle: 2 * time.Second,
	}
	c, err := Dial(ctx, cfg, env, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	queue := cfg.Queues.Agent

	w := c.NewWorker(queue, cfg.Limits)
	w.RegisterWorkflow(durable.Workflow{Name: "ItestWorkflow", Fn: itestWorkflow})
	w.RegisterWorkflow(durable.Workflow{Name: "WaitForever", Fn: waitForever})
	w.RegisterActivity(durable.Activity{Name: "itest_activity", Kind: durable.KindData, Fn: func(_ context.Context, in itestIn) (itestOut, error) {
		return itestOut{Reply: "go:" + in.Query, Elapsed: in.Timeout * 2}, nil
	}})
	w.RegisterActivity(durable.Activity{Name: "itest_deny", Kind: durable.KindControl, Fn: func(context.Context, itestIn) error {
		return &durable.ApplicationError{Type: "GovernanceDeniedError", Message: "no", NonRetryable: true}
	}})
	runCtx, stop := context.WithCancel(ctx)
	ran := make(chan error, 1)
	go func() { ran <- w.Run(runCtx) }()

	opts := durable.StartOptions{TaskQueue: queue, Timeout: time.Minute, RetryAttempts: 1, StartOnce: true}
	in := itestIn{Query: "hi", Timeout: 1500 * time.Millisecond, Meta: map[string]any{"n": 1}}
	id := "itest-" + queue
	if got, err := c.Start(ctx, "ItestWorkflow", id, []any{in}, opts); err != nil || got != id {
		t.Fatalf("start: %s %v", got, err)
	}
	if _, err := c.Start(ctx, "ItestWorkflow", id, []any{in}, opts); !errors.Is(err, durable.ErrAlreadyStarted) {
		t.Fatalf("second start: %v", err)
	}
	var bumped int
	if err := c.Update(ctx, id, "bump", &bumped, 3); err != nil || bumped != 3 {
		t.Fatalf("update: %d %v", bumped, err)
	}
	var st itestState
	if err := c.Query(ctx, id, "state", &st); err != nil || st.Bumps != 3 {
		t.Fatalf("query: %+v %v", st, err)
	}
	if err := c.Signal(ctx, id, "done", true); err != nil {
		t.Fatal(err)
	}
	res, err := c.Wait(ctx, id, 30*time.Second)
	if err != nil || res.Status != durable.StatusCompleted || res.StartTime == nil || res.EndTime == nil {
		t.Fatalf("wait: %+v %v", res, err)
	}
	if err := json.Unmarshal(res.Result, &st); err != nil || st.Reply != "go:hi/3s" || st.Denial != "GovernanceDeniedError nonretryable=true" {
		t.Fatalf("result %s: %+v %v", res.Result, st, err)
	}
	status, err := c.Status(ctx, id)
	if err != nil || status.Status != durable.StatusCompleted || string(status.Result) != string(res.Result) {
		t.Fatalf("status: %+v %v", status, err)
	}

	sigID := "itest-sws-" + queue
	sws := durable.StartOptions{TaskQueue: queue, Timeout: time.Minute, StartSignal: "workflow_command",
		StartSignalArgs: []any{"queue_message", map[string]any{"message": "first", "sender": nil}}}
	if _, err := c.Start(ctx, "WaitForever", sigID, nil, sws); err != nil {
		t.Fatalf("signal-with-start: %v", err)
	}
	if err := c.Signal(ctx, sigID, "workflow_command", "remove_message", map[string]any{"id": 2}); err != nil {
		t.Fatal(err)
	}
	// A signal that arrives during a workflow task is buffered until the task completes.
	want := `[["queue_message" {"message":"first","sender":null}] ["remove_message" {"id":2}]]`
	got := fmt.Sprint(signalInputs(ctx, t, c, sigID))
	for deadline := time.Now().Add(10 * time.Second); got != want && time.Now().Before(deadline); {
		time.Sleep(50 * time.Millisecond)
		got = fmt.Sprint(signalInputs(ctx, t, c, sigID))
	}
	if got != want {
		t.Fatalf("signal arguments on the wire:\n got %s\nwant %s", got, want)
	}
	if err := c.Cancel(ctx, sigID); err != nil {
		t.Fatal(err)
	}
	if res, err := c.Wait(ctx, sigID, 10*time.Second); err != nil || res.Status != durable.StatusCancelled || res.Error == "" {
		t.Fatalf("cancelled wait: %+v %v", res, err)
	}

	missing := "itest-missing-" + queue
	if res, err := c.Status(ctx, missing); err != nil || res.Status != durable.StatusUnknown || res.Error != "Workflow not found" {
		t.Fatalf("missing status: %+v %v", res, err)
	}
	if err := c.Cancel(ctx, missing); !errors.Is(err, durable.ErrNotFound) {
		t.Fatalf("missing cancel: %v", err)
	}
	if err := c.Signal(ctx, missing, "done", true); !errors.Is(err, durable.ErrNotFound) {
		t.Fatalf("missing signal: %v", err)
	}

	schedID := "itest-schedule-" + queue
	s := durable.Schedule{ID: schedID, Workflow: "ItestWorkflow", WorkflowID: "itest-sched-run", TaskQueue: queue,
		Args: []any{in}, Every: []time.Duration{time.Hour}, Overlap: durable.OverlapSkip, Paused: true, Note: "n1"}
	if err := c.Ensure(ctx, s); err != nil {
		t.Fatal(err)
	}
	s.Every, s.Note, s.CatchupWindow = []time.Duration{2 * time.Hour}, "n2", 10*time.Minute
	if err := c.Ensure(ctx, s); err != nil {
		t.Fatalf("ensure existing: %v", err)
	}
	info, err := c.Describe(ctx, schedID)
	if err != nil || info.Note != "n2" || len(info.Every) != 1 || info.Every[0] != 2*time.Hour || !info.Paused ||
		info.Workflow != "ItestWorkflow" || info.TaskQueue != queue || info.CatchupWindow != 10*time.Minute || len(info.Args) != 1 {
		t.Fatalf("describe: %+v %v", info, err)
	}
	var arg itestIn
	if err := json.Unmarshal(info.Args[0], &arg); err != nil || arg.Query != "hi" {
		t.Fatalf("schedule arg %s: %v", info.Args[0], err)
	}
	if err := c.Delete(ctx, schedID); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Describe(ctx, schedID); !errors.Is(err, durable.ErrNotFound) {
		t.Fatalf("deleted schedule: %v", err)
	}

	stop()
	if err := <-ran; err != nil {
		t.Fatalf("worker stop: %v", err)
	}
}
