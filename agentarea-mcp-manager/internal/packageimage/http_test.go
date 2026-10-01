package packageimage

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/mcpgateway"
	"github.com/agentarea/mcp-manager/internal/models"
)

type missingImportRepository struct{}

func (missingImportRepository) LoadInstance(_ context.Context, _ string) (*models.MCPServerInstance, error) {
	return nil, mcpgateway.ErrInstanceNotFound
}

func TestServeHTTPUsesGatewayAuthorizationAndNotFoundStatus(t *testing.T) {
	service, err := NewService(Options{
		Repository: missingImportRepository{},
		Backend:    &importTestBackend{},
		AuthSecret: strings.Repeat("a", 32),
		Logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
	})
	if err != nil {
		t.Fatal(err)
	}
	unauthorized := httptest.NewRequest(http.MethodPost, "/packages/import", strings.NewReader(`{"instance_id":"x"}`))
	unauthorizedRecorder := httptest.NewRecorder()
	service.ServeHTTP(unauthorizedRecorder, unauthorized)
	if unauthorizedRecorder.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status = %d", unauthorizedRecorder.Code)
	}

	authorized := httptest.NewRequest(http.MethodPost, "/packages/import", strings.NewReader(`{"instance_id":"x"}`))
	authorized.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+strings.Repeat("a", 32))
	authorizedRecorder := httptest.NewRecorder()
	service.ServeHTTP(authorizedRecorder, authorized)
	if authorizedRecorder.Code != http.StatusNotFound {
		t.Fatalf("authorized status = %d", authorizedRecorder.Code)
	}
}
