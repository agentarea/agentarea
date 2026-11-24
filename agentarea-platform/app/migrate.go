package app

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
	clusterauthn "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

// migrationSets is the core set, then every extension set in the order
// registered.
func (b *Build) migrationSets() []schema.Set {
	sets := []schema.Set{schema.Core()}
	for _, m := range b.ext.Migrations {
		sets = append(sets, schema.Extension(m.Name, m.FS, m.Schema, m.AlembicTable, m.AlembicHead))
	}
	return sets
}

// runMigrate is the migrate role: every set to its latest version, on the
// primary (agentarea-api migrate, then agentarea-enterprise-migrate's
// enterprise stream), then the pending graph migrations, then the
// first-party OAuth clients when this API takes Hydra's tokens.
func (b *Build) runMigrate(ctx context.Context) error {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	dbc := db.LoadConfig(l)
	hydra := clusterauthn.LoadConfig(l)
	conn := connections.LoadConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", "migrate")
	sql, err := schema.Open(dbc.WriteURL())
	if err != nil {
		return err
	}
	defer func() { _ = sql.Close() }()
	for _, set := range b.migrationSets() {
		if err := schema.Migrate(ctx, sql, set); err != nil {
			return err
		}
		log.InfoContext(ctx, "migrated", "set", set.Name)
	}
	if err := b.applyGraphMigrations(ctx, dbc, graphMigrations(log), log); err != nil {
		return err
	}
	return ensureFirstPartyClients(ctx, conn.HydraAdminURL, hydra.HydraAudience, log)
}

// ensureFirstPartyClients registers the CLI and desktop clients in Hydra
// (ADR-0058); without AGENTAREA_AUTH_HYDRA_AUDIENCE this API takes no
// Hydra tokens and there is nothing to register.
func ensureFirstPartyClients(ctx context.Context, adminURL, audience string, log *slog.Logger) error {
	if audience == "" {
		log.InfoContext(ctx, "first-party OAuth clients skipped: AGENTAREA_AUTH_HYDRA_AUDIENCE is not set")
		return nil
	}
	if err := service.EnsureFirstPartyClients(ctx, &http.Client{Timeout: 15 * time.Second}, adminURL, audience); err != nil {
		return fmt.Errorf("first-party OAuth clients: %w", err)
	}
	log.InfoContext(ctx, "first-party OAuth clients registered", "hydra", adminURL)
	return nil
}
