package domain

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

func eventsCode(t *testing.T, err error) int {
	t.Helper()
	var e *api.EventsError
	if !errors.As(err, &e) {
		t.Fatalf("err = %v, want an events error", err)
	}
	return e.Code
}

func TestEventArgumentsAreTheInputSchema(t *testing.T) {
	a, err := ParseEventArguments(map[string]any{"kind": "order", "session_key": "chat-1"})
	if err != nil || *a.Kind != "order" || *a.SessionKey != "chat-1" || a.SourceType != nil {
		t.Fatalf("parsed %+v %v", a, err)
	}
	if got := a.Canonical(); got != `{"kind":"order","session_key":"chat-1"}` {
		t.Fatalf("canonical %s", got)
	}
	f := a.Filter()
	if len(f.Kinds) != 1 || f.Kinds[0] != "order" || *f.SessionKey != "chat-1" || f.SourceType != nil {
		t.Fatalf("filter %+v", f)
	}
	if none, err := ParseEventArguments(nil); err != nil || none.Canonical() != "{}" || len(none.Filter().Kinds) != 0 {
		t.Fatalf("none %+v %v", none, err)
	}
	for _, bad := range []any{
		map[string]any{"other": "x"},
		map[string]any{"kind": ""},
		map[string]any{"kind": 3},
		map[string]any{"source_type": strings.Repeat("s", 65)},
		"order",
	} {
		if _, err := ParseEventArguments(bad); eventsCode(t, err) != api.EventsInvalidParams ||
			err.Error() != "arguments do not match the event's inputSchema" {
			t.Fatalf("%v: %v", bad, err)
		}
	}
	if _, err := ParseEventArguments(map[string]any{"kind": nil}); err != nil {
		t.Fatalf("null kind: %v", err)
	}
}

func TestEventNameHoldsWorkspaceAndStream(t *testing.T) {
	ws, id, err := ParseEventName("acme/6F9619FF-8B86-D011-B42D-00C04FC964FF")
	if err != nil || ws != "acme" || id != "6f9619ff-8b86-d011-b42d-00c04fc964ff" {
		t.Fatalf("%s %s %v", ws, id, err)
	}
	for _, bad := range []string{"acme", "/6f9619ff-8b86-d011-b42d-00c04fc964ff", "acme/nope"} {
		_, _, err := ParseEventName(bad)
		var e *api.EventsError
		if !errors.As(err, &e) || e.Code != api.EventsNotFound || e.Message != "no event type '"+bad+"'" || e.Data["kind"] != "event" {
			t.Fatalf("%s: %v", bad, err)
		}
	}
}

func TestPollCursorRoundTrips(t *testing.T) {
	at := time.UnixMilli(1_700_000_000_123).UTC()
	c := PollCursor{At: at, Sequence: 42}
	want := strings.TrimRight(base64.URLEncoding.EncodeToString([]byte("v1:1700000000123:42")), "=")
	if c.Encode() != want {
		t.Fatalf("encoded %s, want %s", c.Encode(), want)
	}
	back, err := DecodePollCursor(want)
	if err != nil || !back.At.Equal(at) || back.Sequence != 42 {
		t.Fatalf("decoded %+v %v", back, err)
	}
	if !back.Before(at.Add(time.Millisecond)) || back.Before(at) {
		t.Fatal("before")
	}
	for _, bad := range []string{"!!", base64.RawURLEncoding.EncodeToString([]byte("v2:1:2")), base64.RawURLEncoding.EncodeToString([]byte("v1:x:2")), base64.RawURLEncoding.EncodeToString([]byte("v1:1"))} {
		_, err := DecodePollCursor(bad)
		if eventsCode(t, err) != api.EventsInvalidParams || err.Error() != "cursor is not one this server issued" {
			t.Fatalf("%s: %v", bad, err)
		}
	}
}

func TestWebhookSecretIsStandardWebhooks(t *testing.T) {
	ok := "whsec_" + base64.StdEncoding.EncodeToString(make([]byte, 32))
	if err := ValidateWebhookSecret(ok); err != nil {
		t.Fatal(err)
	}
	for secret, msg := range map[string]string{
		"sk_abc":   "delivery.secret must start with whsec_",
		"whsec_%%": "delivery.secret is not base64",
		"whsec_" + base64.StdEncoding.EncodeToString(make([]byte, 8)):  "delivery.secret must encode 24 to 64 random bytes",
		"whsec_" + base64.StdEncoding.EncodeToString(make([]byte, 65)): "delivery.secret must encode 24 to 64 random bytes",
	} {
		err := ValidateWebhookSecret(secret)
		if eventsCode(t, err) != api.EventsInvalidParams || err.Error() != msg {
			t.Fatalf("%s: %v", secret, err)
		}
	}
}

func TestSubscriptionKeyIsTheHashOfItsParts(t *testing.T) {
	a, _ := ParseEventArguments(map[string]any{"kind": "örder"})
	key, _ := json.Marshal([]string{"user:u1", "https://hook.example/x", "6f9619ff-8b86-d011-b42d-00c04fc964ff", `{"kind":"` + `\` + `u00f6rder"}`})
	sum := sha256.Sum256(key)
	want := "sub_" + hex.EncodeToString(sum[:])[:32]
	if got := SubscriptionKey("user:u1", "https://hook.example/x", "6f9619ff-8b86-d011-b42d-00c04fc964ff", a); got != want {
		t.Fatalf("key %s, want %s", got, want)
	}
}

func TestGrantClampsTheSuggestedTTL(t *testing.T) {
	now := time.Date(2026, 11, 17, 10, 0, 0, 0, time.UTC)
	ms := func(d time.Duration) *int64 { v := d.Milliseconds(); return &v }
	for in, want := range map[*int64]time.Duration{
		nil:                  24 * time.Hour,
		ms(time.Second):      time.Minute,
		ms(2 * time.Hour):    2 * time.Hour,
		ms(48 * time.Hour):   24 * time.Hour,
		ms(90 * time.Second): 90 * time.Second,
	} {
		if got := GrantRefreshBefore(in, now); !got.Equal(now.Add(want)) {
			t.Fatalf("%v: %s", in, got)
		}
	}
}

func TestEventSchemasAreJSON(t *testing.T) {
	for _, raw := range []json.RawMessage{EventsInputSchema(), EventsPayloadSchema()} {
		var m map[string]any
		if err := json.Unmarshal(raw, &m); err != nil || m["type"] != "object" {
			t.Fatalf("%s: %v", raw, err)
		}
	}
	var in struct {
		AdditionalProperties bool                       `json:"additionalProperties"`
		Properties           map[string]json.RawMessage `json:"properties"`
	}
	_ = json.Unmarshal(EventsInputSchema(), &in)
	if in.AdditionalProperties || len(in.Properties) != 3 {
		t.Fatalf("input schema %+v", in)
	}
}
