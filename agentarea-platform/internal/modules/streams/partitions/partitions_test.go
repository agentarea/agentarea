package partitions_test

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/partitions"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

// isolated is a fresh database migrated to the core schema: a pass drops every partition past
// retention, which would break other packages' tests sharing one database.
func isolated(t *testing.T) *db.Pools {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	ctx := context.Background()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	admin, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	name := "partitions_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.ExecContext(context.Background(), "DROP DATABASE IF EXISTS "+name+" WITH (FORCE)")
		_ = admin.Close()
	})
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatal(err)
	}
	pw, _ := u.User.Password()
	cfg := db.Config{Host: u.Hostname(), Port: port, Name: name, User: u.User.Username(), Password: pw, SSLMode: "disable",
		PoolSize: 4, PoolOverflow: 4, PoolTimeout: 10 * time.Second}
	sqlDB, err := schema.Open(cfg.WriteURL())
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(ctx, sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pools, err := db.Open(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

func names(t *testing.T, d *db.Pools) []string {
	t.Helper()
	q, release, err := d.Global().Read(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	rows, err := q.Query(context.Background(), `SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
		JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'stream_events' ORDER BY 1`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			t.Fatal(err)
		}
		out = append(out, n)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return out
}

func exec(t *testing.T, d *db.Pools, sql string, args ...any) {
	t.Helper()
	if err := d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, sql, args...)
		return err
	}); err != nil {
		t.Fatal(err)
	}
}

func streamIn(t *testing.T, d *db.Pools, ws string) uuid.UUID {
	t.Helper()
	exec(t, d, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, ws, "ws-"+uuid.NewString()[:8])
	id := uuid.New()
	exec(t, d, `INSERT INTO streams (id, workspace_id, created_by, name, kind) VALUES ($1, $2, 'u', 's', 'inbound')`, id, ws)
	return id
}

type memArchive struct {
	mu   sync.Mutex
	objs map[string][]byte
	fail bool
}

func (a *memArchive) Put(_ context.Context, key string, body io.Reader, _ int64, opts blob.PutOptions) error {
	if a.fail {
		return errors.New("store down")
	}
	if opts.ContentType != "application/gzip" {
		return errors.New("content type " + opts.ContentType)
	}
	b, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.objs == nil {
		a.objs = map[string][]byte{}
	}
	a.objs[key] = b
	return nil
}

func lines(t *testing.T, gz []byte) []map[string]any {
	t.Helper()
	r, err := gzip.NewReader(bytes.NewReader(gz))
	if err != nil {
		t.Fatal(err)
	}
	var out []map[string]any
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		var m map[string]any
		if err := json.Unmarshal(sc.Bytes(), &m); err != nil {
			t.Fatal(err)
		}
		out = append(out, m)
	}
	return out
}

