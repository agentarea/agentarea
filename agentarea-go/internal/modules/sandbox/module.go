// Package sandbox is the sandbox module: sandboxes: control, placement, warm pool, backends, artifact events.
package sandbox

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// Config is what sandbox reads from the environment (MCPSettings.MANAGER_URL,
// SandboxSettings, AWSSettings.S3_ARTIFACTS_BUCKET).
type Config struct {
	Manager service.Manager
	// Bucket is the artifacts bucket's name, for s3:// manifest URIs.
	Bucket string
}

// LoadConfig reads Config; failures are recorded on l.
func LoadConfig(l *config.Loader) Config {
	inspect, _ := l.OptionalEnv("AGENTAREA_SANDBOX_INSPECT_SECRET")
	file, _ := l.OptionalEnv("AGENTAREA_SANDBOX_FILE_SECRET")
	control, _ := l.OptionalEnv("AGENTAREA_SANDBOX_CONTROL_SECRET")
	c := Config{
		Manager: service.Manager{
			URL:           l.StringEnv("AGENTAREA_MCP_MANAGER_URL", "http://mcp-manager:8000"),
			InspectSecret: inspect, FileSecret: file, ControlSecret: control,
		},
		Bucket: l.StringEnv("AGENTAREA_S3_ARTIFACTS_BUCKET", "artifacts"),
	}
	if err := service.ValidateSecrets(c.Manager); err != nil {
		l.Fail("AGENTAREA_SANDBOX_*_SECRET", err)
	}
	return c
}

// Deps are what sandbox needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Blob is the artifacts bucket.
	Blob blob.Store
	// Harness is the default bucket (AGENTAREA_S3_BUCKET) holding runner
	// tasks' harness files.
	Harness blob.Store
	// Projects is read at call time: projects is built after sandbox, since
	// it serves its file routes over sandbox's store.
	Projects func() service.Projects
	Config   Config
	// APIURL is AGENTAREA_API_URL.
	APIURL string
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	HTTP      *http.Client
	Log       *slog.Logger
}

// Module is sandbox, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Events: store.Events{}, Projects: lateProjects(d.Projects), Blob: d.Blob, Harness: d.Harness, Bucket: d.Config.Bucket,
		Manager: d.Config.Manager, HTTP: d.HTTP, APIURL: d.APIURL, Log: d.Log,
	})}
}

type lateProjects func() service.Projects

func (f lateProjects) IDs(ctx context.Context, ws scope.Workspace) ([]string, error) {
	return f().IDs(ctx, ws)
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "sandbox" }

// Files is the workspace file store the projects routes serve.
func (m *Module) Files() api.Files { return m.svc.Files() }

// Runtime is the sandbox runtime the runs module's tools call.
func (m *Module) Runtime() api.Runtime { return m.svc.Runtime() }

// TaskWorkspace is the task workspace repository.
func (m *Module) TaskWorkspace() api.TaskWorkspace { return m.svc.TaskWorkspace() }

// Processors runs stream processors' code in their sandbox sessions.
func (m *Module) Processors() api.Processors { return m.svc.Processors() }

// RunInputs copies a run's selected files and trigger event into its task workspace.
func (m *Module) RunInputs() api.RunInputs {
	return service.RunInputs{Files: m.svc.Files(), Workspace: m.svc.TaskWorkspace()}
}

// Inventory is the workspace's live sandboxes.
func (m *Module) Inventory() api.Inventory { return m.svc.Inventory() }

// TaskFiles is a task's artifacts and live sandbox files, for the runs routes.
func (m *Module) TaskFiles() api.TaskFiles { return m.svc.TaskFiles() }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.svc))
			return nil
		},
	}
}

// Projects is what sandbox reads about projects: their ids.
type Projects = service.Projects
