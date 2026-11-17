package delivery

import (
	"context"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// The Standard Webhooks reference vector.
func TestSignMatchesStandardWebhooks(t *testing.T) {
	sig, err := Sign("whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, []byte(`{"test": 2432232314}`))
	if err != nil || sig != "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=" {
		t.Fatalf("sig = %q, err = %v", sig, err)
	}
	if _, err := Sign("whsec_not base64!", "m", 1, nil); err == nil {
		t.Fatal("signed with a secret that is not base64")
	}
}

func TestEncodeBodyIsCompactAndKeepsNonASCII(t *testing.T) {
	raw, err := EncodeBody(map[string]any{"a": "<привет>", "b": 1})
	if err != nil || string(raw) != `{"a":"<привет>","b":1}` {
		t.Fatalf("raw = %s, err = %v", raw, err)
	}
}

type open struct{}

func (open) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (open) Dialer() netguard.Dialer                          { return &net.Dialer{} }

func TestAPostIsSignedAndItsAnswerCategorized(t *testing.T) {
	var got http.Header
	var body []byte
	status := http.StatusOK
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Clone()
		body, _ = io.ReadAll(r.Body)
		if status == http.StatusFound {
			http.Redirect(w, r, "/elsewhere", status)
			return
		}
		w.WriteHeader(status)
	}))
	defer srv.Close()
	at := time.Unix(1614265330, 0)
	ep := NewEndpoint(open{}, func() time.Time { return at }, slog.Default())
	ctx := context.Background()

	out, err := ep.Post(ctx, srv.URL, "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "sub_1", "msg_1", map[string]any{"x": 1})
	if err != nil || out != (Outcome{}) {
		t.Fatalf("out = %+v, err = %v", out, err)
	}
	want, _ := Sign("whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "msg_1", 1614265330, body)
	if got.Get("webhook-id") != "msg_1" || got.Get("webhook-timestamp") != "1614265330" || got.Get("webhook-signature") != want ||
		got.Get(SubscriptionHeader) != "sub_1" || got.Get("Content-Type") != "application/json" || string(body) != `{"x":1}` {
		t.Fatalf("headers = %v, body = %s", got, body)
	}
	for code, want := range map[int]Outcome{
		http.StatusGone:                  {Error: "http_4xx", Final: true},
		http.StatusRequestEntityTooLarge: {Error: "http_4xx", Final: true},
		http.StatusNotFound:              {Error: "http_4xx"},
		http.StatusFound:                 {Error: "http_4xx"},
		http.StatusBadGateway:            {Error: "http_5xx"},
	} {
		status = code
		if out, _ := ep.Post(ctx, srv.URL, "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "s", "m", map[string]any{}); out != want {
			t.Errorf("%d: out = %+v, want %+v", code, out, want)
		}
	}
	srv.Close()
	if out, _ := ep.Post(ctx, srv.URL, "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "s", "m", map[string]any{}); out.Error != "connection_refused" {
		t.Fatalf("closed server: %+v", out)
	}
}
