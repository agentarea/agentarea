package netguard

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

func TestSafeURLKeepsNoCredentials(t *testing.T) {
	for raw, want := range map[string]string{
		"https://u:p@mcp.example/sse?token=s3cret#frag": "https://mcp.example/sse",
		"http://127.0.0.1:8080/mcp?":                    "http://127.0.0.1:8080/mcp",
		"https://api.example/v1/chat":                   "https://api.example/v1/chat",
		"::not a url":                                   "<unparsable URL>",
	} {
		if got := SafeURL(raw); got != want {
			t.Errorf("SafeURL(%q) = %q, want %q", raw, got, want)
		}
	}
}

func TestSafeURLErrorScrubsTheWrappedURL(t *testing.T) {
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, "http://127.0.0.1:1/x?api_key=s3cret", nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = http.DefaultClient.Do(req)
	wrapped := SafeURLError(errors.Join(errors.New("upstream"), err))
	if wrapped == nil || strings.Contains(wrapped.Error(), "s3cret") {
		t.Fatalf("SafeURLError = %v, want an error without the query", wrapped)
	}
	if SafeURLError(nil) != nil {
		t.Fatal("SafeURLError(nil) != nil")
	}
}
