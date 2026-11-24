package docker

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

// Backend is workload.Backend over a Docker or Podman CLI.
type Backend struct {
	cfg Config
	run Runner
	log *slog.Logger
}

var _ workload.Backend = (*Backend)(nil)

// New runs workloads through the configured runtime binary.
func New(cfg Config, log *slog.Logger) (*Backend, error) {
	return NewWithRunner(cfg, execRunner{binary: cfg.Runtime}, log)
}

// NewWithRunner runs workloads through r.
func NewWithRunner(cfg Config, r Runner, log *slog.Logger) (*Backend, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	if r == nil || log == nil {
		return nil, errors.New("docker backend: a runner and a logger are required")
	}
	return &Backend{cfg: cfg, run: r, log: log}, nil
}

// ContainerName is the runtime name, and network host name, of a service's container.
func (b *Backend) ContainerName(serviceName string) string { return b.cfg.ContainerName(serviceName) }

// Create starts the workload's container and returns once the runtime accepted
// it; the caller polls Status until it runs. A running container under the
// instance's name is reported, never replaced; a stopped one this instance
// owns is removed first.
func (b *Backend) Create(ctx context.Context, spec workload.Spec) (workload.Status, error) {
	ct, err := b.cfg.fromSpec(spec)
	if err != nil {
		return workload.Status{}, err
	}
	if err := b.cfg.enforceCeiling(ct.memory, ct.cpu); err != nil {
		return workload.Status{}, err
	}
	if err := b.ensureRuntimeAvailable(ctx, ct.isolation); err != nil {
		return workload.Status{}, err
	}
	if err := b.clearContainerName(ctx, ct.name, ct.serviceName); err != nil {
		return workload.Status{}, err
	}
	occupied, err := b.occupied(ctx)
	if err != nil {
		return workload.Status{}, err
	}
	if occupied >= b.cfg.MaxContainers {
		return workload.Status{}, fmt.Errorf("maximum container limit reached (%d)", b.cfg.MaxContainers)
	}
	stdout, stderr, err := b.run.Run(ctx, b.cfg.runArgs(ct)...)
	if err != nil {
		b.log.ErrorContext(ctx, "container runtime refused the MCP workload",
			"container", ct.name, "error", err, "output", strings.TrimSpace(string(stderr)))
		return workload.Status{}, fmt.Errorf("failed to create container: %s", runtimeRefusal(stderr))
	}
	b.log.InfoContext(ctx, "MCP container created", "container", ct.name, "instance_id", spec.InstanceID)
	return workload.Status{
		ID:     lastLine(stdout),
		Name:   ct.name,
		Status: workload.StatusStarting,
		Port:   spec.Port,
		Labels: ct.labels,
	}, nil
}

