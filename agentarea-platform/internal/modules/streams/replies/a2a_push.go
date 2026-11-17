package replies

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

const (
	// A2APushSender is the sender and target type of an A2A client's push notification webhook.
	A2APushSender = "a2a_webhook"
	// A2ANotificationTokenHeader echoes the client's callback token so it can authenticate us.
	A2ANotificationTokenHeader = "X-A2A-Notification-Token"

	a2aPushConfigsParameter = "a2a_push_configs"
)

// A2APushTokenSecret is the secret-store key of a push config's callback token.
func A2APushTokenSecret(taskID, configID string) string {
	return "a2a_push_token:" + taskID + ":" + configID
}

func pushTargets(task map[string]any) ([]Target, []string) {
	configs, _ := task[a2aPushConfigsParameter].([]any)
	var out []Target
	var malformed []string
	for _, c := range configs {
		config, _ := c.(map[string]any)
		id, url := config["id"], config["url"]
		if !truthy(id) || !truthy(url) {
			malformed = append(malformed, fmt.Sprintf("A2A push config without id or url: %v", c))
			continue
		}
		out = append(out, Target{
			Key: "a2a:" + pyStr(id, ""), Sender: A2APushSender, Presentation: Silent,
			Config: map[string]any{"type": A2APushSender, "url": url, "config_id": id, "presentation": Silent},
		})
	}
	return out, malformed
}

// A2APush tells an A2A client its task ended: a POST of the A2A StreamResponse for each
// terminal event, with the callback token the client registered.
type A2APush struct {
	Secret Secret
	// Client posts to the client's URL (netguard.Public, no redirects).
	Client *http.Client
}

func (p A2APush) Format(s Send) (string, error) { return A2APushBody(s.Event) }

// A2APushBody is build_push_notification_body: the StreamResponse statusUpdate of a terminal
// task event as MessageToJson writes it, "" for any other.
func A2APushBody(e Event) (string, error) {
	state := map[string]string{
		"task.completed": "TASK_STATE_COMPLETED", "task.failed": "TASK_STATE_FAILED", "task.cancelled": "TASK_STATE_CANCELED",
	}[CanonicalType(e.Type)]
	if state == "" {
		return "", nil
	}
	d := e.Data
	if d == nil {
		d = map[string]any{}
	}
	taskID := pyStr(firstTruthy(d, "task_id"), e.TaskID)
	contextID := pyStr(firstTruthy(d, "context_id"), taskID)
	text := pyStr(firstTruthy(d, "result", "final_response", "error"), "")
	status := `"state": "` + state + `"`
	if text != "" {
		status += `, "message": {"messageId": "` + strings.ReplaceAll(uuid.NewString(), "-", "") +
			`", "role": "ROLE_AGENT", "parts": [{"text": ` + domain.PyJSONString(text) + `}]}`
	}
	var update []string
	if taskID != "" {
		update = append(update, `"taskId": `+domain.PyJSONString(taskID))
	}
	if contextID != "" {
		update = append(update, `"contextId": `+domain.PyJSONString(contextID))
	}
	update = append(update, `"status": {`+status+`}`)
	return `{"statusUpdate": {` + strings.Join(update, ", ") + `}}`, nil
}

func (p A2APush) Send(ctx context.Context, s Send, message string) error {
	target, _ := s.Target.Config["url"].(string)
	if target == "" || message == "" {
		return nil
	}
	headers := http.Header{"Content-Type": {"application/json"}}
	if configID := pyStr(s.Target.Config["config_id"], ""); s.Event.TaskID != "" && configID != "" {
		token, ok, err := p.Secret(ctx, s.Workspace, s.Owner, A2APushTokenSecret(s.Event.TaskID, configID))
		if err != nil {
			return fmt.Errorf("push webhook token: %w", err)
		}
		if ok && token != "" {
			headers.Set(A2ANotificationTokenHeader, token)
		}
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(message))
	if err != nil {
		return fatalf("unsafe push webhook url: %v", err)
	}
	req.Header = headers
	resp, err := p.Client.Do(req)
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return fatalf("unsafe push webhook url: %v", err)
		}
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return fmt.Errorf("push webhook network error: %w", err)
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	switch {
	case resp.StatusCode >= 500 || resp.StatusCode == http.StatusTooManyRequests:
		return fmt.Errorf("push webhook returned %d", resp.StatusCode)
	case resp.StatusCode >= 400:
		return fatalf("push webhook returned %d", resp.StatusCode)
	}
	return nil
}

var _ Sender = A2APush{}
