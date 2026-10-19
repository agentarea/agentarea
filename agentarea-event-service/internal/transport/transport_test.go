package transport

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/egress"
	"github.com/agentarea/event-service/internal/template"
)

func openPolicy(t *testing.T) egress.Policy {
	t.Helper()
	p, err := egress.NewPolicy(true, nil)
	if err != nil {
		t.Fatalf("NewPolicy: %v", err)
	}
	return p
}

func TestHTTPJSONReadsItemsAndAdvancesTheCursor(t *testing.T) {
	var gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.RequestURI()
		_, _ = w.Write([]byte(`{"ok": true, "result": [{"update_id": 9007199254740993, "message": {"text": "a"}}, {"update_id": 9007199254740995}]}`))
	}))
	defer server.Close()

	set := NewSet(openPolicy(t))
	tr, _ := set.Get(HTTPJSON)
	res, err := tr.Fetch(context.Background(), Fetch{
		Poll: catalog.Poll{
			Transport: HTTPJSON,
			Request:   &catalog.Request{Method: "GET", URL: server.URL + "/bot{credentials.token}/getUpdates?offset={cursor}"},
			Items:     "result",
			Cursor:    "{item:update_id}+1",
		},
		Values: template.Values{Credentials: map[string]string{"token": "1:abc"}, Cursor: "7"},
	})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if gotPath != "/bot1:abc/getUpdates?offset=7" {
		t.Fatalf("path = %q", gotPath)
	}
	if len(res.Items) != 2 || res.Cursor != "9007199254740996" {
		t.Fatalf("result = %+v", res)
	}
	encoded, _ := json.Marshal(res.Items[0])
	if !strings.Contains(string(encoded), "9007199254740993") {
		t.Fatalf("a big id lost precision: %s", encoded)
	}
}

func TestHTTPJSONWithNothingNewKeepsTheCursor(t *testing.T) {
	res, err := ReadItems([]byte(`{"result": []}`), "result", "{item:update_id}+1")
	if err != nil || len(res.Items) != 0 || res.Cursor != "" {
		t.Fatalf("result = %+v, err = %v", res, err)
	}
}

func TestHTTPJSONRefusesAnAnswerWithoutTheItemsList(t *testing.T) {
	if _, err := ReadItems([]byte(`{"error": "x"}`), "result", ""); err == nil {
		t.Fatal("read items from an answer that has none")
	}
}

func TestACallErrorDoesNotLeakTheURL(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"description": "Unauthorized"}`))
	}))
	defer server.Close()

	_, err := NewCaller(openPolicy(t)).Call(context.Background(),
		catalog.Request{URL: server.URL + "/botSECRET/getUpdates"}, template.Values{})
	if err == nil || strings.Contains(err.Error(), "SECRET") || !strings.Contains(err.Error(), "401") {
		t.Fatalf("err = %v", err)
	}
}

func TestACallWithAMissingCredentialIsNotSent(t *testing.T) {
	_, err := NewCaller(openPolicy(t)).Call(context.Background(),
		catalog.Request{URL: "https://api.example.com/bot{credentials.token}"}, template.Values{})
	if !errors.Is(err, template.ErrMissing) {
		t.Fatalf("err = %v, want ErrMissing", err)
	}
}

func TestACallRendersAJSONBody(t *testing.T) {
	var got map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&got)
	}))
	defer server.Close()

	_, err := NewCaller(openPolicy(t)).Call(context.Background(), catalog.Request{
		Method: "POST", URL: server.URL,
		JSON: map[string]any{"url": "{webhook_url}", "max": 5},
	}, template.Values{WebhookURL: "https://api.example.com/webhooks/w1"})
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	if got["url"] != "https://api.example.com/webhooks/w1" || got["max"] != float64(5) {
		t.Fatalf("body = %v", got)
	}
}

func TestMCPEventsIsNotBuilt(t *testing.T) {
	tr, err := NewSet(openPolicy(t)).Get(MCPEvents)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if _, err := tr.Fetch(context.Background(), Fetch{}); !errors.Is(err, ErrMCPEventsNotBuilt) {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUnknownTransportIsRefused(t *testing.T) {
	if _, err := NewSet(openPolicy(t)).Get("carrier_pigeon"); err == nil {
		t.Fatal("got a transport that does not exist")
	}
}
