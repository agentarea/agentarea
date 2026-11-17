package app

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestMCPRefusesMissingRuntimeConfiguration(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(dbVars)
	err := b.Run(context.Background(), []string{"mcp"})
	if err == nil || errors.Is(err, ErrNotImplemented) || b.exitCode(err) != 1 {
		t.Fatalf("got %v", err)
	}
	for _, name := range []string{"AGENTAREA_MCP_GATEWAY_SECRET", "AGENTAREA_MCP_LEASE_TTL", "AGENTAREA_MCP_IDLE_TIMEOUT"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error does not name %s: %v", name, err)
		}
	}
}

func TestMCPHostRefusesTheDataPlaneBackend(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(map[string]string{"AGENTAREA_MCP_MODE": "dataplane", "AGENTAREA_MCP_BACKEND": "dataplane"})
	err := b.Run(context.Background(), []string{"mcp"})
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_MCP_BACKEND") {
		t.Fatalf("got %v", err)
	}
}
