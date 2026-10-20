package transport

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/event-service/internal/mcpevents"
	"github.com/agentarea/event-service/internal/template"
)

type fakePoller struct {
	answers []mcpevents.PollResult
	asked   []mcpevents.PollRequest
	ids     []string
}

func (f *fakePoller) Poll(_ context.Context, instanceID string, req mcpevents.PollRequest) (mcpevents.PollResult, error) {
	f.asked = append(f.asked, req)
	f.ids = append(f.ids, instanceID)
	answer := f.answers[0]
	f.answers = f.answers[1:]
	return answer, nil
}

func ptr(s string) *string { return &s }

func occurrence(id string) mcpevents.Occurrence {
	return json.RawMessage(`{"eventId":"` + id + `","name":"ticket.created","timestamp":"2026-10-19T10:00:00Z","data":{}}`)
}

func mcpFetch(cursor string) Fetch {
	return Fetch{
		SourceID:      "s1",
		MCPInstanceID: "inst-1",
		Values: template.Values{
			Cursor: cursor,
			Config: map[string]any{"event": "ticket.created", "arguments": `{"queue":"support"}`},
		},
	}
}

func TestTheFirstMCPPollStartsFromNowAndKeepsTheFreshCursor(t *testing.T) {
	poller := &fakePoller{answers: []mcpevents.PollResult{{Cursor: ptr("c0"), NextPollMs: 2000}}}
	res, err := NewMCPEventsTransport(poller).Fetch(context.Background(), mcpFetch(""))
	if err != nil {
		t.Fatal(err)
	}
	if poller.asked[0].Cursor != nil || poller.ids[0] != "inst-1" {
		t.Fatalf("asked %+v on %v", poller.asked[0], poller.ids)
	}
	if poller.asked[0].Name != "ticket.created" || poller.asked[0].Arguments["queue"] != "support" {
		t.Fatalf("asked %+v", poller.asked[0])
	}
	if res.Cursor != "c0" || len(res.Items) != 0 || res.Next != 2*time.Second || res.Gap != "" {
		t.Fatalf("result %+v", res)
	}
}

func TestMCPPollDrainsWhileTheServerHasMore(t *testing.T) {
	poller := &fakePoller{answers: []mcpevents.PollResult{
		{Events: []mcpevents.Occurrence{occurrence("e1"), occurrence("e2")}, Cursor: ptr("c2"), HasMore: true},
		{Events: []mcpevents.Occurrence{occurrence("e3")}, Cursor: ptr("c3"), NextPollMs: 10},
	}}
	res, err := NewMCPEventsTransport(poller).Fetch(context.Background(), mcpFetch("c0"))
	if err != nil {
		t.Fatal(err)
	}
	if *poller.asked[0].Cursor != "c0" || *poller.asked[1].Cursor != "c2" {
		t.Fatal("the second poll did not resume at the first one's cursor")
	}
	if len(res.Items) != 3 || res.Cursor != "c3" || res.Next != time.Second {
		t.Fatalf("result %+v", res)
	}
}

func TestATruncatedMCPPollIsAGap(t *testing.T) {
	poller := &fakePoller{answers: []mcpevents.PollResult{{Cursor: ptr("fresh"), Truncated: true}}}
	res, err := NewMCPEventsTransport(poller).Fetch(context.Background(), mcpFetch("stale"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res.Gap, "truncated") || res.Cursor != "fresh" || res.Next != 0 {
		t.Fatalf("result %+v", res)
	}
}

func TestAnMCPSourceOfAnotherWorkspaceIsNotPolled(t *testing.T) {
	poller := &fakePoller{}
	f := mcpFetch("")
	f.MCPInstanceID = ""
	if _, err := NewMCPEventsTransport(poller).Fetch(context.Background(), f); err == nil || len(poller.asked) != 0 {
		t.Fatalf("err %v, asked %d", err, len(poller.asked))
	}
}

func TestMCPArgumentsMustBeAnObject(t *testing.T) {
	if _, err := ReadMCPEventsConfig(map[string]any{"event": "e", "arguments": "[1]"}); err == nil {
		t.Fatal("a list was taken as arguments")
	}
	cfg, err := ReadMCPEventsConfig(map[string]any{"event": "e"})
	if err != nil || cfg.Arguments == nil {
		t.Fatalf("cfg %+v err %v", cfg, err)
	}
}

func TestAnMCPPollItemKeepsTheProducersChainForTheIngest(t *testing.T) {
	sent := json.RawMessage(`{"eventId":"e1","name":"ws/s","timestamp":"2026-10-19T10:00:00Z","data":{"id":"5b1c3c7e-0a4e-4f43-9b7f-0a1d1f3b6c11","depth":3,"correlation_id":"8f0f4a8c-6f2d-4c43-a4a5-2f1f61c0e0aa"}}`)
	poller := &fakePoller{answers: []mcpevents.PollResult{{Events: []mcpevents.Occurrence{sent}, Cursor: ptr("c1")}}}
	res, err := NewMCPEventsTransport(poller).Fetch(context.Background(), mcpFetch("c0"))
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Items) != 1 {
		t.Fatalf("items %+v", res.Items)
	}
	got, err := json.Marshal(res.Items[0])
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(sent) {
		t.Fatalf("item %s, sent %s", got, sent)
	}
}
