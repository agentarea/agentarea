package source

import "testing"

func TestWebhookURL(t *testing.T) {
	if got := (Source{WebhookID: "w1"}).WebhookURL("https://api.example.com"); got != "https://api.example.com/webhooks/w1" {
		t.Fatalf("got %q", got)
	}
	if got := (Source{}).WebhookURL("https://api.example.com"); got != "" {
		t.Fatalf("a poll source has a webhook URL: %q", got)
	}
}
