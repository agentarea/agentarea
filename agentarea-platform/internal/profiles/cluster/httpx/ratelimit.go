// Package httpx is the edge's Valkey adapter: the token bucket
// rate_limit.py runs, one bucket per key shared by every replica.
package httpx

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// RateLimiter implements kernel.RateLimiter on Valkey.
type RateLimiter struct {
	client redis.Scripter
	script *redis.Script
}

// NewRateLimiter runs the bucket on client.
func NewRateLimiter(client redis.Scripter) *RateLimiter {
	return &RateLimiter{client: client, script: redis.NewScript(kernel.RateLimitScript)}
}

// DialRateLimiter opens its own client on url (AGENTAREA_REDIS_URL) with
// rate_limit.py's one-second connect and socket timeouts: a slow Valkey
// lets the request through rather than holding it.
func DialRateLimiter(url string) (*RateLimiter, *redis.Client, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, nil, fmt.Errorf("rate limit redis url: %w", err)
	}
	opts.DialTimeout = time.Second
	opts.ReadTimeout = time.Second
	opts.WriteTimeout = time.Second
	client := redis.NewClient(opts)
	return NewRateLimiter(client), client, nil
}

// Take implements kernel.RateLimiter.
func (l *RateLimiter) Take(ctx context.Context, scope, identity string, limit int) (bool, int, error) {
	res, err := l.script.Run(ctx, l.client, []string{kernel.RateLimitKey(scope, identity)}, limit, kernel.RateLimitBucketTTL).Int64Slice()
	if err != nil {
		return false, 0, err
	}
	if len(res) != 2 {
		return false, 0, fmt.Errorf("rate limit script returned %d values", len(res))
	}
	return res[0] == 1, int(res[1]), nil
}

var _ kernel.RateLimiter = (*RateLimiter)(nil)
