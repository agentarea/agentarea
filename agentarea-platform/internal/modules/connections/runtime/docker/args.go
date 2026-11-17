package docker

import (
	"fmt"
	"maps"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

// Labels and variables every MCP container carries.
const (
	// ownerLabel records the service a container was created for, so a name is
	// reclaimed only by the workload that owns it.
	ownerLabel     = "ai.agentarea.service"
	instanceLabel  = "agentarea.io/instance-id"
	workspaceLabel = "agentarea.io/workspace-id"

	envInstanceID  = "MCP_INSTANCE_ID"
	envServiceName = "MCP_SERVICE_NAME"
	envPort        = "MCP_CONTAINER_PORT"
)

var nonAlnumRE = regexp.MustCompile(`[^a-z0-9]+`)

func sanitizeServiceName(serviceName string) string {
	s := strings.Trim(nonAlnumRE.ReplaceAllString(strings.ToLower(serviceName), "-"), "-")
	if s == "" {
		return "container-"
	}
	return s
}

// ContainerName is the runtime name of a service's container, which is also
// its host name on the shared network.
func (c Config) ContainerName(serviceName string) string {
	return c.NamePrefix + sanitizeServiceName(serviceName)
}

// container is one workload ready to be rendered into a run command.
type container struct {
	name        string
	serviceName string
	image       string
	entrypoint  []string
	command     []string
	environment map[string]string
	labels      map[string]string
	isolation   workload.Isolation
	memory      string
	cpu         string
}

func (c Config) fromSpec(spec workload.Spec) (container, error) {
	if spec.InstanceID == "" || spec.ServiceName == "" {
		return container{}, fmt.Errorf("a workload needs an instance id and a service name")
	}
	if err := workload.ValidateImageReference(spec.Image); err != nil {
		return container{}, err
	}
	if spec.Port < 1 || spec.Port > 65535 {
		return container{}, fmt.Errorf("port %d is out of range", spec.Port)
	}
	iso, err := workload.SpecIsolation(spec, c.IsolationTier)
	if err != nil {
		return container{}, err
	}
	labels := make(map[string]string, len(spec.Labels)+3)
	for k, v := range spec.Labels {
		if k != ownerLabel {
			labels[k] = v
		}
	}
	labels[workspaceLabel] = spec.WorkspaceID
	labels[instanceLabel] = spec.InstanceID
	env := maps.Clone(spec.Environment)
	if env == nil {
		env = map[string]string{}
	}
	env[envInstanceID] = spec.InstanceID
	env[envServiceName] = spec.ServiceName
	env[envPort] = strconv.Itoa(spec.Port)
	return container{
		name:        c.ContainerName(spec.ServiceName),
		serviceName: spec.ServiceName,
		image:       spec.Image,
		entrypoint:  spec.Entrypoint,
		command:     spec.Command,
		environment: env,
		labels:      labels,
		isolation:   iso,
		memory:      spec.Resources.Limits.Memory,
		cpu:         spec.Resources.Limits.CPU,
	}, nil
}

// runArgs renders a container into `run`. MCP containers publish no port and
// carry no router labels: every request crosses the demand gateway.
func (c Config) runArgs(ct container) []string {
	args := []string{"run", "-d", "--name", ct.name, "--network", c.Network}
	for _, k := range slices.Sorted(maps.Keys(ct.environment)) {
		args = append(args, "-e", k+"="+ct.environment[k])
	}
	for _, k := range slices.Sorted(maps.Keys(ct.labels)) {
		args = append(args, "--label", k+"="+ct.labels[k])
	}
	args = append(args, "--label", ownerLabel+"="+ct.serviceName)
	args = append(args, isolationRunArgs(ct.isolation)...)
	if memory := firstNonEmpty(ct.memory, c.DefaultMemory); memory != "" {
		args = append(args, "--memory", memory)
	}
	if cpus := firstNonEmpty(ct.cpu, c.DefaultCPU); cpus != "" {
		args = append(args, "--cpus", cpus)
	}
	command := ct.command
	if len(ct.entrypoint) > 0 {
		args = append(args, "--entrypoint", ct.entrypoint[0])
		command = append(slices.Clone(ct.entrypoint[1:]), ct.command...)
	}
	args = append(args, ct.image)
	return append(args, command...)
}

// isolationRunArgs renders an Isolation into run flags; the zero value renders none.
func isolationRunArgs(iso workload.Isolation) []string {
	var args []string
	if iso.Runtime != "" {
		args = append(args, "--runtime", iso.Runtime)
	}
	for _, c := range iso.DropCapabilities {
		args = append(args, "--cap-drop", c)
	}
	if iso.NoNewPrivileges {
		args = append(args, "--security-opt", "no-new-privileges")
	}
	if iso.PidsLimit > 0 {
		args = append(args, "--pids-limit", strconv.Itoa(iso.PidsLimit))
	}
	if iso.User != "" {
		args = append(args, "--user", iso.User)
	}
	if iso.ReadOnlyRootFilesystem {
		args = append(args, "--read-only")
		for _, p := range iso.WritablePaths {
			args = append(args, "--tmpfs", p+":rw,nosuid,nodev")
		}
	}
	return args
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
