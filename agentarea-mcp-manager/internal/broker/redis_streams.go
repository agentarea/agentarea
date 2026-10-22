package broker

import (
	"context"
	"fmt"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
)

type RedisStreams struct {
	client *redis.Client
	prefix string
}

func NewRedisStreams(client *redis.Client, namespace string) *RedisStreams {
	return &RedisStreams{client: client, prefix: namespace + "."}
}

func DialRedisStreams(redisURL, namespace string) *RedisStreams {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		addr, _ := strings.CutPrefix(redisURL, "redis://")
		opts = &redis.Options{Addr: addr}
	}
	return NewRedisStreams(redis.NewClient(opts), namespace)
}

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

func (r *RedisStreams) Close() error {
	return r.client.Close()
}

func MinID(now time.Time, retention time.Duration) string {
	return fmt.Sprintf("%d-0", now.Add(-retention).UnixMilli())
}
