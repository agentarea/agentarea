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

// ErrClaimLost means the claim expired or another worker now holds it.
var ErrClaimLost = errors.New("claim lost")

// renewLua atomically refreshes the TTL only if the key still belongs to this worker.
var renewLua = redis.NewScript(`
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
`)

// Renew refreshes the TTL on our claim. Returns ErrClaimLost if the claim
// expired or is held by another worker, so the caller stops polling.
func (c *RedisClaimer) Renew(ctx context.Context, triggerID string) error {
	renewed, err := renewLua.Run(ctx, c.client, []string{claimKey(triggerID)}, c.workerID, c.ttl.Milliseconds()).Int()
	if err != nil {
		return fmt.Errorf("redis renew: %w", err)
	}
	if renewed == 0 {
		return fmt.Errorf("renew %s: %w", triggerID, ErrClaimLost)
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
