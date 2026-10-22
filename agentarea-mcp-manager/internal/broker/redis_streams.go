// Package broker is the Redis Streams adapter behind the producers' Submitter
// ports. Callers name topics logically; the adapter puts the namespace in
// front and owns retention, so swapping the broker touches only this package.
package broker

import (
	"context"
	"fmt"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
)

// RedisStreams appends to Redis Streams under "<namespace>.<topic>".
type RedisStreams struct {
	client *redis.Client
	prefix string
}

// NewRedisStreams wraps a go-redis client with broker semantics under namespace.
func NewRedisStreams(client *redis.Client, namespace string) *RedisStreams {
	return &RedisStreams{client: client, prefix: namespace + "."}
}

// DialRedisStreams opens its own client for redisURL. A URL go-redis cannot
// parse is taken as a bare host:port.
func DialRedisStreams(redisURL, namespace string) *RedisStreams {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		addr, _ := strings.CutPrefix(redisURL, "redis://")
		opts = &redis.Options{Addr: addr}
	}
	return NewRedisStreams(redis.NewClient(opts), namespace)
}

// Submit appends fields to topic and returns the broker-assigned id. Entries
// older than retention are trimmed as it appends (XADD MINID ~).
func (r *RedisStreams) Submit(ctx context.Context, topic string, fields map[string]string, retention time.Duration) (string, error) {
	if retention <= 0 {
		return "", fmt.Errorf("XADD %s: retention must be positive", topic)
	}
	values := make(map[string]any, len(fields))
	for k, v := range fields {
		values[k] = v
	}
	id, err := r.client.XAdd(ctx, &redis.XAddArgs{
		Stream: r.prefix + topic,
		Values: values,
		MinID:  MinID(time.Now(), retention),
		Approx: true,
	}).Result()
	if err != nil {
		return "", fmt.Errorf("XADD %s: %w", topic, err)
	}
	return id, nil
}

// Close closes the underlying client.
func (r *RedisStreams) Close() error {
	return r.client.Close()
}

// MinID is the stream id below which entries are older than retention at now.
func MinID(now time.Time, retention time.Duration) string {
	return fmt.Sprintf("%d-0", now.Add(-retention).UnixMilli())
}
