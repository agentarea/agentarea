package ext

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/resourceusage"
)

// Usage samples a runtime takes of its workloads, in source units.
type (
	ResourceSample  = resourceusage.Sample
	Sampler         = resourceusage.Sampler
	ResourceSampler = resourceusage.ResourceSampler
	RuntimeSampler  = resourceusage.RuntimeSampler
)

// Workloads is what a process runs, handed to WorkloadHooks.Attach once, after
// the core built it and before it serves. A field is nil when the process does
// not run that part.
type Workloads struct {
	// Host is set in a data-plane host, which runs the specs a control plane
	// built and holds neither database nor Redis.
	Host bool
	// Redis is the process's Redis; nil in a data-plane host.
	Redis redis.UniversalClient
	// Backend is the MCP backend: docker, kubernetes or dataplane; "" without one.
	Backend string
	// Runtime samples the MCP backend's workloads. On a data-plane host it sees
	// only that host's own workloads.
	Runtime RuntimeSampler
	// SandboxProvider names the sandbox provider the process runs; "" without one.
	SandboxProvider string
	// Allocations samples an external sandbox provider's inventory; nil for a
	// built-in sandbox or a provider that lists none.
	Allocations Sampler
	// Artifacts is the published-artifact store the process serves.
	Artifacts ArtifactStorage
}

// SandboxSession is a value copy of an external provider's sandbox binding.
// CreatedAtSource says how CreatedAt was established ("" is the session record);
// Resources holds only the allocation entries the provider reported.
type SandboxSession struct {
	Provider        string
	ID              string
	WorkspaceID     string
	TaskID          string
	CreatedAt       time.Time
	ExpiresAt       time.Time
	CreatedAtSource string
	Resources       map[string]string
}

// SandboxProvisioning is one phase (started, completed, failed) of a provider
// request; it proves no allocation. RespondedAt is zero for started.
type SandboxProvisioning struct {
	Provider       string
	ProvisioningID string
	WorkspaceID    string
	TaskID         string
	Phase          string
	RequestedAt    time.Time
	RespondedAt    time.Time
}

// SandboxDelete is one provider delete about to be sent.
type SandboxDelete struct {
	Session     SandboxSession
	OperationID string
	Reason      string
	RequestedAt time.Time
}

// SandboxDeleteResult is what the provider answered: Outcome accepted, missing or failed.
type SandboxDeleteResult struct {
	Attempt     SandboxDelete
	Outcome     string
	RespondedAt time.Time
}

// SandboxObserver sees an external provider's sandbox lifecycle. The provider
// delete is sent exactly once between BeforeDelete and AfterDelete, whatever
// BeforeDelete returns; any other error fails the operation that was observed.
type SandboxObserver interface {
	Allocation(ctx context.Context, s SandboxSession) error
	LeaseRenewed(ctx context.Context, s SandboxSession, state string, observedAt time.Time) error
	Missing(ctx context.Context, s SandboxSession) error
	Provisioning(ctx context.Context, p SandboxProvisioning) error
	BeforeDelete(ctx context.Context, d SandboxDelete) error
	AfterDelete(ctx context.Context, r SandboxDeleteResult) error
}

// ResourceRequirements are a container's requests and limits as quantities.
type ResourceRequirements struct {
	Limits   map[string]string `json:"limits,omitempty"`
	Requests map[string]string `json:"requests,omitempty"`
}

// ContainerResources is one container's declared requirements.
type ContainerResources struct {
	Name      string
	Resources ResourceRequirements
}

// TaskPod copies a warm-pool task pod's operational metadata and declared
// resources; the timestamps keep the annotation text exactly as stored.
type TaskPod struct {
	Namespace      string
	Name           string
	UID            string
	WorkspaceID    string
	TaskID         string
	State          string
	AssignedAt     string
	LeaseUntil     string
	CleanupAt      string
	Containers     []ContainerResources
	InitContainers []ContainerResources
	Overhead       map[string]string
}

// TaskPodDelete is one Kubernetes delete about to be sent.
type TaskPodDelete struct {
	Pod         TaskPod
	OperationID string
	Reason      string
	RequestedAt time.Time
}

// TaskPodDeleteResult is what Kubernetes answered: Outcome accepted, missing or failed.
type TaskPodDeleteResult struct {
	Attempt     TaskPodDelete
	Outcome     string
	RespondedAt time.Time
}

// TaskPodObserver sees warm-pool task pods. The delete is sent exactly once
// between BeforeDelete and AfterDelete, whatever BeforeDelete returns.
type TaskPodObserver interface {
	Allocation(ctx context.Context, p TaskPod) error
	Lease(ctx context.Context, p TaskPod) error
	BeforeDelete(ctx context.Context, d TaskPodDelete) error
	AfterDelete(ctx context.Context, r TaskPodDeleteResult) error
}

// StoredArtifact is a published artifact as the object store reports it after
// the write: HeadSize and LastModified come from a HEAD of the stored object,
// SizeBytes from the publication.
type StoredArtifact struct {
	WorkspaceID  string
	TaskID       string
	Bucket       string
	Prefix       string
	ObjectKey    string
	SizeBytes    int64
	HeadSize     int64
	VersionID    string
	ETag         string
	LastModified *time.Time
}

// ArtifactObserver is told about each publication before the publish returns;
// its error fails the publish, the stored object is kept.
type ArtifactObserver interface {
	Published(ctx context.Context, a StoredArtifact) error
}

// StorageScope, StorageObservation and StorageInventory are one complete scan
// of the artifact bucket, by task and kind of content.
type (
	StorageScope       = resourceusage.StorageScope
	StorageObservation = resourceusage.StorageObservation
	StorageInventory   = resourceusage.StorageInventory
)

// ArtifactStorage is the published-artifact store's bucket.
type ArtifactStorage interface {
	Location() (bucket, prefix string)
	// Inventory lists every retained version; a partial scan is an error.
	Inventory(ctx context.Context) (StorageInventory, error)
}
