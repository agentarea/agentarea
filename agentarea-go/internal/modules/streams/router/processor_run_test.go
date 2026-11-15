package router_test

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/router"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

func reason(t *testing.T, err error) string {
	t.Helper()
	var f *router.ProcessorFailed
	if !errors.As(err, &f) {
		t.Fatalf("not a processor failure: %v", err)
	}
	return f.Reason
}

func TestOutputsOfRefusesUnusableRuns(t *testing.T) {
	cases := []struct {
		run  service.CodeRun
		want string
	}{
		{service.CodeRun{ExitCode: 124}, "process() did not finish within 10s"},
		{service.CodeRun{StdoutTruncated: true}, "process() returned more than 262144 bytes"},
		{service.CodeRun{ExitCode: 1, Stderr: "Traceback\n  boom  "}, "The processor exited with code 1: Traceback boom"},
		{service.CodeRun{ExitCode: 2}, "The processor exited with code 2"},
		{service.CodeRun{Stdout: "hello"}, "The processor printed no result"},
		{service.CodeRun{Stdout: `{"ok": "yes"}`}, "The processor printed no result"},
		{service.CodeRun{Stdout: `{"ok": false, "error": "KeyError: 'x'"}`}, "KeyError: 'x'"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": {"a": 1}}`}, "process() must return a list of events or None, not an object"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": 3}`}, "process() must return a list of events or None, not a number"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": [1]}`}, "event 0 is not {stream, kind, data, key?}: Input should be a valid dictionary or instance of ProcessorOutput"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": [{"kind": "k", "data": {}}]}`}, "event 0 is not {stream, kind, data, key?}: stream: Field required"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": [{"stream": "s", "kind": "k", "data": []}]}`}, "event 0 is not {stream, kind, data, key?}: data: Input should be a valid dictionary"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": [{"stream": "s", "kind": "k", "data": {}, "x": 1}]}`}, "event 0 is not {stream, kind, data, key?}: x: Extra inputs are not permitted"},
		{service.CodeRun{Stdout: `{"ok": true, "outputs": [{"stream": "s", "kind": "", "data": {}}]}`}, "event 0 is not {stream, kind, data, key?}: kind: String should have at least 1 character"},
	}
	for _, c := range cases {
		_, err := router.OutputsOf(c.run)
		if got := reason(t, err); got != c.want {
			t.Errorf("%+v: %q, want %q", c.run, got, c.want)
		}
	}
	many := `{"ok": true, "outputs": [` + strings.TrimSuffix(strings.Repeat(`{"stream":"s","kind":"k","data":{}},`, 101), ",") + `]}`
	if _, err := router.OutputsOf(service.CodeRun{Stdout: many}); reason(t, err) != "process() returned more than 100 events" {
		t.Fatal(err)
	}
	long := strings.Repeat("x", 2000)
	_, err := router.OutputsOf(service.CodeRun{Stdout: `{"ok": false, "error": "` + long + `"}`})
	if r := reason(t, err); len([]rune(r)) != 1000 || !strings.HasSuffix(r, "…") {
		t.Fatalf("clip = %d", len(r))
	}
}

func TestOutputsOfReadsEvents(t *testing.T) {
	for _, stdout := range []string{`{"ok": true, "outputs": null}`, `{"ok": true}`} {
		out, err := router.OutputsOf(service.CodeRun{Stdout: stdout})
		if err != nil || len(out) != 0 {
			t.Fatalf("%s: %v %v", stdout, out, err)
		}
	}
	out, err := router.OutputsOf(service.CodeRun{Stdout: `{"ok": true, "outputs": [{"stream": "s", "kind": "k", "data": {"n": 1}, "key": "a"}]}`})
	if err != nil || len(out) != 1 || out[0].Key == nil || *out[0].Key != "a" || out[0].Data["n"] != json.Number("1") {
		t.Fatalf("%+v %v", out, err)
	}
}

func TestResolveStreams(t *testing.T) {
	declared := map[string]string{"s1": "alpha", "s2": "beta"}
	out := []router.ProcessorOutput{{Stream: "alpha"}, {Stream: "s2"}}
	routed, err := router.ResolveStreams(out, declared, "in")
	if err != nil || routed[0].StreamID != "s1" || routed[1].StreamID != "s2" {
		t.Fatalf("%+v %v", routed, err)
	}
	_, err = router.ResolveStreams([]router.ProcessorOutput{{Stream: "gamma"}}, declared, "in")
	if r := reason(t, err); r != "event 0 names stream 'gamma', which is not one of this processor's outputs (alpha, beta)" {
		t.Fatal(r)
	}
	_, err = router.ResolveStreams([]router.ProcessorOutput{{Stream: "in"}}, declared, "in")
	if r := reason(t, err); r != "event 0 names the processor's own input stream; a processor never writes to its own input" {
		t.Fatal(r)
	}
	_, err = router.ResolveStreams([]router.ProcessorOutput{{Stream: "x"}}, map[string]string{}, "in")
	if r := reason(t, err); !strings.HasSuffix(r, "(none)") {
		t.Fatal(r)
	}
}

func TestHarnessAndPayload(t *testing.T) {
	at := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	e := domain.Event{ID: "e1", Kind: "k", Source: "s", OccurredAt: at, ReceivedAt: at, StreamID: "st", EventKey: "key",
		Data: map[string]any{"html": "<b>"}, Depth: 1}
	p, err := router.EventPayload(e)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(string(p), `{"id":"e1","kind":"k","source":"s","subject":null,"time":"2026-01-02T03:04:05+00:00"`) ||
		!strings.Contains(string(p), `"data":{"html":"<b>"},"attachments":[]}`) {
		t.Fatalf("payload = %s", p)
	}
	cmd, err := router.HarnessCommand("def process(e): pass", p)
	if err != nil || !strings.HasSuffix(cmd, "result.flush()\nAGENTAREA_PROCESSOR_HARNESS\n") {
		t.Fatalf("command = %v", err)
	}
	_, err = router.HarnessCommand(strings.Repeat("x", router.MaxCommandBytes), p)
	if r := reason(t, err); !strings.HasPrefix(r, "The event is too large for a processor") {
		t.Fatal(r)
	}
}

func TestEventFromBusRoundTrip(t *testing.T) {
	at := time.Date(2026, 1, 2, 3, 4, 5, 123456000, time.UTC)
	key, sender := "sess", "alice"
	e := domain.Event{ID: "0b6a3c1e-0000-4000-8000-000000000001", Kind: "k", Source: "s", OccurredAt: at, ReceivedAt: at,
		StreamID: "0b6a3c1e-0000-4000-8000-000000000002", WorkspaceID: "ws", CreatedBy: "u", EventKey: "key", Depth: 3,
		SessionKey: &key, Sender: &sender, Data: map[string]any{},
		Attachments: []domain.Attachment{{Name: "a.txt", Ref: "r", Stored: true}}}
	fields, err := events.Encode(service.BusEvent(e))
	if err != nil {
		t.Fatal(err)
	}
	m, err := events.Decode(fields)
	if err != nil {
		t.Fatal(err)
	}
	got, err := router.EventFromBus(m)
	if err != nil || got.Depth != 3 || got.Sender == nil || *got.Sender != "alice" || !got.ReceivedAt.Equal(at) ||
		len(got.Attachments) != 1 || got.Attachments[0].Name != "a.txt" {
		t.Fatalf("%+v %v", got, err)
	}
	delete(m.Extensions, "streamid")
	if _, err := router.EventFromBus(m); !errors.Is(err, events.ErrUnprocessable) {
		t.Fatalf("missing stream id = %v", err)
	}
}
