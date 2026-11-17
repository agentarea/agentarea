package cluster

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/redis/go-redis/v9"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	kevents "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authn"
	authnstore "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authn/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/obs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/store"
)

// Config is the environment of a cluster deployment.
type Config struct {
	DB      db.Config
	Authn   authn.Config
	Authz   kauthz.Config
	Events  kevents.Config
	Secrets ksecrets.Config
	Blob    kblob.Config
	// OTel, Service, Version and Environment configure telemetry.
	OTel        bool
	Service     string
	Version     string
	Environment string
	Getenv      func(string) string
}

// LoadConfig reads every adapter's configuration; l reports what is missing.
func LoadConfig(l *config.Loader) Config {
	return Config{
		DB:      db.LoadConfig(l),
		Authn:   authn.LoadConfig(l),
		Authz:   kauthz.LoadConfig(l),
		Events:  kevents.LoadConfig(l),
		Secrets: ksecrets.LoadConfig(l),
		Blob:    kblob.LoadConfig(l),
	}
}

// Profile is the adapters one process uses, built once.
type Profile struct {
	DB    *db.Pools
	Graph *authz.Client
	Gate  *authn.Gate
	// LiveTurns and TurnTokens are nil without AGENTAREA_MCP_GATEWAY_SECRET.
	LiveTurns  *authn.LiveTurns
	TurnTokens *authn.TurnTokens
	Redis      *redis.Client
	Broker     *events.Broker
	Blob       *blob.Client
	Secrets    *secrets.Factory
	Telemetry  *obs.Telemetry

	primary *store.Primary
	closers []func() error
}

// Open builds the profile. Nothing waits for a dependency to answer: the
// readiness checks report them.
func Open(ctx context.Context, cfg Config, log *slog.Logger) (_ *Profile, err error) {
	p := &Profile{}
	defer func() {
		if err != nil {
			err = errors.Join(err, p.Close())
		}
	}()
	if p.Telemetry, err = obs.Setup(ctx, obs.Options{
		Enabled: cfg.OTel, Service: cfg.Service, Version: cfg.Version, Environment: cfg.Environment, Getenv: cfg.Getenv,
	}); err != nil {
		return nil, fmt.Errorf("telemetry: %w", err)
	}
	p.closers = append(p.closers, func() error { return p.Telemetry.Shutdown(context.WithoutCancel(ctx)) })
	if p.DB, err = db.Open(ctx, cfg.DB, log); err != nil {
		return nil, fmt.Errorf("database: %w", err)
	}
	p.closers = append(p.closers, func() error { p.DB.Close(); return nil })
	if p.primary, err = store.OpenPrimary(ctx, cfg.DB); err != nil {
		return nil, err
	}
	p.closers = append(p.closers, func() error { p.primary.Close(); return nil })
	if p.Graph, _, err = authz.Open(ctx, cfg.Authz, authz.Options{Log: log}); err != nil {
		return nil, fmt.Errorf("authorization graph: %w", err)
	}
	if p.Redis, err = events.NewClient(cfg.Events.RedisURL); err != nil {
		return nil, fmt.Errorf("redis: %w", err)
	}
	p.closers = append(p.closers, p.Redis.Close)
	if p.Broker, err = events.NewBroker(p.Redis, cfg.Events.Namespace, log); err != nil {
		return nil, fmt.Errorf("event broker: %w", err)
	}
	if p.Secrets, err = secrets.NewFactory(cfg.Secrets, &http.Client{}); err != nil {
		return nil, fmt.Errorf("secrets: %w", err)
	}
	p.Blob = blob.New(cfg.Blob)
	deps := authn.Deps{Store: authnstore.New(p.primary.Querier()), Graph: p.Graph, Log: log}
	if cfg.Authn.GatewaySecret != "" {
		p.LiveTurns = authn.NewLiveTurns(p.Redis)
		deps.LiveTurns = p.LiveTurns
		if p.TurnTokens, err = authn.NewTurnTokens(cfg.Authn.GatewaySecret, nil); err != nil {
			return nil, fmt.Errorf("authentication: %w", err)
		}
	}
	if p.Gate, err = authn.New(cfg.Authn, deps); err != nil {
		return nil, fmt.Errorf("authentication: %w", err)
	}
	return p, nil
}

// Checks are the readiness checks of the profile's dependencies.
func (p *Profile) Checks() []lifecycle.Checker {
	return []lifecycle.Checker{
		check{name: "database", fn: p.DB.Ping},
		check{name: "redis", fn: func(ctx context.Context) error { return p.Redis.Ping(ctx).Err() }},
	}
}

// Close releases what Open built, last first.
func (p *Profile) Close() error {
	var errs []error
	for i := len(p.closers) - 1; i >= 0; i-- {
		errs = append(errs, p.closers[i]())
	}
	p.closers = nil
	return errors.Join(errs...)
}

type check struct {
	name string
	fn   func(ctx context.Context) error
}

func (c check) Name() string                    { return c.name }
func (c check) Check(ctx context.Context) error { return c.fn(ctx) }
