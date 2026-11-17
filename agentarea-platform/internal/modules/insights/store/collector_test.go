package store

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCollectorPostsTheBatchAsJSON(t *testing.T) {
	var got []map[string]any
	status := http.StatusAccepted
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/events" || r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("%s %s", r.Method, r.URL.Path)
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.WriteHeader(status)
	}))
	defer srv.Close()
	c := Collector{URL: srv.URL, Transport: http.DefaultTransport}
	if err := c.Post(context.Background(), []map[string]any{{"event": "x"}}); err != nil || len(got) != 1 || got[0]["event"] != "x" {
		t.Fatal(got, err)
	}
	status = http.StatusBadGateway
	if err := c.Post(context.Background(), nil); err == nil {
		t.Fatal("a 502 was taken")
	}
}
