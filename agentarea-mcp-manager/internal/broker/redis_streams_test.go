package broker

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"
)

func newTestBroker(t *testing.T) (*RedisStreams, *redis.Client) {
	t.Helper()
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return NewRedisStreams(client, "agentarea"), client
}

func TestSubmitWritesUnderNamespace(t *testing.T) {
	b, client := newTestBroker(t)
	ctx := context.Background()

	id, err := b.Submit(ctx, "domain.events.x", map[string]string{"ce_type": "x"}, time.Hour)
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}

	entries, err := client.XRange(ctx, "agentarea.domain.events.x", "-", "+").Result()
	if err != nil {
		t.Fatalf("XRANGE: %v", err)
	}
	if len(entries) != 1 || entries[0].ID != id {
		t.Fatalf("entries = %v, want one entry with id %s", entries, id)
	}
	if got := entries[0].Values["ce_type"]; got != "x" {
		t.Errorf("ce_type = %v, want x", got)
	}
}

type recordArgs struct{ args [][]any }

func (r *recordArgs) BeforeProcess(ctx context.Context, cmd redis.Cmder) (context.Context, error) {
	r.args = append(r.args, cmd.Args())
	return ctx, nil
}

func (r *recordArgs) AfterProcess(context.Context, redis.Cmder) error { return nil }

func (r *recordArgs) BeforeProcessPipeline(ctx context.Context, _ []redis.Cmder) (context.Context, error) {
	return ctx, nil
}

func (r *recordArgs) AfterProcessPipeline(context.Context, []redis.Cmder) error { return nil }

func TestSubmitTrimsByRetentionApproximately(t *testing.T) {
	b, client := newTestBroker(t)
	recorder := &recordArgs{}
	client.AddHook(recorder)

	before := time.Now()
	if _, err := b.Submit(context.Background(), "domain.events.x", map[string]string{"k": "v"}, time.Hour); err != nil {
		t.Fatalf("Submit: %v", err)
	}

	if len(recorder.args) != 1 {
		t.Fatalf("commands = %v, want one XADD", recorder.args)
	}
	args := recorder.args[0]
	if len(args) < 5 || args[0] != "xadd" || args[1] != "agentarea.domain.events.x" || args[2] != "minid" || args[3] != "~" {
		t.Fatalf("args = %v, want xadd <key> minid ~ <id> ...", args)
	}
	var ms int64
	if _, err := fmt.Sscanf(args[4].(string), "%d-0", &ms); err != nil {
		t.Fatalf("minid %v: %v", args[4], err)
	}
	if want := before.Add(-time.Hour).UnixMilli(); ms < want-1000 || ms > want+1000 {
		t.Errorf("minid = %d ms, want about %d", ms, want)
	}
}

func TestSubmitRejectsNonPositiveRetention(t *testing.T) {
	b, _ := newTestBroker(t)
	if _, err := b.Submit(context.Background(), "domain.events.x", map[string]string{}, 0); err == nil {
		t.Fatal("Submit with zero retention returned nil error")
	}
}

func TestMinID(t *testing.T) {
	now := time.UnixMilli(10_000)
	if got := MinID(now, 4*time.Second); got != "6000-0" {
		t.Errorf("MinID = %s, want 6000-0", got)
	}
}
