package replies_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

func TestATelegramMessageIsPlainTextCutAtTheLimit(t *testing.T) {
	var got []map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m map[string]any
		_ = json.NewDecoder(r.Body).Decode(&m)
		got = append(got, m)
		if r.URL.Path != "/botTOKEN/sendMessage" {
			t.Errorf("path %s", r.URL.Path)
		}
		if m["chat_id"] == "666" {
			w.WriteHeader(http.StatusForbidden)
			_, _ = io.WriteString(w, `{"ok":false,"error_code":403,"description":"Forbidden: bot can't initiate conversation with a user"}`)
			return
		}
		_, _ = io.WriteString(w, `{"ok":true,"result":{"message_id":77}}`)
	}))
	t.Cleanup(srv.Close)
	tg := replies.TelegramLive{Client: srv.Client(), API: srv.URL}
	ctx := context.Background()

	id, cut, err := tg.Message(ctx, "TOKEN", "42", "The *report* is ready_")
	if err != nil || id != 77 || cut {
		t.Fatalf("sent %d cut=%v %v", id, cut, err)
	}
	if got[0]["chat_id"] != "42" || got[0]["text"] != "The *report* is ready_" || got[0]["parse_mode"] != nil {
		t.Fatalf("payload %v", got[0])
	}

	_, cut, err = tg.Message(ctx, "TOKEN", "42", strings.Repeat("я", 5000))
	text, _ := got[1]["text"].(string)
	if err != nil || !cut || utf8.RuneCountInString(text) != 4096 || !strings.HasSuffix(text, "\n\n(truncated)") {
		t.Fatalf("cut=%v len=%d %v", cut, utf8.RuneCountInString(text), err)
	}

	_, _, err = tg.Message(ctx, "TOKEN", "666", "hello")
	var refused *replies.TelegramRefused
	if !errors.As(err, &refused) || refused.Status != http.StatusForbidden || !strings.Contains(refused.Description, "can't initiate conversation") {
		t.Fatalf("refusal %v", err)
	}
}
