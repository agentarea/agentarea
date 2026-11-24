package docker

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func validating(images map[string]bool, pullOK bool, ps string) *fakeRunner {
	return &fakeRunner{handle: func(args []string) reply {
		switch {
		case args[0] == "ps":
			return reply{stdout: ps}
		case args[0] == "image" && args[3] == "{{.Id}}":
			if images[args[4]] {
				return reply{stdout: "sha256:1"}
			}
			return reply{stderr: "Error: No such image: " + args[4], err: exitErr()}
		case args[0] == "image" && args[3] == "{{.Size}}":
			return reply{stdout: "1234\n"}
		case args[0] == "pull":
			if pullOK {
				return reply{}
			}
			return reply{stderr: "manifest unknown", err: exitErr()}
		}
		return reply{err: errors.New("unexpected " + strings.Join(args, " "))}
	}}
}

func TestDryRunAcceptsACommandSpecWithoutAnImage(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(nil, false, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"type": "command", "command": "npx"})
	if err != nil {
		t.Fatal(err)
	}
	if !r.Valid || !r.ImageExists || !r.CanPull {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunRefusesACommandSpecWithoutACommand(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(nil, false, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"type": "command"})
	if err != nil {
		t.Fatal(err)
	}
	if r.Valid {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunReportsALocalImageAndItsSize(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(map[string]bool{"vendor/mcp:1.0": true}, false, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"image": "vendor/mcp:1.0", "port": float64(8080)})
	if err != nil {
		t.Fatal(err)
	}
	if !r.Valid || !r.ImageExists || r.EstimatedSize != "1234 bytes" {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunRefusesAnImageThatCannotBePulled(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(nil, false, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"image": "vendor/typo:1.0", "port": 8080})
	if err != nil {
		t.Fatal(err)
	}
	if r.Valid || r.CanPull || !strings.Contains(strings.Join(r.Errors, ";"), "cannot be pulled") {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunWarnsThatAPullableImageWillBePulled(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(nil, true, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"image": "vendor/mcp:2.0", "port": 8080})
	if err != nil {
		t.Fatal(err)
	}
	if !r.Valid || !r.CanPull || len(r.Warnings) != 1 {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunRefusesMalformedSpecs(t *testing.T) {
	for name, spec := range map[string]map[string]any{
		"no port":       {"image": "vendor/mcp:1.0"},
		"port range":    {"image": "vendor/mcp:1.0", "port": 70000},
		"cmd not list":  {"image": "vendor/mcp:1.0", "port": 8080, "cmd": "serve"},
		"env not map":   {"image": "vendor/mcp:1.0", "port": 8080, "environment": "A=1"},
		"flag image":    {"image": "--privileged", "port": 8080},
		"missing image": {"port": 8080},
	} {
		b, _ := newTestBackend(t, testConfig(), validating(map[string]bool{"vendor/mcp:1.0": true}, false, ""))
		r, err := b.ValidateDryRun(context.Background(), spec)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if r.Valid {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestDryRunChecksTheContainerLimit(t *testing.T) {
	spec := map[string]any{"type": "command", "command": "uvx"}
	b, _ := newTestBackend(t, testConfig(), validating(nil, false, "running\nrunning\nrunning\nrunning\n"))
	r, err := b.ValidateDryRun(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	if r.Valid || !strings.Contains(strings.Join(r.Errors, ";"), "Container limit reached: 4/4") {
		t.Fatalf("result = %+v", r)
	}
	b, _ = newTestBackend(t, testConfig(), validating(nil, false, "running\nrunning\nrunning\nexited\n"))
	r, err = b.ValidateDryRun(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	if !r.Valid || !strings.Contains(strings.Join(r.Warnings, ";"), "Close to container limit: 3/4") {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunWarnsOnNonStringResources(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), validating(nil, false, ""))
	r, err := b.ValidateDryRun(context.Background(), map[string]any{"type": "command", "command": "npx",
		"resources": map[string]any{"memory_limit": 512}})
	if err != nil {
		t.Fatal(err)
	}
	if !r.Valid || len(r.Warnings) != 1 {
		t.Fatalf("result = %+v", r)
	}
}

func TestDryRunReportsARuntimeThatCannotAnswer(t *testing.T) {
	r := &fakeRunner{handle: func([]string) reply {
		return reply{stderr: "Cannot connect to the Docker daemon", err: exitErr()}
	}}
	b, _ := newTestBackend(t, testConfig(), r)
	if _, err := b.ValidateDryRun(context.Background(), map[string]any{"image": "vendor/mcp:1.0", "port": 8080}); err == nil {
		t.Fatal("a dead daemon read as an invalid spec")
	}
}
