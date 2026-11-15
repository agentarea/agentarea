package quota

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

func TestTheWindowSlidesOverThePreviousMinute(t *testing.T) {
	url := os.Getenv("AGENTAREA_TEST_REDIS_URL")
	if url == "" {
		t.Skip("AGENTAREA_TEST_REDIS_URL is not set")
	}
	opt, err := redis.ParseURL(url)
	if err != nil {
		t.Fatal(err)
	}
	rdb := redis.NewClient(opt)
	defer func() { _ = rdb.Close() }()
	q, err := New(rdb, "test-"+uuid.NewString()[:8])
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	ws := uuid.NewString()
	start := time.Unix(1_800_000_000/60*60, 0)
	for i := range 3 {
		if ok, err := q.take(ctx, ws, 3, start.Add(50*time.Second)); err != nil || !ok {
			t.Fatalf("event %d refused: %v", i, err)
		}
	}
	if ok, _ := q.take(ctx, ws, 3, start.Add(55*time.Second)); ok {
		t.Fatal("the fourth event in a minute of three was admitted")
	}
	if ok, _ := q.take(ctx, ws, 3, start.Add(70*time.Second)); ok {
		t.Fatal("ten seconds into the next minute five-sixths of the last minute still count")
	}
	if ok, _ := q.take(ctx, ws, 3, start.Add(110*time.Second)); !ok {
		t.Fatal("near the end of the next minute the window has room again")
	}
	if ok, _ := q.take(ctx, uuid.NewString(), 3, start.Add(55*time.Second)); !ok {
		t.Fatal("another workspace shares the count")
	}
}
