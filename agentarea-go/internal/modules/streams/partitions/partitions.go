// Package partitions keeps daily partitions of the events read model (stream_events) ahead of
// today and drops expired days (partitions.py PartitionMaintainer).
//
// A day older than AGENTAREA_EVENT_RETENTION is dropped whole, with its rows of
// stream_event_counts in the same transaction. With AGENTAREA_EVENT_ARCHIVE on, its events are
// first written to the object store, one gzipped JSONL object per workspace; a day the store does
// not take is kept and the next pass tries again. Partition DDL takes an ACCESS EXCLUSIVE lock on
// stream_events, so each step commits on its own and waits at most LockTimeout for that lock; a
// step that runs out is deferred to the next pass.
package partitions

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"regexp"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Config is the read model's retention (EventStreamSettings).
type Config struct {
	Retention time.Duration
	Archive   bool
	Ahead     int
}

// minRetention is the shortest retention that cannot drop a live partition.
const minRetention = 24 * time.Hour

// LoadConfig reads AGENTAREA_EVENT_RETENTION, AGENTAREA_EVENT_ARCHIVE and
// AGENTAREA_EVENT_PARTITIONS_AHEAD.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		Retention: l.DurationEnv("AGENTAREA_EVENT_RETENTION", 7*24*time.Hour),
		Archive:   l.BoolEnv("AGENTAREA_EVENT_ARCHIVE", false),
		Ahead:     l.IntEnv("AGENTAREA_EVENT_PARTITIONS_AHEAD", 7),
	}
	if c.Retention < minRetention {
		l.Fail("AGENTAREA_EVENT_RETENTION", fmt.Errorf("must be at least %s, got %s", minRetention, c.Retention))
	}
	if c.Ahead < 1 {
		l.Fail("AGENTAREA_EVENT_PARTITIONS_AHEAD", errors.New("must be at least 1"))
	}
	return c
}

// passLock is partitions.py's fixed advisory key: one pass at a time across replicas.
const passLock = 798_021_335_641

var partitionName = regexp.MustCompile(`^stream_events_p(\d{8})$`)

// Name is the partition of day.
func Name(day time.Time) string { return "stream_events_p" + day.UTC().Format("20060102") }

// Report is what one pass did.
type Report struct {
	Created  []string
	Dropped  []string
	Deferred []string
	// Archived is the object keys written.
	Archived []string
	// Kept is expired days not dropped because archiving them failed.
	Kept []string
}

// Archive is the object store's write, which is all archiving needs.
type Archive interface {
	Put(ctx context.Context, key string, body io.Reader, size int64, opts blob.PutOptions) error
}

// Deps are the maintainer's ports.
type Deps struct {
	DB db.Database
	// Archive is the store expired days go to (AGENTAREA_S3_BUCKET); required when Config.Archive is on.
	Archive Archive
	Now     func() time.Time
	Log     *slog.Logger
	// LockTimeout bounds each DDL's wait for stream_events; zero is 5s.
	LockTimeout time.Duration
}

// Maintainer runs passes.
type Maintainer struct {
	d   Deps
	cfg Config
	st  store.Partitions
}

// New refuses an archive setting with no store to archive to.
func New(d Deps, cfg Config) (*Maintainer, error) {
	if d.DB == nil {
		return nil, errors.New("partition maintenance needs the database")
	}
	if cfg.Retention < minRetention {
		return nil, fmt.Errorf("AGENTAREA_EVENT_RETENTION must be at least %s, got %s", minRetention, cfg.Retention)
	}
	if cfg.Archive && d.Archive == nil {
		return nil, errors.New("AGENTAREA_EVENT_ARCHIVE is on, but no event archive was given")
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.LockTimeout <= 0 {
		d.LockTimeout = 5 * time.Second
	}
	return &Maintainer{d: d, cfg: cfg}, nil
}

// Component runs a pass at once, failing the process when it fails, then one every interval,
// logging a failed pass and retrying at the next.
func (m *Maintainer) Component(interval time.Duration) lifecycle.Component {
	return lifecycle.Loop("stream event partitions", func(ctx context.Context) error {
		if _, err := m.RunOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("event partition maintenance failed on startup: %w", err)
		}
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return nil
			case <-t.C:
				if _, err := m.RunOnce(ctx); err != nil && ctx.Err() == nil {
					m.d.Log.ErrorContext(ctx, "Event partition maintenance failed; retrying next interval", "error", err)
				}
			}
		}
	})
}

