package telegram

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

func TestGetUpdatesErrorOmitsBotToken(t *testing.T) {
	const secret = "SUPERSECRETTOKEN" // pragma: allowlist secret
	tests := []struct {
		name  string
		token string
	}{
		// net/http wraps a transport failure in a *url.Error carrying the URL.
		{name: "transport failure", token: "123456:" + secret},
		// net/url reports a URL it cannot parse in full.
		{name: "unparsable URL", token: "123456:" + secret + "\n"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := NewClient(tt.token)
			c.httpClient.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
				return nil, errors.New("connection refused")
			})

			_, err := c.GetUpdates(context.Background(), 0)
			if err == nil {
				t.Fatal("GetUpdates returned nil error")
			}
			if strings.Contains(err.Error(), secret) {
				t.Fatalf("error contains the bot token: %v", err)
			}
		})
	}
}
