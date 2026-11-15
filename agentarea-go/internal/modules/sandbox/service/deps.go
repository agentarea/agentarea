package service

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	projectsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// Events is the artifact_events repository (store.Events).
type Events interface {
	Insert(ctx context.Context, s db.Session, e domain.ArtifactEvent) error
	History(ctx context.Context, s db.Session, path string) ([]domain.ArtifactEvent, error)
	Rename(ctx context.Context, s db.Session, source, destination string, now time.Time) error
}

// Projects lists the workspace's project ids (projects module).
type Projects = projectsapi.Lookup

// Manager is where the sandbox manager answers and the secrets each of its
// trust scopes takes (AGENTAREA_MCP_MANAGER_URL, AGENTAREA_SANDBOX_*).
type Manager struct {
	URL           string
	InspectSecret string
	FileSecret    string
	ControlSecret string
}

// Deps are the service's ports.
type Deps struct {
	DB       db.Database
	Events   Events
	Projects Projects
	// Blob is the artifacts bucket (AGENTAREA_S3_ARTIFACTS_BUCKET).
	Blob blob.Store
	// Harness is AGENTAREA_S3_BUCKET, where a runner copies its task's files
	// (HarnessFiles).
	Harness blob.Store
	// Bucket names Blob in the s3:// URIs task manifests carry.
	Bucket  string
	Manager Manager
	// HTTP reaches the sandbox manager; nil is a client without a timeout.
	HTTP *http.Client
	// APIURL is AGENTAREA_API_URL, the base of file download URLs.
	APIURL string
	// Now is the wall clock events are stamped with; nil is time.Now.
	Now func() time.Time
	// NewHex is uuid4().hex; nil draws a random one.
	NewHex func() string
	// PollInterval is how often an execution is polled; zero is 2 s.
	PollInterval time.Duration
	Log          *slog.Logger
}

// Service is the sandbox module's use cases.
type Service struct {
	d   Deps
	art *Artifacts
	ws  *Workspaces
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.HTTP == nil {
		d.HTTP = &http.Client{}
	}
	if d.PollInterval == 0 {
		d.PollInterval = 2 * time.Second
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.NewHex == nil {
		d.NewHex = randomHex
	}
	s := &Service{d: d}
	s.art = &Artifacts{Blob: d.Blob, Record: s.recordEvent, RecordMove: s.recordMove, Now: d.Now}
	s.ws = &Workspaces{Blob: d.Blob, Bucket: d.Bucket, Record: s.recordEvent, Now: d.Now, NewHex: d.NewHex, Limits: DefaultLimits()}
	return s
}

// Artifacts is the workspace file store.
func (s *Service) Artifacts() *Artifacts { return s.art }

// Workspaces is the task workspace repository.
func (s *Service) Workspaces() *Workspaces { return s.ws }

func workspaceScope(id string) (scope.Workspace, error) { return scope.NewWorkspace(id, "") }

// TaskWorkspace is the task workspace repository as the runs module sees it.
func (s *Service) TaskWorkspace() api.TaskWorkspace { return s.ws }
