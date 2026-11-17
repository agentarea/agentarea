package app

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	kevents "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/events"
)

func TestCommandsAreListedAndCannotBeShadowed(t *testing.T) {
	b, out := quiet()
	_ = b.Run(context.Background(), nil)
	for _, c := range commands() {
		if !strings.Contains(out.String(), c.name) {
			t.Errorf("usage does not list %s", c.name)
		}
	}
	shadow, _ := quiet(ext.WithCommand(ext.Command{Name: "dlq-replay", Run: func(context.Context, ext.Deps, []string) error { return nil }}))
	if err := shadow.Run(context.Background(), []string{"dlq-replay"}); err == nil || !strings.Contains(err.Error(), "shadows") {
		t.Fatalf("an extension took a core command: %v", err)
	}
}

func TestDLQReplayUsage(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(map[string]string{"AGENTAREA_REDIS_URL": "redis://127.0.0.1:1"})
	for _, args := range [][]string{{"dlq-replay"}, {"dlq-replay", "a", "b"}, {"dlq-replay", "--bogus", "x"}} {
		if err := b.Run(context.Background(), args); !errors.Is(err, ErrUsage) {
			t.Errorf("%v: %v", args, err)
		}
	}
	err := b.Run(context.Background(), []string{"dlq-replay", "nope.dlq"})
	if !errors.Is(err, ErrUsage) || !strings.Contains(err.Error(), "streams.events.router.dlq") {
		t.Fatalf("unknown dlq: %v", err)
	}
}

// TestDLQReplayMovesDeadLettersBack needs AGENTAREA_REDIS_TEST_URL.
func TestDLQReplayMovesDeadLettersBack(t *testing.T) {
	redisURL := os.Getenv("AGENTAREA_REDIS_TEST_URL")
	if redisURL == "" {
		t.Skip("AGENTAREA_REDIS_TEST_URL not set")
	}
	ctx := context.Background()
	ns := "dlq" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	client, err := events.NewClient(redisURL)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = client.Close() }()
	broker, err := events.NewBroker(client, ns, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	dlq := kevents.DeadLetterTopic(kevents.StreamEvents, kevents.RouterGroup)
	for _, source := range []string{"streams.events.1", "streams.events.0", "elsewhere"} {
		if _, err := broker.Submit(ctx, dlq, map[string]string{"ce_id": source, kevents.DeadLetterSourceField: source,
			kevents.DeadLetterReasonField: "boom"}, kevents.DeadLetterRetention); err != nil {
			t.Fatal(err)
		}
	}
	b, out := quiet()
	b.lookup = mapLookup(map[string]string{"AGENTAREA_REDIS_URL": redisURL, "AGENTAREA_EVENT_NAMESPACE": ns, "AGENTAREA_EVENT_PARTITIONS": "2"})
	if err := b.Run(ctx, []string{"dlq-replay", dlq, "--end", "+"}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Replayed 2 dead letters from "+dlq+"; 1 left in place") {
		t.Fatalf("output %q", out.String())
	}
	for _, p := range []string{"streams.events.0", "streams.events.1"} {
		msgs, err := broker.ReadRange(ctx, p, "-", "+", 10)
		if err != nil || len(msgs) != 1 || msgs[0].Fields["ce_id"] != p {
			t.Fatalf("%s holds %v %v", p, msgs, err)
		}
		if _, ok := msgs[0].Fields[kevents.DeadLetterReasonField]; ok {
			t.Errorf("replayed message keeps the dead-letter fields: %v", msgs[0].Fields)
		}
	}
	if n, _ := broker.Length(ctx, dlq); n != 1 {
		t.Fatalf("dlq holds %d", n)
	}
}

func TestInitBucketsCreatesAndAllowsBrowserUploads(t *testing.T) {
	var mu sync.Mutex
	got := map[string]string{}
	s3 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		got[r.Method+" "+r.URL.Path+"?"+r.URL.RawQuery] = string(body)
		mu.Unlock()
		if r.URL.Path == "/artifacts" && r.URL.RawQuery == "" {
			w.WriteHeader(http.StatusConflict)
			_, _ = io.WriteString(w, `<Error><Code>BucketAlreadyOwnedByYou</Code><Message>mine</Message></Error>`)
		}
	}))
	defer s3.Close()
	vars := map[string]string{
		"AGENTAREA_S3_ENDPOINT": s3.URL, "AGENTAREA_S3_ACCESS_KEY": "k", "AGENTAREA_S3_SECRET_KEY": "s",
		"AGENTAREA_S3_BUCKETS": "documents, artifacts", "AGENTAREA_S3_CORS_ORIGINS": "http://localhost:3000",
	}
	b, _ := quiet()
	b.lookup = mapLookup(vars)
	if err := b.Run(context.Background(), []string{"init-buckets"}); err != nil {
		t.Fatal(err)
	}
	keys := slices.Sorted(maps.Keys(got))
	want := []string{"PUT /artifacts?", "PUT /artifacts?cors=", "PUT /documents?", "PUT /documents?cors="}
	if !slices.Equal(keys, want) {
		t.Fatalf("requests %v", keys)
	}
	if c := got["PUT /documents?cors="]; !strings.Contains(c, "<AllowedOrigin>http://localhost:3000</AllowedOrigin>") ||
		!strings.Contains(c, "<AllowedMethod>PUT</AllowedMethod>") || !strings.Contains(c, "<ExposeHeader>ETag</ExposeHeader>") {
		t.Fatalf("cors %s", c)
	}

	vars["AGENTAREA_S3_CORS_ORIGINS"] = "*"
	if err := b.Run(context.Background(), []string{"init-buckets"}); err == nil || !strings.Contains(err.Error(), "explicit origins") {
		t.Fatalf("'*' accepted: %v", err)
	}
	delete(vars, "AGENTAREA_S3_BUCKETS")
	if err := b.Run(context.Background(), []string{"init-buckets"}); err == nil || !strings.Contains(err.Error(), "AGENTAREA_S3_BUCKETS") {
		t.Fatalf("no buckets: %v", err)
	}
}
