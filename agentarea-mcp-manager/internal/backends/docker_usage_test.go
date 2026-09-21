package backends

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/usage"
)

func usageDockerCLI(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "docker")
	script := `#!/bin/sh
case "$1" in
ps)
  case "$*" in *com.docker.compose.service*) exit 0 ;; esac
  printf '%s\n' container-one
  ;;
inspect)
  printf '%s\n' '{"ID":"container-one","Name":"/mcp-one","Labels":{"ai.agentarea.service":"mcp-one","agentarea.io/workspace-id":"workspace-one","agentarea.io/instance-id":"instance-one","agentarea.io/dataplane-id":"agent-one"},"State":{"Status":"running","Running":true,"StartedAt":"2026-01-01T00:00:00Z"},"HostConfig":{"NanoCpus":250000000,"Memory":67108864}}'
  ;;
system)
  while IFS= read -r line; do [ "${#line}" -eq 1 ] && break; done
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n'
  printf '%s' '{"id":"container-one","read":"2026-01-01T00:00:30Z","cpu_stats":{"cpu_usage":{"total_usage":9007199254740993}},"memory_stats":{"usage":9007199254740995}}'
  ;;
*) exit 1 ;;
esac
`
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestDockerUsagePreservesCountersAndEffectiveLimits(t *testing.T) {
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{Runtime: usageDockerCLI(t)}}}
	samples, err := backend.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 {
		t.Fatalf("samples = %v", samples)
	}
	s := samples[0]
	if s.MeasurementStatus != "available" || s.CPUUsageNS == nil || *s.CPUUsageNS != 9007199254740993 || s.MemoryUsageBytes == nil || *s.MemoryUsageBytes != 9007199254740995 || s.MemoryMetric != "usage" {
		t.Fatalf("lossy usage: %+v", s)
	}
	if s.CPULimitNanocores == nil || *s.CPULimitNanocores != 250000000 || s.MemoryLimitBytes == nil || *s.MemoryLimitBytes != 67108864 || s.CPURequestNanocores != nil || s.MemoryRequestBytes != nil {
		t.Fatalf("limits and requests conflated: %+v", s)
	}
	if s.WorkspaceID != "workspace-one" || s.ResourceID != "instance-one" || s.IncarnationID != "container-one" {
		t.Fatalf("wrong ownership: %+v", s)
	}
}

func TestDockerUsageOwnerFilterCannotLeakOtherAgent(t *testing.T) {
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{Runtime: usageDockerCLI(t)}}}
	samples, err := backend.SampleUsageForOwner(context.Background(), "other-agent")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 0 {
		t.Fatalf("unowned usage leaked: %+v", samples)
	}
}

func TestDockerSharedExecutorRemainsPlatformUsage(t *testing.T) {
	container := dockerUsageInspect{ID: "shared", Name: "/sandbox", Labels: map[string]string{"com.docker.compose.service": "sandbox-executor", "agentarea.io/workspace-id": "must-not-own-shared-container"}}
	sample := dockerUsageConfiguration(container)
	if sample.ResourceKind != "platform_runtime" || sample.WorkspaceID != "" || sample.TaskID != "" {
		t.Fatalf("shared runtime assigned to tenant: %+v", sample)
	}
}

func TestDockerResourceUsageFiltersBeforeInspectAndStats(t *testing.T) {
	cli := usageDockerCLI(t)
	path := filepath.Join(t.TempDir(), "docker")
	script := fmt.Sprintf(`#!/bin/sh
if [ "$1" = ps ]; then
  case "$*" in
    *label=agentarea.io/instance-id=instance-one*) ;;
    *label=agentarea.io/instance-id=missing*) exit 0 ;;
    *) exit 1 ;;
  esac
fi
exec '%s' "$@"
`, cli)
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{Runtime: path, Network: "runtime"}}}
	var sampler usage.ResourceSampler = backend
	samples, err := sampler.SampleResourceUsage(context.Background(), "instance-one")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 || samples[0].ResourceID != "instance-one" || samples[0].CPUUsageNS == nil || *samples[0].CPUUsageNS != 9007199254740993 {
		t.Fatalf("targeted sample = %+v", samples)
	}
	samples, err = sampler.SampleResourceUsage(context.Background(), "missing")
	if err != nil || samples == nil || len(samples) != 0 {
		t.Fatalf("missing resource: samples=%v err=%v", samples, err)
	}
}

