package models

// Isolation is the resolved sandboxing applied to one workload container.
//
// It is a property of WHAT is being run, not of WHERE it runs: an MCP server
// from the public catalog and an agent's bash session are both third-party code
// and both need confinement, whether the data plane is Docker or Kubernetes.
// The Kubernetes backend has always expressed this through the pod security
// context; carrying it here is what lets the Docker backend honour the same
// contract instead of silently dropping it.
//
// A zero value means "no confinement declared" and must never be treated as
// "confinement not needed" — callers resolve a named profile first.
type Isolation struct {
	// Profile is the tier this was resolved from, kept for logging and events.
	Profile string `json:"profile,omitempty"`

	// Runtime selects the container runtime (Docker `--runtime`, Kubernetes
	// runtimeClassName), e.g. "runsc" for gVisor. Empty means the daemon
	// default, which is normally runc and provides no extra isolation.
	Runtime string `json:"runtime,omitempty"`

	// DropCapabilities lists Linux capabilities to drop; ["ALL"] is the norm.
	DropCapabilities []string `json:"drop_capabilities,omitempty"`

	// NoNewPrivileges blocks setuid/setgid escalation inside the container.
	NoNewPrivileges bool `json:"no_new_privileges,omitempty"`

	// ReadOnlyRootFilesystem mounts the image read-only. WritablePaths get
	// tmpfs mounts so the workload still has scratch space.
	ReadOnlyRootFilesystem bool `json:"read_only_root_filesystem,omitempty"`

	// WritablePaths are the only paths writable under a read-only rootfs.
	WritablePaths []string `json:"writable_paths,omitempty"`

	// PidsLimit caps process count, bounding fork-bomb blast radius. 0 = unset.
	PidsLimit int `json:"pids_limit,omitempty"`

	// User is the uid[:gid] the entrypoint runs as. Empty keeps the image's own
	// USER, which is frequently root.
	User string `json:"user,omitempty"`
}

// RequiresRuntime reports whether this isolation depends on a non-default
// container runtime being installed. Callers use it to fail closed rather than
// starting an unconfined container when the runtime is missing.
func (i Isolation) RequiresRuntime() bool {
	return i.Runtime != ""
}