// Delete removes the instance's container; one that is already gone is the
// state asked for.
func (b *Backend) Delete(ctx context.Context, instanceID string) error {
	name := b.cfg.ContainerName(instanceID)
	info, err := b.inspect(ctx, name)
	if errors.Is(err, workload.ErrNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	if err := info.ownedBy(instanceID); err != nil {
		return err
	}
	if _, stderr, err := b.run.Run(ctx, "rm", "-f", name); err != nil && !containerAlreadyGone(stderr) {
		return fmt.Errorf("removing container %s: %w: %s", name, err, strings.TrimSpace(string(stderr)))
	}
	b.log.InfoContext(ctx, "MCP container removed", "container", name, "instance_id", instanceID)
	return nil
}

// Status reports the instance's container. A stopped container carries the
// classified reason it stopped, never its own output.
func (b *Backend) Status(ctx context.Context, instanceID string) (workload.Status, error) {
	name := b.cfg.ContainerName(instanceID)
	info, err := b.inspect(ctx, name)
	if err != nil {
		return workload.Status{}, err
	}
	if err := info.ownedBy(instanceID); err != nil {
		return workload.Status{}, err
	}
	env := info.environment()
	port, err := strconv.Atoi(env[envPort])
	if err != nil {
		return workload.Status{}, fmt.Errorf("container %s carries no usable %s: %w", name, envPort, err)
	}
	st := workload.Status{
		ID:     info.ID,
		Name:   name,
		Status: mapState(info.State.Status),
		Port:   port,
		Labels: info.Config.Labels,
	}
	switch st.Status {
	case workload.StatusRunning:
		ip, err := info.address(b.cfg.Network)
		if err != nil {
			return workload.Status{}, fmt.Errorf("container %s: %w", name, err)
		}
		st.InternalURL = "http://" + net.JoinHostPort(ip, strconv.Itoa(port))
	case workload.StatusStopped:
		st.Message = b.stopDiagnostic(ctx, name, info, env)
	}
	return st, nil
}

// Reservation is the default limit: Docker reserves no request.
func (b *Backend) Reservation(context.Context) (workload.Reservation, error) {
	cpu, memory, err := b.cfg.defaultLimits()
	if err != nil {
		return workload.Reservation{}, err
	}
	return workload.Reservation{CPUMillicores: cpu, MemoryBytes: memory}, nil
}

type inspected struct {
	ID    string `json:"Id"`
	State struct {
		Status   string `json:"Status"`
		Running  bool   `json:"Running"`
		ExitCode int    `json:"ExitCode"`
	} `json:"State"`
	Config struct {
		Env    []string          `json:"Env"`
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
	NetworkSettings struct {
		IPAddress string `json:"IPAddress"`
		Networks  map[string]struct {
			IPAddress string `json:"IPAddress"`
		} `json:"Networks"`
	} `json:"NetworkSettings"`
}

func (b *Backend) inspect(ctx context.Context, name string) (inspected, error) {
	stdout, stderr, err := b.run.Run(ctx, "container", "inspect", name)
	if err != nil {
		if noSuchObject(stderr) {
			return inspected{}, fmt.Errorf("%w: %s", workload.ErrNotFound, name)
		}
		return inspected{}, fmt.Errorf("inspecting container %s: %w: %s", name, err, strings.TrimSpace(string(stderr)))
	}
	var out []inspected
	if err := json.Unmarshal(stdout, &out); err != nil {
		return inspected{}, fmt.Errorf("reading the inspection of %s: %w", name, err)
	}
	if len(out) != 1 {
		return inspected{}, fmt.Errorf("inspecting container %s returned %d records", name, len(out))
	}
	return out[0], nil
}

// ownedBy refuses a container under the instance's name that was not created
// for it: names come from lossy sanitization, so a namesake can be another's.
func (i inspected) ownedBy(instanceID string) error {
	if i.Config.Labels[instanceLabel] != instanceID {
		return fmt.Errorf("container %s exists and was not created for instance %s", i.ID, instanceID)
	}
	return nil
}

func (i inspected) environment() map[string]string {
	env := make(map[string]string, len(i.Config.Env))
	for _, kv := range i.Config.Env {
		if k, v, ok := strings.Cut(kv, "="); ok {
			env[k] = v
		}
	}
	return env
}

// address is the container's IP on the configured network, else on any
// network, else the flat field: a container on a user-defined network has no
// flat address, and some runtimes report only the flat one.
func (i inspected) address(network string) (string, error) {
	if n, ok := i.NetworkSettings.Networks[network]; ok && strings.TrimSpace(n.IPAddress) != "" {
		return strings.TrimSpace(n.IPAddress), nil
	}
	names := make([]string, 0, len(i.NetworkSettings.Networks))
	for name := range i.NetworkSettings.Networks {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if ip := strings.TrimSpace(i.NetworkSettings.Networks[name].IPAddress); ip != "" {
			return ip, nil
		}
	}
	if ip := strings.TrimSpace(i.NetworkSettings.IPAddress); ip != "" {
		return ip, nil
	}
	return "", errors.New("container has no network address yet")
}

func mapState(state string) string {
	switch strings.ToLower(strings.TrimSpace(state)) {
	case "running":
		return workload.StatusRunning
	case "created", "configured", "restarting":
		return workload.StatusStarting
	default:
		return workload.StatusStopped
	}
}

// clearContainerName frees the name a workload is about to take. A stopped
// container this service owns is a corpse of an earlier attempt and is removed;
// a running one, or one owned by something else, is reported.
func (b *Backend) clearContainerName(ctx context.Context, name, owner string) error {
	info, err := b.inspect(ctx, name)
	if errors.Is(err, workload.ErrNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.State.Running {
		return fmt.Errorf("container %s is already running", name)
	}
	if info.Config.Labels[ownerLabel] != owner {
		return fmt.Errorf("container %s exists and was not created for %s", name, owner)
	}
	if _, stderr, err := b.run.Run(ctx, "rm", "-f", name); err != nil && !containerAlreadyGone(stderr) {
		return fmt.Errorf("removing stale container %s: %w: %s", name, err, strings.TrimSpace(string(stderr)))
	}
	b.log.InfoContext(ctx, "removed a stale container holding the name of a new workload", "container", name)
	return nil
}

// occupied counts the MCP containers that hold host resources: an exited or
// dead container holds none, and counting it wedges the host for good.
func (b *Backend) occupied(ctx context.Context) (int, error) {
	stdout, stderr, err := b.run.Run(ctx, "ps", "-a",
		"--filter", "label="+ownerLabel, "--filter", "label="+instanceLabel, "--format", "{{.State}}")
	if err != nil {
		return 0, fmt.Errorf("listing MCP containers: %w: %s", err, strings.TrimSpace(string(stderr)))
	}
	n := 0
	for _, line := range strings.Split(string(stdout), "\n") {
		switch strings.ToLower(strings.TrimSpace(line)) {
		case "", "exited", "dead", "stopped":
		default:
			n++
		}
	}
	return n, nil
}

// ensureRuntimeAvailable fails closed when the isolation asks for a runtime
// the daemon does not have, rather than starting the workload unconfined.
func (b *Backend) ensureRuntimeAvailable(ctx context.Context, iso workload.Isolation) error {
	if iso.Runtime == "" {
		return nil
	}
	stdout, stderr, err := b.run.Run(ctx, "info", "--format", "{{json .Runtimes}}")
	if err != nil {
		return fmt.Errorf("cannot verify container runtime %q is installed: %w: %s", iso.Runtime, err, strings.TrimSpace(string(stderr)))
	}
	var runtimes map[string]any
	if err := json.Unmarshal(stdout, &runtimes); err != nil {
		return fmt.Errorf("cannot verify container runtime %q is installed: parsing the runtime list: %w", iso.Runtime, err)
	}
	available := make([]string, 0, len(runtimes))
	for name := range runtimes {
		available = append(available, name)
	}
	sort.Strings(available)
	if slices.Contains(available, iso.Runtime) {
		return nil
	}
	return &RuntimeUnavailableError{Runtime: iso.Runtime, Available: available}
}

// RuntimeUnavailableError is an isolation this daemon cannot provide.
type RuntimeUnavailableError struct {
	Runtime   string
	Available []string
}

func (e *RuntimeUnavailableError) Error() string {
	return fmt.Sprintf("container runtime %q is not installed on this host (available: %s); refusing to start without the requested isolation",
		e.Runtime, strings.Join(e.Available, ", "))
}

func lastLine(b []byte) string {
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	return strings.TrimSpace(lines[len(lines)-1])
}

func containerAlreadyGone(stderr []byte) bool {
	return strings.Contains(strings.ToLower(string(stderr)), "no such container")
}

func noSuchObject(stderr []byte) bool {
	lowered := strings.ToLower(string(stderr))
	return strings.Contains(lowered, "no such container") || strings.Contains(lowered, "no such object")
}

// runtimeRefusal classifies why a runtime would not create a container. The
// runtime's own text, which can carry host paths and registry hints, stays in
// the log.
func runtimeRefusal(output []byte) string {
	lowered := strings.ToLower(string(output))
	switch {
	case strings.Contains(lowered, "pull access denied"),
		strings.Contains(lowered, "requested access to the resource is denied"),
		strings.Contains(lowered, "authentication required"),
		strings.Contains(lowered, "unauthorized"):
		return "the image registry refused the pull; this host has no credentials for it"
	case strings.Contains(lowered, "manifest unknown"),
		strings.Contains(lowered, "not found"),
		strings.Contains(lowered, "repository does not exist"):
		return "the image does not exist in the registry"
	case strings.Contains(lowered, "already in use by container"):
		return "a container already holds this instance's name"
	case strings.Contains(lowered, "no space left on device"):
		return "the host is out of disk"
	case strings.Contains(lowered, "no such image"):
		return "the image is not present on this host"
	case strings.TrimSpace(lowered) == "":
		return "the runtime failed without output"
	default:
		return "the runtime rejected the container; see the data-plane log for its output"
	}
}
