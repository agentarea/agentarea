package app

import (
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/partitions"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster"
)

// partitionInterval is how often the events read model's partitions are kept (partitions.py start).
const partitionInterval = time.Hour

// addPartitions keeps the daily partitions of stream_events, as the Python worker's stream
// runtime did; the events role runs the events view that writes them.
func (b *Build) addPartitions(g *lifecycle.Group, profile *cluster.Profile, log *slog.Logger) error {
	l := config.New(b.lookup)
	cfg := partitions.LoadConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	d := partitions.Deps{DB: profile.DB, Log: log.With("component", "stream event partitions")}
	if cfg.Archive {
		d.Archive = profile.Blob.Default()
	}
	m, err := partitions.New(d, cfg)
	if err != nil {
		return err
	}
	g.Add(m.Component(partitionInterval))
	return nil
}
