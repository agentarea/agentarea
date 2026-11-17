package replies

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Task webhook headers (utils/task_webhook.py).
const (
	SignatureHeader = "X-AgentArea-Signature"
	EventHeader     = "X-AgentArea-Event"
	DeliveryHeader  = "X-AgentArea-Delivery"
	webhookVersion  = "1"
)

// WebhookSecretName is the secret-store key of a task webhook's signing secret.
func WebhookSecretName(taskID string) string { return "task_webhook:" + taskID }

// Sign is the X-AgentArea-Signature of body sent at timestamp: t=<ts>,v1=<hex HMAC-SHA256 of "<ts>.<body>">.
func Sign(secret string, body []byte, timestamp int64) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(strconv.FormatInt(timestamp, 10) + "."))
	mac.Write(body)
	return "t=" + strconv.FormatInt(timestamp, 10) + ",v1=" + hex.EncodeToString(mac.Sum(nil))
}

// Secret reads a workspace secret as owner; false when there is none.
type Secret func(ctx context.Context, ws scope.Workspace, owner, name string) (string, bool, error)

// TaskWebhook tells the API caller a task's turn ended, with what it cost: a POST of the body
// for each terminal event, signed when the caller gave a secret.
type TaskWebhook struct {
	Secret Secret
	// Client posts to the caller's URL (netguard.Member, no redirects).
	Client *http.Client
	Now    func() time.Time
}

func (w TaskWebhook) Format(s Send) (string, error) {
	body, err := TaskWebhookBody(s.Event)
	return string(body), err
}

// TaskWebhookBody is build_task_webhook_body: the JSON body of a terminal task event, nil for
// any other. total_cost and tokens_used are the task's running totals.
func TaskWebhookBody(e Event) ([]byte, error) {
	t := CanonicalType(e.Type)
	status := map[string]string{"task.completed": "completed", "task.failed": "failed", "task.cancelled": "cancelled"}[t]
	if status == "" {
		return nil, nil
	}
	d := e.Data
	if d == nil {
		d = map[string]any{}
	}
	taskID := firstTruthy(d, "task_id")
	if taskID == nil {
		taskID = e.TaskID
	}
	ts := any(e.Timestamp)
	if e.Timestamp == "" {
		ts = d["timestamp"]
	}
	return orderedJSON([]field{
		{"version", webhookVersion}, {"type", t}, {"event_id", e.ID}, {"task_id", fmt.Sprint(taskID)},
		{"agent_id", d["agent_id"]}, {"execution_id", d["execution_id"]}, {"status", status},
		{"execution_status", d["execution_status"]}, {"end_user_id", d["end_user_id"]}, {"metadata", d["app_metadata"]},
		{"total_cost", d["total_cost"]}, {"tokens_used", d["tokens_used"]}, {"result", firstTruthy(d, "result", "final_response")},
		{"error", d["error"]}, {"failure_reason", d["failure_reason"]}, {"timestamp", ts},
	})
}

type field struct {
	k string
	v any
}

func orderedJSON(fields []field) ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('{')
	for i, f := range fields {
		if i > 0 {
			b.WriteByte(',')
		}
		k, _ := json.Marshal(f.k)
		b.Write(k)
		b.WriteByte(':')
		var v bytes.Buffer
		enc := json.NewEncoder(&v)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(f.v); err != nil {
			return nil, fatalf("task webhook body %s: %v", f.k, err)
		}
		b.Write(bytes.TrimSuffix(v.Bytes(), []byte("\n")))
	}
	b.WriteByte('}')
	return b.Bytes(), nil
}

func (w TaskWebhook) Send(ctx context.Context, s Send, message string) error {
	target, _ := s.Target.Config["url"].(string)
	if target == "" || message == "" {
		return nil
	}
	headers := http.Header{"Content-Type": {"application/json"}, EventHeader: {CanonicalType(s.Event.Type)}, DeliveryHeader: {s.Event.ID}}
	if signed, _ := s.Target.Config["signed"].(bool); signed {
		secret, ok, err := w.Secret(ctx, s.Workspace, s.Owner, WebhookSecretName(s.Event.TaskID))
		if err != nil {
			return fmt.Errorf("task webhook secret: %w", err)
		}
		if !ok || secret == "" {
			return errors.New("task webhook secret is not readable yet")
		}
		now := time.Now
		if w.Now != nil {
			now = w.Now
		}
		headers.Set(SignatureHeader, Sign(secret, []byte(message), now().Unix()))
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, bytes.NewReader([]byte(message)))
	if err != nil {
		return fatalf("unsafe task webhook url: %v", err)
	}
	req.Header = headers
	resp, err := w.Client.Do(req)
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return fatalf("unsafe task webhook url: %v", err)
		}
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return fmt.Errorf("task webhook network error: %w", err)
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	switch {
	case resp.StatusCode >= 500 || resp.StatusCode == http.StatusTooManyRequests:
		return fmt.Errorf("task webhook returned %d", resp.StatusCode)
	case resp.StatusCode >= 400:
		return fatalf("task webhook returned %d", resp.StatusCode)
	}
	return nil
}

var _ Sender = TaskWebhook{}
