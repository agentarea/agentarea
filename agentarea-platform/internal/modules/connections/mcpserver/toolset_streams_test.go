package mcpserver

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

type fakeTriggers struct{ *recorder }

func (f fakeTriggers) List(_ context.Context, _ authn.Caller, agentID string, activeOnly bool, limit int) ([]streamsapi.TriggerView, error) {
	f.saw("list %q %v %d", agentID, activeOnly, limit)
	return []streamsapi.TriggerView{{ID: "t1", Name: "Nightly", TriggerType: "cron", Status: "active"}}, nil
}
func (f fakeTriggers) Get(_ context.Context, _ authn.Caller, id string) (streamsapi.TriggerView, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return streamsapi.TriggerView{}, streamsapi.ErrTriggerNotFound
	}
	return streamsapi.TriggerView{ID: id, Name: "Nightly"}, nil
}
func (f fakeTriggers) Create(_ context.Context, _ authn.Caller, in streamsapi.TriggerCreate) (streamsapi.TriggerView, error) {
	extra := ""
	if in.CronExpression != nil {
		extra = *in.CronExpression + " " + *in.Timezone
	}
	if in.StreamID != nil {
		extra = *in.StreamID
	}
	f.saw("create %s %s %s enabled=%v threshold=%d %s session=%v", in.Type, in.Name, in.AgentID, in.Enabled, in.FailureThreshold, extra, in.Session != nil)
	return streamsapi.TriggerView{ID: "t2", Name: in.Name, TriggerType: in.Type}, nil
}
func (f fakeTriggers) Delete(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	if id == "denied" {
		return false, errors.New("Permission denied")
	}
	return id != "gone", nil
}
func (f fakeTriggers) Enable(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("enable %s", id)
	return true, nil
}
func (f fakeTriggers) Disable(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("disable %s", id)
	return id != "gone", nil
}
func (f fakeTriggers) History(_ context.Context, _ authn.Caller, id string, limit, offset int) ([]streamsapi.TriggerExecution, error) {
	f.saw("history %s %d %d", id, limit, offset)
	return []streamsapi.TriggerExecution{{ID: "x1", Status: "succeeded", ExecutionTimeMs: 12}}, nil
}

func TestTriggersToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Triggers: fakeTriggers{rec}}, "triggers")
	runToolCases(t, ts, rec, []toolCase{
		{"triggers_list", `{}`, `list "" false 100`, `"name":"Nightly"`, false},
		{"triggers_list", `{"agent_id":"a1","active_only":true,"limit":3}`, `list "a1" true 3`, `"t1"`, false},
		{"triggers_list", `{"limit":5000}`, `list "" false 1000`, `"t1"`, false},
		{"triggers_get", `{"trigger_id":"t1"}`, "get t1", `"id":"t1"`, false},
		{"triggers_get", `{"trigger_id":"gone"}`, "get gone", "Trigger not found", true},
		{"triggers_create_cron", `{"name":"N","agent_id":"a1","cron_expression":"0 9 * * *"}`, "create cron N a1 enabled=true threshold=5 0 9 * * * UTC session=false", `"trigger_type":"cron"`, false},
		{"triggers_create_cron", `{"name":"N","agent_id":"a1","cron_expression":"0 9 * * *","timezone":"Europe/Moscow","enabled":false,"failure_threshold":2}`, "create cron N a1 enabled=false threshold=2 0 9 * * * Europe/Moscow session=false", `"t2"`, false},
		{"triggers_create_stream", `{"name":"S","agent_id":"a1","stream_id":"s1","session":{"continue":true}}`, "create stream S a1 enabled=true threshold=5 s1 session=true", `"trigger_type":"stream"`, false},
		{"triggers_delete", `{"trigger_id":"gone"}`, "delete gone", `{"deleted":false}`, false},
		{"triggers_delete", `{"trigger_id":"denied"}`, "delete denied", "Permission denied", true},
		{"triggers_enable", `{"trigger_id":"t1"}`, "enable t1", `{"enabled":true}`, false},
		{"triggers_disable", `{"trigger_id":"gone"}`, "disable gone", `{"disabled":false}`, false},
		{"triggers_get_history", `{"trigger_id":"t1"}`, "history t1 50 0", `"execution_time_ms":12`, false},
		{"triggers_get_history", `{"trigger_id":"t1","limit":5,"offset":10}`, "history t1 5 10", `"x1"`, false},
		{"triggers_get_history", `{"trigger_id":"t1","limit":5000}`, "history t1 100 0", `"x1"`, false},
	})
}

type fakeStreams struct{ *recorder }

