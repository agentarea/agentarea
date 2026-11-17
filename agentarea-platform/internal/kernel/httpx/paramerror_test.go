package httpx

import (
	"errors"
	"io"
	"log/slog"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

type InvalidParamFormatError struct {
	ParamName string
	Err       error
}

func (e *InvalidParamFormatError) Error() string { return "Invalid format for parameter " + e.ParamName }

type RequiredParamError struct{ ParamName string }

func (e *RequiredParamError) Error() string { return "Query argument " + e.ParamName + " is required" }

func TestGeneratedParamErrorsAre422(t *testing.T) {
	x := NewErrors("http://api.example", slog.New(slog.NewTextHandler(io.Discard, nil)))
	_, convErr := strconv.Atoi("null")
	for _, c := range []struct {
		url  string
		err  error
		want string
	}{
		{"/v1/x?hours=null", &InvalidParamFormatError{ParamName: "hours", Err: convErr}, `"loc":["query","hours"]`},
		{"/v1/x", &RequiredParamError{ParamName: "limit"}, `"type":"missing","loc":["query","limit"]`},
	} {
		w := httptest.NewRecorder()
		x.Write(w, httptest.NewRequest("GET", c.url, nil), c.err)
		body := w.Body.String()
		if w.Code != 422 || !strings.Contains(body, c.want) {
			t.Fatalf("%s: %d %s", c.url, w.Code, body)
		}
	}
	w := httptest.NewRecorder()
	x.Write(w, httptest.NewRequest("GET", "/v1/x", nil), errors.New("boom"))
	if w.Code != 500 {
		t.Fatalf("an unknown error must stay 500, got %d", w.Code)
	}
}
