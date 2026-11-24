package httpx

import (
	"bytes"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A 5xx logs the error it wraps: the response shows only the public detail.
func TestServerErrorLogsWrappedCause(t *testing.T) {
	var buf bytes.Buffer
	x := NewErrors("http://api", slog.New(slog.NewJSONHandler(&buf, nil)))
	cause := fmt.Errorf("hydra advertises registration_endpoint %q: %w", "http://hydra/oauth2/register", errors.New("set client_registration_url"))
	rec := httptest.NewRecorder()
	x.Write(rec, httptest.NewRequest(http.MethodGet, "/.well-known/x", nil), HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(cause))

	if rec.Code != http.StatusBadGateway || strings.Contains(rec.Body.String(), "client_registration_url") {
		t.Fatalf("response %d %s", rec.Code, rec.Body.String())
	}
	if line := buf.String(); !strings.Contains(line, "Authorization server unavailable") || !strings.Contains(line, "set client_registration_url") {
		t.Fatalf("log line lacks the cause: %s", line)
	}
}

func TestErrorFormatsCauseOnlyWithPlusV(t *testing.T) {
	e := HTTPError(http.StatusBadGateway, "public").Wrap(errors.New("private"))
	if got := fmt.Sprintf("%v %s", e, e); got != "public public" {
		t.Fatalf("%%v/%%s = %q", got)
	}
	if got := fmt.Sprintf("%+v", e); got != "public: private" {
		t.Fatalf("%%+v = %q", got)
	}
	if got := fmt.Sprintf("%+v", HTTPError(http.StatusBadGateway, "alone")); got != "alone" {
		t.Fatalf("%%+v without a cause = %q", got)
	}
}
