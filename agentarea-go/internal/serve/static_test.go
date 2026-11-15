package serve

import (
	"net/http"
	"strings"
	"testing"
)

func TestStaticServesTheIconsTheAPIPointsAt(t *testing.T) {
	s := edge(t, Options{})
	for _, p := range []string{"/static/icons/agentarea.svg", "/static/icons/providers/openai.svg",
		"/static/icons/providers/default.svg", "/static/icons/channels/telegram.svg"} {
		resp, body := call(t, http.MethodGet, s.URL+p)
		if resp.StatusCode != http.StatusOK || resp.Header.Get("Content-Type") != "image/svg+xml" || !strings.Contains(body, "<svg") {
			t.Errorf("%s: %d %q", p, resp.StatusCode, resp.Header.Get("Content-Type"))
		}
	}
	if resp, _ := call(t, http.MethodHead, s.URL+"/static/icons/agentarea.svg"); resp.StatusCode != http.StatusOK {
		t.Errorf("HEAD: %d", resp.StatusCode)
	}
	for _, p := range []string{"/static/icons/providers/nope.svg", "/static/icons/providers", "/static/icons/providers/",
		"/static/", "/static/../serve.go", "/static/icons/%2e%2e/static.go"} {
		if resp, _ := call(t, http.MethodGet, s.URL+p); resp.StatusCode != http.StatusNotFound {
			t.Errorf("%s: %d", p, resp.StatusCode)
		}
	}
}
