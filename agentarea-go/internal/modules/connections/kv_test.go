package connections

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

func TestRedisKVGetDelReadsOnce(t *testing.T) {
	addr := os.Getenv("AGENTAREA_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("AGENTAREA_TEST_REDIS_ADDR is not set")
	}
	c := redis.NewClient(&redis.Options{Addr: addr})
	t.Cleanup(func() { _ = c.Close() })
	kv := RedisKV(c)
	ctx := context.Background()
	if err := kv.SetEx(ctx, "oauth_state:t1", "v", time.Minute); err != nil {
		t.Fatal(err)
	}
	if v, ok, err := kv.GetDel(ctx, "oauth_state:t1"); err != nil || !ok || v != "v" {
		t.Fatalf("first read %q %v %v", v, ok, err)
	}
	if _, ok, err := kv.GetDel(ctx, "oauth_state:t1"); err != nil || ok {
		t.Fatalf("second read %v %v", ok, err)
	}
	if RedisKV(nil) != nil {
		t.Fatal("nil client gives a store")
	}
}
