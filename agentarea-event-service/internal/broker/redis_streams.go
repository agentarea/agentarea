// Package broker provides a stream broker abstraction. The OSS deployment
// uses Redis Streams; enterprise deployments can swap in Kafka behind the
// same interface (Submit / EnsureGroup / Consume / Ack / Autoclaim).
//
// The Go side currently only needs Submit + EnsureGroup (it produces inbound
// events; the Python worker consumes). The full interface is mirrored so
// adding a Kafka backend later is a single-file swap.
package broker

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/redis/go-redis/v9"
)

// Client is the broker abstraction. Methods are independent of the underlying
// broker implementation.
type Client interface {
	Submit(ctx context.Context, stream string, fields map[string]string) (string, error)
	EnsureGroup(ctx context.Context, stream, group, start string) error
}

// RedisStreams implements Client on top of go-redis XADD + XGROUP CREATE.
type RedisStreams struct {
	client *redis.Client
}

// NewRedisStreams wraps a go-redis client with broker semantics.
func NewRedisStreams(client *redis.Client) *RedisStreams {
	return &RedisStreams{client: client}
}

// Submit appends `fields` to `stream` and returns the broker-assigned id.
// XADD with "*" lets Redis assign the timestamp-based id; dedup is the
// consumer's job (it owns the dedup cache).
func (r *RedisStreams) Submit(ctx context.Context, stream string, fields map[string]string) (string, error) {
	values := make(map[string]any, len(fields))
	for k, v := range fields {
		values[k] = v
	}
	id, err := r.client.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		Values: values,
	}).Result()
	if err != nil {
		return "", fmt.Errorf("XADD %s: %w", stream, err)
	}
	return id, nil
}

// EnsureGroup creates the consumer group + stream if absent. Idempotent:
// BUSYGROUP (group already exists) is treated as success.
func (r *RedisStreams) EnsureGroup(ctx context.Context, stream, group, start string) error {
	if start == "" {
		start = "$"
	}
	err := r.client.XGroupCreateMkStream(ctx, stream, group, start).Err()
	if err == nil {
		return nil
	}
	if errors.Is(err, redis.Nil) || strings.Contains(err.Error(), "BUSYGROUP") {
		return nil
	}
	return fmt.Errorf("XGROUP CREATE %s %s: %w", stream, group, err)
}
