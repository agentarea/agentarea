package claim

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

const defaultTTL = 60 * time.Second

// RedisClaimer provides distributed SETNX-based claim semantics so that only
// one worker processes a given trigger at a time.
type RedisClaimer struct {
	client   *redis.Client
	workerID string
	ttl      time.Duration
}

// NewRedisClaimer creates a new RedisClaimer.
func NewRedisClaimer(client *redis.Client, workerID string) *RedisClaimer {
	return &RedisClaimer{
		client:   client,
		workerID: workerID,
		ttl:      defaultTTL,
	}
}

func claimKey(triggerID string) string {
	return fmt.Sprintf("polling:claim:%s", triggerID)
}

// TryClaim attempts to claim the trigger using SET NX PX.
// Returns (true, nil) if the claim was acquired or re-acquired,
// (false, nil) if already claimed by another worker.
func (c *RedisClaimer) TryClaim(ctx context.Context, triggerID string) (bool, error) {
	key := claimKey(triggerID)
	ok, err := c.client.SetNX(ctx, key, c.workerID, c.ttl).Result()
	if err != nil {
		return false, fmt.Errorf("redis SETNX: %w", err)
	}
	if ok {
		return true, nil
	}
	// Key exists — check if we already own it (e.g. after process restart)
	val, err := c.client.Get(ctx, key).Result()
	if err != nil {
		return false, nil
	}
	if val == c.workerID {
		// Re-acquire: refresh TTL
		c.client.PExpire(ctx, key, c.ttl)
		return true, nil
	}
	return false, nil
}

// Renew refreshes the TTL on our claim.  Fails silently if the key was lost.
func (c *RedisClaimer) Renew(ctx context.Context, triggerID string) error {
	key := claimKey(triggerID)
	val, err := c.client.Get(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		// Key expired; nothing to renew
		return nil
	}
	if err != nil {
		return fmt.Errorf("redis GET: %w", err)
	}
	if val != c.workerID {
		// Claimed by someone else; do not renew
		return nil
	}
	if err := c.client.PExpire(ctx, key, c.ttl).Err(); err != nil {
		return fmt.Errorf("redis PEXPIRE: %w", err)
	}
	return nil
}

// releaseLua atomically deletes the key only if it still belongs to this worker.
var releaseLua = redis.NewScript(`
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
`)

// Release removes the claim if it still belongs to this worker.
func (c *RedisClaimer) Release(ctx context.Context, triggerID string) error {
	if err := releaseLua.Run(ctx, c.client, []string{claimKey(triggerID)}, c.workerID).Err(); err != nil && !errors.Is(err, redis.Nil) {
		return fmt.Errorf("redis release: %w", err)
	}
	return nil
}
