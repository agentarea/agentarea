package dataplane

import (
	"io"
	"log/slog"
	"net/http"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestRouteExtensionIsServedOnlyBehindAuthentication(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	server := NewServer(&Config{AgentID: "agent-1", AuthToken: testToken, ListenAddr: ":0"}, &fakeBackend{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	server.SetRouteExtension(func(group *gin.RouterGroup) {
		group.GET("/extension", func(c *gin.Context) { c.Status(http.StatusNoContent) })
	})
	server.Routes(router)
	for _, token := range []string{"", "wrong-token"} {
		if response := request(t, router, http.MethodGet, "/dataplane/v1/extension", token, nil); response.Code != http.StatusUnauthorized {
			t.Fatalf("unauthenticated extension route returned %d", response.Code)
		}
	}
	if response := request(t, router, http.MethodGet, "/dataplane/v1/extension", testToken, nil); response.Code != http.StatusNoContent {
		t.Fatalf("authenticated extension route returned %d", response.Code)
	}
}

func TestCoreDataPlaneServesNoUsageRoute(t *testing.T) {
	if response := request(t, newTestServer(&fakeBackend{}), http.MethodGet, "/dataplane/v1/usage", testToken, nil); response.Code != http.StatusNotFound {
		t.Fatalf("core data plane usage route returned %d", response.Code)
	}
}
