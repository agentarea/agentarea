package replies

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// TelegramAPI is where the Telegram Bot API answers.
const TelegramAPI = "https://api.telegram.org"

const (
	telegramLimit    = 4096
	telegramStateTTL = time.Hour
	telegramLockTTL  = 30 * time.Second
	telegramLockWait = 20 * time.Second

	telegramDonePrefix = "tg:live:done:"
	telegramLockPrefix = "tg:live:lock:"
)

// TelegramLive streams a task's progress into one live message: the first event sends it, every
// later one edits it, and the end replaces the feed with the answer. The message id and the feed
// live in Redis under tg:live:<task>, so they survive redeliveries and restarts.
type TelegramLive struct {
	Credentials Credentials
	Redis       *redis.Client
	// Client calls the Bot API (netguard.Vendor); API is its base, TelegramAPI when empty.
	Client *http.Client
	API    string
}

func (t TelegramLive) Format(s Send) (string, error) { return formatInMarkup(s) }

func terminal(eventType string) bool {
	switch CanonicalType(eventType) {
	case "task.completed", "task.failed", "task.cancelled":
		return true
	}
	return false
}

func (t TelegramLive) Send(ctx context.Context, s Send, message string) error {
	creds, err := s.credentials(ctx, t.Credentials)
	if err != nil {
		return err
	}
	token := creds["bot_token"]
	if token == "" {
		return fatalf("the source's credentials have no bot_token")
	}
	target, _ := s.Target.Config["target"].(map[string]any)
	chatID, ok := target["chat_id"]
	if !ok || chatID == nil {
		return fatalf("the delivery address has no chat_id")
	}
	reply, err := replyOf(s)
	if err != nil {
		return err
	}
	release, err := t.lock(ctx, s.Event.TaskID)
	if err != nil {
		return err
	}
	defer release()
	key := "tg:live:" + s.Event.TaskID
	end := terminal(s.Event.Type)
	if over, err := t.Redis.Exists(ctx, telegramDonePrefix+s.Event.TaskID).Result(); err != nil {
		return fmt.Errorf("live message state: %w", err)
	} else if over > 0 {
		return nil
	}
	state, err := t.Redis.HGetAll(ctx, key).Result()
	if err != nil {
		return fmt.Errorf("live message state: %w", err)
	}
	var feed []string
	if raw := state["feed"]; raw != "" {
		if err := json.Unmarshal([]byte(raw), &feed); err != nil {
			return fmt.Errorf("live message feed of task %s: %w", s.Event.TaskID, err)
		}
	}
	line := strings.TrimSpace(message)
	switch {
	case end && line != "":
		feed = []string{line}
	case end:
		feed = []string{"Done"}
	case line != "" && (len(feed) == 0 || feed[len(feed)-1] != line):
		feed = append(feed, line)
	}
	text := line
	if len(feed) > 0 {
		text = strings.Join(feed, "\n")
	}
	if text == "" {
		return nil
	}
	if r := []rune(text); len(r) > telegramLimit {
		text = "…\n" + string(r[len(r)-(telegramLimit-3):])
	}
	feedJSON, err := json.Marshal(feed)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if msgID := state["message_id"]; msgID == "" {
		payload := map[string]any{"chat_id": chatID, "text": text, "parse_mode": "MarkdownV2"}
		if replyTo := target["message_id"]; truthy(replyTo) {
			payload["reply_to_message_id"] = replyTo
			payload["allow_sending_without_reply"] = true
		}
		status, body, err := t.call(ctx, token, "sendMessage", payload)
		if err == nil && status == http.StatusBadRequest && strings.Contains(strings.ToLower(string(body)), "parse") {
			payload["text"] = StripMarkup(text)
			delete(payload, "parse_mode")
			status, body, err = t.call(ctx, token, "sendMessage", payload)
		}
		if err != nil {
			return err
		}
		if err := raiseFor(status, body, reply.PermanentErrors); err != nil {
			return err
		}
		var sent struct {
			Result struct {
				MessageID json.Number `json:"message_id"`
			} `json:"result"`
		}
		if json.Unmarshal(body, &sent) == nil && sent.Result.MessageID != "" {
			if err := t.Redis.HSet(ctx, key, "message_id", sent.Result.MessageID.String(), "feed", string(feedJSON)).Err(); err != nil {
				return err
			}
			if err := t.Redis.Expire(ctx, key, telegramStateTTL).Err(); err != nil {
				return err
			}
		}
	} else {
		id, err := strconv.ParseInt(msgID, 10, 64)
		if err != nil {
			return fatalf("the live message id %q is not a number", msgID)
		}
		payload := map[string]any{"chat_id": chatID, "message_id": id, "text": text, "parse_mode": "MarkdownV2"}
		status, body, err := t.call(ctx, token, "editMessageText", payload)
		if err != nil {
			return err
		}
		lower := strings.ToLower(string(body))
		notModified := status == http.StatusBadRequest && strings.Contains(lower, "not modified")
		if !notModified && status == http.StatusBadRequest && strings.Contains(lower, "parse") {
			payload["text"] = StripMarkup(text)
			delete(payload, "parse_mode")
			if status, body, err = t.call(ctx, token, "editMessageText", payload); err != nil {
				return err
			}
		}
		if !notModified {
			if err := raiseFor(status, body, reply.PermanentErrors); err != nil {
				return err
			}
		}
		if err := t.Redis.HSet(ctx, key, "feed", string(feedJSON)).Err(); err != nil {
			return err
		}
	}
	if end {
		if err := t.Redis.Set(ctx, telegramDonePrefix+s.Event.TaskID, "1", telegramStateTTL).Err(); err != nil {
			return err
		}
		return t.Redis.Del(ctx, key).Err()
	}
	return nil
}

const unlockScript = `if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) end return 0`

// lock serializes the sends of one task across replicas, so a retried progress update cannot
// interleave with the end; the returned func frees it.
func (t TelegramLive) lock(ctx context.Context, taskID string) (func(), error) {
	key, token := telegramLockPrefix+taskID, uuid.NewString()
	wait, cancel := context.WithTimeout(ctx, telegramLockWait)
	defer cancel()
	for {
		ok, err := t.Redis.SetNX(wait, key, token, telegramLockTTL).Result()
		if err != nil {
			return nil, fmt.Errorf("live message lock of task %s: %w", taskID, err)
		}
		if ok {
			return func() {
				free, stop := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
				defer stop()
				_ = redis.NewScript(unlockScript).Run(free, t.Redis, []string{key}, token).Err()
			}, nil
		}
		select {
		case <-wait.Done():
			return nil, fmt.Errorf("live message of task %s is busy: %w", taskID, wait.Err())
		case <-time.After(20 * time.Millisecond):
		}
	}
}

func (t TelegramLive) call(ctx context.Context, token, method string, payload map[string]any) (int, []byte, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return 0, nil, fatalf("telegram %s payload: %v", method, err)
	}
	base := t.API
	if base == "" {
		base = TelegramAPI
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/bot"+token+"/"+method, bytes.NewReader(raw))
	if err != nil {
		return 0, nil, fatalf("telegram %s request: %v", method, err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := t.Client.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return 0, nil, fmt.Errorf("network: telegram %s: %w", method, err)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	if err != nil {
		return 0, nil, fmt.Errorf("network: telegram %s answer: %w", method, err)
	}
	return resp.StatusCode, body, nil
}

func raiseFor(status int, body []byte, permanent []string) error {
	resp := &http.Response{StatusCode: status, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(bytes.NewReader(body))}
	return RaiseForReply(resp, permanent)
}

var _ Sender = TelegramLive{}
var _ Sender = HTTPReply{}