func (f fakeStreams) List(_ context.Context, _ authn.Caller, limit, offset int) (any, error) {
	f.saw("list %d %d", limit, offset)
	return []map[string]any{{"id": "s1", "name": "orders"}}, nil
}
func (f fakeStreams) Get(_ context.Context, _ authn.Caller, id string) (any, error) {
	f.saw("get %s", id)
	if id == "denied" {
		return nil, errors.New("Permission denied")
	}
	return map[string]any{"id": id}, nil
}
func (f fakeStreams) Create(_ context.Context, _ authn.Caller, name, desc string) (any, error) {
	f.saw("create %s %q", name, desc)
	return map[string]any{"id": "s2", "name": name}, nil
}
func (f fakeStreams) Delete(_ context.Context, _ authn.Caller, id string) error {
	f.saw("delete %s", id)
	return nil
}
func (f fakeStreams) ListSourceTypes(context.Context, authn.Caller) (any, error) {
	f.saw("types")
	return []map[string]any{{"slug": "webhook"}}, nil
}
func (f fakeStreams) ListSources(_ context.Context, _ authn.Caller, id string) (any, error) {
	f.saw("sources %s", id)
	return []map[string]any{}, nil
}
func (f fakeStreams) CreateSource(_ context.Context, _ authn.Caller, id string, doc []byte) (any, error) {
	f.saw("source %s %s", id, doc)
	return map[string]any{"id": "src1"}, nil
}
func (f fakeStreams) UpdateSource(_ context.Context, _ authn.Caller, id, src string, senders []byte) (any, error) {
	f.saw("senders %s %s %s", id, src, senders)
	return map[string]any{"id": src}, nil
}
func (f fakeStreams) DeleteSource(_ context.Context, _ authn.Caller, id, src string) error {
	f.saw("unsource %s %s", id, src)
	return nil
}
func (f fakeStreams) ListSubscriptions(_ context.Context, _ authn.Caller, id string) (any, error) {
	f.saw("subs %s", id)
	return []map[string]any{{"kind": "trigger"}}, nil
}
func (f fakeStreams) CreateForward(_ context.Context, _ authn.Caller, id string, outs []string, filter map[string]any) (any, error) {
	f.saw("forward %s %v %v", id, outs, filter)
	return map[string]any{"kind": "forward"}, nil
}
func (f fakeStreams) DeleteForward(_ context.Context, _ authn.Caller, id, sub string) error {
	f.saw("unforward %s %s", id, sub)
	return nil
}
func (f fakeStreams) CreateProcessor(_ context.Context, _ authn.Caller, id string, outs []string, code string, _ map[string]any) (any, error) {
	f.saw("processor %s %v %d", id, outs, len(code))
	return map[string]any{"kind": "processor"}, nil
}
func (f fakeStreams) UpdateProcessor(_ context.Context, _ authn.Caller, id, sub string, ch streamsapi.ProcessorChange) (any, error) {
	f.saw("reprocess %s %s code=%v outs=%v filter=%v", id, sub, ch.Code != nil, ch.Outputs, ch.EventFilter != nil)
	return map[string]any{"kind": "processor"}, nil
}
func (f fakeStreams) DeleteProcessor(_ context.Context, _ authn.Caller, id, sub string) error {
	f.saw("unprocess %s %s", id, sub)
	return errors.New("Subscription x not found")
}
func (f fakeStreams) ListEvents(_ context.Context, _ authn.Caller, q streamsapi.EventQuery) (any, error) {
	sid := "<all>"
	if q.StreamID != nil {
		sid = *q.StreamID
	}
	f.saw("events %s after=%d before=%v since=%v limit=%d", sid, q.After, q.Before != nil, q.Since != nil, q.Limit)
	return map[string]any{"events": []any{}, "next_after": nil}, nil
}

func TestStreamsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Streams: fakeStreams{rec}}, "streams")
	runToolCases(t, ts, rec, []toolCase{
		{"streams_list", `{}`, "list 100 0", `"orders"`, false},
		{"streams_list", `{"limit":1001}`, "", "limit must be between 1 and 1000, got 1001", true},
		{"streams_list", `{"offset":-1}`, "", "offset must be between 0 and 1000000000, got -1", true},
		{"streams_get", `{"stream_id":"s1"}`, "get s1", `"s1"`, false},
		{"streams_get", `{"stream_id":"denied"}`, "get denied", "Permission denied", true},
		{"streams_create", `{"name":"orders"}`, `create orders ""`, `"s2"`, false},
		{"streams_delete", `{"stream_id":"s1"}`, "delete s1", `{"deleted":true}`, false},
		{"streams_list_source_types", `{}`, "types", `"webhook"`, false},
		{"streams_list_sources", `{"stream_id":"s1"}`, "sources s1", `[]`, false},
		{"streams_create_source", `{"stream_id":"s1","source_type":"github"}`, `source s1 {"config":{},"credentials":{},"kind":"webhook","source_type":"github"}`, `"src1"`, false},
		{"streams_create_source", `{"stream_id":"s1","source_type":"tg","kind":"poll","senders":{"allow":"owner"}}`, `source s1 {"config":{},"credentials":{},"kind":"poll","senders":{"allow":"owner"},"source_type":"tg"}`, `"src1"`, false},
		{"streams_update_source", `{"stream_id":"s1","source_id":"src1","senders":{"allow":"members"}}`, `senders s1 src1 {"allow":"members"}`, `"src1"`, false},
		{"streams_update_source", `{"stream_id":"s1","source_id":"src1"}`, "", "senders: Input should be a valid dictionary", true},
		{"streams_delete_source", `{"stream_id":"s1","source_id":"src1"}`, "unsource s1 src1", `{"deleted":true}`, false},
		{"streams_list_subscriptions", `{"stream_id":"s1"}`, "subs s1", `"trigger"`, false},
		{"streams_create_forward", `{"stream_id":"s1","output_stream_ids":["s2"]}`, "forward s1 [s2] map[]", `"forward"`, false},
		{"streams_delete_forward", `{"stream_id":"s1","subscription_id":"f1"}`, "unforward s1 f1", `{"deleted":true}`, false},
		{"streams_create_processor", `{"stream_id":"s1","output_stream_ids":["s2"],"code":"def process(e): pass"}`, "processor s1 [s2] 20", `"processor"`, false},
		{"streams_update_processor", `{"stream_id":"s1","subscription_id":"p1","code":"x"}`, "reprocess s1 p1 code=true outs=[] filter=false", `"processor"`, false},
		{"streams_delete_processor", `{"stream_id":"s1","subscription_id":"x"}`, "unprocess s1 x", "Subscription x not found", true},
		{"streams_list_events", `{}`, "events <all> after=0 before=false since=false limit=50", `"events"`, false},
		{"streams_list_events", `{"stream_id":"s1","after":7,"since":"2026-11-01T09:00:00Z","limit":200}`, "events s1 after=7 before=false since=true limit=200", `"events"`, false},
		{"streams_list_events", `{"limit":201}`, "", "limit must be between 1 and 200, got 201", true},
		{"streams_list_events", `{"after":-1}`, "", "after must be at least 0, got -1", true},
		{"streams_list_events", `{"since":"yesterday"}`, "", "since: Input should be a valid datetime", true},
	})
}

type fakeStreamEvents struct{ *recorder }

func (f fakeStreamEvents) Read(_ context.Context, _ authn.Caller, stream string, after int64, limit int, since *time.Time) (streamsapi.StreamEventsRead, error) {
	at := "none"
	if since != nil {
		at = since.UTC().Format(time.RFC3339)
	}
	f.saw("read %s %d %d %s", stream, after, limit, at)
	if stream == "gone" {
		return streamsapi.StreamEventsRead{}, errors.New("Stream gone not found")
	}
	return streamsapi.StreamEventsRead{Stream: streamsapi.StreamRef{ID: "s1", Name: stream}, Events: []streamsapi.StreamEventItem{}, NextAfter: after}, nil
}

func TestStreamEventsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{StreamEvents: fakeStreamEvents{rec}}, "stream_events")
	runToolCases(t, ts, rec, []toolCase{
		{"stream_events_read_stream", `{"stream":"orders"}`, "read orders 0 50 none", `"name":"orders"`, false},
		{"stream_events_read_stream", `{"stream":"orders","after_sequence":4,"limit":200,"since":"2026-11-01T12:00:00+03:00"}`, "read orders 4 200 2026-11-01T09:00:00Z", `"next_after":4`, false},
		{"stream_events_read_stream", `{"stream":"orders","limit":0}`, "", "limit must be between 1 and 200, got 0", true},
		{"stream_events_read_stream", `{"stream":"orders","after_sequence":-1}`, "", "after_sequence must be at least 0, got -1", true},
		{"stream_events_read_stream", `{"stream":"orders","since":"2026-11-01T09:00:00"}`, "", "since must carry a timezone (e.g. Z or +03:00), got '2026-11-01T09:00:00'", true},
		{"stream_events_read_stream", `{"stream":"orders","since":"soon"}`, "", "since must be an ISO 8601 time, got 'soon'", true},
		{"stream_events_read_stream", `{"stream":"gone"}`, "read gone 0 50 none", "Stream gone not found", true},
	})
}
