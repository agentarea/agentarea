package delivery

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"net/url"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

const maxCallbackURL = 2048

// Callback is a subscriber's callback endpoint before its first delivery (webhook_endpoint.py
// check and challenge). A callback must be https, but for a development receiver: a host that
// resolves only to private addresses Guard's policy admits may be http.
type Callback struct {
	Endpoint *Endpoint
	Guard    *netguard.Guard
}

// Check refuses a callback URL that is not https or a development receiver's http.
func (c Callback) Check(ctx context.Context, raw string) error {
	invalid := func(msg string) error { return &api.EventsError{Code: api.EventsInvalidParams, Message: msg} }
	if len(raw) > maxCallbackURL {
		return invalid("delivery.url is too long")
	}
	u, err := url.Parse(raw)
	if err != nil || u.Hostname() == "" {
		return invalid("delivery.url has no host")
	}
	switch strings.ToLower(u.Scheme) {
	case "https":
		return nil
	case "http":
		if c.developmentReceiver(ctx, strings.ToLower(u.Hostname())) {
			return nil
		}
	}
	return invalid("delivery.url must be https")
}

func (c Callback) developmentReceiver(ctx context.Context, host string) bool {
	addrs, err := c.Guard.Addresses(ctx, host)
	if err != nil || len(addrs) == 0 {
		return false
	}
	for _, a := range addrs {
		if _, private := netguard.Blocked(a); !private || !c.Guard.Policy.Permits(host, a) {
			return false
		}
	}
	return true
}

// Challenge proves the endpoint wants deliveries: it must echo a one-time nonce in a 2xx body.
func (c Callback) Challenge(ctx context.Context, rawURL, secret, subscription string) error {
	nonceID, err := ControlMessageID("challenge")
	if err != nil {
		return err
	}
	messageID, err := ControlMessageID("verification")
	if err != nil {
		return err
	}
	nonce := strings.TrimPrefix(nonceID, "msg_challenge_")
	out, answer, err := c.Endpoint.send(ctx, rawURL, secret, subscription, messageID,
		map[string]any{"type": "verification", "challenge": nonce})
	if err != nil {
		return err
	}
	if out.Error != "" {
		return &api.EventsError{Code: api.EventsCallbackError, Message: "the callback endpoint did not answer the challenge",
			Data: map[string]any{"reason": out.Error}}
	}
	var echoed struct {
		Challenge any `json:"challenge"`
	}
	if json.Unmarshal(answer, &echoed) != nil || !equalString(echoed.Challenge, nonce) {
		return &api.EventsError{Code: api.EventsCallbackError, Message: "the callback endpoint did not echo the challenge",
			Data: map[string]any{"reason": "challenge_failed"}}
	}
	return nil
}

func equalString(v any, want string) bool {
	s, ok := v.(string)
	return ok && subtle.ConstantTimeCompare([]byte(s), []byte(want)) == 1
}
