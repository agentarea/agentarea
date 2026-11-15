package transport

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
)

// stallingServer answers with headers and the given first bytes, then sends
// nothing until the client goes away; headersFirst=false holds the headers too.
func stallingServer(t *testing.T, headersFirst bool, first string) *httptest.Server {
	t.Helper()
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if headersFirst {
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			_, _ = io.WriteString(w, first)
			w.(http.Flusher).Flush()
		}
		select {
		case <-r.Context().Done():
		case <-release:
		}
	}))
	t.Cleanup(srv.Close)
	t.Cleanup(func() { close(release) })
	return srv
}

func TestAnIdleReadPastTheTimeoutIsAReadTimeout(t *testing.T) {
	srv := stallingServer(t, true, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n")
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Timeout = 200 * time.Millisecond

	start := time.Now()
	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Errorf("took %v", elapsed)
	}
	var te *TransportError
	if !errors.As(err, &te) {
		t.Fatalf("err = %v", err)
	}
	if !te.Timeout || te.Kind != "ReadTimeout" || PyType(err) != "ReadTimeout" {
		t.Errorf("transport error = %+v", te)
	}
	if o.content != "a" {
		t.Errorf("content before the stall = %q", o.content)
	}
	if f, ok := Classify(err); !ok || f.Cause != "timeout" || !f.Retryable {
		t.Errorf("Classify = %+v, %v", f, ok)
	}
}

func TestEachByteRestartsTheIdleTimer(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(200)
		for range 4 {
			_, _ = io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n")
			w.(http.Flusher).Flush()
			time.Sleep(120 * time.Millisecond)
		}
	}))
	t.Cleanup(srv.Close)
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Timeout = 300 * time.Millisecond

	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if err != nil || o.content != "aaaa" {
		t.Errorf("content, err = %q, %v", o.content, err)
	}
}

func TestWaitingForTheResponseHeadersIsAReadTimeout(t *testing.T) {
	srv := stallingServer(t, false, "")
	m := claude(t, srv.URL)
	m.Timeout = 200 * time.Millisecond

	_, err := runStream(context.Background(), m, Request{Messages: userHi()})
	var te *TransportError
	if !errors.As(err, &te) || !te.Timeout {
		t.Fatalf("err = %v", err)
	}
	if te.Kind != "ReadTimeout" {
		t.Errorf("differs from Python: httpx raises ReadTimeout while waiting for the response headers, Go reports %s", te.Kind)
	}
}

func TestCancellingTheContextEndsTheStream(t *testing.T) {
	srv := stallingServer(t, true, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	m := openAIModel(t, srv.URL, domain.Profile{})

	err := m.Stream(ctx, Request{Messages: userHi()}, func(Delta) error {
		cancel()
		return nil
	})
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v", err)
	}
	var te *TransportError
	if errors.As(err, &te) {
		t.Errorf("a cancel is reported as a transport failure: %+v", te)
	}
}

func TestACancelledContextNeverReachesTheProvider(t *testing.T) {
	srv, c := serveRaw(t, 200, openAISSE())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := runStream(ctx, claude(t, srv.URL), Request{Messages: userHi()})
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v", err)
	}
	if hits, _, _, _ := c.snapshot(); hits != 0 {
		t.Error("the provider was called")
	}
}

func TestARefusedConnectionIsAConnectError(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	url := srv.URL
	srv.Close()

	_, err := runStream(context.Background(), openAIModel(t, url, domain.Profile{}), Request{Messages: userHi()})
	var te *TransportError
	if !errors.As(err, &te) || te.Kind != "ConnectError" || te.Timeout {
		t.Fatalf("err = %v", err)
	}
	if f, ok := Classify(err); !ok || f.Cause != "provider_unavailable" || !f.Retryable {
		t.Errorf("Classify = %+v, %v", f, ok)
	}
}
