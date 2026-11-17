package app

import (
	"context"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
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
// enterprise stream), then the pending graph migrations.
func (b *Build) runMigrate(ctx context.Context) error {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	dbc := db.LoadConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", "migrate")
	conn, err := schema.Open(dbc.WriteURL())
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close() }()
	for _, set := range b.migrationSets() {
		if err := schema.Migrate(ctx, conn, set); err != nil {
			return err
		}
		log.InfoContext(ctx, "migrated", "set", set.Name)
	}
	return b.applyGraphMigrations(ctx, dbc, graphMigrations(log), log)
}
