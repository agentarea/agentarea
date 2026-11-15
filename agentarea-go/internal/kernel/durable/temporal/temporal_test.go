package temporal

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

type envMap map[string]string

func (e envMap) Environ() []string {
	out := make([]string, 0, len(e))
	for k, v := range e {
		out = append(out, k+"="+v)
	}
	return out
}

func (e envMap) LookupEnv(k string) (string, bool) {
	v, ok := e[k]
	return v, ok
}

func TestConnectOptionsReadTemporalEnvconfig(t *testing.T) {
	opts, err := ConnectOptions(envMap{
		"TEMPORAL_CONFIG_FILE":       "/nonexistent/temporal.toml",
		"TEMPORAL_ADDRESS":           "temporal:7233",
		"TEMPORAL_NAMESPACE":         "agentarea",
		"TEMPORAL_API_KEY":           "k",
		"TEMPORAL_TLS_SERVER_NAME":   "temporal.example",
		"TEMPORAL_GRPC_META_X_TRACE": "1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if opts.HostPort != "temporal:7233" || opts.Namespace != "agentarea" || opts.Credentials == nil {
		t.Fatalf("%+v", opts)
	}
	if opts.ConnectionOptions.TLS == nil || opts.ConnectionOptions.TLS.ServerName != "temporal.example" {
		t.Fatalf("tls: %+v", opts.ConnectionOptions.TLS)
	}
}

func TestConnectOptionsRequireAddressAndNamespace(t *testing.T) {
	_, err := ConnectOptions(envMap{"TEMPORAL_CONFIG_FILE": "/nonexistent/temporal.toml"})
	if !errors.Is(err, ErrNotConfigured) || !strings.Contains(err.Error(), "TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE") {
		t.Fatal(err)
	}
}

func TestActivityErrorsBecomeTypedApplicationErrors(t *testing.T) {
	err := toTemporalError(&durable.ApplicationError{Type: "SpendCapReachedError", Message: "cap", NonRetryable: true})
	appErr, ok := errors.AsType[*temporal.ApplicationError](err)
	if !ok || appErr.Type() != "SpendCapReachedError" || !appErr.NonRetryable() {
		t.Fatalf("%#v", err)
	}
	plain := errors.New("boom")
	if !errors.Is(toTemporalError(plain), plain) {
		t.Fatal("plain error changed")
	}
}

func lazyClient(t *testing.T) *Client {
	t.Helper()
	c, err := client.NewLazyClient(client.Options{HostPort: "127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	return &Client{sdk: c, config: durable.Config{ShutdownGrace: time.Second, HeartbeatThrottle: 2 * time.Second}}
}

func TestRegistrationErrorsStopRun(t *testing.T) {
	w := lazyClient(t).NewWorker("q", durable.Limits{MaxActivities: 1, MaxWorkflows: 2, ActivityPollers: 1, WorkflowPollers: 2})
	fn := func(context.Context, string) (string, error) { return "", nil }
	w.RegisterActivity(durable.Activity{Name: "a", Kind: durable.KindData, Fn: fn})
	w.RegisterActivity(durable.Activity{Name: "a", Kind: durable.KindData, Fn: fn})
	w.RegisterActivity(durable.Activity{Name: "b", Fn: fn})
	w.RegisterActivity(durable.Activity{Kind: durable.KindControl, Fn: fn})
	w.RegisterActivity(durable.Activity{Name: "c", Kind: durable.KindControl, Fn: "not a function"})
	err := w.Run(context.Background())
	for _, want := range []string{"activity a registered twice", "activity b: kind must be control or data", "activity registered without a name", "register activity c"} {
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("missing %q in %v", want, err)
		}
	}
	if got := w.Kinds(); len(got) != 2 || got["a"] != durable.KindData {
		t.Fatalf("kinds: %v", got)
	}
}

func TestWorkerRequiresLimits(t *testing.T) {
	err := lazyClient(t).NewWorker("", durable.Limits{}).Run(context.Background())
	if err == nil || !strings.Contains(err.Error(), "task queue is required") || !strings.Contains(err.Error(), "workflow slots and pollers must be at least 2") {
		t.Fatal(err)
	}
}

func TestScheduleRejectsUnknownOverlap(t *testing.T) {
	_, _, _, err := scheduleParts(durable.Schedule{ID: "s", Workflow: "W", WorkflowID: "w", TaskQueue: "q", Overlap: "sometimes"})
	if err == nil {
		t.Fatal("unknown overlap accepted")
	}
	_, _, _, err = scheduleParts(durable.Schedule{ID: "s", Workflow: "W"})
	if err == nil {
		t.Fatal("schedule without a queue accepted")
	}
}
