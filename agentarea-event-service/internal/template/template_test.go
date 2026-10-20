package template

import (
	"errors"
	"reflect"
	"testing"
)

func TestRenderFillsRequestPlaceholders(t *testing.T) {
	got, err := Render(
		"https://api.telegram.org/bot{credentials.bot_token}/getUpdates?offset={cursor}&timeout=30",
		Values{Credentials: map[string]string{"bot_token": "1:abc"}, Cursor: "42"},
	)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	if got != "https://api.telegram.org/bot1:abc/getUpdates?offset=42&timeout=30" {
		t.Fatalf("got %q", got)
	}
}

func TestRenderRefusesAMissingValue(t *testing.T) {
	_, err := Render("{credentials.bot_token}", Values{})
	if !errors.Is(err, ErrMissing) {
		t.Fatalf("err = %v, want ErrMissing", err)
	}
	if _, err := Render("{config.url}", Values{Config: map[string]any{"url": ""}}); !errors.Is(err, ErrMissing) {
		t.Fatalf("empty config value err = %v", err)
	}
	if _, err := Render("{nonsense}", Values{}); err == nil {
		t.Fatal("rendered an unknown placeholder")
	}
}

func TestAConstantRendersAsItself(t *testing.T) {
	if got, err := Render("INBOX", Values{}); err != nil || got != "INBOX" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestRenderJSONKeepsTheTypeOfAWholePlaceholder(t *testing.T) {
	body := map[string]any{
		"url":             "{webhook_url}",
		"secret_token":    "{credentials.webhook_secret}",
		"allowed_updates": []any{"message", "{config.extra}"},
		"limit":           "{config.limit}",
		"note":            "for {source_id}",
	}
	got, err := RenderJSON(body, Values{
		WebhookURL:  "https://h/webhooks/w1",
		Credentials: map[string]string{"webhook_secret": "s"},
		Config:      map[string]any{"extra": "edited_message", "limit": float64(5)},
		SourceID:    "src-1",
	})
	if err != nil {
		t.Fatalf("RenderJSON: %v", err)
	}
	want := map[string]any{
		"url":             "https://h/webhooks/w1",
		"secret_token":    "s",
		"allowed_updates": []any{"message", "edited_message"},
		"limit":           float64(5),
		"note":            "for src-1",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v", got)
	}
}

func TestRenderJSONLeavesOutAMemberWithNoValue(t *testing.T) {
	got, err := RenderJSON(map[string]any{"url": "{webhook_url}", "secret_token": "{credentials.secret_token}"},
		Values{WebhookURL: "https://h/webhooks/w1"})
	if err != nil {
		t.Fatalf("RenderJSON: %v", err)
	}
	if !reflect.DeepEqual(got, map[string]any{"url": "https://h/webhooks/w1"}) {
		t.Fatalf("got %#v", got)
	}
	if _, err := RenderJSON(map[string]any{"x": "{nonsense}"}, Values{}); err == nil || errors.Is(err, ErrMissing) {
		t.Fatalf("an unknown placeholder err = %v, want a template error", err)
	}
}

func TestRenderCursorAddsTheIncrement(t *testing.T) {
	got, err := RenderCursor("{item:update_id}+1", map[string]any{"update_id": float64(81234)})
	if err != nil || got != "81235" {
		t.Fatalf("got %q, %v", got, err)
	}
	got, err = RenderCursor("{item:id}", map[string]any{"id": "abc"})
	if err != nil || got != "abc" {
		t.Fatalf("got %q, %v", got, err)
	}
	if _, err := RenderCursor("{item:id}+1", map[string]any{"id": "abc"}); err == nil {
		t.Fatal("added to a non-integer cursor")
	}
}

func TestLookupFollowsPathsIndexesAndAlternatives(t *testing.T) {
	root := map[string]any{
		"result":         []any{map[string]any{"message": map[string]any{"chat": map[string]any{"id": float64(7)}}}},
		"callback_query": map[string]any{"from": map[string]any{"id": "u"}},
	}
	if v, ok := Lookup(root, "result.0.message.chat.id"); !ok || v != float64(7) {
		t.Fatalf("got %v, %v", v, ok)
	}
	if v, ok := Lookup(root, "message.from.id|callback_query.from.id"); !ok || v != "u" {
		t.Fatalf("alternative got %v, %v", v, ok)
	}
	if _, ok := Lookup(root, "result.9"); ok {
		t.Fatal("found an index past the end")
	}
}
