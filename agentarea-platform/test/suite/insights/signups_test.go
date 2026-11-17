//go:build suite

package insights

import (
	"net/http"
	"strings"
	"testing"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// The suite sets no AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY: the Kratos hook does not exist.
func TestSignupHookWithoutAKeyIsNotFound(t *testing.T) {
	h.Anonymous(t).Do(t, h.Request{Method: http.MethodPost, Path: "/internal/analytics/signups",
		Body: map[string]any{"identity_id": "x", "created_at": "2026-11-17T10:00:00Z"}}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "http_error", "Not Found"))
}

// The served spec and the docs pages are FastAPI's: the webapp's generate:openapi reads the spec.
func TestOpenAPISpecAndDocsAreServed(t *testing.T) {
	spec := h.Anonymous(t).Get(t, "/openapi.json").Expect(http.StatusOK).Object()
	paths, _ := spec["paths"].(map[string]any)
	if _, ok := paths["/v1/workspaces/{workspace}/dashboard"]; !ok {
		t.Fatalf("the spec has no dashboard path: %d paths", len(paths))
	}
	for _, path := range []string{"/docs", "/redoc", "/docs/oauth2-redirect"} {
		r := h.Anonymous(t).Get(t, path).Expect(http.StatusOK)
		if !strings.HasPrefix(r.ContentType(), "text/html") {
			t.Errorf("%s: %s", path, r.ContentType())
		}
	}
}
