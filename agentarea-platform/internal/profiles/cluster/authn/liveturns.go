package authn

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"

	port "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// LiveTurns keeps running turns in Redis as runners:live-turn:<id> = "1"
// with an expiry the runner's heartbeat renews (turn_token.py LiveTurns).
type LiveTurns struct {
	rdb    redis.Cmdable
	prefix string
}

var _ port.LiveTurns = (*LiveTurns)(nil)

// NewLiveTurns keeps live turns on the broker's Redis.
func NewLiveTurns(rdb redis.Cmdable) *LiveTurns {
	return &LiveTurns{rdb: rdb, prefix: "runners:live-turn"}
}

func (l *LiveTurns) key(turnID string) string { return l.prefix + ":" + turnID }

// set writes the key with EX in whole seconds, as Python's ex=ttl_seconds;
// a zero ttl would make go-redis write a key that never expires.
func (l *LiveTurns) set(ctx context.Context, turnID string, ttl time.Duration) error {
	seconds := ttl / time.Second
	if seconds < 1 {
		return fmt.Errorf("live turn ttl must be at least one second, got %s", ttl)
	}
	return l.rdb.Set(ctx, l.key(turnID), "1", seconds*time.Second).Err()
}

// Begin marks the turn live for ttl.
func (l *LiveTurns) Begin(ctx context.Context, turnID string, ttl time.Duration) error {
	return l.set(ctx, turnID, ttl)
}

// Renew sets the key again rather than extending it, so a turn outlives a
// lapse while Redis was away.
func (l *LiveTurns) Renew(ctx context.Context, turnID string, ttl time.Duration) error {
	return l.set(ctx, turnID, ttl)
}

// End drops the turn.
func (l *LiveTurns) End(ctx context.Context, turnID string) error {
	return l.rdb.Del(ctx, l.key(turnID)).Err()
}

// Alive reports whether the turn's key exists.
func (l *LiveTurns) Alive(ctx context.Context, turnID string) (bool, error) {
	n, err := l.rdb.Exists(ctx, l.key(turnID)).Result()
	return n > 0, err
}
