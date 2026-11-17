package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestErrorBodyStaysJSONWhenTheMessageCarriesAQuote(t *testing.T) {
	r := httptest.NewRequest(http.MethodPost, "/workspace/writeback", strings.NewReader(`{"bo\"gus": 1}`))
	w := httptest.NewRecorder()
	workspaceWritebackHandler(w, r)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", w.Code, w.Body.String())
	}
	var body struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("error body is not JSON: %v: %s", err, w.Body.String())
	}
	if !strings.Contains(body.Error, `unknown field "bo\"gus"`) {
		t.Fatalf("error = %q", body.Error)
	}
}
