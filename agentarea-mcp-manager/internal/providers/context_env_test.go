package providers

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/mcpcontext"
	"github.com/agentarea/mcp-manager/internal/models"
)

func contextInstance() *models.MCPServerInstance {
	return &models.MCPServerInstance{
		InstanceID: "inst-1", WorkspaceID: "ws-1",
		JSONSpec: map[string]any{
			"type":        "docker",
			"image":       "ghcr.io/acme/app:1",
			"port":        8080.0,
			"context":     map[string]any{"enabled": true},
			"environment": map[string]any{"APP_MODE": "prod", "MCP_CONTEXT_KEY": "spoofed"},
		},
	}
}

func TestProvidersInjectTheDerivedContextKey(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	want := mcpcontext.Key(storageSecret, "inst-1")

	manager := &capturingContainerManager{}
	docker := NewDockerProvider(nil, manager, storageIssuer(), logger)
	docker.SetContextIssuer(mcpcontext.NewIssuer(storageSecret))
	if err := docker.CreateInstance(context.Background(), contextInstance()); err != nil {
		t.Fatalf("docker CreateInstance() error = %v", err)
	}
	if got := manager.spec["environment"].(map[string]any)["MCP_CONTEXT_KEY"]; got != want {
		t.Fatalf("docker MCP_CONTEXT_KEY = %v, want the derived key", got)
	}

	backend := &capturingBackend{}
	provider := NewBackendProvider(backend, nil, storageIssuer(), logger)
	provider.SetContextIssuer(mcpcontext.NewIssuer(storageSecret))
	if err := provider.CreateInstance(context.Background(), contextInstance()); err != nil {
		t.Fatalf("backend CreateInstance() error = %v", err)
	}
	if got := backend.spec.Environment["MCP_CONTEXT_KEY"]; got != want {
		t.Fatalf("backend MCP_CONTEXT_KEY = %q, want the derived key", got)
	}
	if backend.spec.Environment["APP_MODE"] != "prod" {
		t.Fatalf("the spec's own environment was dropped: %v", backend.spec.Environment)
	}
}

func TestAnOptedInInstanceWithoutAContextIssuerIsRefused(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	err := NewBackendProvider(&capturingBackend{}, nil, storageIssuer(), logger).CreateInstance(context.Background(), contextInstance())
	if err == nil || !strings.Contains(err.Error(), "caller context") {
		t.Fatalf("err = %v, want a refusal naming caller context", err)
	}
}
