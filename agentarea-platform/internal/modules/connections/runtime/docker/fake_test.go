package docker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"sync"
	"testing"
)

type reply struct {
	stdout, stderr string
	err            error
}

// fakeRunner answers runtime commands from a handler and records every call.
type fakeRunner struct {
	mu     sync.Mutex
	calls  []string
	handle func(args []string) reply
}

func (f *fakeRunner) Run(_ context.Context, args ...string) ([]byte, []byte, error) {
	f.mu.Lock()
	f.calls = append(f.calls, strings.Join(args, " "))
	f.mu.Unlock()
	r := reply{err: errors.New("unexpected command")}
	if f.handle != nil {
		r = f.handle(args)
	}
	return []byte(r.stdout), []byte(r.stderr), r.err
}

func (f *fakeRunner) called(prefix string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, c := range f.calls {
		if strings.HasPrefix(c, prefix) {
			return true
		}
	}
	return false
}

func (f *fakeRunner) joined() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return strings.Join(f.calls, "\n")
}

func exitErr() error { return errors.New("exit status 1") }

func absent() reply {
	return reply{stderr: "Error: No such container: x", err: exitErr()}
}

type containerState struct {
	status   string
	exitCode int
	labels   map[string]string
	env      []string
	networks map[string]string
	flatIP   string
}

func (c containerState) json(t *testing.T) string {
	t.Helper()
	nets := map[string]map[string]string{}
	for k, v := range c.networks {
		nets[k] = map[string]string{"IPAddress": v}
	}
	out, err := json.Marshal([]map[string]any{{
		"Id":     "cid-1",
		"State":  map[string]any{"Status": c.status, "Running": c.status == "running", "ExitCode": c.exitCode},
		"Config": map[string]any{"Env": c.env, "Labels": c.labels},
		"NetworkSettings": map[string]any{
			"IPAddress": c.flatIP,
			"Networks":  nets,
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	return string(out)
}

func testConfig() Config {
	return Config{
		Runtime:       "docker",
		Network:       "agentarea-mcp",
		NamePrefix:    "mcp-",
		MaxContainers: 4,
		DefaultMemory: "512m",
		DefaultCPU:    "1.0",
		MaxMemory:     "512m",
		MaxCPU:        "1.0",
		IsolationTier: "standard",
	}
}

func newTestBackend(t *testing.T, cfg Config, r *fakeRunner) (*Backend, *bytes.Buffer) {
	t.Helper()
	var logged bytes.Buffer
	b, err := NewWithRunner(cfg, r, slog.New(slog.NewTextHandler(&logged, nil)))
	if err != nil {
		t.Fatal(err)
	}
	return b, &logged
}

func hasFlagPair(args []string, flag, value string) bool {
	for i := 0; i < len(args)-1; i++ {
		if args[i] == flag && args[i+1] == value {
			return true
		}
	}
	return false
}
