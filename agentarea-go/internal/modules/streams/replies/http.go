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
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// Send is one (event, target) a sender formats and sends.
type Send struct {
	Event     Event
	Target    Target
	Workspace scope.Workspace
	Owner     string
	// Reply is the catalog entry's reply block; set for the delivery address only.
	Reply *domain.Reply
}

// Sender formats an event for its channel and sends it. A *Fatal error is final; any other is retried.
type Sender interface {
	Format(s Send) (string, error)
	Send(ctx context.Context, s Send, message string) error
}

// Credentials reads the credentials of the source an address sends with, in the task's
// workspace; a *Fatal when there are none or they cannot be used.
type Credentials func(ctx context.Context, ws scope.Workspace, owner, credentialType, credentialKey string) (map[string]string, error)

const maxAnswer = 64 * 1024

func replyOf(s Send) (*domain.Reply, error) {
	if s.Reply == nil {
		return nil, fatalf("no reply block for %v", s.Target.Config["type"])
	}
	return s.Reply, nil
}

func credentialsOf(config map[string]any) (string, string, error) {
	kind, _ := config["credential_type"].(string)
	key, _ := config["credential_key"].(string)
	if kind == "" || key == "" {
		return "", "", fatalf("the delivery address names no source credentials")
	}
	return kind, key, nil
}

func (s Send) credentials(ctx context.Context, read Credentials) (map[string]string, error) {
	kind, key, err := credentialsOf(s.Target.Config)
	if err != nil {
		return nil, err
	}
	return read(ctx, s.Workspace, s.Owner, kind, key)
}

func formatInMarkup(s Send) (string, error) {
	reply, err := replyOf(s)
	if err != nil {
		return "", err
	}
	m, err := MarkupNamed(reply.Markup)
	if err != nil {
		return "", err
	}
	return FormatEvent(m, s.Event, s.Target.Presentation), nil
}

// HTTPReply is the one generic reply sender: the catalog entry's reply request, one HTTP call.
type HTTPReply struct {
	Credentials Credentials
	// Client calls the provider (netguard.Vendor).
	Client *http.Client
}

func (h HTTPReply) Format(s Send) (string, error) { return formatInMarkup(s) }

func (h HTTPReply) Send(ctx context.Context, s Send, message string) error {
	if message == "" {
		return nil
	}
	reply, err := replyOf(s)
	if err != nil {
		return err
	}
	kind := s.Target.Config["type"]
	req := reply.Request
	if req == nil {
		return fatalf("the %q reply block has no request", kind)
	}
	creds, err := s.credentials(ctx, h.Credentials)
	if err != nil {
		return err
	}
	m, err := MarkupNamed(reply.Markup)
	if err != nil {
		return err
	}
	target, _ := s.Target.Config["target"].(map[string]any)
	if target == nil {
		target = map[string]any{}
	}
	tc := domain.TemplateContext{Values: map[string]any{
		"credentials": creds, "target": target, "message": Limited(m, message, reply.Limit),
	}}
	endpoint, ok := domain.Render(req.URL, tc)
	if !ok {
		return fatalf("the %q reply URL cannot be filled for this task", kind)
	}
	headers, _ := domain.RenderValue(req.Headers, tc).(map[string]any)
	var missing []string
	for k := range req.Headers {
		if _, ok := headers[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		slices.Sort(missing)
		return fatalf("the %q reply headers %s cannot be filled", kind, strings.Join(missing, ", "))
	}
	var body io.Reader
	if rendered := domain.RenderValue(req.JSON, tc); req.JSON != nil && rendered != nil {
		raw, err := json.Marshal(rendered)
		if err != nil {
			return fatalf("the %q reply body is malformed: %v", kind, err)
		}
		body = bytes.NewReader(raw)
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	r, err := http.NewRequestWithContext(ctx, req.Method, endpoint, body)
	if err != nil {
		return fatalf("the %q reply request is malformed: %v", kind, err)
	}
	if body != nil {
		r.Header.Set("Content-Type", "application/json")
	}
	for k, v := range headers {
		text, _ := domain.Scalar(v)
		r.Header.Set(k, text)
	}
	resp, err := h.Client.Do(r)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return fmt.Errorf("network: %w", err)
	}
	return RaiseForReply(resp, reply.PermanentErrors)
}

// RaiseForReply is raise_for_reply: nil for a delivered reply. An answer naming one of the
// entry's permanent errors is final; past that 429 and 5xx are retried, any other 4xx is final,
// and a 2xx refusal ({"ok": false}) is retried until the attempts run out.
func RaiseForReply(resp *http.Response, permanent []string) error {
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	if !refused(resp, raw) {
		return nil
	}
	status := resp.StatusCode
	text := []rune(string(raw))
	if len(text) > 300 {
		text = text[:300]
	}
	answer := string(text)
	for _, marker := range permanent {
		if strings.Contains(answer, marker) {
			return fatalf("refused %d: %s", status, answer)
		}
	}
	switch {
	case status == http.StatusTooManyRequests:
		return fmt.Errorf("rate limited: %s", answer)
	case status >= 500 || success(status):
		return fmt.Errorf("refused %d: %s", status, answer)
	}
	return fatalf("refused %d: %s", status, answer)
}

func success(status int) bool { return status >= 200 && status < 300 }

func refused(resp *http.Response, raw []byte) bool {
	if !success(resp.StatusCode) {
		return true
	}
	if !strings.Contains(resp.Header.Get("Content-Type"), "json") {
		return false
	}
	var answer map[string]any
	if json.Unmarshal(raw, &answer) != nil {
		return false
	}
	ok, has := answer["ok"]
	return has && ok == false
}
