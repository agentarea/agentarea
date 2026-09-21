package backends

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"net/url"
	"os/exec"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
)

type dockerUsageInspect struct {
	ID     string
	Name   string
	Labels map[string]string
	State  struct {
		Status    string
		Running   bool
		StartedAt time.Time
	}
	HostConfig struct {
		NanoCpus  int64
		CpuQuota  int64
		CpuPeriod int64
		Memory    int64
	}
}

type dockerUsageStats struct {
	ID       string    `json:"id"`
	Read     time.Time `json:"read"`
	CPUStats struct {
		CPUUsage struct {
			TotalUsage *uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
	} `json:"cpu_stats"`
	MemoryStats struct {
		Usage *uint64 `json:"usage"`
	} `json:"memory_stats"`
}

func (d *DockerBackend) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	return d.sampleUsage(ctx, "", "")
}

func (d *DockerBackend) SampleUsageForOwner(ctx context.Context, agentID string) ([]usage.Sample, error) {
	if agentID == "" {
		return nil, fmt.Errorf("usage owner is required")
	}
	return d.sampleUsage(ctx, agentID, "")
}

func (d *DockerBackend) SampleResourceUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	if resourceID == "" {
		return nil, fmt.Errorf("usage resource is required")
	}
	return d.sampleUsage(ctx, "", resourceID)
}

func (d *DockerBackend) SampleResourceUsageForOwner(ctx context.Context, agentID, resourceID string) ([]usage.Sample, error) {
	if agentID == "" || resourceID == "" {
		return nil, fmt.Errorf("usage owner and resource are required")
	}
	return d.sampleUsage(ctx, agentID, resourceID)
}

func (d *DockerBackend) sampleUsage(ctx context.Context, agentID, resourceID string) ([]usage.Sample, error) {
	ctx, cancel := context.WithTimeout(ctx, usageSampleTimeout)
	defer cancel()
	// The reserved manager label is authoritative, not a container-name prefix.
	filters := []string{"ai.agentarea.service"}
	if agentID == "" && resourceID == "" && d.config.Container.Network != "" {
		filters = append(filters, "com.docker.compose.service=sandbox-executor")
	}
	seen := make(map[string]bool)
	samples := make([]usage.Sample, 0)
	for _, filter := range filters {
		args := []string{"ps", "--all", "--no-trunc", "--quiet", "--filter", "label=" + filter}
		if agentID != "" {
			args = append(args, "--filter", "label="+usageOwnerLabel+"="+agentID)
		}
		if resourceID != "" {
			args = append(args, "--filter", "label=agentarea.io/instance-id="+resourceID)
		}
		if d.config.Container.Network != "" {
			args = append(args, "--filter", "network="+d.config.Container.Network)
		}
		inventory, err := d.usageCommand(ctx, args...).Output()
		if err != nil {
			return nil, fmt.Errorf("listing Docker usage containers: %w", err)
		}
		for _, id := range strings.Fields(string(inventory)) {
			if seen[id] {
				continue
			}
			seen[id] = true
			// Select fields explicitly: inspecting .Config or .HostConfig wholesale
			// would pull environment values and host secrets into this path.
			format := `{"ID":{{json .Id}},"Name":{{json .Name}},"Labels":{{json .Config.Labels}},"State":{"Status":{{json .State.Status}},"Running":{{json .State.Running}},"StartedAt":{{json .State.StartedAt}}},"HostConfig":{"NanoCpus":{{json .HostConfig.NanoCpus}},"CpuQuota":{{json .HostConfig.CpuQuota}},"CpuPeriod":{{json .HostConfig.CpuPeriod}},"Memory":{{json .HostConfig.Memory}}}}`
			body, err := d.usageCommand(ctx, "inspect", id, "--format", format).Output()
			if err != nil {
				return nil, fmt.Errorf("inspecting Docker usage container %s: %w", id, err)
			}
			var container dockerUsageInspect
			if err := json.Unmarshal(body, &container); err != nil {
				return nil, fmt.Errorf("decoding Docker usage configuration: %w", err)
			}
			if container.ID != id {
				return nil, fmt.Errorf("docker usage container identity changed")
			}
			managed := container.Labels["ai.agentarea.service"] != ""
			shared := container.Labels["com.docker.compose.service"] == "sandbox-executor"
			if !managed && !shared {
				continue
			}
			if agentID != "" && container.Labels[usageOwnerLabel] != agentID {
				continue
			}
			sample := dockerUsageConfiguration(container)
			if resourceID != "" && (sample.ResourceKind != "mcp_instance" || sample.ResourceID != resourceID) {
				continue
			}
			if container.State.Running {
				stats, err := d.readDockerUsage(ctx, id)
				if err != nil {
					sample.MeasurementReason = "docker_stats_unavailable"
				} else if stats.ID != id || stats.Read.IsZero() || (!container.State.StartedAt.IsZero() && stats.Read.Before(container.State.StartedAt)) {
					sample.MeasurementReason = "docker_stats_identity_or_time_invalid"
				} else {
					sample.MeasurementAt = &stats.Read
					sample.CPUUsageNS = stats.CPUStats.CPUUsage.TotalUsage
					sample.MemoryUsageBytes = stats.MemoryStats.Usage
					if sample.MemoryUsageBytes != nil {
						sample.MemoryMetric = "usage"
					}
					if sample.CPUUsageNS != nil && sample.MemoryUsageBytes != nil {
						sample.MeasurementStatus, sample.MeasurementReason = "available", ""
					} else {
						sample.MeasurementStatus, sample.MeasurementReason = "partial", "docker_stats_incomplete"
					}
				}
			}
			samples = append(samples, sample)
		}
	}
	return samples, nil
}

