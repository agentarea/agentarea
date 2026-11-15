package events

import (
	"context"
	"log/slog"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

// env is the services the integration tests run against; they skip without them.
type env struct {
	pgURL, redisURL string
}

func testEnv(t *testing.T) env {
	t.Helper()
	e := env{pgURL: os.Getenv("AGENTAREA_TEST_POSTGRES_URL"), redisURL: os.Getenv("AGENTAREA_TEST_REDIS_URL")}
	if e.pgURL == "" || e.redisURL == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL and AGENTAREA_TEST_REDIS_URL not set")
	}
	return e
}

func configFromURL(t *testing.T, raw string) db.Config {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pw, _ := u.User.Password()
	return db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pw,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 5, PoolOverflow: 5, PoolTimeout: 10 * time.Second, PoolRecycle: time.Hour,
	}
}

// freshDatabase is a fresh database at the goose baseline.
func freshDatabase(t *testing.T, e env) *db.Pools {
	t.Helper()
	ctx := context.Background()
	admin := configFromURL(t, e.pgURL)
	ap, err := db.Open(ctx, admin, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	name := "aa_go_events_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	q, release, err := ap.Global().Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_, err = q.Exec(ctx, "CREATE DATABASE "+name)
	release()
	if err != nil {
		t.Fatal(err)
	}
	c := admin
	c.Name = name
	sqlDB, err := schema.Open(c.WriteURL())
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(ctx, sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	p, err := db.Open(ctx, c, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		p.Close()
		if q, release, err := ap.Global().Read(ctx); err == nil {
			_, _ = q.Exec(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
			release()
		}
		ap.Close()
	})
	return p
}

// namespace isolates a test's keys on the shared Valkey.
func namespace() string { return "t" + strings.ReplaceAll(uuid.NewString(), "-", "")[:10] }

func newBroker(t *testing.T, e env, ns string) *Broker {
	t.Helper()
	client, err := NewClient(e.redisURL)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx := context.Background()
		if keys, err := client.Keys(ctx, ns+".*").Result(); err == nil && len(keys) > 0 {
			client.Del(ctx, keys...)
		}
		_ = client.Close()
	})
	b, err := NewBroker(client, ns, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	return b
}
