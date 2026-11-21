package delivery

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// SubscriptionHeader names the subscription a delivery is for (SEP-3415).
const SubscriptionHeader = "X-MCP-Subscription-Id"

const (
	postTimeout  = 10 * time.Second
	secretPrefix = "whsec_" // pragma: allowlist secret
	maxAnswer    = 64 * 1024
)

// Outcome is a POST's result: Error is "" on a 2xx, else one of the SEP's lastError
// categories (timeout, tls_error, connection_refused, http_4xx, http_5xx), never the answer.
type Outcome struct {
	Error string
	// Final is an answer a retry would not change (410, 413).
	Final bool
}

// Poster sends one signed delivery.
type Poster interface {
	Post(ctx context.Context, url, secret, subscription, messageID string, body any) (Outcome, error)
}

// Endpoint posts to subscriber callbacks through the member-address client: every hop
// vetted and pinned, no redirects (webhook_endpoint.py).
type Endpoint struct {
	client *http.Client
	now    func() time.Time
	log    *slog.Logger
}

// NewEndpoint builds an Endpoint over out's member transport.
func NewEndpoint(out netguard.Clients, now func() time.Time, log *slog.Logger) *Endpoint {
	return &Endpoint{
		client: &http.Client{
			Transport:     out.Transport(netguard.Member),
			Timeout:       postTimeout,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
		now: now,
		log: log,
	}
}

// Post sends body signed by Standard Webhooks; a fresh timestamp and signature each time. The
// error is a secret that cannot sign, which no retry fixes.
func (e *Endpoint) Post(ctx context.Context, url, secret, subscription, messageID string, body any) (Outcome, error) {
	out, _, err := e.send(ctx, url, secret, subscription, messageID, body)
	return out, err
}

// send is Post that also returns a 2xx answer's body.
func (e *Endpoint) send(ctx context.Context, url, secret, subscription, messageID string, body any) (Outcome, []byte, error) {
	raw, err := EncodeBody(body)
	if err != nil {
		return Outcome{}, nil, err
	}
	ts := e.now().Unix()
	sig, err := Sign(secret, messageID, ts, raw)
	if err != nil {
		return Outcome{}, nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		e.log.WarnContext(ctx, "callback of subscription is not a URL", "subscription", subscription, "error", netguard.SafeURLError(err))
		return Outcome{Error: "connection_refused"}, nil, nil
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("webhook-id", messageID)
	req.Header.Set("webhook-timestamp", strconv.FormatInt(ts, 10))
	req.Header.Set("webhook-signature", sig)
	req.Header.Set(SubscriptionHeader, subscription)
	resp, err := e.client.Do(req)
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			e.log.WarnContext(ctx, "callback of subscription points where the policy refuses", "subscription", subscription)
			return Outcome{Error: "connection_refused"}, nil, nil
		}
		e.log.WarnContext(ctx, "POST to the callback of subscription failed", "subscription", subscription, "error", netguard.SafeURLError(err))
		return Outcome{Error: category(err)}, nil, nil
	}
	answer, _ := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	switch {
	case resp.StatusCode >= 200 && resp.StatusCode < 300:
		return Outcome{}, answer, nil
	case resp.StatusCode < 500:
		return Outcome{Error: "http_4xx", Final: resp.StatusCode == http.StatusGone || resp.StatusCode == http.StatusRequestEntityTooLarge}, nil, nil
	default:
		return Outcome{Error: "http_5xx"}, nil, nil
	}
}

func category(err error) string {
	var ne net.Error
	if errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &ne) && ne.Timeout()) {
		return "timeout"
	}
	var (
		rec     tls.RecordHeaderError
		alert   tls.AlertError
		verify  *tls.CertificateVerificationError
		unknown x509.UnknownAuthorityError
		host    x509.HostnameError
		invalid x509.CertificateInvalidError
	)
	if errors.As(err, &rec) || errors.As(err, &alert) || errors.As(err, &verify) ||
		errors.As(err, &unknown) || errors.As(err, &host) || errors.As(err, &invalid) {
		return "tls_error"
	}
	return "connection_refused"
}

// Sign is webhook-signature: "v1," and the base64 HMAC-SHA256 over "id.timestamp.body", keyed by
// the secret's bytes (base64 after the whsec_ prefix).
func Sign(secret, messageID string, timestamp int64, body []byte) (string, error) {
	key, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(secret, secretPrefix))
	if err != nil {
		return "", fmt.Errorf("the subscriber's secret is not base64: %w", err)
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(messageID + "." + strconv.FormatInt(timestamp, 10) + "."))
	mac.Write(body)
	return "v1," + base64.StdEncoding.EncodeToString(mac.Sum(nil)), nil
}

// EncodeBody is json.dumps(body, separators=(",", ":"), ensure_ascii=False).
func EncodeBody(body any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(body); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// ControlMessageID is a control message's id: msg_<kind>_ and 24 random hex digits.
func ControlMessageID(kind string) (string, error) {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return "msg_" + kind + "_" + hex.EncodeToString(b[:]), nil
}
