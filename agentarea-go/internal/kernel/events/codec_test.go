package events

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

func TestPyJSON(t *testing.T) {
	got, err := PyJSON(map[string]any{"b": "é😀\x7f<>&/\n\b", "a": []any{1, 2.5, nil, true}, "c": map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	// json.dumps of the same dict with its keys sorted.
	want := `{"a": [1, 2.5, null, true], "b": "` + `\u00e9\ud83d\ude00\u007f<>&/\n\b", "c": {}}`
	if got != want {
		t.Errorf("PyJSON\n got %s\nwant %s", got, want)
	}
	if got, _ := PyJSON(map[string]string{"k": "a,b: c"}); got != `{"k": "a,b: c"}` {
		t.Errorf("separators inside strings changed: %s", got)
	}
}

func TestPyISO(t *testing.T) {
	cases := map[string]time.Time{
		"2026-11-12T10:00:00+00:00":        time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC),
		"2026-11-12T10:00:00.001500+03:00": time.Date(2026, 11, 12, 10, 0, 0, 1500999, time.FixedZone("", 3*3600)),
	}
	for want, in := range cases {
		if got := PyISO(in); got != want {
			t.Errorf("PyISO = %s, want %s", got, want)
		}
		back, err := ParsePyISO(want)
		if err != nil || !back.Equal(in.Truncate(time.Microsecond)) {
			t.Errorf("ParsePyISO(%s) = %v, %v", want, back, err)
		}
	}
	if _, err := ParsePyISO("2026-11-12T10:00:00.123456Z"); err != nil {
		t.Error(err)
	}
	if naive, err := ParsePyISO("2026-11-12T10:00:00.5"); err != nil || naive.Location() != time.UTC {
		t.Errorf("naive time: %v %v", naive, err)
	}
}

func TestEncodeDecode(t *testing.T) {
	e := IntegrationEvent{
		ID: "6F1C2A7E-3C1B-4B8E-9A51-2F4F0D1C9E10", Type: "task.completed", Source: "agentarea-worker",
		Time: time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC), Subject: "task-1",
		Data:       map[string]any{"n": 1, "s": "x"},
		Extensions: map[string]string{"seq": "7", "workspace": "ws-1"},
	}
	fields, err := Encode(e)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{
		"ce_id": e.ID, "ce_type": "task.completed", "ce_source": "agentarea-worker",
		"ce_time": "2026-11-12T10:00:00+00:00", "ce_specversion": "1.0", "ce_datacontenttype": "application/json",
		"data": `{"n": 1, "s": "x"}`, "ce_subject": "task-1", "ce_seq": "7", "ce_workspace": "ws-1",
	}
	if len(fields) != len(want) {
		t.Errorf("fields %v, want %v", fields, want)
	}
	for k, v := range want {
		if fields[k] != v {
			t.Errorf("%s = %q, want %q", k, fields[k], v)
		}
	}
	got, err := Decode(fields)
	if err != nil {
		t.Fatal(err)
	}
	if got.ID != strings.ToLower(e.ID) || got.Subject != "task-1" || got.Extensions["seq"] != "7" || !got.Time.Equal(e.Time) {
		t.Errorf("decoded %+v", got)
	}
	if n, _ := got.Data["n"].(json.Number); n.String() != "1" {
		t.Errorf("data n = %#v", got.Data["n"])
	}
	if _, ok := got.Extensions["data"]; ok {
		t.Error("data is not an extension")
	}
}

func TestEncodeRefusesBadExtension(t *testing.T) {
	for _, name := range []string{"Seq", "subject", "a_b", strings.Repeat("a", 21)} {
		if _, err := Encode(IntegrationEvent{Type: "t", Source: "s", Extensions: map[string]string{name: "v"}}); err == nil {
			t.Errorf("extension %q accepted", name)
		}
	}
}