// RunOnce is one pass: partitions from yesterday through Ahead days created, expired days
// archived (when on) and dropped. Another replica's pass in progress makes it a no-op.
func (m *Maintainer) RunOnce(ctx context.Context) (Report, error) {
	var r Report
	today := m.d.Now().UTC().Truncate(24 * time.Hour)
	held, err := m.d.DB.TryLock(ctx, db.Key(passLock), func(ctx context.Context, _ db.Querier) error {
		for offset := -1; offset <= m.cfg.Ahead && len(r.Deferred) == 0; offset++ {
			if err := m.create(ctx, today.AddDate(0, 0, offset), &r); err != nil {
				return err
			}
		}
		if len(r.Deferred) > 0 {
			return nil
		}
		horizon := today.AddDate(0, 0, -int(m.cfg.Retention/(24*time.Hour)))
		days, err := m.partitions(ctx)
		if err != nil {
			return err
		}
		for _, p := range days {
			if len(r.Deferred) > 0 {
				break
			}
			if !p.day.Before(horizon) || !m.archived(ctx, p, &r) {
				continue
			}
			done, err := m.ddl(ctx, p.name, &r, func(ctx context.Context, q db.Querier) error {
				return m.st.DropPartition(ctx, q, p.name, p.day)
			})
			if err != nil {
				return err
			}
			if done {
				r.Dropped = append(r.Dropped, p.name)
			}
		}
		return nil
	})
	if err != nil {
		return r, err
	}
	if !held {
		m.d.Log.InfoContext(ctx, "Event partition maintenance already running in another process; skipping this pass")
		return r, nil
	}
	if len(r.Created)+len(r.Dropped)+len(r.Deferred)+len(r.Kept) > 0 {
		m.d.Log.InfoContext(ctx, "Event partitions", "created", r.Created, "dropped", r.Dropped, "deferred", r.Deferred,
			"kept", r.Kept, "archived", r.Archived)
	}
	return r, nil
}

func (m *Maintainer) create(ctx context.Context, day time.Time, r *Report) error {
	name := Name(day)
	q, release, err := m.d.DB.Global().Read(ctx)
	if err != nil {
		return err
	}
	exists, err := m.st.PartitionExists(ctx, q, name)
	release()
	if err != nil || exists {
		return err
	}
	done, err := m.ddl(ctx, name, r, func(ctx context.Context, q db.Querier) error {
		return m.st.CreatePartition(ctx, q, name, day)
	})
	if done {
		r.Created = append(r.Created, name)
	}
	return err
}

// ddl runs fn in its own short transaction bounded by LockTimeout; false when the wait ran out.
func (m *Maintainer) ddl(ctx context.Context, name string, r *Report, fn func(ctx context.Context, q db.Querier) error) (bool, error) {
	err := m.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		if err := db.SetLockTimeout(ctx, q, m.d.LockTimeout); err != nil {
			return err
		}
		return fn(ctx, q)
	})
	if db.IsLockNotAvailable(err) {
		m.d.Log.WarnContext(ctx, "Event partition deferred to the next pass: lock_timeout ran out waiting for stream_events",
			"partition", name, "lock_timeout", m.d.LockTimeout.String(), "error", err)
		r.Deferred = append(r.Deferred, name)
		return false, nil
	}
	return err == nil, err
}

type partition struct {
	name string
	day  time.Time
}

func (m *Maintainer) partitions(ctx context.Context) ([]partition, error) {
	q, release, err := m.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	names, err := m.st.PartitionNames(ctx, q)
	if err != nil {
		return nil, err
	}
	out := make([]partition, 0, len(names))
	for _, n := range names {
		match := partitionName.FindStringSubmatch(n)
		if match == nil {
			return nil, fmt.Errorf("unexpected stream_events partition %q", n)
		}
		day, err := time.Parse("20060102", match[1])
		if err != nil {
			return nil, fmt.Errorf("unexpected stream_events partition %q: %w", n, err)
		}
		out = append(out, partition{name: n, day: day})
	}
	return out, nil
}

// archived is true when the day may be dropped: archived, or archiving is off.
func (m *Maintainer) archived(ctx context.Context, p partition, r *Report) bool {
	if !m.cfg.Archive {
		return true
	}
	keys, err := m.writeArchive(ctx, p.day)
	if err != nil {
		m.d.Log.ErrorContext(ctx, "Event partition kept: archiving it to the object store failed; the next pass tries again",
			"partition", p.name, "error", err)
		r.Kept = append(r.Kept, p.name)
		return false
	}
	r.Archived = append(r.Archived, keys...)
	return true
}