func dockerUsageConfiguration(container dockerUsageInspect) usage.Sample {
	s := usage.Sample{Provider: "docker", ResourceKind: "platform_runtime", ResourceID: container.ID, IncarnationID: container.ID, State: container.State.Status, ObservedAt: time.Now().UTC(), MeasurementStatus: "unavailable", MeasurementReason: "container_not_running"}
	// A shared executor remains platform usage regardless of any task metadata.
	if container.Labels["ai.agentarea.service"] != "" && container.Labels["com.docker.compose.service"] != "sandbox-executor" && container.Labels["agentarea.io/workspace-id"] != "" {
		s.ResourceKind = "mcp_instance"
		s.WorkspaceID = container.Labels["agentarea.io/workspace-id"]
		s.ResourceID = container.Labels["agentarea.io/instance-id"]
		if s.ResourceID == "" {
			s.ResourceID = container.Labels["ai.agentarea.service"]
		}
	}
	if !container.State.StartedAt.IsZero() {
		started := container.State.StartedAt
		s.StartedAt = &started
	}
	if container.HostConfig.NanoCpus > 0 {
		cpu := container.HostConfig.NanoCpus
		s.CPULimitNanocores = &cpu
	} else if container.HostConfig.CpuQuota > 0 && container.HostConfig.CpuPeriod > 0 {
		quota, period := container.HostConfig.CpuQuota, container.HostConfig.CpuPeriod
		s.CPUQuotaUS, s.CPUPeriodUS = &quota, &period
		var cpu, remainder big.Int
		cpu.Mul(big.NewInt(quota), big.NewInt(1000000000))
		cpu.QuoRem(&cpu, big.NewInt(period), &remainder)
		if cpu.IsInt64() && remainder.Sign() == 0 {
			value := cpu.Int64()
			s.CPULimitNanocores = &value
		}
	}
	if container.HostConfig.Memory > 0 {
		memory := container.HostConfig.Memory
		s.MemoryLimitBytes = &memory
	}
	// Docker CPU shares and memory reservations are not scheduler requests.
	return s
}

func (d *DockerBackend) usageCommand(ctx context.Context, args ...string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, d.config.Container.Runtime, args...)
	cmd.WaitDelay = time.Second
	return cmd
}

// The Docker CLI's stats display rounds values and omits the cumulative CPU
// counter. Its daemon stdio transport respects DOCKER_HOST, contexts and TLS
// exactly like the existing CLI backend, while exposing the raw Engine response.
func (d *DockerBackend) readDockerUsage(ctx context.Context, id string) (*dockerUsageStats, error) {
	ctx, cancel := context.WithTimeout(ctx, usageSourceTimeout)
	defer cancel()
	cmd := d.usageCommand(ctx, "system", "dial-stdio")
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	defer stdin.Close()
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	defer stdout.Close()
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	defer func() {
		_ = stdin.Close()
		cancel()
		_ = cmd.Wait()
	}()
	// Keep the input half open until the response is decoded. Docker Desktop's
	// socket bridge can abort a request when dial-stdio receives premature EOF.
	if _, err := io.WriteString(stdin, "GET /containers/"+url.PathEscape(id)+"/stats?stream=false&one-shot=true HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"); err != nil {
		return nil, err
	}
	response, err := http.ReadResponse(bufio.NewReader(stdout), nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("docker stats returned HTTP %d", response.StatusCode)
	}
	var stats dockerUsageStats
	if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&stats); err != nil {
		return nil, err
	}
	return &stats, nil
}