func TestEncodeDefaults(t *testing.T) {
	fields, err := Encode(IntegrationEvent{Type: "t", Source: "s"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := uuid.Parse(fields[FieldID]); err != nil {
		t.Error(err)
	}
	if fields[FieldData] != "{}" || fields[FieldSpecVersion] != "1.0" {
		t.Errorf("defaults: %v", fields)
	}
	if _, ok := fields[FieldSubject]; ok {
		t.Error("an empty subject is left out")
	}
}

// A tasks.events entry the Python worker left before cutover
// (testdata/stored_task_event.json) decodes to the event it wrote.
func TestDecodeStoredTaskEvent(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("testdata", "stored_task_event.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]string
	if err := json.Unmarshal(raw, &fields); err != nil {
		t.Fatal(err)
	}
	e, err := Decode(fields)
	if err != nil {
		t.Fatal(err)
	}
	if e.ID != "8d6b4a52-0c1e-4f7a-9a43-2b1f6c3d9e01" || e.Type != "task.completed" || e.Source != "agentarea-worker" ||
		e.Subject != "task-1" || !e.Time.Equal(time.Date(2026, 11, 12, 10, 0, 0, 123456000, time.UTC)) ||
		e.Extensions["seq"] != "42" || e.Extensions["workspace"] != "ws-1" || len(e.Extensions) != 2 {
		t.Errorf("decoded %+v", e)
	}
	data, _ := json.Marshal(e.Data)
	if string(data) != `{"n":3,"nested":{"a":[1,null]},"result":"ok é"}` {
		t.Errorf("data %s", data)
	}
	again, err := Encode(e)
	if err != nil {
		t.Fatal(err)
	}
	for k, v := range fields {
		if k != FieldData && again[k] != v {
			t.Errorf("re-encoded %s = %q, stored %q", k, again[k], v)
		}
	}
}

func TestDecodeRequiresTypeAndSource(t *testing.T) {
	if _, err := Decode(map[string]string{"ce_source": "s"}); err == nil {
		t.Error("no type accepted")
	}
	if _, err := Decode(map[string]string{"ce_type": "t"}); err == nil {
		t.Error("no source accepted")
	}
}

func TestTopics(t *testing.T) {
	// zlib.crc32(UUID("6f1c2a7e-...").bytes) % 16 == 12
	if got := StreamEventsPartition(uuid.MustParse("6f1c2a7e-3c1b-4b8e-9a51-2f4f0d1c9e10"), 16); got != "streams.events.12" {
		t.Errorf("partition = %s", got)
	}
	if got := DeadLetterTopic("streams.ingest", "ingest"); got != "streams.ingest.ingest.dlq" {
		t.Error(got)
	}
	if TaskLiveChannel("t1") != "tasks.live.t1" || StreamsLiveChannel("w") != "streams.live.w" ||
		DomainEventsTopic("X") != "domain.events.X" || ExternalRetryTopic(2) != "streams.external.retry.2" {
		t.Error("channel names")
	}
	if p := StreamEventsPartitions(3); len(p) != 3 || p[2] != "streams.events.2" {
		t.Error(p)
	}
}

func TestLoadConfig(t *testing.T) {
	l := config.FromMap(nil)
	LoadConfig(l)
	if err := l.Err(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_REDIS_URL") {
		t.Errorf("missing url not reported: %v", err)
	}
	l = config.FromMap(map[string]string{"AGENTAREA_REDIS_URL": "redis://v:6379", "AGENTAREA_BROKER": "kafka", "AGENTAREA_EVENT_NAMESPACE": "Bad"})
	LoadConfig(l)
	if err := l.Err(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_BROKER") || !strings.Contains(err.Error(), "AGENTAREA_EVENT_NAMESPACE") {
		t.Errorf("bad values not reported: %v", err)
	}
	l = config.FromMap(map[string]string{"AGENTAREA_REDIS_URL": "redis://v:6379"})
	c := LoadConfig(l)
	if l.Err() != nil || c.Namespace != "agentarea" || c.Partitions != 16 {
		t.Errorf("defaults: %+v %v", c, l.Err())
	}
}
