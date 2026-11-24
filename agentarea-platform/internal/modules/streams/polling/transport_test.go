package polling

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// openClients reaches any address, as a deployment that allows private ones does.
type openClients struct{}

func (openClients) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (openClients) Dialer() netguard.Dialer                          { return &net.Dialer{} }

func openTransports() Transports {
	return NewTransports(NewCaller(openClients{}), openClients{}.Dialer().DialContext, nil)
}

func TestMemberHostIsAHostWithAPlaceholder(t *testing.T) {
	for tmpl, want := range map[string]bool{
		"https://api.telegram.org/bot{credentials.bot_token}/getUpdates": false,
		"{config.url}":                    true,
		"https://{config.host}/feed":      true,
		"https://example.com/?q={cursor}": false,
	} {
		if MemberHost(tmpl) != want {
			t.Errorf("MemberHost(%q) = %v", tmpl, !want)
		}
	}
}

func TestHTTPJSONReadsItemsAndAdvancesTheCursor(t *testing.T) {
	var gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.RequestURI()
		_, _ = w.Write([]byte(`{"ok": true, "result": [{"update_id": 9007199254740993, "message": {"text": "a"}}, {"update_id": 9007199254740995}]}`))
	}))
	defer server.Close()

	set := openTransports()
	tr, _ := set.Get(HTTPJSON)
	res, err := tr.Fetch(context.Background(), Fetch{
		Poll: Poll{
			Transport: HTTPJSON,
			Request:   &Request{Method: "GET", URL: server.URL + "/bot{credentials.token}/getUpdates?offset={cursor}"},
			Items:     "result",
			Cursor:    "{item:update_id}+1",
		},
		Values: Values{Credentials: map[string]string{"token": "1:abc"}, Cursor: "7"},
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

	_, err := NewCaller(openClients{}).Call(context.Background(),
		Request{URL: server.URL + "/botSECRET/getUpdates"}, Values{})
	if err == nil || strings.Contains(err.Error(), "SECRET") || !strings.Contains(err.Error(), "401") {
		t.Fatalf("err = %v", err)
	}
}

func TestACallWithAMissingCredentialIsNotSent(t *testing.T) {
	_, err := NewCaller(openClients{}).Call(context.Background(),
		Request{URL: "https://api.example.com/bot{credentials.token}"}, Values{})
	if !errors.Is(err, ErrMissing) {
		t.Fatalf("err = %v, want ErrMissing", err)
	}
}

func TestACallRendersAJSONBody(t *testing.T) {
	var got map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&got)
	}))
	defer server.Close()

	_, err := NewCaller(openClients{}).Call(context.Background(), Request{
		Method: "POST", URL: server.URL,
		JSON: map[string]any{"url": "{webhook_url}", "max": 5},
	}, Values{WebhookURL: "https://api.example.com/webhooks/w1"})
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	if got["url"] != "https://api.example.com/webhooks/w1" || got["max"] != float64(5) {
		t.Fatalf("body = %v", got)
	}
}

func TestAnUnknownTransportIsRefused(t *testing.T) {
	if _, err := openTransports().Get("carrier_pigeon"); err == nil {
		t.Fatal("got a transport that does not exist")
	}
}
