package telegram

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestPollGivesEachEventItsOwnOrigin(t *testing.T) {
	body := `{"ok":true,"result":[
		{"update_id":10,"message":{"message_id":1,"from":{"id":111,"username":"alice"},"chat":{"id":111},"text":"hello from alice"}},
		{"update_id":11,"message":{"message_id":2,"from":{"id":222,"username":"bob"},"chat":{"id":222},"text":"hello from bob"}}]}`
	p := NewPoller(map[string]any{"bot_token": "123:TOKEN"}).(*Poller)
	p.client.httpClient.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(body)), Header: http.Header{}}, nil
	})

	result, err := p.Poll(context.Background(), 0)
	if err != nil {
		t.Fatalf("Poll returned error: %v", err)
	}
	if len(result.Events) != 2 {
		t.Fatalf("events = %d, want 2", len(result.Events))
	}
	if result.NewOffset != 12 {
		t.Fatalf("new offset = %d, want 12", result.NewOffset)
	}

	want := []struct {
		chatID string
		user   string
	}{{"111", "alice"}, {"222", "bob"}}
	for i, polled := range result.Events {
		origin := polled.ChannelOrigin
		if origin["chat_id"] != want[i].chatID || origin["user_display_name"] != want[i].user {
			t.Fatalf("event %d (chat %d) origin = %+v, want chat_id %s, user %s",
				i, polled.Event.ChatID, origin, want[i].chatID, want[i].user)
		}
	}
}
