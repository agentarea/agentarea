package polling

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

func host() (string, error) { return "pod-1", nil }

func TestConfigDefaultsAreTheEventServices(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_MCP_MANAGER_URL": "http://mcp-manager:8000/"})
	c := LoadConfig(l, host)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Interval != 5*time.Second || c.MaxPollers != 200 || c.WorkerID != "pod-1" || c.ManagerURL != "http://mcp-manager:8000" {
		t.Fatalf("config = %+v", c)
	}
}

// The event service read a malformed AGENTAREA_EVENT_POLL_INTERVAL or MAX_POLLERS as unset and
// ran on the default; a typo went unnoticed.
func TestAMalformedPollSettingFailsStartup(t *testing.T) {
	for name, value := range map[string]string{
		"AGENTAREA_EVENT_POLL_INTERVAL": "5",
		"AGENTAREA_EVENT_MAX_POLLERS":   "0",
	} {
		l := config.FromMap(map[string]string{"AGENTAREA_MCP_MANAGER_URL": "http://m", name: value})
		LoadConfig(l, host)
		if err := l.Err(); err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("%s=%q: err = %v", name, value, err)
		}
	}
}

func TestTheManagerURLIsRequired(t *testing.T) {
	l := config.FromMap(nil)
	LoadConfig(l, host)
	if err := l.Err(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_MCP_MANAGER_URL") {
		t.Fatalf("err = %v", err)
	}
}

func TestAWorkerIDIsSetOrTheHostname(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_MCP_MANAGER_URL": "http://m", "AGENTAREA_EVENT_WORKER_ID": "w9"})
	if c := LoadConfig(l, host); c.WorkerID != "w9" {
		t.Fatalf("worker = %q", c.WorkerID)
	}
	l = config.FromMap(map[string]string{"AGENTAREA_MCP_MANAGER_URL": "http://m"})
	LoadConfig(l, func() (string, error) { return "", errors.New("no host") })
	if l.Err() == nil {
		t.Fatal("no worker id and no hostname started")
	}
}