func TestDockerResourceUsageOwnerConjunction(t *testing.T) {
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{Runtime: usageDockerCLI(t)}}}
	for _, tc := range []struct {
		owner, resource string
		want            int
	}{
		{"agent-one", "instance-one", 1},
		{"other-agent", "instance-one", 0},
		{"agent-one", "other-instance", 0},
	} {
		samples, err := backend.SampleResourceUsageForOwner(context.Background(), tc.owner, tc.resource)
		if err != nil {
			t.Fatal(err)
		}
		if len(samples) != tc.want {
			t.Fatalf("owner=%s resource=%s: %+v", tc.owner, tc.resource, samples)
		}
	}
}

func TestDockerUsageKeepsStdinOpenUntilResponse(t *testing.T) {
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("USAGE_STDIO_HELPER", "1")
	cli := filepath.Join(t.TempDir(), "docker")
	if err := os.WriteFile(cli, []byte(fmt.Sprintf("#!/bin/sh\nexec %q -test.run=TestDockerUsageStdioHelper -- \"$@\"\n", binary)), 0700); err != nil {
		t.Fatal(err)
	}
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{Runtime: cli}}}
	stats, err := backend.readDockerUsage(context.Background(), "container-one")
	if err != nil {
		t.Fatal(err)
	}
	if stats.ID != "container-one" || stats.CPUStats.CPUUsage.TotalUsage == nil || *stats.CPUStats.CPUUsage.TotalUsage != 9007199254740993 {
		t.Fatalf("transport lost response: %+v", stats)
	}
}

func TestDockerUsageStdioHelper(t *testing.T) {
	if os.Getenv("USAGE_STDIO_HELPER") != "1" {
		return
	}
	reader := bufio.NewReader(os.Stdin)
	if _, err := http.ReadRequest(reader); err != nil {
		os.Exit(2)
	}
	inputClosed := make(chan error, 1)
	go func() { _, err := reader.ReadByte(); inputClosed <- err }()
	select {
	case err := <-inputClosed:
		if err == io.EOF {
			fmt.Print("HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n")
			os.Exit(0)
		}
		os.Exit(3)
	case <-time.After(100 * time.Millisecond):
	}
	body := `{"id":"container-one","read":"2026-01-01T00:00:30Z","cpu_stats":{"cpu_usage":{"total_usage":9007199254740993}}}`
	fmt.Printf("HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s", len(body), body)
	os.Exit(0)
}

func TestDockerQuotaRatioIsNeverRoundedToNanocores(t *testing.T) {
	container := dockerUsageInspect{ID: "fractional-quota"}
	container.HostConfig.CpuQuota = 1
	container.HostConfig.CpuPeriod = 3
	sample := dockerUsageConfiguration(container)
	if sample.CPULimitNanocores != nil {
		t.Fatalf("one third CPU was rounded to %d nanocores", *sample.CPULimitNanocores)
	}
	if sample.CPUQuotaUS == nil || sample.CPUPeriodUS == nil || *sample.CPUQuotaUS != 1 || *sample.CPUPeriodUS != 3 {
		t.Fatalf("exact quota ratio is unavailable: %+v", sample)
	}
	container.HostConfig.CpuPeriod = 4
	sample = dockerUsageConfiguration(container)
	if sample.CPULimitNanocores == nil || *sample.CPULimitNanocores != 250000000 {
		t.Fatalf("exactly representable CPU limit is unavailable: %+v", sample)
	}
}
