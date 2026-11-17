package streams

import (
	"log/slog"
	"net"
	"net/http"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/polling"
)

type openClients struct{}

func (openClients) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (openClients) Dialer() netguard.Dialer                          { return &net.Dialer{} }

// The event service registered a provider at AGENTAREA_API_URL/webhooks/<id> while the API
// showed AGENTAREA_TELEGRAM_WEBHOOK_URL/webhooks/<id> when that was set: the provider posted where the
// source was not shown, and the API reported the source unregistered.
func TestPollersRegisterAtTheURLTheAPIShows(t *testing.T) {
	m := New(Deps{APIURL: "https://api.example", WebhookURL: "https://hooks.example/", Out: openClients{}})
	d := m.pollingDeps(PollerDeps{Config: polling.Config{ManagerURL: "http://m", WorkerID: "w"}, GatewaySecret: "s"}, slog.Default())
	if got := d.WebhookURL("w1"); got != "https://hooks.example/webhooks/w1" || got != m.svc.PublicWebhookURL("w1") {
		t.Fatalf("webhook url = %q", got)
	}
	m = New(Deps{APIURL: "https://api.example/", Out: openClients{}})
	d = m.pollingDeps(PollerDeps{Config: polling.Config{ManagerURL: "http://m", WorkerID: "w"}, GatewaySecret: "s"}, slog.Default())
	if got := d.WebhookURL("w1"); got != "https://api.example/webhooks/w1" {
		t.Fatalf("webhook url = %q", got)
	}
}
