package secrets

import (
	"fmt"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

// Factory builds workspace-scoped managers for the configured backend
// (secret_manager_factory.py). Configuration is validated by
// kernel.LoadConfig, so building one only fails on a key that does not parse.
type Factory struct {
	cfg       kernel.Config
	cipher    kernel.Cipher
	infisical *InfisicalClient
}

// NewFactory prepares the backend; hc is the HTTP client for Infisical (nil for a default).
func NewFactory(cfg kernel.Config, hc *http.Client) (*Factory, error) {
	f := &Factory{cfg: cfg}
	switch cfg.Backend {
	case kernel.BackendDatabase:
		fernet, err := kernel.NewFernet(cfg.EncryptionKey)
		if err != nil {
			return nil, fmt.Errorf("AGENTAREA_SECRET_ENCRYPTION_KEY: %w", err)
		}
		f.cipher = fernet
	case kernel.BackendInfisical:
		f.infisical = NewInfisicalClient(cfg, hc)
	default:
		return nil, fmt.Errorf("invalid AGENTAREA_SECRET_BACKEND: %q; supported types: 'database', 'infisical'", cfg.Backend)
	}
	return f, nil
}

// Backend is the configured backend name, for the startup log line operators compare across processes.
func (f *Factory) Backend() string { return f.cfg.Backend }

// Manager is the backend for the session's workspace; userID is the actor recorded on writes.
func (f *Factory) Manager(s db.Session, userID string) kernel.Manager {
	if f.infisical != nil {
		return f.infisical.ForWorkspace(s.Workspace().ID())
	}
	return NewDatabase(s, f.cipher, userID)
}

// UserSecrets reads the session's workspace's user-owned secrets.
func (f *Factory) UserSecrets(s db.Session) kernel.UserSecrets {
	if f.infisical != nil {
		return infisicalUserSecrets{s: s, inf: f.infisical.ForWorkspace(s.Workspace().ID())}
	}
	return NewDatabase(s, f.cipher, "")
}

// external is the Infisical backend of ws when one is configured.
func (f *Factory) external(ws scope.Workspace) (kernel.Manager, bool) {
	if f.infisical == nil {
		return nil, false
	}
	return f.infisical.ForWorkspace(ws.ID()), true
}
