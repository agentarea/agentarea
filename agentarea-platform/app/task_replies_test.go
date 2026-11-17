package app

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
	cluster "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/events"
)

type replyTasks map[string]runsapi.OutcomeTask

func (t replyTasks) OutcomeTask(_ context.Context, _ scope.Workspace, id string) (runsapi.OutcomeTask, bool, error) {
	x, ok := t[id]
	return x, ok, nil
}

// TestTaskRepliesOverValkey needs AGENTAREA_REDIS_TEST_URL: task reply delivery on the real broker
// sends a task's end to its webhook once and leaves nothing pending.
func TestTaskRepliesOverValkey(t *testing.T) {
	url := os.Getenv("AGENTAREA_REDIS_TEST_URL")
	if url == "" {
		t.Skip("AGENTAREA_REDIS_TEST_URL is not set")
	}
	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatal(err)
	}
	rdb := redis.NewClient(opts)
	t.Cleanup(func() { _ = rdb.Close() })
	ns := "test-delivery-" + uuid.NewString()[:8]
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	b, err := cluster.NewBroker(rdb, ns, log)
	if err != nil {
		t.Fatal(err)
	}
	dd, err := cluster.NewDedup(rdb, ns, replies.DedupPrefix, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	got := make(chan *http.Request, 4)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got <- r
		w.WriteHeader(http.StatusNoContent)
	}))
	t.Cleanup(srv.Close)
	ws, task := uuid.NewString(), uuid.NewString()
	cfg := replies.DefaultConfig()
	cfg.Block = 100 * time.Millisecond
	x, err := replies.New(replies.Deps{
		Broker: b, Dedup: dd, Consumer: "c1", Config: cfg, Log: log,
		Tasks:   replyTasks{task: {ID: task, Owner: "u1", Metadata: map[string]any{"task_webhook": map[string]any{"url": srv.URL, "signed": false}}}},
		Replies: func(context.Context, string) (*domain.Reply, bool, error) { return nil, false, nil },
		Senders: map[string]replies.Sender{"task_webhook": replies.TaskWebhook{Client: srv.Client()}},
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	if err := b.EnsureGroup(ctx, events.TaskEvents, events.DeliveryGroup, "0"); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"tool.call", "task.completed"} {
		fields, err := events.Encode(events.IntegrationEvent{ID: uuid.NewString(), Type: kind, Source: "runs", Time: time.Now().UTC(),
			Subject: task, Data: map[string]any{"task_id": task, "result": "42"}, Extensions: map[string]string{"workspace": ws}})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := b.Submit(ctx, events.TaskEvents, fields, time.Hour); err != nil {
			t.Fatal(err)
		}
	}
	for _, c := range x.Components() {
		if err := c.Start(ctx); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = c.Stop(context.Background()) })
	}
	select {
	case r := <-got:
		if r.Header.Get(replies.EventHeader) != "task.completed" {
			t.Fatalf("webhook got %v", r.Header)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the task webhook was not called")
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		p, err := b.Pending(ctx, events.TaskEvents, events.DeliveryGroup)
		if err != nil {
			t.Fatal(err)
		}
		if p.Count == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("still pending: %+v", p)
		}
		time.Sleep(50 * time.Millisecond)
	}
	select {
	case r := <-got:
		t.Fatalf("a second call: %v", r.Header)
	default:
	}
}
