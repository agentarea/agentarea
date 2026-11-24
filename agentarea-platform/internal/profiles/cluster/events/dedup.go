package events

import (
	"context"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
)

// Dedup is kernel/events.Dedup on "<namespace>.dedup.<prefix>:<key>"
// (broker/dedup.py DedupCache): a claim is SET NX of "1" with the TTL, so
// claims stored before cutover still count.
type Dedup struct {
	client *redis.Client
	prefix string
	ttl    time.Duration
}

var _ kernel.Dedup = (*Dedup)(nil)

// NewDedup keys claims under prefix for ttl (AGENTAREA_CHANNEL_DEDUP_TTL, 1d in Python).
func NewDedup(client *redis.Client, namespace, prefix string, ttl time.Duration) (*Dedup, error) {
	if namespace == "" {
		return nil, errors.New("dedup needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
	}
	if ttl <= 0 {
		return nil, errors.New("dedup needs a positive TTL")
	}
	return &Dedup{client: client, prefix: namespace + ".dedup." + prefix, ttl: ttl}, nil
}

func (d *Dedup) key(k string) string { return d.prefix + ":" + k }

func (d *Dedup) Claim(ctx context.Context, key string, hold time.Duration) (bool, error) {
	ttl := d.ttl
	if hold > 0 {
		ttl = hold
	}
	return d.client.SetNX(ctx, d.key(key), "1", ttl).Result()
}

func (d *Dedup) Keep(ctx context.Context, key string) error {
	return d.client.Set(ctx, d.key(key), "1", d.ttl).Err()
}

func (d *Dedup) Contains(ctx context.Context, key string) (bool, error) {
	n, err := d.client.Exists(ctx, d.key(key)).Result()
	return n > 0, err
}

func (d *Dedup) Release(ctx context.Context, key string) error {
	return d.client.Del(ctx, d.key(key)).Err()
}
