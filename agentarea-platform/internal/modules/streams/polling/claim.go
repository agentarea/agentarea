package polling

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// ErrClaimLost means the claim expired or another replica holds it now.
var ErrClaimLost = errors.New("claim lost")

// Claimer lets one replica at a time act for a source.
type Claimer interface {
	TryClaim(ctx context.Context, id string) (bool, error)
	Renew(ctx context.Context, id string) error
	Release(ctx context.Context, id string) error
}

const claimTTL = 60 * time.Second

const renewScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
`

const releaseScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
`

// RedisClaimer is a SET NX lease per source, owned by one replica's worker id. Keys are
// polling:claim:<id> in the deployment's Redis, the event service's keys, so a replica of
// either respects the other's lease during the cutover.
type RedisClaimer struct {
	client   *redis.Client
	workerID string
	ttl      time.Duration
}

// NewRedisClaimer leases sources for workerID (AGENTAREA_EVENT_WORKER_ID).
func NewRedisClaimer(client *redis.Client, workerID string) *RedisClaimer {
	return &RedisClaimer{client: client, workerID: workerID, ttl: claimTTL}
}

func claimKey(id string) string { return "polling:claim:" + id }

// TryClaim takes the lease, or takes it back after a restart of this worker.
func (c *RedisClaimer) TryClaim(ctx context.Context, id string) (bool, error) {
	key := claimKey(id)
	ok, err := c.client.SetNX(ctx, key, c.workerID, c.ttl).Result()
	if err != nil {
		return false, fmt.Errorf("claim %s: %w", id, err)
	}
	if ok {
		return true, nil
	}
	owner, err := c.client.Get(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("claim %s: %w", id, err)
	}
	if owner != c.workerID {
		return false, nil
	}
	if err := c.client.PExpire(ctx, key, c.ttl).Err(); err != nil {
		return false, fmt.Errorf("claim %s: %w", id, err)
	}
	return true, nil
}

// Renew extends the lease; ErrClaimLost when it is no longer this worker's.
func (c *RedisClaimer) Renew(ctx context.Context, id string) error {
	renewed, err := c.client.Eval(ctx, renewScript, []string{claimKey(id)}, c.workerID, c.ttl.Milliseconds()).Int()
	if err != nil {
		return fmt.Errorf("renew %s: %w", id, err)
	}
	if renewed == 0 {
		return fmt.Errorf("renew %s: %w", id, ErrClaimLost)
	}
	return nil
}

// Release drops the lease if it is still this worker's.
func (c *RedisClaimer) Release(ctx context.Context, id string) error {
	if err := c.client.Eval(ctx, releaseScript, []string{claimKey(id)}, c.workerID).Err(); err != nil && !errors.Is(err, redis.Nil) {
		return fmt.Errorf("release %s: %w", id, err)
	}
	return nil
}
