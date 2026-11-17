package app

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable/temporal"
)

func TestEventsRefusesMissingPollerConfiguration(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(dbVars)
	err := b.Run(context.Background(), []string{"events"})
	if err == nil || errors.Is(err, ErrNotImplemented) || b.exitCode(err) != 1 {
		t.Fatalf("got %v", err)
	}
	for _, name := range []string{"AGENTAREA_MCP_MANAGER_URL", "AGENTAREA_MCP_GATEWAY_SECRET"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error does not name %s: %v", name, err)
		}
	}
}

func TestEventsRefusesAMalformedPollInterval(t *testing.T) {
	b, _ := quiet()
	vars := map[string]string{"AGENTAREA_EVENT_POLL_INTERVAL": "five"}
	for k, v := range dbVars {
		vars[k] = v
	}
	b.lookup = mapLookup(vars)
	if err := b.Run(context.Background(), []string{"events"}); err == nil || !strings.Contains(err.Error(), "AGENTAREA_EVENT_POLL_INTERVAL") {
		t.Fatalf("got %v", err)
	}
}

// roleVars are serveVars plus what the events part reads.
func roleVars() map[string]string {
	vars := map[string]string{"HOST": "127.0.0.1", "PORT": "0", "AGENTAREA_MCP_MANAGER_URL": "http://127.0.0.1:1"}
	for k, v := range serveVars {
		vars[k] = v
	}
	return vars
}

// Every role builds the whole module set with every port implemented. Against
// nothing listening the Temporal workers and the Redis consumers fail loud on
// their first dial (the stack suite runs them for real); serve, which dials
// nothing before a request, runs until cancelled.
func TestRolesStartWithEveryPort(t *testing.T) {
	t.Setenv("TEMPORAL_ADDRESS", "127.0.0.1:1")
	t.Setenv("TEMPORAL_NAMESPACE", "default")
	for _, role := range []string{"serve", "worker", "events", "all"} {
		b, out := quiet()
		b.lookup = mapLookup(roleVars())
		ctx, cancel := context.WithTimeout(context.Background(), 2*temporal.NamespaceDescribeTimeout)
		err := b.Run(ctx, []string{role})
		cancel()
		switch {
		case role == "serve" && err != nil:
			t.Errorf("serve: %v\n%s", err, out)
		case role != "serve" && (err == nil || (!strings.Contains(err.Error(), "connection refused") && !strings.Contains(err.Error(), "server unreachable"))):
			t.Errorf("%s: want a dial failure, got %v\n%s", role, err, out)
		}
	}
}
