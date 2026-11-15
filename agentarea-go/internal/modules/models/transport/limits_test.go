package transport

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
)

// endlessServer writes prefix, then piece every pause until the client goes away.
func endlessServer(t *testing.T, prefix, piece string, pause time.Duration) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, prefix)
		for r.Context().Err() == nil {
			if _, err := io.WriteString(w, piece); err != nil {
				return
			}
			w.(http.Flusher).Flush()
			if pause > 0 {
				time.Sleep(pause)
			}
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func assertTooLarge(t *testing.T, err error) {
	t.Helper()
	if PyType(err) != "ResponseTooLarge" || !strings.Contains(err.Error(), "exceeded") {
		t.Fatalf("err = %v (%s)", err, PyType(err))
	}
	var app *durable.ApplicationError
	if !errors.As(CallFailure(err), &app) || !app.NonRetryable {
		t.Fatalf("an oversized answer is retried: %+v", app)
	}
}

func TestALineWithoutEndIsCut(t *testing.T) {
	srv := endlessServer(t, "data: ", strings.Repeat("a", 64<<10), 0)
	m := openAIModel(t, srv.URL, domain.Profile{})
	_, err := runStream(context.Background(), m, Request{Messages: userHi()})
	assertTooLarge(t, err)
}

func TestAnAnswerPastTheBodyLimitIsCut(t *testing.T) {
	srv := endlessServer(t, "", "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n", 0)
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.BodyLimit = 1 << 20
	o, err := runStream(context.Background(), m, Request{Messages: userHi()})
	assertTooLarge(t, err)
	if len(o.content) == 0 || len(o.content) > 1<<20 {
		t.Fatalf("content before the cut: %d bytes", len(o.content))
	}
}

func TestACallPastItsDeadlineEndsWhileBytesStillArrive(t *testing.T) {
	srv := endlessServer(t, "", "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n", 20*time.Millisecond)
	m := openAIModel(t, srv.URL, domain.Profile{})
	m.Deadline = 300 * time.Millisecond
	start := time.Now()
	_, err := runStream(context.Background(), m, Request{Messages: userHi()})
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("took %v", elapsed)
	}
	var te *TransportError
	if !errors.As(err, &te) || te.Kind != "ReadTimeout" || !strings.Contains(err.Error(), "deadline") {
		t.Fatalf("err = %v", err)
	}
}

func TestTheDefaultsBoundEveryCall(t *testing.T) {
	if CallDeadline <= 0 || CallDeadline > 30*time.Minute || StreamBodyLimit <= 0 || StreamBodyLimit > 256<<20 || LineLimit <= 0 || LineLimit > StreamBodyLimit {
		t.Fatalf("CallDeadline %v, StreamBodyLimit %d, LineLimit %d", CallDeadline, StreamBodyLimit, LineLimit)
	}
}
