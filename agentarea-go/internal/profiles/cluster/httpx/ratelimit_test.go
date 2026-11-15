package httpx

import (
	"context"
	"os"
	"testing"

	"github.com/redis/go-redis/v9"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

func TestRateLimiterAgainstValkey(t *testing.T) {
	url := os.Getenv("AGENTAREA_TEST_REDIS_URL")
	if url == "" {
		t.Skip("AGENTAREA_TEST_REDIS_URL is not set")
	}
	rl, client, err := DialRateLimiter(url)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = client.Close() }()
	ctx := context.Background()
	identity := "ip:" + t.Name()
	key := kernel.RateLimitKey("test", identity)
	client.Del(ctx, key)
	defer client.Del(ctx, key)

	for i := range 3 {
		allowed, _, err := rl.Take(ctx, "test", identity, 3)
		if err != nil || !allowed {
			t.Fatalf("take %d: allowed=%v err=%v", i, allowed, err)
		}
	}
	allowed, retry, err := rl.Take(ctx, "test", identity, 3)
	if err != nil || allowed || retry < 1 || retry > 20 {
		t.Fatalf("over the limit: allowed=%v retry=%d err=%v", allowed, retry, err)
	}
	ttl, err := client.TTL(ctx, key).Result()
	if err != nil || ttl.Seconds() <= 0 || ttl.Seconds() > kernel.RateLimitBucketTTL {
		t.Fatalf("ttl %v %v", ttl, err)
	}
	fields, err := client.HGetAll(ctx, key).Result()
	if err != nil || fields["tokens"] == "" || fields["updated_at"] == "" {
		t.Fatalf("bucket %v %v", fields, err)
	}
	allowed, retry, err = rl.Take(ctx, "test", "ip:zero", 0)
	if err != nil || allowed || retry != 60 {
		t.Fatalf("zero capacity: %v %d %v", allowed, retry, err)
	}
}

func TestRateLimiterUnreachableFailsOpen(t *testing.T) {
	rl, client, err := DialRateLimiter("redis://127.0.0.1:1")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = client.Close() }()
	if err := kernel.EnforceRateLimit(context.Background(), rl, nil, "test", "ip:x", 1); err != nil {
		t.Fatalf("unreachable limiter refused: %v", err)
	}
}

var _ redis.Scripter = (*redis.Client)(nil)