func TestPassCreatesAheadAndDropsExpiredDays(t *testing.T) {
	d := isolated(t)
	ctx := context.Background()
	now := time.Now().UTC().AddDate(0, 0, 30)
	m, err := partitions.New(partitions.Deps{DB: d, Now: func() time.Time { return now }}, partitions.Config{Retention: 7 * 24 * time.Hour, Ahead: 3})
	if err != nil {
		t.Fatal(err)
	}
	ws := uuid.NewString()
	stream := streamIn(t, d, ws)
	expired := time.Now().UTC()
	exec(t, d, `INSERT INTO stream_event_counts (workspace_id, created_by, stream_id, day, source_type, count) VALUES ($1, 'u', $2, $3::date, 'webhook', 1)`,
		ws, stream, expired.Format(time.DateOnly))

	r, err := m.RunOnce(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var want []string
	for off := -1; off <= 3; off++ {
		want = append(want, partitions.Name(now.AddDate(0, 0, off)))
	}
	if !slices.Equal(r.Created, want) {
		t.Fatalf("created %v, want %v", r.Created, want)
	}
	got := names(t, d)
	for _, n := range got {
		dd, _ := time.Parse("20060102", strings.TrimPrefix(n, "stream_events_p"))
		if dd.Before(now.UTC().Truncate(24*time.Hour).AddDate(0, 0, -7)) {
			t.Errorf("expired partition %s kept", n)
		}
	}
	if len(r.Dropped) == 0 {
		t.Fatal("the baseline's partitions, 30 days old, were not dropped")
	}
	var counts int
	q, release, _ := d.Global().Read(ctx)
	_ = q.QueryRow(ctx, `SELECT count(*) FROM stream_event_counts WHERE workspace_id = $1`, ws).Scan(&counts)
	release()
	if counts != 0 {
		t.Fatalf("counts of a dropped day kept: %d", counts)
	}

	again, err := m.RunOnce(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(again.Created)+len(again.Dropped) != 0 {
		t.Fatalf("second pass changed things: %+v", again)
	}

	exec(t, d, `CREATE TABLE stream_events_odd PARTITION OF stream_events FOR VALUES FROM ('2001-01-01') TO ('2001-01-02')`)
	if _, err := m.RunOnce(ctx); err == nil || !strings.Contains(err.Error(), "stream_events_odd") {
		t.Fatalf("an unexpected partition passed: %v", err)
	}
}

func TestExpiredDayIsArchivedPerWorkspaceBeforeItIsDropped(t *testing.T) {
	d := isolated(t)
	ctx := context.Background()
	now := time.Now().UTC().Truncate(24*time.Hour).AddDate(0, 0, 20)
	old := now.AddDate(0, 0, -9)
	if err := d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, `CREATE TABLE IF NOT EXISTS `+partitions.Name(old)+` PARTITION OF stream_events FOR VALUES FROM ('`+
			old.Format(time.DateOnly)+` 00:00:00+00') TO ('`+old.AddDate(0, 0, 1).Format(time.DateOnly)+` 00:00:00+00')`)
		return err
	}); err != nil {
		t.Fatal(err)
	}
	wsA, wsB := "aaa-"+uuid.NewString(), "bbb/"+uuid.NewString()
	streamA, streamB := streamIn(t, d, wsA), streamIn(t, d, wsB)
	insert := `INSERT INTO stream_events (sequence, received_at, stream_id, event_id, event_key, kind, source, occurred_at, data, workspace_id, created_by, attachments, reacted)
		VALUES ($1, $2, $3, $4, $5, 'order.paid', 'src', $2, '{"n":1}', $6, 'u', '[{"name":"a.txt","ref":"files/a.txt","stored":true}]', 1)`
	for i := range 501 {
		exec(t, d, insert, i+1, old.Add(time.Hour), streamA, uuid.New(), "k"+uuid.NewString(), wsA)
	}
	exec(t, d, insert, 1, old.Add(2*time.Hour), streamB, uuid.New(), "kb", wsB)

	archive := &memArchive{fail: true}
	m, err := partitions.New(partitions.Deps{DB: d, Archive: archive, Now: func() time.Time { return now }},
		partitions.Config{Retention: 7 * 24 * time.Hour, Ahead: 1, Archive: true})
	if err != nil {
		t.Fatal(err)
	}
	r, err := m.RunOnce(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(r.Kept, partitions.Name(old)) || slices.Contains(r.Dropped, partitions.Name(old)) {
		t.Fatalf("a day the store refused was not kept: %+v", r)
	}

	archive.fail = false
	r, err = m.RunOnce(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(r.Dropped, partitions.Name(old)) {
		t.Fatalf("archived day not dropped: %+v", r)
	}
	keyA, keyB := partitions.ArchiveKey(wsA, old), partitions.ArchiveKey(wsB, old)
	if !strings.Contains(keyB, "bbb%2F") {
		t.Fatalf("workspace id not quoted: %s", keyB)
	}
	a := lines(t, archive.objs[keyA])
	b := lines(t, archive.objs[keyB])
	if len(a) != 501 || len(b) != 1 {
		t.Fatalf("archived %d and %d events", len(a), len(b))
	}
	if a[0]["sequence"].(float64) != 1 || a[500]["sequence"].(float64) != 501 || a[0]["type"] != "order.paid" ||
		a[0]["specversion"] != "1.0" || a[0]["workspace_id"] != wsA || a[0]["reacted"].(float64) != 1 {
		t.Fatalf("archive line %v", a[0])
	}
	if atts := a[0]["attachments"].([]any); len(atts) != 1 || atts[0].(map[string]any)["ref"] != "files/a.txt" {
		t.Fatalf("attachments %v", a[0]["attachments"])
	}
}

func TestArchiveNeedsAStore(t *testing.T) {
	if _, err := partitions.New(partitions.Deps{DB: &db.Pools{}}, partitions.Config{Retention: 7 * 24 * time.Hour, Archive: true, Ahead: 1}); err == nil {
		t.Fatal("archive on with no store accepted")
	}
}

func TestDDLWaitingPastLockTimeoutIsDeferred(t *testing.T) {
	d := isolated(t)
	ctx := context.Background()
	now := time.Now().UTC().AddDate(0, 0, 40)
	m, err := partitions.New(partitions.Deps{DB: d, Now: func() time.Time { return now }, LockTimeout: 200 * time.Millisecond},
		partitions.Config{Retention: 365 * 24 * time.Hour, Ahead: 2})
	if err != nil {
		t.Fatal(err)
	}
	holding, release := make(chan struct{}), make(chan struct{})
	done := make(chan error, 1)
	go func() {
		done <- d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			if _, err := q.Exec(ctx, `LOCK TABLE stream_events IN ACCESS SHARE MODE`); err != nil {
				return err
			}
			close(holding)
			<-release
			return nil
		})
	}()
	<-holding
	r, err := m.RunOnce(ctx)
	close(release)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Deferred) != 1 || r.Deferred[0] != partitions.Name(now.AddDate(0, 0, -1)) || len(r.Created) != 0 {
		t.Fatalf("report %+v", r)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	r, err = m.RunOnce(ctx)
	if err != nil || len(r.Created) != 4 {
		t.Fatalf("next pass: %+v %v", r, err)
	}
}

func TestRetentionUnderADayIsRefused(t *testing.T) {
	for _, retention := range []time.Duration{0, -time.Hour, 23 * time.Hour} {
		if _, err := partitions.New(partitions.Deps{DB: &db.Pools{}}, partitions.Config{Retention: retention, Ahead: 1}); err == nil ||
			!strings.Contains(err.Error(), "AGENTAREA_EVENT_RETENTION") {
			t.Errorf("retention %s accepted: %v", retention, err)
		}
		l := config.FromMap(map[string]string{"AGENTAREA_EVENT_RETENTION": retention.String()})
		partitions.LoadConfig(l)
		if err := l.Err(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_EVENT_RETENTION") {
			t.Errorf("configured retention %s accepted: %v", retention, err)
		}
	}
	l := config.FromMap(map[string]string{"AGENTAREA_EVENT_RETENTION": "24h"})
	partitions.LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Errorf("one day refused: %v", err)
	}
}
