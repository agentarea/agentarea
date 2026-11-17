package docker

import (
	"context"
	"log/slog"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

func TestNonFiniteCPUCeilingRefusesRatherThanAdmittingEverything(t *testing.T) {
	for name, tc := range map[string]struct{ maxCPU, requested string }{
		"nan maximum":   {"NaN", "4"},
		"inf maximum":   {"Inf", "64"},
		"nan requested": {"1.0", "NaN"},
		"inf requested": {"1.0", "+Inf"},
	} {
		cfg := testConfig()
		cfg.MaxCPU = tc.maxCPU
		if err := cfg.enforceCeiling("256m", tc.requested); err == nil {
			t.Fatalf("%s: max %q accepted %q", name, tc.maxCPU, tc.requested)
		}
	}
}

func TestFiniteCPURequestInsideTheCeilingIsStillAdmitted(t *testing.T) {
	cfg := testConfig()
	cfg.MaxCPU = "2.0"
	if err := cfg.enforceCeiling("256m", "1.5"); err != nil {
		t.Fatalf("a request under the ceiling was refused: %v", err)
	}
}

func TestOverflowingMemoryRequestRefusesRatherThanWrappingNegative(t *testing.T) {
	cfg := testConfig()
	if err := cfg.enforceCeiling("9223372036g", "0.5"); err == nil {
		t.Fatal("an overflowing memory request was admitted")
	}
}

func TestLargeButRepresentableMemoryRequestIsStillCompared(t *testing.T) {
	cfg := testConfig()
	cfg.MaxMemory = "8g"
	if err := cfg.enforceCeiling("4g", ""); err != nil {
		t.Fatalf("4g under 8g refused: %v", err)
	}
	if err := cfg.enforceCeiling("16g", ""); err == nil {
		t.Fatal("16g over 8g admitted")
	}
}

func TestAnUnusableMaximumRefusesTheRequestRatherThanAllowingIt(t *testing.T) {
	for name, m := range map[string]struct{ maxMemory, maxCPU string }{
		"empty memory":     {"", "1.0"},
		"malformed memory": {"512 megabytes", "1.0"},
		"empty cpu":        {"512m", ""},
		"malformed cpu":    {"512m", "one"},
	} {
		cfg := testConfig()
		cfg.MaxMemory, cfg.MaxCPU = m.maxMemory, m.maxCPU
		if err := cfg.enforceCeiling("256m", "0.5"); err == nil {
			t.Fatalf("%s: a request was accepted against a maximum the host cannot read", name)
		}
	}
}

func TestDockerReservationIsTheDefaultLimit(t *testing.T) {
	b, _ := newTestBackend(t, testConfig(), &fakeRunner{})
	got, err := b.Reservation(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := (workload.Reservation{CPUMillicores: 1000, MemoryBytes: 512 * 1024 * 1024}); got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestLoadConfigReadsTheManagerDefaults(t *testing.T) {
	l := config.FromMap(map[string]string{})
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	want := Config{Runtime: "docker", Network: "agentarea_mcp-network", NamePrefix: "mcp-", MaxContainers: 50,
		DefaultMemory: "512m", DefaultCPU: "1.0", MaxMemory: "512m", MaxCPU: "1.0", IsolationTier: "untrusted"}
	if cfg != want {
		t.Fatalf("got %+v, want %+v", cfg, want)
	}
}

func TestLoadConfigMaximaFollowTheDefaultsUnlessSet(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_MCP_MEMORY": "1g", "AGENTAREA_MCP_MAX_CPU": "4"})
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if cfg.MaxMemory != "1g" || cfg.MaxCPU != "4" {
		t.Fatalf("maxima = %q, %q", cfg.MaxMemory, cfg.MaxCPU)
	}
}

func TestLoadConfigRefusesWhatItCannotUse(t *testing.T) {
	for name, env := range map[string]map[string]string{
		"unknown tier":    {"AGENTAREA_MCP_ISOLATION": "loose"},
		"unknown runtime": {"AGENTAREA_MCP_RUNTIME": "lxc"},
		"bad memory":      {"AGENTAREA_MCP_MEMORY": "lots"},
		"nan cpu ceiling": {"AGENTAREA_MCP_MAX_CPU": "NaN"},
		"zero containers": {"AGENTAREA_MCP_MAX_CONTAINERS": "0"},
	} {
		l := config.FromMap(env)
		LoadConfig(l)
		if l.Err() == nil {
			t.Errorf("%s: loaded without an error", name)
		}
	}
}

// The manager put workloads on agentarea_default, the compose network that
// carries Postgres, Valkey, Hydra's admin port and every other platform
// service; the default is now the dedicated MCP network compose declares, and
// a network shared with the platform is refused.
func TestBackendRefusesThePlatformNetwork(t *testing.T) {
	for _, network := range []string{"agentarea_default", "suite_default", "host"} {
		cfg := testConfig()
		cfg.Network = network
		if _, err := NewWithRunner(cfg, &fakeRunner{}, slog.New(slog.DiscardHandler)); err == nil || !strings.Contains(err.Error(), "platform") {
			t.Fatalf("%s: err %v", network, err)
		}
	}
	cfg := testConfig()
	cfg.Network = "agentarea_mcp-network"
	if _, err := NewWithRunner(cfg, &fakeRunner{}, slog.New(slog.DiscardHandler)); err != nil {
		t.Fatal(err)
	}
}
