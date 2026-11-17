package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
)

// Store is the models tables (store.Store).
type Store interface {
	Config(ctx context.Context, s db.Session, id uuid.UUID) (domain.Config, bool, error)
	Configs(ctx context.Context, s db.Session, f store.ConfigFilter) ([]domain.Config, error)
	InstanceSpecIDs(ctx context.Context, s db.Session, configIDs []uuid.UUID) (map[string][]string, error)
	InsertConfig(ctx context.Context, s db.Session, c domain.Config, now time.Time) error
	UpdateConfig(ctx context.Context, s db.Session, c domain.Config, now time.Time) (bool, error)
	DeleteConfig(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	ProviderSpecIDsWithVisibleConfigs(ctx context.Context, s db.Session) ([]uuid.UUID, error)
	Instance(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error)
	Instances(ctx context.Context, s db.Session, f store.InstanceFilter) ([]domain.Instance, error)
	VisibleInstanceSpecs(ctx context.Context, s db.Session) (map[uuid.UUID]uuid.UUID, error)
	ConfigsOfInstances(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]domain.Config, error)
	InsertInstance(ctx context.Context, s db.Session, in domain.Instance, now time.Time) error
	DeleteInstance(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// Catalog is catalog's provider and model specs.
type Catalog = catalogapi.Specs

// Secrets is the secret rows of a session's workspace, inside its transaction.
type Secrets interface {
	Manager(s db.Session, userID string) ksecrets.Manager
	Secret(ctx context.Context, s db.Session, id string) (ksecrets.Secret, bool, error)
	SecretNamed(ctx context.Context, s db.Session, name string) (ksecrets.Secret, bool, error)
	StageReferences(ctx context.Context, s db.Session, consumerType, consumerID string, refs []ksecrets.Reference) error
}

// Outbound is the deployment's HTTP clients and the policy a member's address is vetted against.
type Outbound interface {
	netguard.Clients
	Guard() *netguard.Guard
}

// Deps are what the models service is built over.
type Deps struct {
	DB      db.Database
	Store   Store
	Catalog Catalog
	Secrets Secrets
	Out     Outbound
	// VideoJobs is the video_generation_jobs table; nil keeps no video jobs.
	VideoJobs VideoJobStore
	// Admin refuses a caller who does not administer the workspace (assert_workspace_admin).
	Admin func(ctx context.Context) error
	// Pricing names the billing currency.
	Pricing func() money.CustomerPricing
	// LocalHost replaces localhost and 127.0.0.1 in an endpoint a call goes to (AGENTAREA_LOCAL_HOST).
	LocalHost string
	// APIURL is the public base built-in icons are served from.
	APIURL string
	Now    func() time.Time
}
