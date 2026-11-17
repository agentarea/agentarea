package delivery

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

type hosts map[string][]netip.Addr

func (h hosts) LookupNetIP(_ context.Context, _, host string) ([]netip.Addr, error) {
	if a, ok := h[host]; ok {
		return a, nil
	}
	return nil, errors.New("no such host")
}

func callback(t *testing.T, allowlist ...string) Callback {
	t.Helper()
	policy, err := netguard.NewAddressPolicy(false, allowlist)
	if err != nil {
		t.Fatal(err)
	}
	return Callback{
		Endpoint: NewEndpoint(open{}, time.Now, slog.Default()),
		Guard: &netguard.Guard{Policy: policy, Resolver: hosts{
			"dev.local":  {netip.MustParseAddr("10.0.0.5")},
			"mixed.test": {netip.MustParseAddr("10.0.0.5"), netip.MustParseAddr("8.8.8.8")},
		}},
	}
}

func eventsErr(t *testing.T, err error) *api.EventsError {
	t.Helper()
	var e *api.EventsError
	if !errors.As(err, &e) {
		t.Fatalf("err = %v, want an events error", err)
	}
	return e
}

func TestCheckAdmitsHTTPSAndADevelopmentReceiver(t *testing.T) {
	ctx := context.Background()
	strict := callback(t)
	dev := callback(t, "10.0.0.0/8")
	for _, ok := range []string{"https://hook.example/x", "HTTPS://hook.example"} {
		if err := strict.Check(ctx, ok); err != nil {
			t.Fatalf("%s: %v", ok, err)
		}
	}
	if err := dev.Check(ctx, "http://dev.local:8080/hook"); err != nil {
		t.Fatalf("development receiver: %v", err)
	}
	for url, msg := range map[string]string{
		"http://dev.local/hook": "delivery.url must be https",
		"http://hook.example/x": "delivery.url must be https",
		"ftp://hook.example/x":  "delivery.url must be https",
		"https:///x":            "delivery.url has no host",
		"https://hook.example/" + strings.Repeat("a", 2048): "delivery.url is too long",
	} {
		if e := eventsErr(t, strict.Check(ctx, url)); e.Code != api.EventsInvalidParams || e.Message != msg {
			t.Fatalf("%s: %+v", url[:min(len(url), 40)], e)
		}
	}
	for _, url := range []string{"http://mixed.test/x", "http://8.8.8.8/x", "http://unknown.test/x"} {
		if e := eventsErr(t, dev.Check(ctx, url)); e.Message != "delivery.url must be https" {
			t.Fatalf("%s: %+v", url, e)
		}
	}
}

func TestChallengeWantsTheNonceEchoed(t *testing.T) {
	answer := "echo"
	var sent map[string]any
	var headers http.Header
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &sent)
		headers = r.Header.Clone()
		switch answer {
		case "echo":
			_ = json.NewEncoder(w).Encode(map[string]any{"challenge": sent["challenge"]})
		case "wrong":
			_, _ = w.Write([]byte(`{"challenge":"nope"}`))
		case "list":
			_, _ = w.Write([]byte(`[1]`))
		default:
			w.WriteHeader(http.StatusInternalServerError)
		}
	}))
	defer srv.Close()
	cb := callback(t)
	ctx := context.Background()
	secret := "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
	if err := cb.Challenge(ctx, srv.URL, secret, "sub_1"); err != nil {
		t.Fatal(err)
	}
	nonce, _ := sent["challenge"].(string)
	if sent["type"] != "verification" || len(nonce) != 24 || !strings.HasPrefix(headers.Get("webhook-id"), "msg_verification_") ||
		headers.Get(SubscriptionHeader) != "sub_1" {
		t.Fatalf("sent %v %v", sent, headers)
	}
	for kind, want := range map[string]map[string]any{
		"wrong": {"reason": "challenge_failed"},
		"list":  {"reason": "challenge_failed"},
		"fail":  {"reason": "http_5xx"},
	} {
		answer = kind
		e := eventsErr(t, cb.Challenge(ctx, srv.URL, secret, "sub_1"))
		if e.Code != api.EventsCallbackError || e.Data["reason"] != want["reason"] {
			t.Fatalf("%s: %+v", kind, e)
		}
	}
	answer = "fail"
	if e := eventsErr(t, cb.Challenge(ctx, srv.URL, secret, "sub_1")); e.Message != "the callback endpoint did not answer the challenge" {
		t.Fatalf("message %q", e.Message)
	}
	answer = "wrong"
	if e := eventsErr(t, cb.Challenge(ctx, srv.URL, secret, "sub_1")); e.Message != "the callback endpoint did not echo the challenge" {
		t.Fatalf("message %q", e.Message)
	}
}
