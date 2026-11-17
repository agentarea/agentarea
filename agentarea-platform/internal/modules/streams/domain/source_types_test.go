package domain

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func shippedEntries(t *testing.T) map[string]SourceTypeEntry {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "..", "data", "catalog", "source-types.json"))
	if err != nil {
		t.Skipf("shipped catalog not readable: %v", err)
	}
	var doc struct {
		SourceTypes []json.RawMessage `json:"source_types"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	out := map[string]SourceTypeEntry{}
	for _, r := range doc.SourceTypes {
		e, err := ParseSourceTypeEntry(r)
		if err != nil {
			t.Fatalf("entry %s: %v", string(r)[:60], err)
		}
		out[e.Slug] = e
	}
	return out
}

func TestEveryShippedEntryParses(t *testing.T) {
	entries := shippedEntries(t)
	if len(entries) < 15 {
		t.Fatalf("only %d entries", len(entries))
	}
	tg := entries["telegram"]
	if tg.Admission == nil || tg.Reply == nil || tg.Registration == nil || tg.Poll == nil || !tg.ContinuesSessions() {
		t.Fatalf("telegram parsed short: %+v", tg)
	}
	if tg.Verification.Algorithm != "sha256" || tg.Verification.ToleranceSecs != 300 {
		t.Fatalf("defaults not applied: %+v", tg.Verification)
	}
	if !entries["mcp_events"].SpeaksMCPEvents() {
		t.Fatal("mcp_events does not speak MCP Events")
	}
}

func TestAnEntryRefusesExtraKeysAndBadLiterals(t *testing.T) {
	for _, raw := range []string{
		`{"slug":"x","name":"X","delivery":"webhook","event":{"kind":"k"},"extra":1}`,
		`{"slug":"x","name":"X","delivery":"sometimes","event":{"kind":"k"}}`,
		`{"slug":"X","name":"X","delivery":"webhook","event":{"kind":"k"}}`,
		`{"slug":"x","name":"X","delivery":"webhook","event":{}}`,
		`{"slug":"x","name":"X","delivery":"webhook","event":{"kind":"k"},"verification":{"scheme":"hmac","algorithm":"md5"}}`,
		`{"slug":"x","name":"X","delivery":"webhook","event":{"kind":"k"},"registration":{"transport":"mcp_events","unregister":{"url":"u"}}}`,
	} {
		if _, err := ParseSourceTypeEntry(json.RawMessage(raw)); err == nil {
			t.Errorf("accepted %s", raw)
		}
	}
}

func TestShippedTemplatesReadWhatProvidersSend(t *testing.T) {
	entries := shippedEntries(t)
	gh := ReadEvent(entries["github"], EventOverrides{}, "src", map[string]string{"x-github-event": "issues",
		"x-github-delivery": "72d3"}, decoded(t, `{"action":"opened","sender":{"login":"octocat"}}`))
	if gh.Kind != "issues.opened" || gh.Key == nil || *gh.Key != "72d3" {
		t.Fatalf("github: %+v", gh)
	}
	push := ReadEvent(entries["github"], EventOverrides{}, "src", map[string]string{"x-github-event": "push"}, decoded(t, `{"ref":"r"}`))
	if push.Kind != "push" {
		t.Fatalf("github push: %+v", push)
	}
	tg := ReadEvent(entries["telegram"], EventOverrides{}, "src", nil,
		decoded(t, `{"update_id": 81234, "message": {"message_id": 1, "date": 1700000000, "chat": {"id": 555, "type": "private"}, "from": {"id": 42}, "text": "hi"}}`))
	if tg.SessionKey == nil || !strings.HasPrefix(*tg.SessionKey, "src:") || tg.OccurredAt == nil || !tg.OccurredAt.Equal(time.Unix(1700000000, 0)) {
		t.Fatalf("telegram: %+v", tg)
	}
	answer, ok := HandshakeAnswer(entries["discord"], nil, decoded(t, `{"type": 1}`))
	if !ok || answer.(map[string]any)["type"] == nil {
		t.Fatalf("discord handshake: %v %v", answer, ok)
	}
	slack, ok := HandshakeAnswer(entries["slack"], nil, decoded(t, `{"type":"url_verification","challenge":"c1"}`))
	if !ok || slack.(map[string]any)["challenge"] != "c1" {
		t.Fatalf("slack handshake: %v", slack)
	}
}

func TestSendersAreValidatedAsPydanticDoes(t *testing.T) {
	s, err := ParseSenders(map[string]any{"allow": "ids", "ids": []any{" 12 ", "12", json.Number("34")}})
	if err != nil || strings.Join(s.IDs, ",") != "12,34" {
		t.Fatalf("got %+v %v", s, err)
	}
	for _, bad := range []map[string]any{
		{"allow": "ids"}, {"allow": "owner", "ids": []any{"1"}}, {"allow": "ids", "ids": []any{"x1"}}, {"allow": "all"},
		{"allow": "owner", "by": "u"},
	} {
		if _, err := ParseSenders(bad); err == nil {
			t.Errorf("accepted %v", bad)
		}
	}
	stored := SendersToStore(true, nil, "u1")
	rec, ok := SendersRecordOf(stored)
	if !ok || rec.Allow != SendersOwner || *rec.By != "u1" {
		t.Fatalf("round trip: %+v", rec)
	}
	if SendersToStore(false, &s, "u1") != nil {
		t.Fatal("a type without admission stores senders")
	}
}

func TestEnvelopeScrubsCredentialHeadersAndReadsProviderTimes(t *testing.T) {
	v := Verification{Header: sp("X-Webhook-Signature")}
	got := WithoutCredentials(map[string]string{"Authorization": "a", "x-webhook-signature": "s", "X-Shop-Token": "t",
		"X-Api-Key": "k", "x-github-event": "push", "Cookie": "c"}, &v)
	if len(got) != 1 || got["x-github-event"] != "push" {
		t.Fatalf("got %v", got)
	}
	for in, want := range map[string]string{
		"1700000000":                      "2023-11-14T22:13:20Z",
		"1700000000123":                   "2023-11-14T22:13:20.123Z",
		"2026-10-19T10:00:00Z":            "2026-10-19T10:00:00Z",
		"2026-10-19T10:00:00":             "2026-10-19T10:00:00Z",
		"Mon, 19 Oct 2026 10:00:00 +0000": "2026-10-19T10:00:00Z",
	} {
		p := ProviderTime(in)
		if p == nil || p.UTC().Format(time.RFC3339Nano) != want {
			t.Errorf("%s -> %v, want %s", in, p, want)
		}
	}
	for _, bad := range []string{"soon", "inf", "nan", "1e400"} {
		if ProviderTime(bad) != nil {
			t.Errorf("%s parsed", bad)
		}
	}
	if d, ok := CarriedDepth("3", 8); !ok || d != 4 {
		t.Fatal(d)
	}
	if d, _ := CarriedDepth("99", 8); d != 9 {
		t.Fatal(d)
	}
	if _, ok := CarriedDepth("-1", 8); ok {
		t.Fatal("negative depth carried")
	}
}

func TestAttachmentPathsFindFiles(t *testing.T) {
	entries := shippedEntries(t)
	body := decoded(t, `{"message":{"photo":[{"file_id":"s"},{"file_id":"l","file_size":9}]}}`)
	p, ok := AttachmentPath(entries["telegram"], body)
	if !ok || p != "message.photo[-1]" {
		t.Fatalf("path %q", p)
	}
	items := AttachmentItems(body, p)
	if len(items) != 1 || items[0]["file_id"] != "l" {
		t.Fatalf("items %v", items)
	}
	disc := decoded(t, `{"data":{"resolved":{"attachments":{"2":{"id":"b"},"1":{"id":"a"}}}}}`)
	if items := AttachmentItems(disc, "data.resolved.attachments.*"); len(items) != 2 || items[0]["id"] != "a" {
		t.Fatalf("discord items %v", items)
	}
}
