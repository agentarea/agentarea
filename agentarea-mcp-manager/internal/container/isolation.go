package container

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"slices"
	"sort"
	"strings"

	"github.com/agentarea/mcp-manager/internal/models"
)

// isolationRunArgs renders an Isolation into `docker run` flags.
//
// Kept separate from buildContainerRunArgs so the mapping is testable without
// constructing a Manager, and so the Kubernetes backend's equivalent (pod
// security context) can be diffed against one readable list.
func isolationRunArgs(iso models.Isolation) []string {
	var args []string

	if iso.Runtime != "" {
		args = append(args, "--runtime", iso.Runtime)
	}

	for _, capability := range iso.DropCapabilities {
		args = append(args, "--cap-drop", capability)
	}

	if iso.NoNewPrivileges {
		args = append(args, "--security-opt", "no-new-privileges")
	}

	if iso.PidsLimit > 0 {
		args = append(args, "--pids-limit", fmt.Sprintf("%d", iso.PidsLimit))
	}

	if iso.User != "" {
		args = append(args, "--user", iso.User)
	}

	if iso.ReadOnlyRootFilesystem {
		args = append(args, "--read-only")
		// Without writable scratch a read-only rootfs breaks most images, so
		// every declared path becomes a tmpfs rather than a host bind: the
		// workload gets somewhere to write that does not outlive it.
		for _, path := range iso.WritablePaths {
			args = append(args, "--tmpfs", fmt.Sprintf("%s:rw,nosuid,nodev", path))
		}
	}

	return args
}

// ensureRuntimeAvailable fails closed when the workload asked for a container
// runtime this host does not have.
//
// Docker would otherwise reject `--runtime=runsc` at run time with a generic
// error, which reads as "container failed to start" and invites a retry without
// the flag. Checking up front makes the security requirement the explicit
// reason for the refusal.
func (m *Manager) ensureRuntimeAvailable(ctx context.Context, iso models.Isolation) error {
	if !iso.RequiresRuntime() {
		return nil
	}

	available, err := m.availableRuntimes(ctx)
	if err != nil {
		// Do not assume the runtime is present when we cannot tell.
		return fmt.Errorf("cannot verify container runtime %q is installed: %w", iso.Runtime, err)
	}
	if slices.Contains(available, iso.Runtime) {
		return nil
	}
	return &ErrRuntimeUnavailable{Runtime: iso.Runtime, Available: available}
}

// availableRuntimes lists the runtimes the daemon has registered.
func (m *Manager) availableRuntimes(ctx context.Context) ([]string, error) {
	cmd := exec.CommandContext(ctx, m.config.Container.Runtime, "info", "--format", "{{json .Runtimes}}")
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("querying %s info: %w", m.config.Container.Runtime, err)
	}

	var runtimes map[string]any
	if err := json.Unmarshal(out, &runtimes); err != nil {
		return nil, fmt.Errorf("parsing runtime list: %w", err)
	}

	names := make([]string, 0, len(runtimes))
	for name := range runtimes {
		names = append(names, name)
	}
	sort.Strings(names)
	return names, nil
}

// ErrRuntimeUnavailable reports that the isolation a workload asked for cannot
// be provided by this daemon. It is a distinct error so callers can tell an
// unmet security requirement apart from a generic Docker failure.
type ErrRuntimeUnavailable struct {
	Runtime   string
	Available []string
}

func (e *ErrRuntimeUnavailable) Error() string {
	return fmt.Sprintf(
		"container runtime %q is not installed on this host (available: %s); refusing to start without the requested isolation",
		e.Runtime, strings.Join(e.Available, ", "),
	)
}
