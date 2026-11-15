package app

import (
	"context"
	"fmt"
	"log/slog"

	kauthz "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	clusterauthz "github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

// graphMigrations is every graph migration, in id order (agentarea_api/graph_migrations.py).
func graphMigrations(log *slog.Logger) []kauthz.GraphMigration {
	return []kauthz.GraphMigration{secrets.SecretOwners(log)}
}

// applyGraphMigrations applies the steps graph_migrations has not recorded, after the schema
// (cli.py _apply_graph_migrations). The graph is opened only when a step has something to
// write: on a fresh install migrate runs before the graph store is reachable.
func (b *Build) applyGraphMigrations(ctx context.Context, dbc db.Config, steps []kauthz.GraphMigration, log *slog.Logger) error {
	pools, err := db.Open(ctx, dbc, log)
	if err != nil {
		return fmt.Errorf("database: %w", err)
	}
	defer pools.Close()
	graph := kauthz.OnceGraph(func(ctx context.Context) (kauthz.Graph, error) {
		l := config.New(b.lookup)
		cfg := kauthz.LoadConfig(l)
		if err := l.Err(); err != nil {
			return nil, fmt.Errorf("configuration: %w", err)
		}
		c, _, err := clusterauthz.Open(ctx, cfg, clusterauthz.Options{Log: log})
		return c, err
	})
	ran, err := kauthz.ApplyPendingGraphMigrations(ctx, clusterauthz.Ledger{Global: pools.Global()}, steps, graph, log)
	if err != nil {
		return err
	}
	log.InfoContext(ctx, "graph migrations applied", "ids", ran)
	return nil
}
