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

	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// TelegramAPI is where the Telegram Bot API answers.
const TelegramAPI = "https://api.telegram.org"

// NoLinkPreview is the link_preview_options every bot message carries: a reply ends with a link to
// the task's page, and Telegram would render a preview card of the webapp under every answer.
func NoLinkPreview() map[string]any { return map[string]any{"is_disabled": true} }

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
	// Files reads the files a task published; at the end of a turn the chat gets each new one.
	// Nil sends text only.
	Files sandboxapi.TaskFiles
	// AppURL is the webapp (AGENTAREA_APP_URL) and Slugs the workspaces' URL slugs: the end of a
	// turn links the task's page. Either empty leaves the link out.
	AppURL string
	Slugs  identityapi.WorkspaceSlugs
	// LockTTL is how long the per-task lock lives between renewals; zero is 30s.
	LockTTL time.Duration
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
	// A finished turn records when it ended. An event from before that is a late retry of the
	// turn and is dropped; one from after it is the next turn of a session the task continues,
	// which gets a message of its own.
	if endedAt, err := t.Redis.Get(ctx, telegramDonePrefix+s.Event.TaskID).Result(); err == nil {
		if !after(s.Event.Timestamp, endedAt) {
			return nil
		}
		if err := t.Redis.Del(ctx, telegramDonePrefix+s.Event.TaskID, key).Err(); err != nil {
			return fmt.Errorf("live message state: %w", err)
		}
	} else if !errors.Is(err, redis.Nil) {
		return fmt.Errorf("live message state: %w", err)
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
	link, plainLink := "", ""
	if end {
		if link, plainLink, err = t.taskLink(ctx, s); err != nil {
			return err
		}
		if link != "" {
			text += "\n\n" + link
		}
	}
	plain := func(text string) string {
		if link == "" {
			return StripMarkup(text)
		}
		return strings.Replace(StripMarkup(text), StripMarkup(link), plainLink, 1)
	}
	if r := []rune(text); len(r) > telegramLimit {
		text = "…\n" + string(r[len(r)-(telegramLimit-3):])
	}
	feedJSON, err := json.Marshal(feed)
	if err != nil {
		return err
	}
	outer := ctx
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if msgID := state["message_id"]; msgID == "" {
		payload := map[string]any{"chat_id": chatID, "text": text, "parse_mode": "MarkdownV2", "link_preview_options": NoLinkPreview()}
		if replyTo := target["message_id"]; truthy(replyTo) {
			payload["reply_to_message_id"] = replyTo
			payload["allow_sending_without_reply"] = true
		}
		status, body, err := t.call(ctx, token, "sendMessage", payload)
		if err == nil && status == http.StatusBadRequest && strings.Contains(strings.ToLower(string(body)), "parse") {
			payload["text"] = plain(text)
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
		payload := map[string]any{"chat_id": chatID, "message_id": id, "text": text, "parse_mode": "MarkdownV2", "link_preview_options": NoLinkPreview()}
		status, body, err := t.call(ctx, token, "editMessageText", payload)
		if err != nil {
			return err
		}
		lower := strings.ToLower(string(body))
		notModified := status == http.StatusBadRequest && strings.Contains(lower, "not modified")
		if !notModified && status == http.StatusBadRequest && strings.Contains(lower, "parse") {
			payload["text"] = plain(text)
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
	if end && CanonicalType(s.Event.Type) == "task.completed" {
		if err := t.sendOutputs(outer, s, token, chatID); err != nil {
			return err
		}
	}
	if end {
		mark, cancel := context.WithTimeout(outer, 10*time.Second)
		defer cancel()
		if err := t.Redis.Set(mark, telegramDonePrefix+s.Event.TaskID, endMark(s.Event.Timestamp), telegramStateTTL).Err(); err != nil {
			return err
		}
		return t.Redis.Del(mark, key).Err()
	}
	return nil
}

// taskLink is the line that links the task's page in the webapp, as MarkdownV2 and as plain
// text; empty when the webapp or the workspace's slug is unknown.
func (t TelegramLive) taskLink(ctx context.Context, s Send) (string, string, error) {
	page, err := t.taskPage(ctx, s)
	if err != nil || page == "" {
		return "", "", err
	}
	return "[Open in AgentArea](" + strings.NewReplacer(`\`, `\\`, `)`, `\)`).Replace(page) + ")", "Open in AgentArea: " + page, nil
}

// taskPage is the task's page in the webapp; empty when the webapp or the workspace's slug is unknown.
func (t TelegramLive) taskPage(ctx context.Context, s Send) (string, error) {
	if t.AppURL == "" || t.Slugs == nil || s.Workspace.ID() == "" || s.Event.TaskID == "" {
		return "", nil
	}
	slug, err := t.Slugs.Slug(ctx, s.Workspace.ID())
	if errors.Is(err, identityapi.ErrWorkspaceNotFound) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("slug of workspace %s: %w", s.Workspace.ID(), err)
	}
	return TaskPageURL(t.AppURL, slug, s.Event.TaskID), nil
}

// TaskPageURL is a task's page in the webapp; behind sign-in, so a forwarded link opens nothing.
func TaskPageURL(appURL, slug, taskID string) string {
	return strings.TrimRight(appURL, "/") + "/w/" + url.PathEscape(slug) + "/tasks/" + url.PathEscape(taskID)
}

// TaskFileURL is one file of a task in the webapp's files view.
func TaskFileURL(taskPage, filePath string) string {
	return taskPage + "/files?file=" + url.QueryEscape(filePath)
}

// LinkedFile is the line a chat gets instead of a file too large to send: its name, size and link.
func LinkedFile(name string, size int64, link string) string {
	if size < 0 {
		return fmt.Sprintf("%s (over 50 MB): %s", name, link)
	}
	return fmt.Sprintf("%s (%.1f MB): %s", name, float64(size)/(1<<20), link)
}

// TelegramRefused is the Bot API refusing a message: its HTTP status and description.
type TelegramRefused struct {
	Status      int
	Description string
}

func (e *TelegramRefused) Error() string {
	return fmt.Sprintf("telegram refused the message (%d): %s", e.Status, e.Description)
}

// Message sends text to chatID as a new message of its own, plain text cut at Telegram's limit
// as a reply's text is. It answers the message's id and whether the text was cut; a refusal is
// a *TelegramRefused.
func (t TelegramLive) Message(ctx context.Context, token string, chatID any, text string) (int64, bool, error) {
	plain, err := MarkupNamed("plain")
	if err != nil {
		return 0, false, err
	}
	limit := telegramLimit
	cut := Limited(plain, text, &limit)
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	status, body, err := t.call(ctx, token, "sendMessage", map[string]any{"chat_id": chatID, "text": cut, "link_preview_options": NoLinkPreview()})
	if err != nil {
		return 0, false, err
	}
	var answer struct {
		Description string `json:"description"`
		Result      struct {
			MessageID int64 `json:"message_id"`
		} `json:"result"`
	}
	_ = json.Unmarshal(body, &answer)
	if err := raiseFor(status, body, nil); err != nil {
		if answer.Description == "" {
			answer.Description = err.Error()
		}
		return 0, false, &TelegramRefused{Status: status, Description: answer.Description}
	}
	return answer.Result.MessageID, cut != text, nil
}

const renewScript = `if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("pexpire", KEYS[1], ARGV[2]) end return 0`

const unlockScript = `if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) end return 0`

// lock serializes the sends of one task across replicas, so a retried progress update cannot
// interleave with the end. It is renewed while held, however long the files of a turn take to
// upload; the returned func frees it.
func (t TelegramLive) lock(ctx context.Context, taskID string) (func(), error) {
	key, token := telegramLockPrefix+taskID, uuid.NewString()
	ttl := t.LockTTL
	if ttl <= 0 {
		ttl = telegramLockTTL
	}
	wait, cancel := context.WithTimeout(ctx, telegramLockWait)
	defer cancel()
	for {
		ok, err := t.Redis.SetNX(wait, key, token, ttl).Result()
		if err != nil {
			return nil, fmt.Errorf("live message lock of task %s: %w", taskID, err)
		}
		if ok {
			stop, stopped := make(chan struct{}), make(chan struct{})
			go func() {
				defer close(stopped)
				tick := time.NewTicker(ttl / 3)
				defer tick.Stop()
				for {
					select {
					case <-stop:
						return
					case <-tick.C:
						renew, done := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
						_ = redis.NewScript(renewScript).Run(renew, t.Redis, []string{key}, token, ttl.Milliseconds()).Err()
						done()
					}
				}
			}()
			return func() {
				close(stop)
				<-stopped
				free, done := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
				defer done()
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

// endMark is what the end of a turn records: its time, or "1" when the event has none, which no
// later event is after.
func endMark(ts string) string {
	if _, err := time.Parse(time.RFC3339Nano, ts); err != nil {
		return "1"
	}
	return ts
}

// after is whether ts is a time strictly later than the recorded end; an unknown time is not.
func after(ts, endedAt string) bool {
	at, err := time.Parse(time.RFC3339Nano, ts)
	if err != nil {
		return false
	}
	end, err := time.Parse(time.RFC3339Nano, endedAt)
	if err != nil {
		return false
	}
	return at.After(end)
}
